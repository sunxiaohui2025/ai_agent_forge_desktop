from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ...db.session import get_db
from ...db.models import Model
from ...deps import require_admin_or_operator
from ...services.audit import audit
from ...db.models import User
from ...core.crypto import encrypt_str
from ...schemas import ModelIn, ModelOut, LocalModelCandidateOut, ModelImportIn

router = APIRouter(prefix="/api/admin/models", tags=["admin-models"])


def _norm_url(u: str | None) -> str:
    return (u or "").rstrip("/")


def _to_out(m: Model) -> ModelOut:
    return ModelOut(
        id=m.id, code=m.code, provider=m.provider, model_id=m.model_id,
        base_url=m.base_url, max_tokens=m.max_tokens, enabled=m.enabled,
        has_api_key=bool(m.api_key_enc),
        extra_params=m.extra_params_json or {},
    )


@router.get("", response_model=list[ModelOut])
async def list_models(db: AsyncSession = Depends(get_db), _=Depends(require_admin_or_operator)):
    rows = (await db.execute(select(Model).order_by(Model.id))).scalars().all()
    return [_to_out(r) for r in rows]


@router.get("/presets")
async def list_presets(_=Depends(require_admin_or_operator)):
    """Vendor presets for one-click model setup (select vendor → fill key)."""
    from ...services.provider_presets import PROVIDER_PRESETS
    return PROVIDER_PRESETS


@router.get("/discover", response_model=list[LocalModelCandidateOut])
async def discover_local_models(db: AsyncSession = Depends(get_db), _=Depends(require_admin_or_operator)):
    """Read-only scan of locally-installed LLM tools (Claude Code / Codex / CC
    Switch). Returns import candidates, marking those already present in the DB.

    This never writes to those external config files, and never persists here —
    importing is an explicit follow-up POST to /import.
    """
    from ...services.local_model_scan import scan_local_models
    candidates = scan_local_models()
    existing = (await db.execute(select(Model))).scalars().all()
    existing_keys = {(_norm_url(m.base_url), m.model_id) for m in existing}
    existing_codes = {m.code for m in existing}
    out = []
    for c in candidates:
        already = (
            (_norm_url(c["base_url"]), c["model_id"]) in existing_keys
            or c["code"] in existing_codes
        )
        out.append(LocalModelCandidateOut(
            source=c["source"], source_label=c["source_label"], code=c["code"],
            provider=c["provider"], model_id=c["model_id"], base_url=c["base_url"],
            needs_key=c["needs_key"], has_key=not c["needs_key"],
            already_imported=already,
        ))
    return out


@router.post("/import")
async def import_local_models(payload: ModelImportIn, db: AsyncSession = Depends(get_db),
                              actor: User = Depends(require_admin_or_operator)):
    """Import user-selected local candidates into the model manager.

    Skips items whose (base_url, model_id) or code already exists so re-running
    is safe. Codes are de-duplicated with a numeric suffix on collision.
    """
    existing = (await db.execute(select(Model))).scalars().all()
    existing_keys = {(_norm_url(m.base_url), m.model_id) for m in existing}
    used_codes = {m.code for m in existing}
    created, skipped = 0, 0
    for item in payload.items:
        if (_norm_url(item.base_url), item.model_id) in existing_keys:
            skipped += 1
            continue
        code = item.code
        if code in used_codes:
            i = 2
            while f"{code}-{i}" in used_codes:
                i += 1
            code = f"{code}-{i}"
        m = Model(
            code=code, provider=item.provider, model_id=item.model_id,
            base_url=item.base_url, max_tokens=item.max_tokens, enabled=True,
            api_key_enc=encrypt_str(item.api_key) if item.api_key else None,
            extra_params_json={},
        )
        db.add(m)
        used_codes.add(code)
        existing_keys.add((_norm_url(item.base_url), item.model_id))
        created += 1
    if created:
        await audit(db, actor.id, "model.import_local", target_type="model", target_id=None)
        await db.commit()
    return {"ok": True, "created": created, "skipped": skipped}


@router.post("", response_model=ModelOut)
async def create_model(payload: ModelIn, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin_or_operator)):
    if (await db.execute(select(Model).where(Model.code == payload.code))).scalar_one_or_none():
        raise HTTPException(400, "code 已存在")
    m = Model(
        code=payload.code, provider=payload.provider, model_id=payload.model_id,
        base_url=payload.base_url, max_tokens=payload.max_tokens, enabled=payload.enabled,
        api_key_enc=encrypt_str(payload.api_key) if payload.api_key else None,
        extra_params_json=payload.extra_params or {},
    )
    db.add(m)
    await audit(db, actor.id, "model.create", target_type="model", target_id=None)
    await db.commit()
    await db.refresh(m)
    return _to_out(m)


@router.patch("/{mid}", response_model=ModelOut)
async def update_model(mid: int, payload: ModelIn, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin_or_operator)):
    m = (await db.execute(select(Model).where(Model.id == mid))).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "不存在")
    m.code = payload.code
    m.provider = payload.provider
    m.model_id = payload.model_id
    m.base_url = payload.base_url
    m.max_tokens = payload.max_tokens
    m.enabled = payload.enabled
    m.extra_params_json = payload.extra_params or {}
    if payload.api_key:
        m.api_key_enc = encrypt_str(payload.api_key)
    await audit(db, actor.id, "model.update", target_type="model", target_id=m.id)
    await db.commit()
    await db.refresh(m)
    return _to_out(m)


@router.delete("/{mid}")
async def delete_model(mid: int, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin_or_operator)):
    m = (await db.execute(select(Model).where(Model.id == mid))).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "不存在")
    await db.delete(m)
    await audit(db, actor.id, "model.delete", target_type="model", target_id=m.id)
    await db.commit()
    return {"ok": True}


@router.post("/{mid}/test")
async def test_model(mid: int, db: AsyncSession = Depends(get_db), actor: User = Depends(require_admin_or_operator)):
    """Send a test prompt and return the model's reply."""
    m = (await db.execute(select(Model).where(Model.id == mid))).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "不存在")
    if not m.api_key_enc:
        raise HTTPException(400, "未配置 API Key")
    from ...core.crypto import decrypt_str
    api_key = decrypt_str(m.api_key_enc)
    question = "你是哪个大模型?"
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
                model=m.model_id, max_tokens=512,
                messages=[{"role": "user", "content": question}],
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            return {"ok": True, "question": question, "answer": text,
                    "tokens_in": resp.usage.input_tokens, "tokens_out": resp.usage.output_tokens}
        else:
            from openai import AsyncOpenAI
            from ...runtime.agent_runner import AgentRunner
            base_url = m.base_url or AgentRunner.PROVIDER_BASE_URL.get(m.provider.lower())
            base_url = AgentRunner.normalize_base_url(base_url)
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            create_kwargs: dict = {
                "model": m.model_id, "max_tokens": 512,
                "messages": [{"role": "user", "content": question}],
            }
            if m.extra_params_json:
                create_kwargs["extra_body"] = m.extra_params_json
            resp = await client.chat.completions.create(**create_kwargs)
            text = resp.choices[0].message.content if resp.choices else ""
            usage = resp.usage
            return {"ok": True, "question": question, "answer": text,
                    "tokens_in": usage.prompt_tokens if usage else 0,
                    "tokens_out": usage.completion_tokens if usage else 0}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"调用失败: {e}")
