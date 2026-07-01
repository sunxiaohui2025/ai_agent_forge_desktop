from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from ...db.session import get_db
from ...db.models import Agent, AgentSkill, AgentMCP, AgentPack, RoleAgentGrant, SolutionPack, Model, AgentCliApp
from ...deps import require_admin_or_operator
from ...services.audit import audit
from ...db.models import User
from ...schemas import AgentIn, AgentOut

router = APIRouter(prefix="/api/admin/agents", tags=["admin-agents"])


async def _to_out(db: AsyncSession, a: Agent) -> AgentOut:
    skill_ids = [r[0] for r in (await db.execute(select(AgentSkill.skill_id).where(AgentSkill.agent_id == a.id))).all()]
    mcp_ids = [r[0] for r in (await db.execute(select(AgentMCP.mcp_id).where(AgentMCP.agent_id == a.id))).all()]
    pack_ids = [r[0] for r in (await db.execute(select(AgentPack.pack_id).where(AgentPack.agent_id == a.id))).all()]
    role_ids = [r[0] for r in (await db.execute(select(RoleAgentGrant.role_id).where(RoleAgentGrant.agent_id == a.id))).all()]
    cli_app_ids = [r[0] for r in (await db.execute(select(AgentCliApp.cli_app_id).where(AgentCliApp.agent_id == a.id))).all()]
    out = AgentOut.model_validate(a, from_attributes=True)
    out.skill_ids = skill_ids
    out.mcp_ids = mcp_ids
    out.pack_ids = pack_ids
    out.role_ids = role_ids
    out.cli_app_ids = cli_app_ids
    return out


@router.get("", response_model=list[AgentOut])
async def list_agents(db: AsyncSession = Depends(get_db), _=Depends(require_admin_or_operator)):
    rows = (await db.execute(select(Agent).order_by(Agent.id))).scalars().all()
    return [await _to_out(db, a) for a in rows]


_ENGINE_SETTING_KEY = "runtime_engine"


async def _load_global_engine(db: AsyncSession) -> str | None:
    """Read the persisted global engine choice from SystemSetting."""
    from ...db.models import SystemSetting

    row = (await db.execute(
        select(SystemSetting).where(SystemSetting.key == _ENGINE_SETTING_KEY)
    )).scalar_one_or_none()
    if row is None:
        return None
    return (row.value_json or {}).get("engine") or None


@router.get("/_engines")
async def list_engines(db: AsyncSession = Depends(get_db), _=Depends(require_admin_or_operator)):
    """List runtime engines and the current global selection.

    Powers the 「执行引擎」 admin page. Each engine reports whether it is
    actually available on THIS machine (in-process engines always are;
    out-of-process CLI engines are probed for their binary) plus an install
    hint for engines that aren't installed yet. `current` is the global
    engine applied to every agent (empty → 自动/按 provider 推断).
    """
    from ...runtime import engines as _engines

    # Keep the in-process cache in sync with what's persisted.
    current = await _load_global_engine(db)
    _engines.set_global_default(current)

    items = []
    for e in _engines.all_engines():
        c = e.capabilities
        manager = getattr(e, "install_manager", "") or ""
        package = getattr(e, "install_package", "") or ""
        items.append({
            "name": e.name,
            "label": e.label,
            "available": e.is_available(),
            "required_binary": getattr(e, "required_binary", "") or "",
            "install_hint": getattr(e, "install_hint", "") or "",
            "install_url": getattr(e, "install_url", "") or "",
            "install_manager": manager,
            "can_auto_install": bool(manager == "npm" and package),
            "out_of_process": c.out_of_process,
            "capabilities": {
                "native_skills": c.native_skills,
                "native_mcp": c.native_mcp,
                "permission_gating": c.permission_gating,
                "thinking_budget": c.thinking_budget,
                "workspace_fs": c.workspace_fs,
                "out_of_process": c.out_of_process,
                "notes": c.notes,
            },
        })
    return {"engines": items, "current": current or ""}


