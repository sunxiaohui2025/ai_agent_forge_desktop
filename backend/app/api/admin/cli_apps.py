"""Connected Apps (CLI tools) admin API."""
from __future__ import annotations
import asyncio
import os
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...db.models import CliApp, User
from ...deps import require_admin_or_operator
from ...services.audit import audit
from ...schemas import CliAppOut, CliAppCatalogItem, CliAppConnectIn, CliAppCustomIn
from ...runtime.cli_apps_catalog import CLI_APPS_CATALOG, get_catalog_entry, detect_cli_app

router = APIRouter(prefix="/api/admin/cli-apps", tags=["admin-cli-apps"])


@router.get("", response_model=list[CliAppOut])
async def list_cli_apps(db: AsyncSession = Depends(get_db), _=Depends(require_admin_or_operator)):
    return (await db.execute(select(CliApp).order_by(CliApp.id))).scalars().all()


@router.get("/catalog", response_model=list[CliAppCatalogItem])
async def catalog(db: AsyncSession = Depends(get_db), _=Depends(require_admin_or_operator)):
    rows = (await db.execute(select(CliApp))).scalars().all()
    by_key = {r.app_key: r for r in rows}
    detections = await asyncio.gather(
        *[detect_cli_app(list(a.get("bin_names") or [])) for a in CLI_APPS_CATALOG]
    )
    items: list[CliAppCatalogItem] = []
    for app, det in zip(CLI_APPS_CATALOG, detections):
        existing = by_key.get(app["app_key"])
        items.append(CliAppCatalogItem(
            app_key=app["app_key"], name=app["name"], icon=app.get("icon"),
            summary=app.get("summary"), bin_names=list(app.get("bin_names") or []),
            install_command=app.get("install_command"),
            categories=list(app.get("categories") or []),
            homepage=app.get("homepage"), needs_auth=bool(app.get("needs_auth")),
            example_prompts=list(app.get("example_prompts") or []),
            status=det["status"], version=det["version"],
            connected=existing is not None,
            cli_app_id=existing.id if existing else None,
        ))
    return items


async def _connect_from_catalog(db: AsyncSession, app_key: str) -> CliApp:
    entry = get_catalog_entry(app_key)
    if not entry:
        raise HTTPException(404, "未知的应用")
    det = await detect_cli_app(list(entry.get("bin_names") or []))
    existing = (await db.execute(select(CliApp).where(CliApp.app_key == app_key))).scalar_one_or_none()
    bin_name = (entry.get("bin_names") or [app_key])[0]
    if existing:
        existing.status = det["status"]
        existing.version = det["version"]
        existing.bin_path = det["bin_path"]
        return existing
    row = CliApp(
        app_key=app_key, name=entry["name"], icon=entry.get("icon"),
        summary=entry.get("summary"), bin_name=bin_name,
        bin_path=det["bin_path"], version=det["version"],
        install_command=entry.get("install_command"),
        status=det["status"], enabled=True,
    )
    db.add(row)
    return row


@router.post("/connect", response_model=CliAppOut)
async def connect(payload: CliAppConnectIn, db: AsyncSession = Depends(get_db),
                  actor: User = Depends(require_admin_or_operator)):
    row = await _connect_from_catalog(db, payload.app_key)
    await audit(db, actor.id, "cli_app.connect", target_type="cli_app", target_id=payload.app_key)
    await db.commit(); await db.refresh(row)
    return row


@router.post("/custom", response_model=CliAppOut)
async def add_custom(payload: CliAppCustomIn, db: AsyncSession = Depends(get_db),
                     actor: User = Depends(require_admin_or_operator)):
    slug = re.sub(r"[^a-z0-9\-]+", "-", payload.bin_name.lower()).strip("-") or "app"
    app_key = f"custom-{slug}"
    if (await db.execute(select(CliApp).where(CliApp.app_key == app_key))).scalar_one_or_none():
        raise HTTPException(400, "该应用已存在")
    det = await detect_cli_app([payload.bin_name])
    row = CliApp(
        app_key=app_key, name=payload.name, icon=payload.icon or "🧩",
        summary=payload.summary, bin_name=payload.bin_name,
        bin_path=det["bin_path"], version=det["version"],
        install_command=payload.install_command,
        status=det["status"], enabled=True,
    )
    db.add(row)
    await audit(db, actor.id, "cli_app.custom", target_type="cli_app", target_id=app_key)
    await db.commit(); await db.refresh(row)
    return row


@router.post("/{cid}/install")
async def install(cid: int, db: AsyncSession = Depends(get_db),
                  actor: User = Depends(require_admin_or_operator)):
    row = (await db.execute(select(CliApp).where(CliApp.id == cid))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "不存在")
    cmd = (row.install_command or "").strip()
    if not cmd:
        raise HTTPException(400, "该应用没有安装命令，请手动安装后点击「检测」")

    extra = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
             os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.npm-global/bin")]
    merged = os.pathsep.join(dict.fromkeys([*os.environ.get("PATH", "").split(os.pathsep), *extra]))
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PATH": merged},
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
        output = (out or b"").decode("utf-8", "replace")[-4000:]
        rc = proc.returncode
    except asyncio.TimeoutError:
        raise HTTPException(400, "安装超时（>10 分钟）")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"安装失败: {e}")

    entry = get_catalog_entry(row.app_key)
    bin_names = list(entry.get("bin_names")) if entry else [row.bin_name]
    det = await detect_cli_app(bin_names)
    row.status = det["status"]; row.version = det["version"]; row.bin_path = det["bin_path"]
    await audit(db, actor.id, "cli_app.install", target_type="cli_app", target_id=row.app_key)
    await db.commit(); await db.refresh(row)
    return {"ok": rc == 0, "status": row.status, "version": row.version, "output": output}


@router.post("/{cid}/detect", response_model=CliAppOut)
async def detect(cid: int, db: AsyncSession = Depends(get_db), _=Depends(require_admin_or_operator)):
    row = (await db.execute(select(CliApp).where(CliApp.id == cid))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "不存在")
    entry = get_catalog_entry(row.app_key)
    bin_names = list(entry.get("bin_names")) if entry else [row.bin_name]
    det = await detect_cli_app(bin_names)
    row.status = det["status"]; row.version = det["version"]; row.bin_path = det["bin_path"]
    await db.commit(); await db.refresh(row)
    return row


@router.delete("/{cid}")
async def delete_cli_app(cid: int, db: AsyncSession = Depends(get_db),
                         actor: User = Depends(require_admin_or_operator)):
    row = (await db.execute(select(CliApp).where(CliApp.id == cid))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "不存在")
    await audit(db, actor.id, "cli_app.delete", target_type="cli_app", target_id=row.app_key)
    await db.delete(row); await db.commit()
    return {"ok": True}
