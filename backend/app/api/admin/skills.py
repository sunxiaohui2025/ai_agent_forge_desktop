from __future__ import annotations
import os
import shutil
import zipfile
from pathlib import Path
import yaml
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ...core.config import settings
from ...db.session import get_db
from ...db.models import Skill
from ...deps import require_admin_or_operator
from ...services.audit import audit
from ...db.models import User
from ...schemas import SkillIn, SkillOut
from ...runtime.skill_loader import validate_composite_yaml
from ...services.capability_summarizer import summarize_skill

router = APIRouter(prefix="/api/admin/skills", tags=["admin-skills"])


def _validate(payload: SkillIn) -> None:
    if payload.type == "composite":
        yaml_text = payload.source_json.get("yaml", "")
        if not yaml_text:
            raise HTTPException(400, "composite skill 需要 source_json.yaml")
        try:
            data = yaml.safe_load(yaml_text)
            validate_composite_yaml(data)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"YAML 解析失败: {e}")
    elif payload.type == "atomic":
        if "path" not in payload.source_json and "callable" not in payload.source_json:
            raise HTTPException(400, "atomic skill 需要 source_json.path 或 callable")


@router.get("", response_model=list[SkillOut])
async def list_skills(db: AsyncSession = Depends(get_db), _=Depends(require_admin_or_operator)):
    return (await db.execute(select(Skill).order_by(Skill.id))).scalars().all()


@router.post("", response_model=SkillOut)
async def create_skill(payload: SkillIn, background_tasks: BackgroundTasks,
                       db: AsyncSession = Depends(get_db),
                       actor: User = Depends(require_admin_or_operator)):
    _validate(payload)
    if (await db.execute(select(Skill).where(Skill.code == payload.code))).scalar_one_or_none():
        raise HTTPException(400, "code 已存在")
    s = Skill(**payload.model_dump())
    await audit(db, actor.id, "skill.create", target_type="skill", target_id=None)
    db.add(s); await db.commit(); await db.refresh(s)
    background_tasks.add_task(summarize_skill, s.id)
    return s


@router.patch("/{sid}", response_model=SkillOut)
async def update_skill(sid: int, payload: SkillIn, background_tasks: BackgroundTasks,
                       db: AsyncSession = Depends(get_db),
                       actor: User = Depends(require_admin_or_operator)):
    _validate(payload)
    s = (await db.execute(select(Skill).where(Skill.id == sid))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "不存在")
    data = payload.model_dump()
    # `user_summary` is admin-editable. Track whether they explicitly set it
    # this turn so we can (a) stamp updated_at and (b) skip the auto-summarize
    # task that would otherwise clobber the manual text.
    manual_summary = (data.get("user_summary") or "").strip() if "user_summary" in data else None
    for k, v in data.items():
        if k == "user_summary":
            continue  # handled below
        setattr(s, k, v)
    s.version += 1
    if manual_summary:
        from datetime import datetime as _dt
        s.user_summary = manual_summary
        s.user_summary_updated_at = _dt.utcnow()
    await audit(db, actor.id, "skill.update", target_type="skill", target_id=s.id)
    await db.commit(); await db.refresh(s)
    # Only re-summarize when the admin did NOT manually edit the summary.
    if not manual_summary:
        background_tasks.add_task(summarize_skill, s.id)
    return s


@router.delete("/{sid}")
async def delete_skill(sid: int, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin_or_operator)):
    s = (await db.execute(select(Skill).where(Skill.id == sid))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "不存在")
    # Built-in callable skills (seeded on startup) are protected from deletion.
    if (s.source_json or {}).get("builtin") is True:
        raise HTTPException(400, "内置技能不可删除")
    # remove uploaded directory if path under SKILLS_DIR
    skills_root = Path(settings.SKILLS_DIR).resolve()
    p = (s.source_json or {}).get("path")
    if p:
        try:
            target = Path(p).resolve()
            if str(target).startswith(str(skills_root)):
                shutil.rmtree(target, ignore_errors=True)
        except Exception:
            pass
    await audit(db, actor.id, "skill.delete", target_type="skill", target_id=s.id)
    await db.delete(s); await db.commit()
    return {"ok": True}


