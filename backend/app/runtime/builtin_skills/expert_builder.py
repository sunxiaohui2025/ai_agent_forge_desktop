"""Built-in callable Skill: 专家生成器 (create_expert).

This skill lets a user create a new "专家"(= Agent configuration) just by
describing what they want in natural language. The LLM drives a two-step flow:

  1. action="list_resources"
     Return the catalog the LLM must choose from — available models, skills,
     connectors (MCP) and connected CLI apps — each with code + description so
     the model can pick the most relevant ones (≤6 skills, ≤6 connectors/apps).

  2. action="create"
     Persist a new Agent from the structured fields the model assembled (after
     the user confirmed the proposed capabilities). Codes/keys are resolved to
     DB ids server-side, a unique `code` is generated when missing, and sane
     defaults are applied (max_turns=None 表示不限制轮次, enabled=True, is_default=False, empty
     work_dir).

Registered as an `atomic.callable` Skill (source_json.callable =
``app.runtime.builtin_skills.expert_builder:run``) so it executes in-process on
the OpenAI-compatible tool-calling path.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select, update

from ...db.session import SessionLocal
from ...db.models import (
    Agent, AgentSkill, AgentMCP, AgentCliApp, Skill, Model, MCPConnector, CliApp,
)

SKILL_CODE = "create_expert"

# Cap how many capabilities a generated expert may carry, per the product spec.
MAX_SKILLS = 6
MAX_MCPS = 6
MAX_CLI_APPS = 6


def _norm_list(value: Any) -> list[str]:
    """Coerce a model-supplied selection into a clean list[str] of codes/keys."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,\s]+", value.strip())
        return [p for p in parts if p]
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for v in value:
            s = str(v).strip()
            if s:
                out.append(s)
        return out
    return [str(value).strip()]


def _slugify(text: str) -> str:
    """Best-effort ascii code from a name; falls back to 'expert'."""
    s = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    if not s or not re.match(r"^[a-z]", s):
        s = f"expert_{s}" if s else "expert"
    return s[:48]


async def _unique_code(db, base: str) -> str:
    """Return a code not yet used by any agent (suffixes _2, _3 … on clash)."""
    code = base or "expert"
    n = 1
    while True:
        cand = code if n == 1 else f"{code}_{n}"
        exists = (await db.execute(select(Agent.id).where(Agent.code == cand))).first()
        if not exists:
            return cand
        n += 1


async def _list_resources() -> dict[str, Any]:
    async with SessionLocal() as db:
        models = (await db.execute(
            select(Model).where(Model.enabled.is_(True)).order_by(Model.id)
        )).scalars().all()
        skills = (await db.execute(
            select(Skill).where(Skill.enabled.is_(True)).order_by(Skill.id)
        )).scalars().all()
        mcps = (await db.execute(
            select(MCPConnector).where(MCPConnector.enabled.is_(True)).order_by(MCPConnector.id)
        )).scalars().all()
        cli_apps = (await db.execute(
            select(CliApp).where(CliApp.enabled.is_(True)).order_by(CliApp.id)
        )).scalars().all()

    return {
        "models": [
            {"code": m.code, "provider": m.provider, "model_id": m.model_id}
            for m in models
        ],
        "skills": [
            {"code": s.code, "name": s.name,
             "description": (s.user_summary or s.description or "")[:280]}
            for s in skills
            # never offer the builder itself as a child capability
            if s.code != SKILL_CODE
        ],
        "connectors": [
            {"name": m.name, "description": (m.user_summary or "")[:280]}
            for m in mcps
        ],
        "cli_apps": [
            {"app_key": a.app_key, "name": a.name,
             "description": (a.summary or "")[:280],
             "installed": a.status == "installed"}
            for a in cli_apps
        ],
        "limits": {"skills": MAX_SKILLS, "connectors": MAX_MCPS, "cli_apps": MAX_CLI_APPS},
        "hint": (
            "请从以上资源中为新专家挑选：≤6 个最相关的 skills、≤6 个 connectors、"
            "≤6 个 cli_apps。然后用 action='create' 提交。首选/备选模型从 models.code 里各选一个。"
        ),
    }


