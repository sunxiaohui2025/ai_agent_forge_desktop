from __future__ import annotations
import asyncio
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.config import settings
from .api import auth, chat, files, tasks as tasks_api, notifications as notifications_api
from .api import downloads as downloads_api
from .api import favorites as favorites_api
from .api import workspaces as workspaces_api
from .api import bridge as bridge_api
from .api.admin import users as admin_users, models as admin_models, mcp as admin_mcp, \
    skills as admin_skills, agents as admin_agents, logs as admin_logs, \
    departments as admin_departments, packs as admin_packs, approvals as admin_approvals, \
    cli_apps as admin_cli_apps, settings as admin_settings
from .services.file_cleanup import cleanup_loop
from .services.task_runner import get_scheduler
from .services.bridge_manager import get_bridge_manager
from .db.session import engine, Base


async def _auto_migrate() -> None:
    """Idempotent schema sync on boot.

    create_all creates any tables missing in the DB and then we run a few
    column-level ADD COLUMN IF NOT EXISTS for fields added to existing tables.

    On SQLite (desktop mode) we only run create_all: a fresh local db already
    has every column from the current models, and SQLite does not support the
    Postgres `ADD COLUMN IF NOT EXISTS` syntax below. The legacy ALTERs only
    matter for upgrading pre-existing Postgres deployments.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name != "postgresql":
            # SQLite (desktop): create_all won't add columns to a pre-existing
            # table, so newly added columns must be backfilled here. SQLite has
            # no `ADD COLUMN IF NOT EXISTS`, so probe the table first.
            try:
                cols = {
                    r[1]
                    for r in (await conn.exec_driver_sql("PRAGMA table_info(agents)")).all()
                }
                if "work_dir" not in cols:
                    await conn.exec_driver_sql(
                        "ALTER TABLE agents ADD COLUMN work_dir VARCHAR(1024)"
                    )
            except Exception:
                pass
            # call_logs.cache_hit_tokens
            try:
                call_cols = {
                    r[1]
                    for r in (await conn.exec_driver_sql("PRAGMA table_info(call_logs)")).all()
                }
                if "cache_hit_tokens" not in call_cols:
                    await conn.exec_driver_sql(
                        "ALTER TABLE call_logs ADD COLUMN cache_hit_tokens INTEGER NOT NULL DEFAULT 0"
                    )
            except Exception:
                pass
            return
        for stmt in [
            # users.email (needed for task email notifications)
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(256)",
            # agents: max_turns / effort (Claude SDK tuning — added in an earlier change)
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS max_turns INTEGER NOT NULL DEFAULT 15",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS effort VARCHAR(16) NOT NULL DEFAULT 'medium'",
            "ALTER TABLE agents ALTER COLUMN icon TYPE TEXT",
            # capability summary (Skill / MCP) — auto-generated, user-friendly Chinese description
            "ALTER TABLE skills ADD COLUMN IF NOT EXISTS user_summary TEXT",
            "ALTER TABLE skills ADD COLUMN IF NOT EXISTS user_summary_updated_at TIMESTAMP WITH TIME ZONE",
            "ALTER TABLE mcp_connectors ADD COLUMN IF NOT EXISTS user_summary TEXT",
            "ALTER TABLE mcp_connectors ADD COLUMN IF NOT EXISTS tool_summaries_json JSON",
            "ALTER TABLE mcp_connectors ADD COLUMN IF NOT EXISTS user_summary_updated_at TIMESTAMP WITH TIME ZONE",
            # favorites: snapshot of generated files attached to the answer
            "ALTER TABLE favorites ADD COLUMN IF NOT EXISTS files_json JSON",
            # agents: per-agent parsed-content cap. NULL = use global default.
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS parsed_content_limit INTEGER",
            # agents: optional default local working directory.
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS work_dir VARCHAR(1024)",
            # call_logs: cache hit tokens from LLM prompt caching
            "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS cache_hit_tokens INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                await conn.exec_driver_sql(stmt)
            except Exception:
                # Non-fatal — log-only; a fresh DB may not have the parent table yet
                # on the very first boot before create_all, which is fine.
                pass


async def _seed_local_user() -> None:
    """Ensure the single local user (id=1) and base roles exist.

    Desktop mode runs for one machine owner: we seed an `admin` role and a
    `local` user with a fixed id so `deps.current_user` can resolve it without
    a login. Idempotent — safe to run on every boot.
    """
    from sqlalchemy import select
    from .db.session import SessionLocal
    from .db.models import Role, User, Agent
    from .core.security import hash_password

    async with SessionLocal() as db:
        admin_role = (
            await db.execute(select(Role).where(Role.code == "admin"))
        ).scalar_one_or_none()
        if admin_role is None:
            admin_role = Role(code="admin", name="Sun", description="桌面单用户")
            db.add(admin_role)
            await db.flush()

        user = (await db.execute(select(User).where(User.id == 1))).scalar_one_or_none()
        if user is None:
            db.add(User(
                id=1,
                username=settings.SEED_ADMIN_USERNAME,
                password_hash=hash_password(settings.SEED_ADMIN_PASSWORD),
                display_name="Sun",
                role_id=admin_role.id,
            ))

        # Ensure at least one default Agent/Expert exists so the first
        # conversation has something to bind to.
        has_default = (
            await db.execute(select(Agent).where(Agent.is_default == True))  # noqa: E712
        ).scalar_one_or_none()
        if has_default is None:
            any_agent = (await db.execute(select(Agent).limit(1))).scalar_one_or_none()
            if any_agent is None:
                db.add(Agent(
                    code="default",
                    name="通用助手",
                    description="默认专家",
                    system_prompt="你是一个有用的智能助手。",
                    is_default=True,
                    enabled=True,
                ))
        await db.commit()


# Built-in models shipped with the app. Created on first boot (idempotent —
# skipped if a model with the same `code` already exists). The default expert
# is auto-bound to the first one so chat works out of the box.
#
# The default list is EMPTY — users provision their own models via the admin UI.
# To ship pre-seeded models for an internal deployment, set the
# H3C_BUILTIN_MODELS env var to a JSON array:
#   export H3C_BUILTIN_MODELS='[{"code":"my-model","provider":"openai-compatible",...}]'
# Or place a builtin_models.json file in the backend/ directory (gitignored).


def _load_builtin_models_from_env() -> list[dict]:
    """Load built-in models from env var or a local json file (gitignored).

    Reads H3C_BUILTIN_MODELS (JSON string) or backend/builtin_models.json.
    Returns an empty list when neither is present — the user creates models
    manually in the admin UI.  This avoids shipping sensitive credentials in
    the public GitHub repo.
    """
    import json
    # ── Env-var override (highest priority) ──────────────────────
    raw = os.environ.get("H3C_BUILTIN_MODELS", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [m for m in parsed if isinstance(m, dict)]
        except json.JSONDecodeError:
            logging.getLogger(__name__).warning(
                "H3C_BUILTIN_MODELS is not valid JSON — ignored"
            )
    # ── Local file (gitignored) ──────────────────────────────────
    file_path = Path(__file__).parent.parent / "builtin_models.json"
    if file_path.is_file():
        try:
            parsed = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(parsed, list):
                return [m for m in parsed if isinstance(m, dict)]
        except Exception:
            logging.getLogger(__name__).warning(
                "builtin_models.json could not be parsed — ignored"
            )
    return []


async def _seed_builtin_models() -> None:
    """Create built-in models from env / local file on first boot (idempotent).

    By default no models are shipped — users provision their own in the admin UI.
    To pre-seed models for an internal/enterprise deployment, set
    H3C_BUILTIN_MODELS or create backend/builtin_models.json (gitignored).
    """
    specs = _load_builtin_models_from_env()
    if not specs:
        return  # nothing to seed — user adds models manually

    from sqlalchemy import select
    from .db.session import SessionLocal
    from .db.models import Model, Agent
    from .core.crypto import encrypt_str

    async with SessionLocal() as db:
        first_model_id: int | None = None
        for spec in specs:
            existing = (await db.execute(
                select(Model).where(Model.code == spec["code"]))).scalar_one_or_none()
            if existing is not None:
                first_model_id = first_model_id or existing.id
                if not existing.enabled:
                    existing.enabled = True
                continue
            m = Model(
                code=spec["code"],
                provider=spec["provider"],
                model_id=spec["model_id"],
                base_url=spec.get("base_url"),
                api_key_enc=encrypt_str(spec["api_key"]) if spec.get("api_key") else None,
                max_tokens=spec.get("max_tokens", 8192),
                enabled=True,
                extra_params_json=spec.get("extra_params_json") or {},
            )
            db.add(m)
            await db.flush()
            first_model_id = first_model_id or m.id
        # Bind the default expert to the first seeded model if it has none.
        if first_model_id is not None:
            default_agent = (await db.execute(
                select(Agent).where(Agent.is_default == True))  # noqa: E712
            ).scalar_one_or_none()
            if default_agent is not None and default_agent.default_model_id is None:
                default_agent.default_model_id = first_model_id
        await db.commit()


def _bundled_skills_dir() -> "Path | None":
    """Locate the read-only built-in skills shipped inside the app.

    PyInstaller extracts bundled data under ``sys._MEIPASS`` (onedir →
    ``_internal/``). We staged ``storage/skills/*`` there as ``skills/`` in
    sidecar.spec. Returns None when not running frozen / no bundle present.
    """
    import sys
    from pathlib import Path
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None
    cand = Path(base) / "skills"
    return cand if cand.is_dir() else None


async def _seed_builtin_skills() -> None:
    """Install the bundled built-in Skill packages on first boot.

    In the packaged app the bundle is read-only, so we copy each skill into the
    writable ``settings.SKILLS_DIR`` (= DATA_DIR/skills) and register/repair its
    DB row to point at that absolute, machine-local path. Idempotent: existing
    files are not overwritten, and a row's path is only fixed if it no longer
    exists on disk (so user edits are preserved across restarts).
    """
    import shutil
    from pathlib import Path
    from sqlalchemy import select
    from .db.session import SessionLocal
    from .db.models import Skill
    from .core.config import settings
    from .services.skill_scan import scan_skill_dir  # noqa: F401 (kept for parity)

    src_root = _bundled_skills_dir()
    if src_root is None:
        return  # dev run, or nothing bundled — leave existing skills untouched.

    dst_root = Path(settings.SKILLS_DIR)
    dst_root.mkdir(parents=True, exist_ok=True)

    async with SessionLocal() as db:
        for src in sorted(src_root.iterdir()):
            if not src.is_dir() or src.name.startswith("."):
                continue
            if not (src / "SKILL.md").exists():
                continue
            code = src.name
            dst = (dst_root / code).resolve()
            # Copy files if the destination doesn't exist yet (preserve edits).
            if not dst.exists():
                try:
                    shutil.copytree(src, dst)
                except Exception:
                    logging.getLogger(__name__).exception(
                        "copy bundled skill failed: %s", code)
                    continue

            existing = (await db.execute(
                select(Skill).where(Skill.code == code))).scalar_one_or_none()
            if existing is None:
                # Derive a friendly description from SKILL.md frontmatter.
                desc = ""
                try:
                    md = (dst / "SKILL.md").read_text(encoding="utf-8", errors="ignore")
                    desc = _skill_description_from_md(md)
                except Exception:
                    pass
                db.add(Skill(
                    code=code, name=code, description=desc, type="atomic",
                    source_json={"path": str(dst)}, enabled=True,
                ))
            else:
                # Repair a stale/foreign path (e.g. a dev-machine absolute path
                # recorded in a shared DB) so browsing works on this machine.
                cur = (existing.source_json or {}).get("path")
                if not cur or not Path(cur).exists():
                    existing.source_json = {**(existing.source_json or {}),
                                            "path": str(dst)}
        await db.commit()


def _skill_description_from_md(md: str) -> str:
    """Best-effort one-line description from SKILL.md YAML frontmatter / body."""
    import yaml
    lines = md.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = lines.index("---", 1)
            fm = yaml.safe_load("\n".join(lines[1:end])) or {}
            if isinstance(fm, dict) and fm.get("description"):
                return str(fm["description"])[:256]
        except Exception:
            pass
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and s != "---":
            return s[:256]
    return ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await _auto_migrate()
    except Exception:
        # Don't block startup on migration errors; surface them via /api/health failures instead
        pass
    try:
        await _seed_local_user()
    except Exception:
        logging.getLogger(__name__).exception("local user seed failed")
    try:
        await _seed_builtin_models()
    except Exception:
        logging.getLogger(__name__).exception("builtin model seed failed")
    try:
        await _seed_builtin_skills()
    except Exception:
        logging.getLogger(__name__).exception("builtin skill seed failed")
    cleanup = asyncio.create_task(cleanup_loop())
    sch = get_scheduler()
    try:
        await sch.start()
    except Exception:
        pass
    bridge = get_bridge_manager()
    try:
        await bridge.start()
    except Exception:
        logging.getLogger(__name__).exception("bridge manager start failed")
    try:
        yield
    finally:
        cleanup.cancel()
        try:
            await cleanup
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await sch.stop()
        except Exception:
            pass
        try:
            await bridge.stop()
        except Exception:
            pass


app = FastAPI(title="H3C Agent", version="0.1.0", lifespan=lifespan)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(files.router)
app.include_router(downloads_api.router)
app.include_router(tasks_api.router)
app.include_router(tasks_api.detail_router)
app.include_router(notifications_api.router)
app.include_router(favorites_api.router)
app.include_router(workspaces_api.router)
app.include_router(bridge_api.router)
app.include_router(admin_users.router)
app.include_router(admin_models.router)
app.include_router(admin_mcp.router)
app.include_router(admin_skills.router)
app.include_router(admin_agents.router)
app.include_router(admin_logs.router)
app.include_router(admin_departments.router)
app.include_router(admin_packs.router)
app.include_router(admin_approvals.router)
app.include_router(admin_cli_apps.router)
app.include_router(admin_settings.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ── Static frontend (packaged desktop app) ──────────────────────────
# In production the Electron shell sets H3C_FRONTEND_DIR to the bundled Vue
# `dist/`. We serve it from the same origin so the SPA's relative `/api` calls
# work without a dev proxy, and unknown paths fall back to index.html (history
# routing). When unset (web/dev mode) this block is skipped — Vite serves the UI.
def _mount_frontend() -> None:
    import os
    from pathlib import Path
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    fe_dir = os.environ.get("H3C_FRONTEND_DIR")
    if not fe_dir:
        return
    root = Path(fe_dir)
    index = root / "index.html"
    if not index.is_file():
        logging.getLogger(__name__).warning("H3C_FRONTEND_DIR set but index.html missing: %s", root)
        return

    # Serve hashed assets directly.
    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        # API/ws paths never reach here (routers registered first). Serve a real
        # file if it exists, otherwise fall back to index.html for SPA routing.
        candidate = root / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(index))


_mount_frontend()
