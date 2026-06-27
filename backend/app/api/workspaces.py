"""Workspace (project) management + local file browsing.

A workspace is a local directory the user picks via the desktop folder picker.
Conversations bound to a workspace become "tasks" that operate inside it.

The file-tree / read / create endpoints power the right-hand file panel. All
paths are validated to stay within the workspace root (no path traversal).
"""
from __future__ import annotations
import os
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from ..db.session import get_db
from ..db.models import Workspace, Conversation, User
from ..deps import current_user
from ..schemas import WorkspaceOut, WorkspaceCreate, WorkspaceUpdate

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

# Directories never shown in the file tree.
_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".DS_Store",
                ".idea", ".vscode", "dist", "build", ".next", ".cache"}
_MAX_PREVIEW_BYTES = 512 * 1024  # 512 KB cap for file preview


# ---------- helpers ----------
def _resolve_within(root: str, rel: str) -> Path:
    """Resolve `rel` under `root`, refusing escapes outside the workspace."""
    base = Path(root).resolve()
    target = (base / (rel or "")).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(400, "路径越界")
    return target


async def _get_ws(db: AsyncSession, user: User, wid: int) -> Workspace:
    ws = (await db.execute(select(Workspace).where(
        Workspace.id == wid, Workspace.user_id == user.id))).scalar_one_or_none()
    if not ws:
        raise HTTPException(404, "工作区不存在")
    return ws


# ---------- workspace CRUD ----------
@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Workspace).where(Workspace.user_id == user.id)
        .order_by(desc(Workspace.pinned), desc(Workspace.last_opened_at), desc(Workspace.updated_at))
    )).scalars().all()
    return rows


@router.post("", response_model=WorkspaceOut)
async def create_workspace(
    payload: WorkspaceCreate,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    path = os.path.expanduser(payload.path or "").strip()
    if not path or not os.path.isdir(path):
        raise HTTPException(400, "目录不存在")
    path = str(Path(path).resolve())
    # De-dupe: same path for the same user → return existing.
    existing = (await db.execute(select(Workspace).where(
        Workspace.user_id == user.id, Workspace.path == path))).scalar_one_or_none()
    if existing:
        existing.last_opened_at = datetime.now(timezone.utc)
        await db.commit(); await db.refresh(existing)
        return existing
    ws = Workspace(
        user_id=user.id,
        name=(payload.name or os.path.basename(path) or path),
        path=path,
        default_agent_id=payload.default_agent_id,
        permission_mode=payload.permission_mode or "ask",
        icon=payload.icon, color=payload.color,
        last_opened_at=datetime.now(timezone.utc),
    )
    db.add(ws); await db.commit(); await db.refresh(ws)
    return ws


@router.patch("/{wid}", response_model=WorkspaceOut)
async def update_workspace(
    wid: int, payload: WorkspaceUpdate,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    ws = await _get_ws(db, user, wid)
    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(ws, field, val)
    await db.commit(); await db.refresh(ws)
    return ws


@router.post("/{wid}/touch", response_model=WorkspaceOut)
async def touch_workspace(
    wid: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    """Mark a workspace as most-recently-opened (for ordering)."""
    ws = await _get_ws(db, user, wid)
    ws.last_opened_at = datetime.now(timezone.utc)
    await db.commit(); await db.refresh(ws)
    return ws


@router.delete("/{wid}")
async def delete_workspace(
    wid: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    ws = await _get_ws(db, user, wid)
    # Detach bound conversations back to plain chats rather than deleting them.
    convs = (await db.execute(select(Conversation).where(
        Conversation.workspace_id == wid))).scalars().all()
    for c in convs:
        c.workspace_id = None
        c.kind = "chat"
    await db.delete(ws); await db.commit()
    return {"ok": True}


# ---------- file browsing (right-hand panel) ----------
@router.get("/{wid}/tree")
async def list_tree(
    wid: int, path: str = Query("", description="relative path inside workspace"),
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    """List one directory level (lazy tree). Returns dirs first, then files."""
    ws = await _get_ws(db, user, wid)
    target = _resolve_within(ws.path, path)
    if not target.is_dir():
        raise HTTPException(400, "不是目录")
    entries = []
    try:
        for name in sorted(os.listdir(target)):
            if name in _IGNORE_DIRS:
                continue
            full = target / name
            is_dir = full.is_dir()
            try:
                st = full.stat()
                size, mtime = st.st_size, st.st_mtime
            except OSError:
                size, mtime = 0, 0
            entries.append({
                "name": name,
                "path": str(full.relative_to(Path(ws.path).resolve())),
                "type": "directory" if is_dir else "file",
                "size": size,
                "ext": full.suffix.lstrip(".").lower() if not is_dir else "",
                "mtime": mtime,
            })
    except OSError as e:
        raise HTTPException(500, f"读取目录失败: {e}")
    entries.sort(key=lambda x: (x["type"] != "directory", x["name"].lower()))
    return {"workspace_id": wid, "path": path, "entries": entries}


@router.get("/{wid}/file")
async def read_file(
    wid: int, path: str = Query(...),
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    """Read a text file for read-only preview (size-capped)."""
    ws = await _get_ws(db, user, wid)
    target = _resolve_within(ws.path, path)
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    size = target.stat().st_size
    truncated = size > _MAX_PREVIEW_BYTES
    try:
        with open(target, "rb") as f:
            raw = f.read(_MAX_PREVIEW_BYTES)
    except OSError as e:
        raise HTTPException(500, f"读取失败: {e}")
    try:
        content = raw.decode("utf-8")
        is_binary = False
    except UnicodeDecodeError:
        content = ""
        is_binary = True
    return {
        "path": path,
        "name": target.name,
        "ext": target.suffix.lstrip(".").lower(),
        "size": size,
        "truncated": truncated,
        "is_binary": is_binary,
        "content": content,
    }


@router.get("/{wid}/search")
async def search_files(
    wid: int, q: str = Query(..., min_length=1), limit: int = 200,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    """Recursive filename search within the workspace."""
    ws = await _get_ws(db, user, wid)
    base = Path(ws.path).resolve()
    ql = q.lower()
    hits: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]
        for name in filenames:
            if ql in name.lower():
                full = Path(dirpath) / name
                hits.append({
                    "name": name,
                    "path": str(full.relative_to(base)),
                    "type": "file",
                    "ext": full.suffix.lstrip(".").lower(),
                })
                if len(hits) >= limit:
                    return {"results": hits, "truncated": True}
    return {"results": hits, "truncated": False}


@router.post("/{wid}/file")
async def create_file(
    wid: int, payload: dict,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    """Create a new empty (or seeded) file at relative `path`."""
    ws = await _get_ws(db, user, wid)
    rel = (payload.get("path") or "").strip()
    if not rel:
        raise HTTPException(400, "缺少 path")
    target = _resolve_within(ws.path, rel)
    if target.exists():
        raise HTTPException(409, "文件已存在")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload.get("content") or "", encoding="utf-8")
    return {"ok": True, "path": rel}


@router.post("/{wid}/dir")
async def create_dir(
    wid: int, payload: dict,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    """Create a new folder at relative `path`."""
    ws = await _get_ws(db, user, wid)
    rel = (payload.get("path") or "").strip()
    if not rel:
        raise HTTPException(400, "缺少 path")
    target = _resolve_within(ws.path, rel)
    if target.exists():
        raise HTTPException(409, "目录已存在")
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": rel}