# ---------- Upload Skill package ----------
def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    """Extract with path traversal protection."""
    target = target.resolve()
    for member in zf.infolist():
        member_path = (target / member.filename).resolve()
        if not str(member_path).startswith(str(target)):
            raise HTTPException(400, f"压缩包包含非法路径: {member.filename}")
    zf.extractall(target)


def _find_skill_root(extracted: Path) -> Path:
    """Find the directory that contains SKILL.md (root or first child)."""
    if (extracted / "SKILL.md").exists():
        return extracted
    children = [p for p in extracted.iterdir() if p.is_dir()]
    if len(children) == 1 and (children[0] / "SKILL.md").exists():
        return children[0]
    raise HTTPException(400, "压缩包根目录或唯一子目录中必须包含 SKILL.md")


@router.post("/upload", response_model=SkillOut)
async def upload_skill(
    background_tasks: BackgroundTasks,
    code: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    force: bool = Form(False),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin_or_operator),
):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "请上传 zip 包")
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
    return await _install_from_zip_bytes(
        bytes(data), code=code, name=name, description=description, force=force,
        db=db, actor=actor, background_tasks=background_tasks, origin="upload",
    )


async def _install_from_zip_bytes(
    zip_bytes: bytes,
    *,
    code: str,
    name: str,
    description: str,
    force: bool,
    db: AsyncSession,
    actor: User,
    background_tasks: BackgroundTasks,
    origin: str,
    origin_meta: dict | None = None,
    overwrite: bool = False,
) -> Skill:
    """Shared install pipeline for both manual upload and market install.

    extract → locate SKILL.md → static security scan → land on disk → DB insert
    → background summarize. ``origin`` is recorded in source_json so we can later
    tell market-installed skills apart and check for updates.
    """
    existing = (await db.execute(select(Skill).where(Skill.code == code))).scalar_one_or_none()
    if existing and not overwrite:
        raise HTTPException(400, "code 已存在")

    skills_root = Path(settings.SKILLS_DIR)
    skills_root.mkdir(parents=True, exist_ok=True)
    target_dir = skills_root / code
    backup_dir = skills_root / f".__bak_{code}"

    if target_dir.exists() and not overwrite:
        raise HTTPException(400, f"目录已存在: {target_dir}")

    tmp_dir = skills_root / f".__tmp_{code}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir()

    moved_backup = False
    try:
        # save zip
        zip_path = tmp_dir / "upload.zip"
        zip_path.write_bytes(zip_bytes)
        # extract
        extract_dir = tmp_dir / "extract"
        extract_dir.mkdir()
        try:
            with zipfile.ZipFile(zip_path) as zf:
                _safe_extract(zf, extract_dir)
        except zipfile.BadZipFile:
            raise HTTPException(400, "无效的 zip 包")
        # locate SKILL.md
        skill_root = _find_skill_root(extract_dir)

        # Static scan: dangerous bash/python patterns
        from ...services.skill_scan import scan_skill_dir
        findings = scan_skill_dir(skill_root)
        if findings and not force:
            await audit(db, actor.id, "skill.install_blocked", target_type="skill", target_id=code,
                        detail={"origin": origin, "findings": findings[:20]})
            await db.commit()
            raise HTTPException(400, {"message": "Skill 内容触发安全规则,被拒绝",
                                      "findings": findings,
                                      "hint": "确认无问题可在请求中加 force=true 强制通过"})
        if findings:
            await audit(db, actor.id, "skill.install_force", target_type="skill", target_id=code,
                        detail={"origin": origin, "findings": findings[:20]})

        # parse SKILL.md frontmatter for description (best-effort)
        skill_md = (skill_root / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
        if not description:
            description = _extract_description(skill_md) or ""

        # back up an existing dir before overwriting, so a failure is recoverable
        if target_dir.exists():
            if backup_dir.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
            shutil.move(str(target_dir), str(backup_dir))
            moved_backup = True
        # move new bundle into final location
        shutil.move(str(skill_root), str(target_dir))
    except Exception:
        # restore backup on any failure during the move
        if moved_backup and not target_dir.exists() and backup_dir.exists():
            shutil.move(str(backup_dir), str(target_dir))
            moved_backup = False
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    source_json: dict[str, Any] = {"path": str(target_dir.resolve()), "origin": origin}
    if origin_meta:
        source_json.update(origin_meta)

    if existing:
        existing.name = name
        existing.description = description
        existing.type = "atomic"
        existing.source_json = source_json
        existing.enabled = True
        existing.version += 1
        s = existing
        action = "skill.reinstall"
    else:
        s = Skill(code=code, name=name, description=description, type="atomic",
                  source_json=source_json, enabled=True)
        db.add(s)
        action = "skill.install"

    await db.flush()
    await audit(db, actor.id, action, target_type="skill", target_id=s.id,
                detail={"code": code, "origin": origin})
    await db.commit(); await db.refresh(s)
    # successful commit → drop the backup
    if moved_backup:
        shutil.rmtree(backup_dir, ignore_errors=True)
    background_tasks.add_task(summarize_skill, s.id)
    return s


def _extract_description(md: str) -> str | None:
    """Pull description: from YAML frontmatter, or first non-heading line."""
    lines = md.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = lines.index("---", 1)
            fm = yaml.safe_load("\n".join(lines[1:end])) or {}
            if isinstance(fm, dict) and fm.get("description"):
                return str(fm["description"])
        except Exception:
            pass
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and s != "---":
            return s[:256]
    return None


# ---------- Detail (file tree + content) ----------
def _candidate_skill_roots() -> list[Path]:
    """All directories we consider valid roots for managed skills.

    SKILLS_DIR resolves relative to the process CWD, which differs between dev
    (cwd=backend/) and the packaged app (cwd=resources/backend/). The skill's
    stored path is ABSOLUTE and the SQLite DB is shared between both run modes,
    so a path recorded in one environment must still validate in the other.
    We therefore accept several candidate roots.
    """
    roots: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path | str | None) -> None:
        if not p:
            return
        try:
            rp = Path(p).resolve()
        except Exception:
            return
        key = str(rp)
        if key not in seen:
            seen.add(key)
            roots.append(rp)

    # 1) Configured skills dir (relative to CWD).
    _add(settings.SKILLS_DIR)
    # 2) Per-user data dir (where packaging is meant to keep skills).
    try:
        _add(Path(settings.DATA_DIR) / "skills")
    except Exception:
        pass
    # 3) Repo-relative default, resolved from this file's location, so it works
    #    no matter what the process CWD happens to be.
    #    skills.py = <repo>/backend/app/api/admin/skills.py → parents[4] = <repo>.
    _add(Path(__file__).resolve().parents[4] / "storage" / "skills")
    return roots