@router.get("/{aid}", response_model=AgentOut)
async def get_agent(aid: int, db: AsyncSession = Depends(get_db), _=Depends(require_admin_or_operator)):
    a = (await db.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
    if not a:
        raise HTTPException(404, "不存在")
    return await _to_out(db, a)


async def _set_relations(db: AsyncSession, agent_id: int, payload: AgentIn) -> None:
    await db.execute(delete(AgentSkill).where(AgentSkill.agent_id == agent_id))
    await db.execute(delete(AgentMCP).where(AgentMCP.agent_id == agent_id))
    await db.execute(delete(AgentPack).where(AgentPack.agent_id == agent_id))
    await db.execute(delete(RoleAgentGrant).where(RoleAgentGrant.agent_id == agent_id))
    await db.execute(delete(AgentCliApp).where(AgentCliApp.agent_id == agent_id))
    db.add_all([AgentSkill(agent_id=agent_id, skill_id=sid) for sid in payload.skill_ids])
    db.add_all([AgentMCP(agent_id=agent_id, mcp_id=mid) for mid in payload.mcp_ids])
    db.add_all([AgentPack(agent_id=agent_id, pack_id=pid) for pid in payload.pack_ids])
    db.add_all([RoleAgentGrant(role_id=rid, agent_id=agent_id) for rid in payload.role_ids])
    db.add_all([AgentCliApp(agent_id=agent_id, cli_app_id=cid) for cid in payload.cli_app_ids])


@router.post("", response_model=AgentOut)
async def create_agent(payload: AgentIn, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin_or_operator)):
    if (await db.execute(select(Agent).where(Agent.code == payload.code))).scalar_one_or_none():
        raise HTTPException(400, "code 已存在")
    if payload.is_default:
        await db.execute(update(Agent).values(is_default=False))
    data = payload.model_dump(exclude={"skill_ids", "mcp_ids", "pack_ids", "role_ids", "cli_app_ids"})
    a = Agent(**data)
    db.add(a)
    await db.flush()
    await _set_relations(db, a.id, payload)
    await audit(db, actor.id, "agent.create", target_type="agent", target_id=None)
    await db.commit(); await db.refresh(a)
    return await _to_out(db, a)


@router.patch("/{aid}", response_model=AgentOut)
async def update_agent(aid: int, payload: AgentIn, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin_or_operator)):
    a = (await db.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
    if not a:
        raise HTTPException(404, "不存在")
    if payload.is_default:
        await db.execute(update(Agent).where(Agent.id != aid).values(is_default=False))
    for k, v in payload.model_dump(exclude={"skill_ids", "mcp_ids", "pack_ids", "role_ids", "cli_app_ids"}).items():
        setattr(a, k, v)
    await _set_relations(db, a.id, payload)
    await audit(db, actor.id, "agent.update", target_type="agent", target_id=a.id)
    await db.commit(); await db.refresh(a)
    return await _to_out(db, a)


@router.delete("/{aid}")
async def delete_agent(aid: int, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin_or_operator)):
    a = (await db.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
    if not a:
        raise HTTPException(404, "不存在")
    await audit(db, actor.id, "agent.delete", target_type="agent", target_id=a.id)
    await db.delete(a); await db.commit()
    return {"ok": True}


class SetEngineIn(BaseModel):
    # None/"" → 跟随全局默认（不覆盖）；否则该智能体固定为此引擎
    engine_kind: str | None = None


def _validate_engine_or_400(kind: str):
    """Validate an engine name against the registry + availability. Returns the
    engine instance, or raises HTTP 400. Empty string is allowed (caller maps
    it to "follow default / clear")."""
    from ...runtime import engines as _engines

    eng = _engines.get(kind)
    if eng is None:
        raise HTTPException(400, f"未知的执行引擎: {kind}")
    if not eng.is_available():
        raise HTTPException(
            400,
            f"引擎「{eng.label}」在本机不可用，请先安装：{getattr(eng, 'install_hint', '') or eng.name}",
        )
    return eng


@router.put("/_engine", response_model=dict)
async def set_global_engine(
    payload: SetEngineIn,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin_or_operator),
):
    """Set the app-wide DEFAULT runtime engine.

    This is the baseline every agent follows unless it has its own override
    (`agent.engine_kind`). It does NOT overwrite per-agent overrides — agents
    with `engine_kind = NULL` follow this default; agents pinned to a specific
    engine keep their pin. Persisted to SystemSetting so it survives restart.
    Empty string / null → no explicit default (fall back to provider inference).
    """
    from ...db.models import SystemSetting
    from ...runtime import engines as _engines

    kind = (payload.engine_kind or "").strip()
    if kind:
        _validate_engine_or_400(kind)

    row = (await db.execute(
        select(SystemSetting).where(SystemSetting.key == _ENGINE_SETTING_KEY)
    )).scalar_one_or_none()
    if row is None:
        row = SystemSetting(key=_ENGINE_SETTING_KEY, value_json={"engine": kind})
        db.add(row)
    else:
        row.value_json = {**(row.value_json or {}), "engine": kind}
    _engines.set_global_default(kind or None)

    await audit(db, actor.id, "engine.set_global", target_type="system", target_id=None)
    await db.commit()
    return {"ok": True, "engine": kind or ""}


