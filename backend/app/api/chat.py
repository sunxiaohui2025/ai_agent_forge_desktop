from __future__ import annotations
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from ..db.session import get_db, SessionLocal
from ..db.models import (
    Agent, AgentSkill, AgentMCP, AgentPack, RoleAgentGrant, Skill, MCPConnector, Model, SolutionPack,
    Conversation, Message, User, UploadedFile, CallLog, Workspace, AgentCliApp, CliApp,
)
from ..deps import current_user
from ..schemas import (
    AgentOut, ConversationOut, ConversationCreate, ConversationUpdate,
    MessageOut, ChatIn, PermissionDecisionIn, enrich_agent_engine,
)
from ..runtime.agent_runner import AgentRunner, AgentContext


async def _enrich_engine(db: AsyncSession, agent: Agent, out: AgentOut) -> AgentOut:
    """Populate derived engine fields on a user-facing AgentOut."""
    provider = None
    if agent.default_model_id:
        provider = (await db.execute(
            select(Model.provider).where(Model.id == agent.default_model_id)
        )).scalar_one_or_none()
    return enrich_agent_engine(out, provider=provider)

router = APIRouter(prefix="/api", tags=["chat"])

# Large fields that bloat tool_result history — replace with a byte-count summary.
# word_base64 / content_b64 are base64-encoded binaries; markdown_content /
# content are full document text. Neither is needed for conversation replay;
# the model only needs to know the tool succeeded and which files were produced.
_LARGE_RESULT_FIELDS = frozenset({
    "word_base64", "content_b64", "markdown_content", "markdown",
    "content", "audit",
})
_RESULT_CONTENT_CHAR_LIMIT = 4000  # keep at most this many chars of tool_result content


def _slim_trace_event(event: dict) -> dict:
    """Strip large inline fields from tool_result trace entries before
    persisting to the DB. The trimmed version is still sufficient for the
    model to understand what tools were called and what they produced."""
    if not isinstance(event, dict) or event.get("type") != "tool_result":
        return event
    data = event.get("data")
    if not isinstance(data, dict):
        return event
    content_str = data.get("content")
    if not isinstance(content_str, str):
        return event
    try:
        parsed = json.loads(content_str)
    except Exception:
        # Plain text result — just cap length
        if len(content_str) > _RESULT_CONTENT_CHAR_LIMIT:
            slimmed = content_str[:_RESULT_CONTENT_CHAR_LIMIT] + f"…[已截断, 共 {len(content_str)} 字符]"
            return {**event, "data": {**data, "content": slimmed}}
        return event
    if not isinstance(parsed, dict):
        return event
    changed = False
    for key in list(parsed.keys()):
        if key in _LARGE_RESULT_FIELDS:
            val = parsed[key]
            size = len(val) if isinstance(val, str) else len(json.dumps(val, ensure_ascii=False))
            parsed[key] = f"[已省略, {size} 字符]"
            changed = True
    if not changed:
        # Even if no known large fields, cap total length
        slim_str = json.dumps(parsed, ensure_ascii=False)
        if len(slim_str) <= _RESULT_CONTENT_CHAR_LIMIT:
            return event
        return {**event, "data": {**data, "content": slim_str[:_RESULT_CONTENT_CHAR_LIMIT] + "…[截断]"}}
    return {**event, "data": {**data, "content": json.dumps(parsed, ensure_ascii=False)}}