def _is_under_managed_root(target: Path) -> bool:
    """True if ``target`` lives under a known skills root.

    Falls back to a safe structural heuristic: a directory whose immediate
    parent is named ``skills`` is treated as managed. This keeps cross-machine
    paths (dev ↔ packaged, same DB) browsable without weakening the per-file
    traversal guard applied when reading individual files.
    """
    for root in _candidate_skill_roots():
        try:
            if target == root or target.is_relative_to(root):
                return True
        except Exception:
            # is_relative_to may raise on Py<3.9; fall back to prefix compare.
            if str(target).startswith(str(root) + "/"):
                return True
    return target.parent.name == "skills"


def _resolve_skill_dir(s: Skill) -> Path:
    p = (s.source_json or {}).get("path")
    if not p:
        raise HTTPException(400, "该 Skill 没有可浏览的目录")
    target = Path(p).resolve()
    if not _is_under_managed_root(target):
        raise HTTPException(400, "Skill 目录不在受管路径下,无法浏览")
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, "Skill 目录不存在")
    return target


def _build_tree(root: Path, base: Path) -> list[dict]:
    nodes: list[dict] = []
    for p in sorted(root.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        rel = str(p.relative_to(base))
        if p.is_dir():
            nodes.append({"name": p.name, "path": rel, "type": "dir", "children": _build_tree(p, base)})
        else:
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            nodes.append({"name": p.name, "path": rel, "type": "file", "size": size})
    return nodes


@router.get("/{sid}/files")
async def get_skill_files(sid: int, db: AsyncSession = Depends(get_db), _=Depends(require_admin_or_operator)):
    s = (await db.execute(select(Skill).where(Skill.id == sid))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "不存在")
    root = _resolve_skill_dir(s)
    return {"root": root.name, "tree": _build_tree(root, root)}


TEXT_EXT = {".md", ".txt", ".py", ".js", ".ts", ".json", ".yml", ".yaml", ".html", ".css",
            ".sh", ".toml", ".ini", ".cfg", ".csv", ".xml", ".sql", ".go", ".rs", ".java"}


@router.get("/{sid}/file")
async def get_skill_file(sid: int, path: str, db: AsyncSession = Depends(get_db), _=Depends(require_admin_or_operator)):
    s = (await db.execute(select(Skill).where(Skill.id == sid))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "不存在")
    root = _resolve_skill_dir(s)
    target = (root / path).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(400, "非法路径")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "文件不存在")
    size = target.stat().st_size
    if size > 2 * 1024 * 1024:
        raise HTTPException(400, "文件过大,无法预览 (>2MB)")
    ext = target.suffix.lower()
    is_text = ext in TEXT_EXT or size < 64 * 1024
    try:
        content = target.read_text(encoding="utf-8")
        return {"path": path, "size": size, "ext": ext, "content": content, "binary": False, "editable": _is_editable(target)}
    except UnicodeDecodeError:
        return {"path": path, "size": size, "ext": ext, "content": "(二进制文件,无法预览)", "binary": True, "editable": False}