@router.patch("/{aid}/engine", response_model=AgentOut)
async def set_agent_engine(
    aid: int,
    payload: SetEngineIn,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin_or_operator),
):
    """Override (or clear) the runtime engine for a SINGLE agent.

    Empty string / null clears the override so the agent follows the global
    default again. A non-empty value pins this agent to that engine regardless
    of the default.
    """
    a = (await db.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
    if not a:
        raise HTTPException(404, "不存在")
    kind = (payload.engine_kind or "").strip()
    if kind:
        _validate_engine_or_400(kind)
    a.engine_kind = kind or None
    await audit(db, actor.id, "agent.set_engine", target_type="agent", target_id=a.id)
    await db.commit(); await db.refresh(a)
    return await _to_out(db, a)


@router.patch("/_engine/bulk", response_model=dict)
async def bulk_set_agent_engine(
    payload: SetEngineIn,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin_or_operator),
):
    """Apply one per-agent engine choice to ALL agents in one click.

    - Empty string / null → clears every agent's override so they all follow
      the app-wide default engine again.
    - A non-empty value → pins every agent to that specific engine.

    This only touches per-agent overrides (`agent.engine_kind`); the app-wide
    default set via PUT /_engine is unchanged.
    """
    kind = (payload.engine_kind or "").strip()
    if kind:
        _validate_engine_or_400(kind)
    await db.execute(update(Agent).values(engine_kind=(kind or None)))
    await audit(db, actor.id, "agent.bulk_set_engine", target_type="agent", target_id=None)
    await db.commit()
    total = len((await db.execute(select(Agent.id))).all())
    return {"ok": True, "engine": kind or "", "agents_updated": total}


@router.post("/_engines/{name}/install", response_model=dict)
async def install_engine(
    name: str,
    actor: User = Depends(require_admin_or_operator),
):
    """Auto-install an out-of-process engine's CLI via its declared package
    manager (npm). Only engines that declare a whitelisted install package can
    be installed; the package name is validated against the registry entry, so
    an arbitrary command can never be injected.
    """
    import asyncio
    import shutil
    from ...runtime import engines as _engines

    eng = _engines.get(name)
    if eng is None:
        raise HTTPException(404, f"未知的执行引擎: {name}")
    if eng.is_available():
        return {"ok": True, "already": True, "message": f"「{eng.label}」已安装"}

    manager = (getattr(eng, "install_manager", "") or "").strip().lower()
    package = (getattr(eng, "install_package", "") or "").strip()
    if manager != "npm" or not package:
        raise HTTPException(400, f"「{eng.label}」不支持自动安装，请参考安装文档手动安装")

    npm = shutil.which("npm")
    if not npm:
        raise HTTPException(
            400, "本机未找到 npm，请先安装 Node.js（含 npm）后再自动安装引擎")

    # Build argv explicitly (no shell) — package is a registry-declared constant,
    # never user-supplied free text, so injection is not possible.
    argv = [npm, "install", "-g", package]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out_b, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            raise HTTPException(504, "安装超时（>5 分钟），请检查网络或手动安装")
    except FileNotFoundError:
        raise HTTPException(400, "npm 不可用")

    tail = (out_b or b"").decode("utf-8", "replace")[-4000:]
    ok = proc.returncode == 0 and eng.is_available()
    if not ok:
        raise HTTPException(
            500,
            f"安装失败（exit={proc.returncode}）。日志尾部：\n{tail[-1500:]}",
        )
    return {"ok": True, "installed": True, "engine": name,
            "message": f"「{eng.label}」安装成功", "log_tail": tail[-1500:]}


# ── AI polish: refine description / system_prompt ──────────────────────────

class PolishIn(BaseModel):
    kind: str                # "description" | "system_prompt"
    text: str                # original text (may be empty)
    agent_name: str | None = None
    model_id: int | None = None   # which model to use; falls back to any configured


_DESCRIPTION_INSTRUCTION = (
    "你是资深产品经理，帮用户把智能体的「描述」润色得清晰、专业、易懂。"
    "要求：\n"
    "1. 用 1 句话概括这个智能体是做什么的，语言自然、突出亮点；\n"
    "2. 然后换行，给出正好 2 个「示例问题」，用 '- ' 开头，便于用户一眼看懂怎么用；\n"
    "3. 整段不超过 120 字，中文输出；不要出现 Markdown 标题、不要加引号、不要写「描述：」之类的前缀；\n"
    "4. 示例问题要具体可操作，贴合这个智能体的主要能力。"
)


