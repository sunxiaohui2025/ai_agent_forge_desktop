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
    from .db.models import Role, User
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
        await db.commit()


async def _ensure_default_agent() -> None:
    """Fallback: guarantee at least one default Agent so the first conversation
    has something to bind to. Runs LAST, after the bundled experts have been
    seeded — so it only creates the bare placeholder when the build shipped no
    ``builtin_agents.json`` (e.g. the public repo build). Idempotent.
    """
    from sqlalchemy import select
    from .db.session import SessionLocal
    from .db.models import Agent

    async with SessionLocal() as db:
        has_default = (
            await db.execute(select(Agent).where(Agent.is_default == True))  # noqa: E712
        ).scalar_one_or_none()
        if has_default is not None:
            return
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

    Also removes stale models that were seeded by older builds (before the
    hardcoded model list was removed) to prevent leaked internal addresses
    from persisting in user databases.
    """
    from sqlalchemy import select
    from .db.session import SessionLocal
    from .db.models import Model, Agent
    from .core.crypto import encrypt_str

    # ── Clean up stale models from v0.1.0 hardcoded build ──────────
    # Older builds shipped two hardcoded models pointing at an internal IP.
    # Remove any model whose code or base_url matches those leaked values
    # so they don't persist in user databases across upgrades.
    STALE_CODES = {"qwen3.5-397b-a17b", "Kimi-K2.6"}
    STALE_URL_PREFIXES = ("http://1.181.141.96:6018/",)

    async with SessionLocal() as db:
        stale_query = select(Model).where(
            Model.code.in_(STALE_CODES)
        )
        for url_pfx in STALE_URL_PREFIXES:
            stale_query = stale_query.union(
                select(Model).where(Model.base_url.like(f"{url_pfx}%"))
            )
        stale_result = await db.execute(stale_query)
        stale_models = stale_result.scalars().all()
        if stale_models:
            # Unbind the default agent from any stale model to avoid a broken
            # reference after deletion.
            stale_ids = {m.id for m in stale_models}
            agents_hooked = (await db.execute(
                select(Agent).where(Agent.default_model_id.in_(stale_ids))
            )).scalars().all()
            for ag in agents_hooked:
                ag.default_model_id = None
            for m in stale_models:
                await db.delete(m)
            logging.getLogger(__name__).info(
                "cleaned %d stale built-in models from old build", len(stale_models)
            )

    # ── Seed from env / file ──────────────────────────────────────
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


# ── Built-in callable Skills (in-process Python, no SKILL.md bundle) ─────────
# These are registered as `atomic.callable` Skill rows so the agent can invoke
# them like any other tool on the OpenAI-compatible path. The description is the
# tool spec the model sees, so it must spell out the calling protocol.
_CREATE_EXPERT_DESCRIPTION = (
    "【专家生成器】根据用户的自然语言描述，创建一个新的「专家」(智能体配置)。"
    "调用协议(分两步)：\n"
    "1) 先用 input={\"action\":\"list_resources\"} 调用本工具，获取当前可用的"
    "模型(models)、技能(skills)、连接器(connectors)、连接应用(cli_apps)清单；\n"
    "2) 理解用户想法后，从清单里挑选 ≤6 个最相关的 skills、≤6 个 connectors、"
    "≤6 个 cli_apps，并向用户复述你选中的能力，征得用户确认是否使用；\n"
    "3) 确认后用 input={\"action\":\"create\", ...} 提交，字段包括："
    "name(专家名称，按用户描述生成)、description(一句话介绍主要能力)、"
    "system_prompt(专家设定/系统提示词，必须结构化包含[角色身份与能力][工作流程]"
    "[输出规范][注意事项])、default_model_code/fallback_model_code(从 models.code 选)、"
    "skill_codes(数组,来自 skills.code)、connector_names(数组,来自 connectors.name)、"
    "cli_app_keys(数组,来自 cli_apps.app_key)。"
    "编码 code 可不传(系统自动生成)，图标 icon 可不传，工作目录 work_dir 默认空，"
    "max_turns 默认 100。创建成功后会返回新专家信息，请告知用户去「专家管理」查看。"
)

_CREATE_TASK_DESCRIPTION = (
    "【自动化任务生成器】根据用户的自然语言描述，创建一个定时自动化任务(Task)。"
    "任务会按设定的时间，自动调用某个「专家」执行一段指令。"
    "调用协议(分两步)：\n"
    "1) 先用 input={\"action\":\"list_agents\"} 调用本工具，获取当前可用的专家清单"
    "(agents，含 code/name/description)；\n"
    "2) 理解用户想法后，从清单里挑选最合适的执行专家，向用户复述你的理解"
    "(任务做什么、由哪个专家执行、多久执行一次)，征得确认；\n"
    "3) 确认后用 input={\"action\":\"create\", ...} 提交，字段包括："
    "name(任务名称，按用户描述生成)、description(可选，一句话说明)、"
    "agent_code(执行专家，来自 agents.code；也可用 agent_name)、"
    "prompt_text(每次执行时发送给专家的完整指令)、"
    "调度信息二选一：① schedule_type='cron' + schedule_value(5 段 cron 表达式，如 '0 9 * * *')，"
    "或 schedule_type='once' + schedule_value(ISO 时间，如 '2026-07-01T09:00:00')；"
    "② 直接给间隔 interval_minutes / interval_hours / interval_days(可附 at_hour/at_minute 指定具体时刻)，"
    "系统会自动转换成 cron。未提供的其他参数(超时、通知、并发)使用默认值。"
    "创建成功后请告知用户去「自动化」查看。"
)

_BUILTIN_CALLABLE_SKILLS = [
    {
        "code": "create_expert",
        "name": "专家生成器",
        "description": _CREATE_EXPERT_DESCRIPTION,
        "callable": "app.runtime.builtin_skills.expert_builder:run",
    },
    {
        "code": "create_task",
        "name": "自动化任务生成器",
        "description": _CREATE_TASK_DESCRIPTION,
        "callable": "app.runtime.builtin_skills.task_builder:run",
    },
]


async def _seed_builtin_callable_skills() -> None:
    """Register / repair built-in callable Skills (idempotent).

    Inserts a row per entry in ``_BUILTIN_CALLABLE_SKILLS`` if missing, and keeps
    the description + callable path in sync on each boot so spec edits in code
    propagate without a manual DB change. The description doubles as the tool
    spec the model sees, so we always overwrite it from code.
    """
    from sqlalchemy import select
    from .db.session import SessionLocal
    from .db.models import Skill

    async with SessionLocal() as db:
        for spec in _BUILTIN_CALLABLE_SKILLS:
            source = {"callable": spec["callable"], "builtin": True}
            existing = (await db.execute(
                select(Skill).where(Skill.code == spec["code"]))).scalar_one_or_none()
            if existing is None:
                db.add(Skill(
                    code=spec["code"], name=spec["name"],
                    description=spec["description"], type="atomic",
                    source_json=source, enabled=True,
                    # Author the usage summary directly so the auto-summarizer
                    # (which can't introspect a Python callable) won't blank it.
                    user_summary=spec["description"][:280],
                ))
            else:
                existing.name = spec["name"]
                existing.description = spec["description"]
                existing.type = "atomic"
                existing.source_json = source
                existing.enabled = True
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


def _bundled_data_file(name: str) -> "Path | None":
    """Locate a build-time seed file (e.g. builtin_agents.json).

    Packaged (frozen): bundled at the PyInstaller root ``_MEIPASS/<name>``.
    Development: read from the repo ``backend/<name>``.
    Returns None when the file is absent (e.g. the public repo build ships no
    experts), so callers no-op gracefully.
    """
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cand = Path(base) / name
        return cand if cand.is_file() else None
    cand = Path(__file__).resolve().parent.parent / name
    return cand if cand.is_file() else None


async def _seed_builtin_agents() -> None:
    """Install the bundled experts (builtin_agents.json) on first boot.

    Dependencies are referenced by *stable codes* (skill.code, model.code,
    cli_apps.app_key, connector name) so they re-bind correctly on a fresh
    install where row ids differ from the build machine. Runs AFTER models /
    skills / callable-skills seeding so those lookups resolve.

    Idempotent and edit-preserving:
      * A new expert (code not present) is created with its full bindings.
      * An existing expert is left untouched EXCEPT its model binding is
        self-healed when it is missing/dangling (covers the model-id churn from
        the stale-model cleanup in _seed_builtin_models).
    Referenced CLI apps that aren't connected yet are connected from the catalog
    so the binding isn't silently dropped.
    """
    import json
    from sqlalchemy import select
    from .db.session import SessionLocal
    from .db.models import (
        Agent, AgentSkill, AgentCliApp, AgentMCP, Skill, Model, CliApp, MCPConnector,
    )

    f = _bundled_data_file("builtin_agents.json")
    if f is None:
        return
    try:
        specs = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        logging.getLogger(__name__).exception("builtin_agents.json parse failed")
        return
    if not isinstance(specs, list) or not specs:
        return

    log = logging.getLogger(__name__)

    async with SessionLocal() as db:
        # ── stable-code → id lookups ────────────────────────────────
        skill_by_code = {s.code: s.id for s in (await db.execute(select(Skill))).scalars()}
        model_by_code = {m.code: m.id for m in (await db.execute(select(Model))).scalars()}
        conn_by_name = {c.name: c.id for c in (await db.execute(select(MCPConnector))).scalars()}

        async def _ensure_cli_app(app_key: str) -> "int | None":
            row = (await db.execute(
                select(CliApp).where(CliApp.app_key == app_key))).scalar_one_or_none()
            if row is not None:
                return row.id
            # Connect from the catalog so the binding survives on a fresh install
            # even though the binary may not be present on this machine.
            from .runtime.cli_apps_catalog import get_catalog_entry, detect_cli_app
            entry = get_catalog_entry(app_key)
            if not entry:
                return None
            det = await detect_cli_app(list(entry.get("bin_names") or []))
            row = CliApp(
                app_key=app_key, name=entry["name"], icon=entry.get("icon"),
                summary=entry.get("summary"),
                bin_name=(entry.get("bin_names") or [app_key])[0],
                bin_path=det["bin_path"], version=det["version"],
                install_command=entry.get("install_command"),
                status=det["status"], enabled=True,
            )
            db.add(row)
            await db.flush()
            return row.id

        for spec in specs:
            code = spec.get("code")
            if not code:
                continue
            default_mid = model_by_code.get(spec.get("default_model_code"))
            fallback_mid = model_by_code.get(spec.get("fallback_model_code"))

            existing = (await db.execute(
                select(Agent).where(Agent.code == code))).scalar_one_or_none()

            if existing is not None:
                # Preserve user edits; only self-heal a missing/dangling model.
                cur = existing.default_model_id
                if (cur is None or cur not in model_by_code.values()) and default_mid:
                    existing.default_model_id = default_mid
                    if existing.fallback_model_id is None:
                        existing.fallback_model_id = fallback_mid or default_mid
                    log.info("rebound model for existing expert %s", code)
                continue

            # ── Create the expert ───────────────────────────────────
            if spec.get("is_default"):
                from sqlalchemy import update as _update
                await db.execute(_update(Agent).values(is_default=False))
            agent = Agent(
                code=code,
                name=spec.get("name") or code,
                description=spec.get("description"),
                icon=spec.get("icon"),
                system_prompt=spec.get("system_prompt") or "",
                default_model_id=default_mid,
                fallback_model_id=fallback_mid or default_mid,
                upload_policy_json=spec.get("upload_policy_json") or {},
                max_turns=spec.get("max_turns") or 15,
                effort=spec.get("effort") or "low",
                parsed_content_limit=spec.get("parsed_content_limit"),
                work_dir=spec.get("work_dir"),
                enabled=spec.get("enabled", True),
                is_default=bool(spec.get("is_default")),
            )
            db.add(agent)
            await db.flush()

            for sc in spec.get("skill_codes") or []:
                sid = skill_by_code.get(sc)
                if sid:
                    db.add(AgentSkill(agent_id=agent.id, skill_id=sid))
            for ak in spec.get("cli_app_keys") or []:
                cid = await _ensure_cli_app(ak)
                if cid:
                    db.add(AgentCliApp(agent_id=agent.id, cli_app_id=cid))
            for cn in spec.get("connector_names") or []:
                mid = conn_by_name.get(cn)
                if mid:
                    db.add(AgentMCP(agent_id=agent.id, mcp_id=mid))
            log.info("seeded built-in expert %s (%s)", code, agent.name)

        await db.commit()


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
    try:
        await _seed_builtin_callable_skills()
    except Exception:
        logging.getLogger(__name__).exception("builtin callable skill seed failed")
    try:
        await _seed_builtin_agents()
    except Exception:
        logging.getLogger(__name__).exception("builtin agent seed failed")
    try:
        await _ensure_default_agent()
    except Exception:
        logging.getLogger(__name__).exception("default agent ensure failed")
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