# ---------- Editable text files ----------
EDITABLE_EXT = {".md", ".txt", ".yaml", ".yml", ".json", ".ini", ".cfg", ".toml", ".csv", ".xml", ".html", ".css", ".sql"}


def _is_editable(p: Path) -> bool:
    return p.suffix.lower() in EDITABLE_EXT


from pydantic import BaseModel as _BM


class SkillFileSave(_BM):
    path: str
    content: str


@router.put("/{sid}/file")
async def put_skill_file(
    sid: int, payload: SkillFileSave,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin_or_operator),
):
    """In-place edit a text file inside a path-based atomic skill bundle.

    Restrictions:
    - Path must resolve inside the skill directory (no traversal).
    - Extension must be in EDITABLE_EXT (no .py / .sh / binaries).
    - Content size capped at 2 MB.
    - Re-runs the static scanner; high-risk patterns block save (admin can opt out via force=true query).
    """
    s = (await db.execute(select(Skill).where(Skill.id == sid))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "不存在")
    root = _resolve_skill_dir(s)
    target = (root / payload.path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise HTTPException(400, "非法路径")
    if target.is_dir():
        raise HTTPException(400, "目标是目录")
    if not _is_editable(target):
        raise HTTPException(400, f"文件类型不允许编辑: {target.suffix}")
    if len(payload.content.encode("utf-8")) > 2 * 1024 * 1024:
        raise HTTPException(400, "内容超过 2MB 限制")

    # Static scan on the new content (markdown / yaml / shell patterns)
    from ...services.skill_scan import _scan_text
    findings = _scan_text(payload.content)
    if findings:
        await audit(db, actor.id, "skill.file_edit_blocked", target_type="skill", target_id=s.id,
                    detail={"path": payload.path, "findings": findings[:10]})
        await db.commit()
        raise HTTPException(400, {"message": "内容触发安全规则,被拒绝", "findings": findings})

    # Backup old content for audit
    old = ""
    if target.exists():
        try:
            old = target.read_text(encoding="utf-8")
        except Exception:
            old = ""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload.content, encoding="utf-8")
    new_size = target.stat().st_size

    # Bump skill version so other layers know the bundle changed
    s.version += 1
    await audit(db, actor.id, "skill.file_edit", target_type="skill", target_id=s.id,
                detail={"path": payload.path, "old_size": len(old.encode('utf-8')),
                        "new_size": new_size})
    await db.commit()
    if payload.path.lower() in ("skill.md", "readme.md"):
        background_tasks.add_task(summarize_skill, s.id)
    return {"ok": True, "path": payload.path, "size": new_size, "version": s.version}


