from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...db.models import Model, Agent
from ...deps import require_admin_or_operator
from ...db.models import User
from ...services.audit import audit

router = APIRouter(prefix="/api/admin/health", tags=["admin-health"])
log = logging.getLogger(__name__)

# Keep the probe snappy — a health page should not hang on a dead endpoint.
_PROBE_TIMEOUT = 12.0


async def _probe_model(m: Model) -> dict:
    """Lightweight connectivity check for one model.

    Sends a tiny completion and reports whether the provider answered. Returns
    {id, code, provider, model_id, ok, error}. Never raises.
    """
    out = {
        "id": m.id, "code": m.code, "provider": m.provider,
        "model_id": m.model_id, "enabled": bool(m.enabled),
        "ok": False, "error": "",
    }
    if not m.enabled:
        out["error"] = "已禁用"
        return out
    if not m.api_key_enc:
        out["error"] = "未配置 API Key"
        return out

    from ...core.crypto import decrypt_str
    try:
        api_key = decrypt_str(m.api_key_enc)
    except Exception:  # noqa: BLE001
        out["error"] = "API Key 解密失败"
        return out

    async def _call() -> None:
        if m.provider == "anthropic":
            try:
                from anthropic import AsyncAnthropic  # type: ignore
            except ImportError:
                raise RuntimeError("anthropic SDK 未安装")
            kwargs = {"api_key": api_key}
            if m.base_url:
                kwargs["base_url"] = m.base_url
            client = AsyncAnthropic(**kwargs)
            await client.messages.create(
                model=m.model_id, max_tokens=8,
                messages=[{"role": "user", "content": "ping"}],
            )
        else:
            from openai import AsyncOpenAI
            from ...runtime.agent_runner import AgentRunner
            base_url = m.base_url or AgentRunner.PROVIDER_BASE_URL.get(m.provider.lower())
            base_url = AgentRunner.normalize_base_url(base_url)
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            create_kwargs: dict = {
                "model": m.model_id, "max_tokens": 8,
                "messages": [{"role": "user", "content": "ping"}],
            }
            if m.extra_params_json:
                create_kwargs["extra_body"] = m.extra_params_json
            await client.chat.completions.create(**create_kwargs)

    try:
        await asyncio.wait_for(_call(), timeout=_PROBE_TIMEOUT)
        out["ok"] = True
    except asyncio.TimeoutError:
        out["error"] = f"连接超时（>{int(_PROBE_TIMEOUT)}s）"
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
    return out


@router.get("")
async def run_health_check(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin_or_operator),
):
    """Run all health checks and return a structured report.

    1. Model service — probe every configured model for connectivity.
    2. Expert agents — flag agents whose bound model is missing or unhealthy.
    """
    models = (await db.execute(select(Model).order_by(Model.id))).scalars().all()
    probes = await asyncio.gather(*[_probe_model(m) for m in models]) if models else []
    probe_by_id = {p["id"]: p for p in probes}

    providers = sorted({(m.provider or "").strip() for m in models if (m.provider or "").strip()})
    model_ok = sum(1 for p in probes if p["ok"])
    models_report = {
        "providers": len(providers),
        "provider_names": providers,
        "total": len(models),
        "ok": model_ok,
        "abnormal": len(models) - model_ok,
        "items": probes,
    }

    # Agents: evaluate model binding health against the probe results.
    agents = (await db.execute(select(Agent).order_by(Agent.id))).scalars().all()
    agent_items = []
    agent_abnormal = 0
    for a in agents:
        status, reason, model_code = "ok", "", None
        if not a.default_model_id:
            status, reason = "error", "未配置模型"
        else:
            p = probe_by_id.get(a.default_model_id)
            if p is None:
                status, reason = "error", "绑定的模型不存在"
            else:
                model_code = p["code"]
                if not p["ok"]:
                    status, reason = "error", f"模型异常：{p['error'] or '不可用'}"
        if status != "ok":
            agent_abnormal += 1
        agent_items.append({
            "id": a.id, "code": a.code, "name": a.name,
            "is_default": bool(a.is_default),
            "model_id": a.default_model_id, "model_code": model_code,
            "status": status, "reason": reason,
        })

    healthy_model_ids = [p["id"] for p in probes if p["ok"]]
    agents_report = {
        "total": len(agents),
        "ok": len(agents) - agent_abnormal,
        "abnormal": agent_abnormal,
        # Can only auto-fix when there is at least one working model to assign.
        "fixable": agent_abnormal if healthy_model_ids else 0,
        "has_healthy_model": bool(healthy_model_ids),
        "items": agent_items,
    }

    return {"models": models_report, "agents": agents_report}


class FixAgentsIn(BaseModel):
    # Optional: assign this specific (healthy) model. Otherwise pick the first one.
    model_id: int | None = None


@router.post("/fix-agents")
async def fix_agent_models(
    payload: FixAgentsIn,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_admin_or_operator),
):
    """Repair agents whose model binding is missing or unhealthy.

    Picks the first healthy model (or the caller-supplied one) and assigns it as
    the default model of every broken agent.
    """
    models = (await db.execute(select(Model).order_by(Model.id))).scalars().all()
    probes = await asyncio.gather(*[_probe_model(m) for m in models]) if models else []
    probe_by_id = {p["id"]: p for p in probes}
    healthy = [p for p in probes if p["ok"]]
    if not healthy:
        return {"ok": False, "fixed": 0, "reason": "没有可用的模型，请先在模型管理中配置并测试通过"}

    if payload.model_id is not None:
        target = probe_by_id.get(payload.model_id)
        if not target or not target["ok"]:
            return {"ok": False, "fixed": 0, "reason": "指定的模型不可用"}
        chosen = target
    else:
        chosen = healthy[0]

    agents = (await db.execute(select(Agent))).scalars().all()
    fixed = 0
    for a in agents:
        broken = (not a.default_model_id) or (a.default_model_id not in probe_by_id) \
            or (not probe_by_id[a.default_model_id]["ok"])
        if broken:
            a.default_model_id = chosen["id"]
            fixed += 1

    if fixed:
        await audit(db, actor.id, "health.fix_agents", target_type="agent", target_id=None)
        await db.commit()

    return {
        "ok": True, "fixed": fixed,
        "model_id": chosen["id"], "model_code": chosen["code"],
    }