_SYSTEM_PROMPT_INSTRUCTION = (
    "你是资深 Prompt 工程师，帮用户把一个智能体的 System Prompt 润色得更专业、结构化。"
    "要求：\n"
    "1. 用清晰的段落或要点分层（角色定位 / 能力范围 / 回答风格 / 约束）；\n"
    "2. 保留原意，不要发明用户没提过的具体业务规则；\n"
    "3. 中文输出；可以用 Markdown 轻量标记（- 列表），但不要整篇都是 #### 标题；\n"
    "4. 不要写多余的寒暄或解释，直接给最终 prompt 文本。"
)


@router.post("/polish")
async def polish_text(payload: PolishIn,
                      db: AsyncSession = Depends(get_db),
                      _: User = Depends(require_admin_or_operator)):
    kind = (payload.kind or "").strip().lower()
    if kind not in ("description", "system_prompt"):
        raise HTTPException(400, "kind 必须是 description 或 system_prompt")

    # Pick a model: explicit → any configured with API key
    if payload.model_id:
        m = (await db.execute(select(Model).where(Model.id == payload.model_id))).scalar_one_or_none()
    else:
        m = (await db.execute(
            select(Model).where(Model.api_key_enc.isnot(None)).order_by(Model.id)
        )).scalars().first()
    if not m:
        raise HTTPException(400, "未配置可用模型，无法润色")
    if not m.api_key_enc:
        raise HTTPException(400, "所选模型未配置 API Key")

    from ...core.crypto import decrypt_str
    api_key = decrypt_str(m.api_key_enc)

    instruction = _DESCRIPTION_INSTRUCTION if kind == "description" else _SYSTEM_PROMPT_INSTRUCTION
    user_block = (payload.text or "(用户尚未填写，请根据智能体名称合理生成)").strip()
    name_hint = f"智能体名称：{payload.agent_name.strip()}\n\n" if payload.agent_name else ""
    user_message = f"{name_hint}原文：\n{user_block}\n\n请输出润色后的最终文本，不要任何额外解释。"

    try:
        if m.provider == "anthropic":
            try:
                from anthropic import AsyncAnthropic  # type: ignore
            except ImportError:
                raise HTTPException(400, "anthropic SDK 未安装")
            kwargs = {"api_key": api_key}
            if m.base_url:
                kwargs["base_url"] = m.base_url
            client = AsyncAnthropic(**kwargs)
            resp = await client.messages.create(
                model=m.model_id, max_tokens=4000,
                system=instruction,
                messages=[{"role": "user", "content": user_message}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            finish_reason = getattr(resp, "stop_reason", "")
        else:
            from openai import AsyncOpenAI
            from ...runtime.agent_runner import AgentRunner
            base_url = m.base_url or AgentRunner.PROVIDER_BASE_URL.get(m.provider.lower())
            base_url = AgentRunner.normalize_base_url(base_url)
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            create_kwargs: dict = {
                "model": m.model_id, "max_tokens": 4000,
                "messages": [
                    {"role": "system", "content": instruction},
                    # `/no_think` is a qwen3 directive that skips the reasoning
                    # phase. Harmless on other providers (treated as plain text).
                    {"role": "user", "content": user_message + "\n/no_think"},
                ],
            }
            if m.extra_params_json:
                create_kwargs["extra_body"] = m.extra_params_json
            resp = await client.chat.completions.create(**create_kwargs)
            choice = resp.choices[0] if resp.choices else None
            msg = choice.message if choice else None
            text = (msg.content if msg else "") or ""
            # Some providers (DeepSeek-R1, qwen-thinking) put the answer in
            # reasoning_content; fall back to that if main content is empty.
            if not text and msg is not None:
                text = getattr(msg, "reasoning_content", "") or ""
            finish_reason = getattr(choice, "finish_reason", "")

        # Strip leaked reasoning blocks like <think>...</think> that some qwen
        # variants embed inline despite enable_thinking=False.
        import re as _re
        text = _re.sub(r"<think>[\s\S]*?</think>\s*", "", text or "", flags=_re.IGNORECASE).strip()

        if not text:
            hint = (
                "（上下文被推理过程消耗完了，请换一个非 reasoning 模型重试，"
                "或在该智能体配置里把默认模型换成普通对话模型）"
                if finish_reason == "length"
                else "（模型未返回内容，请检查模型配置或换一个模型）"
            )
            raise HTTPException(400, f"润色返回为空 {hint}")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"润色失败: {e}")

    return {"ok": True, "text": text}
