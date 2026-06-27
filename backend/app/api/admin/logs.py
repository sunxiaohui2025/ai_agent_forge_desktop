from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from ...db.session import get_db
from ...db.models import CallLog, AuditLog, User, Agent, Model
from ...deps import require_admin_or_operator
from ...schemas import CallLogOut, AuditLogOut, CallLogPage, AuditLogPage

router = APIRouter(prefix="/api/admin/logs", tags=["admin-logs"],
                   dependencies=[Depends(require_admin_or_operator)])


@router.get("/calls", response_model=CallLogPage)
async def list_call_logs(
    limit: int = Query(20, ge=1, le=500), offset: int = Query(0, ge=0),
    user_id: int | None = Query(None),
    agent_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    filters = []
    if user_id is not None:
        filters.append(CallLog.user_id == user_id)
    if agent_id is not None:
        filters.append(CallLog.agent_id == agent_id)

    total_q = select(func.count(CallLog.id))
    if filters:
        total_q = total_q.where(*filters)
    total = (await db.execute(total_q)).scalar_one()

    user_username = User.username.label("user_username")
    user_display = User.display_name.label("user_display")
    q = (
        select(
            CallLog,
            user_username,
            user_display,
            Agent.name.label("agent_name"),
            Model.code.label("model_code"),
            Model.model_id.label("model_model_id"),
            Model.provider.label("model_provider"),
        )
        .outerjoin(User, User.id == CallLog.user_id)
        .outerjoin(Agent, Agent.id == CallLog.agent_id)
        .outerjoin(Model, Model.id == CallLog.model_id)
    )
    if filters:
        q = q.where(*filters)
    q = q.order_by(desc(CallLog.id)).limit(limit).offset(offset)
    rows = (await db.execute(q)).all()

    items: list[CallLogOut] = []
    for log, uname, udisp, aname, mcode, mmid, mprov in rows:
        items.append(CallLogOut(
            id=log.id,
            user_id=log.user_id,
            user_name=udisp or uname,
            agent_id=log.agent_id,
            agent_name=aname,
            conversation_id=log.conversation_id,
            model_id=log.model_id,
            model_name=mcode or mmid,
            model_provider=mprov,
            tokens_in=log.tokens_in,
            tokens_out=log.tokens_out,
            cache_hit_tokens=log.cache_hit_tokens,
            latency_ms=log.latency_ms,
            status=log.status,
            error=log.error,
            created_at=log.created_at,
        ))
    return CallLogPage(items=items, total=total)


@router.get("/usage")
async def usage_stats(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Token usage statistics aggregated from CallLog over the last N days.

    Returns a summary + per-day series + per-model breakdown for the usage
    dashboard (replaces the old audit log view).
    """
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=days)

    base = select(CallLog).where(CallLog.created_at >= since)

    # Summary
    summ = (await db.execute(
        select(
            func.coalesce(func.sum(CallLog.tokens_in), 0),
            func.coalesce(func.sum(CallLog.tokens_out), 0),
            func.coalesce(func.sum(CallLog.cache_hit_tokens), 0),
            func.count(CallLog.id),
        ).where(CallLog.created_at >= since)
    )).one()
    total_in, total_out, total_cache_hit, total_calls = summ
    ok_calls = (await db.execute(
        select(func.count(CallLog.id)).where(CallLog.created_at >= since, CallLog.status == "ok")
    )).scalar_one()

    # Per-model breakdown
    model_rows = (await db.execute(
        select(
            Model.code, Model.provider,
            func.coalesce(func.sum(CallLog.tokens_in), 0),
            func.coalesce(func.sum(CallLog.tokens_out), 0),
            func.coalesce(func.sum(CallLog.cache_hit_tokens), 0),
            func.count(CallLog.id),
        )
        .outerjoin(Model, Model.id == CallLog.model_id)
        .where(CallLog.created_at >= since)
        .group_by(Model.code, Model.provider)
        .order_by(desc(func.sum(CallLog.tokens_in) + func.sum(CallLog.tokens_out)))
    )).all()
    by_model = [
        {"model": code or "未知", "provider": prov or "", "tokens_in": int(ti), "tokens_out": int(to), "cache_hit_tokens": int(ch), "calls": int(c)}
        for code, prov, ti, to, ch, c in model_rows
    ]

    # Per-day series (date string + summed tokens). SQLite: use strftime via func.
    day_expr = func.strftime("%Y-%m-%d", CallLog.created_at) if db.bind.dialect.name == "sqlite" \
        else func.to_char(CallLog.created_at, "YYYY-MM-DD")
    day_rows = (await db.execute(
        select(
            day_expr.label("d"),
            func.coalesce(func.sum(CallLog.tokens_in), 0),
            func.coalesce(func.sum(CallLog.tokens_out), 0),
            func.coalesce(func.sum(CallLog.cache_hit_tokens), 0),
            func.count(CallLog.id),
        )
        .where(CallLog.created_at >= since)
        .group_by("d").order_by("d")
    )).all()
    daily = [
        {"date": d, "tokens_in": int(ti), "tokens_out": int(to), "cache_hit_tokens": int(ch), "calls": int(c)}
        for d, ti, to, ch, c in day_rows
    ]

    return {
        "days": days,
        "summary": {
            "total_tokens_in": int(total_in),
            "total_tokens_out": int(total_out),
            "total_tokens": int(total_in) + int(total_out),
            "total_cache_hit_tokens": int(total_cache_hit),
            "total_calls": int(total_calls),
            "ok_calls": int(ok_calls),
            "error_calls": int(total_calls) - int(ok_calls),
        },
        "by_model": by_model,
        "daily": daily,
    }


@router.get("/audit", response_model=AuditLogPage)
async def list_audit_logs(
    limit: int = Query(20, ge=1, le=500), offset: int = Query(0, ge=0),
    user_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    filters = []
    if user_id is not None:
        filters.append(AuditLog.user_id == user_id)

    total_q = select(func.count(AuditLog.id))
    if filters:
        total_q = total_q.where(*filters)
    total = (await db.execute(total_q)).scalar_one()

    q = (
        select(
            AuditLog,
            User.username.label("user_username"),
            User.display_name.label("user_display"),
        )
        .outerjoin(User, User.id == AuditLog.user_id)
    )
    if filters:
        q = q.where(*filters)
    q = q.order_by(desc(AuditLog.id)).limit(limit).offset(offset)
    rows = (await db.execute(q)).all()

    items: list[AuditLogOut] = []
    for log, uname, udisp in rows:
        items.append(AuditLogOut(
            id=log.id,
            user_id=log.user_id,
            user_name=udisp or uname,
            action=log.action,
            target_type=log.target_type,
            target_id=log.target_id,
            detail_json=log.detail_json,
            created_at=log.created_at,
        ))
    return AuditLogPage(items=items, total=total)
