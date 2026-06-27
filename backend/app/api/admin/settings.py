"""System-wide runtime settings (desktop personal-assistant mode).

Replaces backend/.env for config that users should own themselves — e.g. the
MinerU API key for document parsing. Config is persisted in the DB
(system_settings table) so it survives upgrades and is editable from the UI.
"""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.crypto import encrypt_str, decrypt_str
from ...db.models import SystemSetting, User
from ...db.session import get_db
from ...deps import current_user

router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])

_SETTING_KEY = "mineru"


class MineruSettings(BaseModel):
    mode: str = "cloud"            # "cloud" | "local" | "disabled"
    base_url: str = "https://mineru.net"
    api_key: str = ""              # write-only from the client side
    timeout_sec: int = 60
    has_api_key: bool = False      # read-side hint (never echoes the secret)


def _row_to_settings(row: SystemSetting | None) -> MineruSettings:
    if row is None:
        return MineruSettings()
    j = row.value_json or {}
    enc = row.value_enc
    api_key = ""
    if enc:
        try:
            api_key = decrypt_str(enc)
        except Exception:
            api_key = ""
    return MineruSettings(
        mode=str(j.get("mode") or "cloud"),
        base_url=str(j.get("base_url") or "https://mineru.net"),
        api_key=api_key,
        timeout_sec=int(j.get("timeout_sec") or 60),
        has_api_key=bool(api_key),
    )


async def get_mineru_settings_raw(db: AsyncSession) -> MineruSettings:
    """Read-side helper used by file_parser (no HTTP, no auth)."""
    row = (await db.execute(
        select(SystemSetting).where(SystemSetting.key == _SETTING_KEY)
    )).scalar_one_or_none()
    return _row_to_settings(row)


@router.get("/mineru", response_model=MineruSettings)
async def get_mineru(
    _user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current MinerU config. The API key is echoed so the user can
    review/edit it; this is a local single-user desktop app, not multi-tenant."""
    return _row_to_settings(
        (await db.execute(
            select(SystemSetting).where(SystemSetting.key == _SETTING_KEY)
        )).scalar_one_or_none()
    )


@router.put("/mineru", response_model=MineruSettings)
async def put_mineru(
    payload: MineruSettings,
    _user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        select(SystemSetting).where(SystemSetting.key == _SETTING_KEY)
    )).scalar_one_or_none()
    value_json = {
        "mode": payload.mode,
        "base_url": payload.base_url,
        "timeout_sec": payload.timeout_sec,
    }
    value_enc = encrypt_str(payload.api_key) if payload.api_key else None
    if row is None:
        row = SystemSetting(key=_SETTING_KEY, value_json=value_json, value_enc=value_enc)
        db.add(row)
    else:
        row.value_json = value_json
        row.value_enc = value_enc
    await db.commit()
    await db.refresh(row)
    return _row_to_settings(row)
