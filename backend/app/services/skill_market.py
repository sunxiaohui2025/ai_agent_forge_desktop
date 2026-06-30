"""SkillHub market client (api.skillhub.cn).

Tencent's `skillhub` CLI is just a wrapper around a public HTTP API. We call
that API directly so installing a market skill works identically in dev and in
packaged Electron builds — no global CLI, no subprocess, no OpenClaw layout.

Flow for an install:
    1. GET /download?slug=<slug>   → application/zip (root contains SKILL.md)
    2. hand the zip bytes to the shared installer in api/admin/skills.py, which
       runs the same extract → security-scan → land-on-disk → DB-insert pipeline
       as a manual upload.

List/search/detail are proxied (and short-cached) so the admin can browse the
catalog inside our own UI. Field names differ between endpoints (search uses
`icon_url`, showcase uses `iconUrl`); `normalize_item` flattens both into one
stable contract the frontend can rely on.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import HTTPException

from ..core.config import settings

# Default browse sections exposed by /showcase/<section>.
SHOWCASE_SECTIONS = {"hot", "featured", "newest", "recommended", "trending"}

# Tiny in-process TTL cache for GET responses. Keyed by full URL. This is a
# best-effort cache to avoid hammering the remote on every keystroke / repaint;
# it is intentionally simple (no eviction beyond TTL check on read).
_cache: dict[str, tuple[float, Any]] = {}


def _base() -> str:
    return settings.SKILLHUB_API_BASE.rstrip("/")


def _ensure_enabled() -> None:
    if not settings.SKILLHUB_ENABLED:
        raise HTTPException(503, "SkillHub 市场未启用")


async def _get_json(url: str, params: dict[str, Any] | None = None,
                    *, use_cache: bool = True) -> Any:
    cache_key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    if use_cache:
        hit = _cache.get(cache_key)
        if hit and (time.time() - hit[0]) < settings.SKILLHUB_CACHE_TTL:
            return hit[1]
    try:
        async with httpx.AsyncClient(timeout=settings.SKILLHUB_TIMEOUT_SEC) as client:
            resp = await client.get(url, params=params)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"无法连接 SkillHub: {e}")
    if resp.status_code != 200:
        raise HTTPException(502, f"SkillHub 返回 {resp.status_code}")
    try:
        data = resp.json()
    except Exception:
        raise HTTPException(502, "SkillHub 返回了非 JSON 响应")
    if use_cache:
        _cache[cache_key] = (time.time(), data)
    return data


def normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten a search/showcase item into a stable frontend contract.

    search → `icon_url`, `owner_name`, `displayName`
    showcase → `iconUrl`, `ownerName`, `name`
    Descriptions: prefer the Chinese variant when present.
    """
    desc = raw.get("description_zh") or raw.get("description") or raw.get("summary") or ""
    return {
        "slug": raw.get("slug") or raw.get("name") or "",
        "name": raw.get("displayName") or raw.get("name") or raw.get("slug") or "",
        "description": desc,
        "icon": raw.get("icon_url") or raw.get("iconUrl") or "",
        "owner": raw.get("owner_name") or raw.get("ownerName") or "",
        "category": raw.get("category") or "",
        "downloads": raw.get("downloads") or 0,
        "installs": raw.get("installs") or 0,
        "stars": raw.get("stars") or 0,
        "version": raw.get("version") or "",
        "source": raw.get("source") or "",
        "homepage": raw.get("homepage") or "",
        "verified": bool(raw.get("verified")),
    }


async def list_skills(section: str, page: int, page_size: int) -> dict[str, Any]:
    """Default browse via /showcase/<section>. Showcase returns the full list,
    so we slice locally for pagination."""
    _ensure_enabled()
    if section not in SHOWCASE_SECTIONS:
        section = "hot"
    data = await _get_json(f"{_base()}/showcase/{section}")
    skills = data.get("skills", []) if isinstance(data, dict) else []
    total = data.get("total", len(skills)) if isinstance(data, dict) else len(skills)
    start = max(0, (page - 1) * page_size)
    items = [normalize_item(s) for s in skills[start:start + page_size]]
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "has_more": start + page_size < len(skills)}


async def search_skills(q: str, page: int, page_size: int) -> dict[str, Any]:
    """Keyword search via /search. The endpoint paginates server-side with
    page/limit and returns a flat `results` array."""
    _ensure_enabled()
    data = await _get_json(f"{_base()}/search",
                           {"q": q, "page": page, "limit": page_size})
    results = data.get("results", []) if isinstance(data, dict) else []
    items = [normalize_item(s) for s in results]
    return {"items": items, "total": len(items), "page": page, "page_size": page_size,
            "has_more": len(results) >= page_size}


async def detail(slug: str) -> dict[str, Any]:
    _ensure_enabled()
    data = await _get_json(f"{_base()}/skills/{slug}")
    if not isinstance(data, dict):
        raise HTTPException(404, "未找到该技能")
    latest = data.get("latestVersion") or {}
    owner = data.get("owner") or {}
    reports = data.get("securityReports") or {}
    # Surface Tencent's security report links (keen / sanbu) as extra context.
    security: list[dict[str, str]] = []
    for vendor, rep in reports.items():
        if isinstance(rep, dict):
            security.append({
                "vendor": vendor,
                "status": rep.get("status") or "",
                "status_text": rep.get("statusText") or "",
                "report_url": rep.get("reportUrl") or "",
            })
    return {
        "slug": slug,
        "version": latest.get("version") or "",
        "changelog": latest.get("changelog") or "",
        "owner": owner.get("displayName") or owner.get("handle") or "",
        "security_reports": security,
    }


async def download_zip(slug: str) -> bytes:
    """Fetch the skill package. Validates Content-Type and size guard."""
    _ensure_enabled()
    url = f"{_base()}/download"
    max_bytes = settings.SKILLHUB_MAX_PACKAGE_MB * 1024 * 1024
    try:
        async with httpx.AsyncClient(timeout=settings.SKILLHUB_TIMEOUT_SEC,
                                     follow_redirects=True) as client:
            async with client.stream("GET", url, params={"slug": slug}) as resp:
                if resp.status_code != 200:
                    raise HTTPException(502, f"下载失败: SkillHub 返回 {resp.status_code}")
                ctype = resp.headers.get("content-type", "")
                if "zip" not in ctype and "octet-stream" not in ctype:
                    raise HTTPException(502, f"下载返回了非 zip 内容: {ctype}")
                buf = bytearray()
                async for chunk in resp.aiter_bytes(1024 * 256):
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise HTTPException(
                            400,
                            f"技能包超过大小上限 {settings.SKILLHUB_MAX_PACKAGE_MB}MB")
                return bytes(buf)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"下载 SkillHub 技能包失败: {e}")