@router.get("/agents/default", response_model=AgentOut | None)
async def my_default_agent(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Resolve the default agent visible to the current user.

    Priority: explicit is_default flag → first enabled agent visible to the user.
    Returns null if none.
    """
    agent = await _resolve_default_agent(db, user)
    if not agent:
        return None
    skill_ids = [r[0] for r in (await db.execute(select(AgentSkill.skill_id).where(AgentSkill.agent_id == agent.id))).all()]
    mcp_ids = [r[0] for r in (await db.execute(select(AgentMCP.mcp_id).where(AgentMCP.agent_id == agent.id))).all()]
    out = AgentOut.model_validate(agent, from_attributes=True)
    out.skill_ids = skill_ids; out.mcp_ids = mcp_ids
    await _enrich_engine(db, agent, out)
    return out


async def _resolve_default_agent(db: AsyncSession, user: User) -> Agent | None:
    # explicit default
    a = (await db.execute(
        select(Agent).where(Agent.is_default.is_(True), Agent.enabled.is_(True))
    )).scalar_one_or_none()
    if a and _user_can_access(user, a, db):
        return a
    # fallback: first enabled visible agent
    if user.role.code in ("admin", "operator"):
        return (await db.execute(
            select(Agent).where(Agent.enabled.is_(True)).order_by(Agent.id).limit(1)
        )).scalar_one_or_none()
    sub = select(RoleAgentGrant.agent_id).where(RoleAgentGrant.role_id == user.role_id)
    return (await db.execute(
        select(Agent).where(Agent.id.in_(sub), Agent.enabled.is_(True)).order_by(Agent.id).limit(1)
    )).scalar_one_or_none()


def _user_can_access(user: User, agent: Agent, db: AsyncSession) -> bool:
    # Manager roles see all agents; for plain users we don't check here (too eager) — caller may re-validate.
    return True


async def _ensure_agent_visible(db: AsyncSession, user: User, agent_id: int) -> Agent:
    a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not a or not a.enabled:
        raise HTTPException(404, "agent 不存在")
    if user.role.code in ("admin", "operator"):
        return a
    granted = (await db.execute(
        select(RoleAgentGrant.agent_id).where(
            RoleAgentGrant.role_id == user.role_id,
            RoleAgentGrant.agent_id == agent_id,
        )
    )).scalar_one_or_none()
    if granted is None:
        raise HTTPException(403, "无权访问该智能体")
    return a


@router.get("/agents/{agent_id}/capabilities")
async def agent_capabilities(
    agent_id: int,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    """Return the model + skills + mcps wired into an agent (without live MCP tools).

    Visible to any user who can access this agent.
    """
    a = await _ensure_agent_visible(db, user, agent_id)

    def _model_brief(m: Model | None) -> dict | None:
        if not m:
            return None
        return {"id": m.id, "code": m.code, "model_id": m.model_id, "provider": m.provider}

    model = (await db.execute(select(Model).where(Model.id == a.default_model_id))).scalar_one_or_none() if a.default_model_id else None
    fb = (await db.execute(select(Model).where(Model.id == a.fallback_model_id))).scalar_one_or_none() if a.fallback_model_id else None

    skill_ids = [r[0] for r in (await db.execute(select(AgentSkill.skill_id).where(AgentSkill.agent_id == a.id))).all()]
    skills = list((await db.execute(
        select(Skill).where(Skill.id.in_(skill_ids))
    )).scalars().all()) if skill_ids else []

    mcp_ids = [r[0] for r in (await db.execute(select(AgentMCP.mcp_id).where(AgentMCP.agent_id == a.id))).all()]
    mcps = list((await db.execute(
        select(MCPConnector).where(MCPConnector.id.in_(mcp_ids))
    )).scalars().all()) if mcp_ids else []

    pack_ids = [r[0] for r in (await db.execute(select(AgentPack.pack_id).where(AgentPack.agent_id == a.id))).all()]
    packs = list((await db.execute(
        select(SolutionPack).where(SolutionPack.id.in_(pack_ids))
    )).scalars().all()) if pack_ids else []

    return {
        "agent": {
            "id": a.id, "code": a.code, "name": a.name,
            "description": a.description,
            "icon": a.icon,
        },
        "model": _model_brief(model),
        "fallback_model": _model_brief(fb),
        "skills": [
            {"id": s.id, "code": s.code, "name": s.name, "type": s.type,
             "description": s.description,
             "user_summary": s.user_summary,
             "enabled": s.enabled}
            for s in skills
        ],
        "mcps": [
            {"id": m.id, "name": m.name, "transport": m.transport,
             "user_summary": m.user_summary,
             "tool_summaries": (m.tool_summaries_json or {}).get("items") or [],
             "enabled": m.enabled}
            for m in mcps
        ],
        "packs": [
            {"id": p.id, "code": p.code, "name": p.name, "version": p.version,
             "description": p.description, "enabled": p.enabled}
            for p in packs
        ],
    }


@router.get("/agents/{agent_id}/mcps/{mid}/tools")
async def agent_mcp_tools(
    agent_id: int, mid: int,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    """Live-fetch tool list for one MCP server bound to an agent the user can access."""
    await _ensure_agent_visible(db, user, agent_id)
    bound = (await db.execute(
        select(AgentMCP).where(AgentMCP.agent_id == agent_id, AgentMCP.mcp_id == mid)
    )).scalar_one_or_none()
    if bound is None:
        raise HTTPException(404, "该智能体未挂载此 MCP")
    m = (await db.execute(select(MCPConnector).where(MCPConnector.id == mid))).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "MCP 不存在")
    try:
        from ..runtime.mcp_manager import list_mcp_tools
        return await list_mcp_tools(m, timeout=20.0)
    except Exception as e:
        raise HTTPException(400, f"连接失败: {e}")


@router.get("/agents", response_model=list[AgentOut])
async def my_agents(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from ..core.config import settings as _settings
    if _settings.DESKTOP_MODE or user.role.code in ("admin", "operator"):
        # Desktop single-user mode: every enabled expert is available (no role grants).
        rows = (await db.execute(select(Agent).where(Agent.enabled.is_(True)))).scalars().all()
    else:
        sub = select(RoleAgentGrant.agent_id).where(RoleAgentGrant.role_id == user.role_id)
        rows = (await db.execute(
            select(Agent).where(Agent.id.in_(sub), Agent.enabled.is_(True))
        )).scalars().all()
    out: list[AgentOut] = []
    for a in rows:
        skill_ids = [r[0] for r in (await db.execute(select(AgentSkill.skill_id).where(AgentSkill.agent_id == a.id))).all()]
        mcp_ids = [r[0] for r in (await db.execute(select(AgentMCP.mcp_id).where(AgentMCP.agent_id == a.id))).all()]
        v = AgentOut.model_validate(a, from_attributes=True)
        v.skill_ids = skill_ids; v.mcp_ids = mcp_ids
        await _enrich_engine(db, a, v)
        out.append(v)
    return out


# ---------- Conversations ----------
@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    workspace_id: int | None = None,
    kind: str | None = None,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    """List conversations, optionally filtered.

    - workspace_id given      → only that project's tasks
    - kind='chat'             → only plain chats (no workspace)
    - kind='task'             → only tasks (any workspace)
    - no filter               → everything (newest first)
    """
    stmt = select(Conversation).where(Conversation.user_id == user.id)
    if workspace_id is not None:
        stmt = stmt.where(Conversation.workspace_id == workspace_id)
    if kind == "chat":
        stmt = stmt.where(Conversation.workspace_id.is_(None))
    elif kind == "task":
        stmt = stmt.where(Conversation.workspace_id.is_not(None))
    rows = (await db.execute(stmt.order_by(desc(Conversation.updated_at)))).scalars().all()
    return rows


@router.post("/conversations", response_model=ConversationOut)
async def create_conversation(
    payload: ConversationCreate,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    # Resolve the workspace (if any) and let it provide the default agent.
    ws = None
    if payload.workspace_id:
        ws = (await db.execute(select(Workspace).where(
            Workspace.id == payload.workspace_id,
            Workspace.user_id == user.id))).scalar_one_or_none()
        if not ws:
            raise HTTPException(404, "工作区不存在")

    if payload.agent_id:
        a = (await db.execute(select(Agent).where(Agent.id == payload.agent_id))).scalar_one_or_none()
        if not a or not a.enabled:
            raise HTTPException(404, "agent 不存在")
    elif ws and ws.default_agent_id:
        a = (await db.execute(select(Agent).where(Agent.id == ws.default_agent_id))).scalar_one_or_none()
        if not a or not a.enabled:
            a = await _resolve_default_agent(db, user)
    else:
        a = await _resolve_default_agent(db, user)
    if not a:
        raise HTTPException(400, "尚未配置默认智能体,请联系管理员")

    # Bound to a workspace → "task"; otherwise plain "chat".
    kind = "task" if ws else "chat"
    default_title = "新任务" if ws else "新对话"
    c = Conversation(
        user_id=user.id, agent_id=a.id,
        title=payload.title or default_title,
        kind=kind,
        workspace_id=ws.id if ws else None,
        model_id=payload.model_id,
        permission_mode=payload.permission_mode or (ws.permission_mode if ws else None),
    )
    db.add(c); await db.commit(); await db.refresh(c)
    return c


@router.patch("/conversations/{cid}", response_model=ConversationOut)
async def rename_conversation(
    cid: int, payload: ConversationUpdate,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    c = (await db.execute(select(Conversation).where(
        Conversation.id == cid, Conversation.user_id == user.id))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "不存在")
    data = payload.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        c.title = data["title"]
    if "model_id" in data:
        c.model_id = data["model_id"]
    if "permission_mode" in data:
        c.permission_mode = data["permission_mode"]
    if "workspace_id" in data:
        wid = data["workspace_id"]
        if wid is not None:
            ws = (await db.execute(select(Workspace).where(
                Workspace.id == wid, Workspace.user_id == user.id))).scalar_one_or_none()
            if not ws:
                raise HTTPException(404, "工作区不存在")
            c.workspace_id = wid
            c.kind = "task"
            if c.permission_mode is None:
                c.permission_mode = ws.permission_mode or "ask"
        else:
            c.workspace_id = None
            c.kind = "chat"
    await db.commit(); await db.refresh(c)
    return c


@router.delete("/conversations/{cid}")
async def delete_conversation(
    cid: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    c = (await db.execute(select(Conversation).where(
        Conversation.id == cid, Conversation.user_id == user.id))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "不存在")
    await db.delete(c); await db.commit()
    return {"ok": True}


@router.get("/conversations/{cid}/messages", response_model=list[MessageOut])
async def list_messages(cid: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    c = (await db.execute(select(Conversation).where(
        Conversation.id == cid, Conversation.user_id == user.id))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "不存在")
    rows = (await db.execute(
        select(Message).where(Message.conversation_id == cid).order_by(Message.id)
    )).scalars().all()

    # Hydrate user-message file briefs from UploadedFile (we only persist file_ids on send)
    file_id_set: set[int] = set()
    for r in rows:
        if r.role == "user":
            ids = (r.content_json or {}).get("file_ids") if isinstance(r.content_json, dict) else None
            if isinstance(ids, list):
                for x in ids:
                    if isinstance(x, int):
                        file_id_set.add(x)
    file_briefs: dict[int, dict] = {}
    if file_id_set:
        ufs = (await db.execute(
            select(UploadedFile).where(UploadedFile.id.in_(file_id_set))
        )).scalars().all()
        import os as _os
        for u in ufs:
            file_briefs[u.id] = {
                "id": u.id, "name": u.name, "size": u.size, "mime": u.mime,
                "ext": _os.path.splitext(u.name or "")[1].lower(),
                "parse_status": u.parse_status, "parsed_chars": u.parsed_chars or 0,
                "download_url": f"/api/files/{u.id}/raw",
            }
    out = []
    for r in rows:
        item = MessageOut.model_validate(r, from_attributes=True)
        if r.role == "user" and isinstance(r.content_json, dict):
            ids = r.content_json.get("file_ids") or []
            if ids:
                # rebuild on a *copy* so we don't mutate the ORM-tracked dict
                cj = dict(r.content_json)
                cj["files"] = [file_briefs[i] for i in ids if i in file_briefs]
                item.content_json = cj
        out.append(item)
    return out


# ---------- Streaming chat ----------
async def _load_agent_context(db: AsyncSession, agent_id: int, conversation_id: int | None = None,
                               history_limit: int = 30,
                               model_override_id: int | None = None,
                               workspace_dir: str | None = None,
                               permission_mode: str | None = None) -> AgentContext:
    a = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
    # When the caller didn't bind a workspace, fall back to the agent's own
    # default working directory (configured in 专家管理). Empty → plain chat.
    if not (workspace_dir or "").strip():
        agent_dir = (a.work_dir or "").strip()
        if agent_dir:
            workspace_dir = agent_dir
            if not permission_mode:
                permission_mode = "ask"
    skill_ids = [r[0] for r in (await db.execute(select(AgentSkill.skill_id).where(AgentSkill.agent_id == a.id))).all()]
    mcp_ids = [r[0] for r in (await db.execute(select(AgentMCP.mcp_id).where(AgentMCP.agent_id == a.id))).all()]
    skills = list((await db.execute(select(Skill).where(Skill.id.in_(skill_ids), Skill.enabled.is_(True)))).scalars().all())
    mcps = list((await db.execute(select(MCPConnector).where(MCPConnector.id.in_(mcp_ids), MCPConnector.enabled.is_(True)))).scalars().all())
    pack_ids = [r[0] for r in (await db.execute(select(AgentPack.pack_id).where(AgentPack.agent_id == a.id))).all()]
    packs = list((await db.execute(select(SolutionPack).where(SolutionPack.id.in_(pack_ids), SolutionPack.enabled.is_(True)))).scalars().all()) if pack_ids else []
    cli_app_ids = [r[0] for r in (await db.execute(select(AgentCliApp.cli_app_id).where(AgentCliApp.agent_id == a.id))).all()]
    cli_apps = list((await db.execute(select(CliApp).where(CliApp.id.in_(cli_app_ids), CliApp.enabled.is_(True)))).scalars().all()) if cli_app_ids else []
    # Per-conversation model override takes priority over the agent default.
    eff_model_id = model_override_id or a.default_model_id
    model = (await db.execute(select(Model).where(Model.id == eff_model_id))).scalar_one_or_none() if eff_model_id else None
    # Desktop fallback: if the expert has no model bound (or it was deleted),
    # fall back to the first enabled model in the system. This means the user
    # only has to configure ONE model under 设置→模型 for chat to work — no need
    # to also edit the expert. Only the explicit per-conversation override is
    # respected as-is; otherwise we auto-pick.
    if model is None:
        model = (await db.execute(
            select(Model).where(Model.enabled.is_(True)).order_by(Model.id)
        )).scalars().first()
    fb = (await db.execute(select(Model).where(Model.id == a.fallback_model_id))).scalar_one_or_none() if a.fallback_model_id else None

    # Load prior turns so the model has conversation context. We load the most recent
    # `history_limit` user/assistant messages, in chronological order, EXCLUDING the
    # message currently being sent (caller persists it after this loads).
    history: list[Message] = []
    if conversation_id is not None:
        from sqlalchemy import desc as _desc
        rows = (await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.role.in_(["user", "assistant"]))
            .order_by(_desc(Message.id))
            .limit(history_limit)
        )).scalars().all()
        history = list(reversed(rows))

    return AgentContext(agent=a, skills=skills, mcps=mcps, packs=packs, model=model,
                        fallback_model=fb, history=history,
                        workspace_dir=workspace_dir, permission_mode=permission_mode,
                        cli_apps=cli_apps)


@router.post("/conversations/{cid}/messages")
async def send_message(
    cid: int, payload: ChatIn,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    c = (await db.execute(select(Conversation).where(
        Conversation.id == cid, Conversation.user_id == user.id))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "不存在")

    # ---- Security: input filter ----
    from ..core.security_rules import scan_user_input
    from ..db.models import AuditLog
    # [UI_ACTION] route: structured user action from a rendered UI Schema → tool call.
    # [UI_MSG]    route: synthetic user message from a UI Schema button → normal LLM turn,
    #                    but hidden from the chat transcript (no user bubble shown).
    # Both bypass scan_user_input because we authored them.
    is_ui_action = payload.content.startswith("[UI_ACTION]")
    is_ui_msg = payload.content.startswith("[UI_MSG]")
    # The clean text the LLM should actually see for [UI_MSG]
    if is_ui_msg:
        clean_text = payload.content[len("[UI_MSG]"):].lstrip()
    else:
        clean_text = payload.content
    hits = [] if (is_ui_action or is_ui_msg) else scan_user_input(payload.content)
    if hits:
        # Persist a high-signal audit record so admins can review attempted attacks
        db.add(AuditLog(
            user_id=user.id,
            action="input_filter_blocked",
            target_type="conversation",
            target_id=str(cid),
            detail_json={
                "patterns": [h.pattern for h in hits],
                "snippets": [h.snippet for h in hits],
                "raw_preview": payload.content[:300],
            },
        ))
        await db.commit()
        raise HTTPException(400, f"输入包含被禁用的模式: {', '.join(h.pattern for h in hits)}")

    # ---- Per-send file count cap (Agent upload policy) ----
    if payload.file_ids:
        a = (await db.execute(select(Agent).where(Agent.id == c.agent_id))).scalar_one()
        policy = a.upload_policy_json or {}
        max_per_send = int(policy.get("max_files_per_send") or 0)
        if max_per_send > 0 and len(payload.file_ids) > max_per_send:
            raise HTTPException(400,
                f"单次发送最多 {max_per_send} 个文件,本次提交 {len(payload.file_ids)} 个")

    # Load history BEFORE inserting the new user message, so it doesn't appear twice
    # (the current turn is passed separately as user_text into the runner)
    # Resolve the workspace dir + effective permission for task-mode conversations.
    # A user-selected workspace wins; otherwise _load_agent_context falls back to
    # the agent's own default work_dir.
    ws_dir = None
    perm_mode = None
    if c.workspace_id:
        ws = (await db.execute(select(Workspace).where(
            Workspace.id == c.workspace_id))).scalar_one_or_none()
        if ws:
            ws_dir = ws.path
            perm_mode = c.permission_mode or ws.permission_mode or "ask"
    ctx = await _load_agent_context(db, c.agent_id, conversation_id=cid,
                                    model_override_id=c.model_id,
                                    workspace_dir=ws_dir,
                                    permission_mode=perm_mode or c.permission_mode)

    # Merge any per-message connected apps from the "连应用" picker. These extend
    # the agent's own connected apps for this turn only.
    if payload.cli_app_ids:
        have = {a.id for a in (ctx.cli_apps or [])}
        extra_ids = [i for i in payload.cli_app_ids if i not in have]
        if extra_ids:
            extra = list((await db.execute(
                select(CliApp).where(CliApp.id.in_(extra_ids), CliApp.enabled.is_(True))
            )).scalars().all())
            ctx.cli_apps = [*(ctx.cli_apps or []), *extra]

    # Merge any per-message skills from the "技能" picker. These extend the
    # agent's own skills for this turn only so the model may hit them.
    if payload.skill_ids:
        have_sk = {s.id for s in (ctx.skills or [])}
        extra_sk_ids = [i for i in payload.skill_ids if i not in have_sk]
        if extra_sk_ids:
            extra_sk = list((await db.execute(
                select(Skill).where(Skill.id.in_(extra_sk_ids), Skill.enabled.is_(True))
            )).scalars().all())
            ctx.skills = [*(ctx.skills or []), *extra_sk]

    user_msg = Message(
        conversation_id=cid, role="user",
        content_json={
            "text": clean_text,
            "file_ids": payload.file_ids,
            **({"hidden": True} if is_ui_msg else {}),
        },
    )
    db.add(user_msg)
    await db.commit()

    # Resolve files: include parsed markdown so the model actually reads contents
    files = []
    if payload.file_ids:
        from datetime import datetime as _dt, timezone as _tz
        rows = (await db.execute(
            select(UploadedFile).where(
                UploadedFile.id.in_(payload.file_ids),
                UploadedFile.user_id == user.id,  # cross-user safeguard
            )
        )).scalars().all()
        for r in rows:
            file_entry = {
                "name": r.name,
                "path": r.path,
                "mime": r.mime,
                "size": r.size,
                "parse_status": r.parse_status,
                "parsed_markdown": r.parsed_markdown if r.parse_status == "done" else None,
                "parse_error": r.parse_error,
            }
            # For files uploaded with parse_mode="never", expose a signed URL
            # so MCP tools (which can't read local paths) can pull raw bytes.
            if r.parse_status == "skipped":
                from ..core.security import create_file_token
                from ..core.config import settings as _s
                base = (_s.BACKEND_BASE_URL or _s.APP_BASE_URL or "").rstrip("/")
                tok = create_file_token(r.id, user.id, minutes=60)
                file_entry["raw_url"] = f"{base}/api/files/{r.id}/raw?t={tok}"
                file_entry["id"] = r.id
            files.append(file_entry)
            # Mark last_used_at so the cleanup task knows this file is still referenced
            r.last_used_at = _dt.now(_tz.utc)
        if rows:
            await db.commit()

    async def event_stream():
        # Use a fresh session inside the generator (request-scoped one is closed after return)
        import asyncio
        async with SessionLocal() as session:
            runner = AgentRunner(ctx, user_id=user.id)
            # Bind the conversation so interactive permission requests + session
            # grants are scoped to this conversation.
            runner._conversation_id = cid
            assistant_text_parts: list[str] = []
            thinking_parts: list[str] = []
            tool_traces: list[dict] = []
            saved_files: list[dict] = []
            saved_uis: list[dict] = []
            tokens_in = tokens_out = cache_hit_tokens = latency = 0
            status_str = "ok"
            err = None
            try:
                # [UI_ACTION] short-circuit: parse + validate against this agent's
                # tool whitelist, then call directly without LLM.
                if is_ui_action:
                    from ..ui_schema.types import whitelist_tool_names
                    import re as _re
                    m = _re.match(r"\[UI_ACTION\]\s*tool=([^\s]+)\s+params=(.*)$",
                                  payload.content, _re.DOTALL)
                    if not m:
                        yield f"data: {json.dumps({'type':'error','data':{'message':'UI_ACTION 格式错误'}}, ensure_ascii=False)}\n\n"
                    else:
                        ui_tool = m.group(1).strip()
                        try:
                            ui_params = json.loads(m.group(2))
                            if not isinstance(ui_params, dict):
                                ui_params = {"value": ui_params}
                        except Exception:
                            ui_params = {"raw": m.group(2)}
                        # Build whitelist: skill codes + mcp__<server>__* prefixes + builtins
                        allowed = whitelist_tool_names(ctx.skills, mcp_tool_routes={})
                        is_allowed = (
                            ui_tool in allowed
                            or any(ui_tool.startswith(f"mcp__{mcp.name}__") for mcp in ctx.mcps)
                        )
                        if not is_allowed:
                            yield f"data: {json.dumps({'type':'error','data':{'message':f'工具 {ui_tool} 不在该智能体的允许列表'}}, ensure_ascii=False)}\n\n"
                        else:
                            async for ev in runner.exec_ui_action(ui_tool, ui_params):
                                payload_json = {"type": ev.type, "data": ev.data}
                                yield f"data: {json.dumps(payload_json, ensure_ascii=False)}\n\n"
                                await asyncio.sleep(0)
                                if ev.type == "ui":
                                    saved_uis.append(ev.data if isinstance(ev.data, dict) else {})
                                elif ev.type == "tool_use" or ev.type == "tool_result":
                                    tool_traces.append(_slim_trace_event(payload_json))
                                elif ev.type == "file":
                                    saved_files.append(ev.data if isinstance(ev.data, dict) else {})
                                elif ev.type == "done":
                                    tokens_in = ev.data.get("tokens_in", 0)
                                    tokens_out = ev.data.get("tokens_out", 0)
                                    cache_hit_tokens = ev.data.get("cache_hit_tokens", 0)
                                    latency = ev.data.get("latency_ms", 0)
                else:
                    async for ev in runner.stream(clean_text, files):
                        payload_json = {"type": ev.type, "data": ev.data}
                        yield f"data: {json.dumps(payload_json, ensure_ascii=False)}\n\n"
                        # cooperative yield so each chunk is flushed to client immediately
                        await asyncio.sleep(0)
                        if ev.type == "text":
                            assistant_text_parts.append(ev.data.get("text", ""))
                        elif ev.type == "thinking":
                            thinking_parts.append(ev.data.get("text", ""))
                        elif ev.type in ("tool_use", "tool_result"):
                            tool_traces.append(_slim_trace_event(payload_json))
                        elif ev.type == "file":
                            saved_files.append(ev.data if isinstance(ev.data, dict) else {})
                        elif ev.type == "ui":
                            saved_uis.append(ev.data if isinstance(ev.data, dict) else {})
                        elif ev.type == "done":
                            tokens_in = ev.data.get("tokens_in", 0)
                            tokens_out = ev.data.get("tokens_out", 0)
                            cache_hit_tokens = ev.data.get("cache_hit_tokens", 0)
                            latency = ev.data.get("latency_ms", 0)
                        elif ev.type == "error":
                            status_str = "error"
                            err = ev.data.get("message")
            finally:
                # Persist assistant message + call log
                content_payload = {"text": "".join(assistant_text_parts)}
                if thinking_parts:
                    content_payload["thinking"] = "".join(thinking_parts)
                if saved_files:
                    content_payload["files"] = saved_files
                if saved_uis:
                    content_payload["uis"] = saved_uis
                am = Message(
                    conversation_id=cid, role="assistant",
                    content_json=content_payload,
                    tool_calls_json={"trace": tool_traces} if tool_traces else None,
                    tokens_in=tokens_in, tokens_out=tokens_out,
                )
                session.add(am)
                session.add(CallLog(
                    user_id=user.id, agent_id=c.agent_id, conversation_id=cid,
                    model_id=ctx.model.id if ctx.model else None,
                    tokens_in=tokens_in, tokens_out=tokens_out, cache_hit_tokens=cache_hit_tokens, latency_ms=latency,
                    status=status_str, error=err,
                ))
                await session.commit()

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- Interactive permission decisions ----------
@router.post("/conversations/{cid}/permissions/{request_id}/decision")
async def decide_permission(
    cid: int, request_id: str, payload: PermissionDecisionIn,
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db),
):
    """Answer a pending tool-approval request raised by the runner's
    can_use_tool callback. The matching coroutine is blocked on a Future which
    this resolves, letting the agent turn continue."""
    c = (await db.execute(select(Conversation).where(
        Conversation.id == cid, Conversation.user_id == user.id))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "不存在")
    from ..runtime import permissions as perm
    behavior = payload.behavior if payload.behavior in ("allow", "deny") else "deny"
    scope = payload.scope if payload.scope in ("once", "session") else "once"
    ok = perm.resolve(request_id, {
        "behavior": behavior,
        "scope": scope,
        "message": payload.message or ("用户拒绝了此操作" if behavior == "deny" else None),
    })
    if not ok:
        # The request already timed out, was cancelled, or never existed.
        raise HTTPException(409, "该授权请求已失效")
    return {"ok": True}