async def _create(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "缺少专家名称 name"}

    system_prompt = str(payload.get("system_prompt") or "").strip()
    if not system_prompt:
        return {"ok": False, "error": "缺少专家设定 system_prompt（应包含角色身份、能力、工作流程、输出规范、注意事项）"}

    description = str(payload.get("description") or "").strip()
    icon = str(payload.get("icon") or "").strip() or None
    work_dir = str(payload.get("work_dir") or "").strip() or None

    # max_turns: None/缺省 = 不限制轮次；若设置则最少 30 轮,无上限。
    raw_mt = payload.get("max_turns")
    if raw_mt in (None, "", 0, "0"):
        max_turns = None
    else:
        try:
            max_turns = max(30, int(raw_mt))
        except (TypeError, ValueError):
            max_turns = None

    skill_codes = _norm_list(payload.get("skill_codes") or payload.get("skills"))[:MAX_SKILLS]
    mcp_names = _norm_list(payload.get("connector_names") or payload.get("connectors"))[:MAX_MCPS]
    cli_keys = _norm_list(payload.get("cli_app_keys") or payload.get("cli_apps"))[:MAX_CLI_APPS]

    default_model_code = str(payload.get("default_model_code") or payload.get("default_model") or "").strip()
    fallback_model_code = str(payload.get("fallback_model_code") or payload.get("fallback_model") or "").strip()

    async with SessionLocal() as db:
        # ── resolve codes → ids ───────────────────────────────────────────
        def_model_id = None
        fb_model_id = None
        if default_model_code:
            def_model_id = (await db.execute(
                select(Model.id).where(Model.code == default_model_code))).scalar_one_or_none()
        if fallback_model_code:
            fb_model_id = (await db.execute(
                select(Model.id).where(Model.code == fallback_model_code))).scalar_one_or_none()
        # Fall back to the first enabled model so the expert is usable out of the box.
        if def_model_id is None:
            def_model_id = (await db.execute(
                select(Model.id).where(Model.enabled.is_(True)).order_by(Model.id))).scalar_one_or_none()

        skill_ids: list[int] = []
        unknown_skills: list[str] = []
        for code in skill_codes:
            sid = (await db.execute(
                select(Skill.id).where(Skill.code == code, Skill.enabled.is_(True)))).scalar_one_or_none()
            if sid is not None and sid not in skill_ids:
                skill_ids.append(sid)
            elif sid is None:
                unknown_skills.append(code)

        mcp_ids: list[int] = []
        unknown_mcps: list[str] = []
        for nm in mcp_names:
            mid = (await db.execute(
                select(MCPConnector.id).where(MCPConnector.name == nm, MCPConnector.enabled.is_(True)))).scalar_one_or_none()
            if mid is not None and mid not in mcp_ids:
                mcp_ids.append(mid)
            elif mid is None:
                unknown_mcps.append(nm)

        cli_ids: list[int] = []
        unknown_clis: list[str] = []
        for key in cli_keys:
            cid = (await db.execute(
                select(CliApp.id).where(CliApp.app_key == key, CliApp.enabled.is_(True)))).scalar_one_or_none()
            if cid is not None and cid not in cli_ids:
                cli_ids.append(cid)
            elif cid is None:
                unknown_clis.append(key)

        # ── generate a unique code ────────────────────────────────────────
        raw_code = str(payload.get("code") or "").strip()
        base = _slugify(raw_code or name)
        code = await _unique_code(db, base)

        agent = Agent(
            code=code,
            name=name,
            description=description or None,
            icon=icon,
            system_prompt=system_prompt,
            default_model_id=def_model_id,
            fallback_model_id=fb_model_id,
            upload_policy_json={},
            max_turns=max_turns,
            effort="medium",
            parsed_content_limit=None,
            work_dir=work_dir,
            enabled=True,
            is_default=False,
        )
        db.add(agent)
        await db.flush()

        db.add_all([AgentSkill(agent_id=agent.id, skill_id=sid) for sid in skill_ids])
        db.add_all([AgentMCP(agent_id=agent.id, mcp_id=mid) for mid in mcp_ids])
        db.add_all([AgentCliApp(agent_id=agent.id, cli_app_id=cid) for cid in cli_ids])

        await db.commit()
        await db.refresh(agent)

        return {
            "ok": True,
            "agent": {
                "id": agent.id,
                "code": agent.code,
                "name": agent.name,
                "description": agent.description,
                "default_model_id": agent.default_model_id,
                "fallback_model_id": agent.fallback_model_id,
                "max_turns": agent.max_turns,
                "skill_ids": skill_ids,
                "mcp_ids": mcp_ids,
                "cli_app_ids": cli_ids,
            },
            "warnings": {
                "unknown_skills": unknown_skills,
                "unknown_connectors": unknown_mcps,
                "unknown_cli_apps": unknown_clis,
            },
            "message": (
                f"已创建专家「{agent.name}」(编码 {agent.code})，"
                f"挂载 {len(skill_ids)} 个技能、{len(mcp_ids)} 个连接器、{len(cli_ids)} 个连接应用。"
                "可在「专家管理」中查看或继续编辑。"
            ),
        }


async def run(**kwargs: Any) -> dict[str, Any]:
    """Skill entrypoint. Dispatch on ``action``.

    action="list_resources" → enumerate models/skills/connectors/cli_apps.
    action="create"          → create the Agent from structured fields.
    Defaults to list_resources so a first call without args is still useful.
    """
    action = str(kwargs.get("action") or "").strip().lower()
    if action in ("", "list", "list_resources", "resources"):
        return await _list_resources()
    if action == "create":
        return await _create(kwargs)
    return {
        "ok": False,
        "error": f"未知 action: {action}",
        "hint": "action 必须是 'list_resources' 或 'create'",
    }