@router.post("/{sid}/resummarize")
async def resummarize_skill(sid: int, background_tasks: BackgroundTasks,
                             db: AsyncSession = Depends(get_db),
                             actor: User = Depends(require_admin_or_operator)):
    s = (await db.execute(select(Skill).where(Skill.id == sid))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "不存在")
    background_tasks.add_task(summarize_skill, s.id)
    await audit(db, actor.id, "skill.resummarize", target_type="skill", target_id=s.id)
    await db.commit()
    return {"ok": True, "queued": True}


# ---------- SkillHub market ----------
import re as _re
from ...services import skill_market


def _slug_to_code(slug: str) -> str:
    """Map a market slug to a local code. SKILLS_DIR/<code> is a directory name
    and the DB column allows a-z0-9_- starting with a letter, so we sanitize and
    fall back to a `skill_` prefix when the slug starts with a digit/symbol."""
    code = _re.sub(r"[^a-z0-9_-]", "-", (slug or "").lower()).strip("-")
    if not code:
        raise HTTPException(400, "无效的 slug")
    if not _re.match(r"^[a-z]", code):
        code = f"skill-{code}"
    return code[:64]


async def _market_installed_map(db: AsyncSession) -> dict[str, dict]:
    """Index local skills by their origin_slug (and code) so the market list can
    mark already-installed entries."""
    rows = (await db.execute(select(Skill))).scalars().all()
    out: dict[str, dict] = {}
    for r in rows:
        sj = r.source_json or {}
        info = {"id": r.id, "code": r.code, "version": sj.get("origin_version")}
        if sj.get("origin_slug"):
            out[sj["origin_slug"]] = info
        out.setdefault(r.code, info)
    return out


@router.get("/market")
async def market_list(
    q: str = "",
    section: str = "hot",
    page: int = 1,
    page_size: int = 24,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin_or_operator),
):
    page = max(1, page)
    page_size = min(max(1, page_size), 60)
    if q.strip():
        result = await skill_market.search_skills(q.strip(), page, page_size)
    else:
        result = await skill_market.list_skills(section, page, page_size)
    installed = await _market_installed_map(db)
    for item in result["items"]:
        hit = installed.get(item["slug"]) or installed.get(_slug_to_code(item["slug"]))
        item["installed"] = bool(hit)
        item["installed_id"] = hit["id"] if hit else None
    return result


@router.get("/market/{slug}")
async def market_detail(slug: str, _=Depends(require_admin_or_operator)):
    return await skill_market.detail(slug)


class MarketInstallIn(_BM):
    name: str | None = None
    description: str | None = None
    force: bool = False
    overwrite: bool = False


@router.post("/market/{slug}/install", response_model=SkillOut)
async def market_install(
    slug: str,
    payload: MarketInstallIn,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin_or_operator),
):
    code = _slug_to_code(slug)
    zip_bytes = await skill_market.download_zip(slug)
    # best-effort version tag for "check updates" later
    version = ""
    try:
        version = (await skill_market.detail(slug)).get("version", "")
    except HTTPException:
        pass
    return await _install_from_zip_bytes(
        zip_bytes,
        code=code,
        name=payload.name or slug,
        description=payload.description or "",
        force=payload.force,
        db=db,
        actor=actor,
        background_tasks=background_tasks,
        origin="skillhub",
        origin_meta={"origin_slug": slug, "origin_version": version},
        overwrite=payload.overwrite,
    )

