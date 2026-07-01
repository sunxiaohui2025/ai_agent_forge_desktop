"""Read-only discovery of locally-installed LLM configurations.

Scans config files written by common desktop LLM tools — Claude Code, Codex
(OpenAI's CLI) and CC Switch — and maps them into candidate `Model` rows so the
user can one-click import them into the admin model manager.

Design rules (important):
  * READ-ONLY. This module never writes to, locks, or migrates any of these
    external files. The SQLite reads use `mode=ro` + `immutable=1` URIs so we
    never contend with the owning app's write lock.
  * Non-fatal. Every source is wrapped in a try/except; a malformed or missing
    file yields no candidates rather than raising.
  * No auto-persist. We only *return* candidates. Importing into the DB is an
    explicit, user-confirmed action handled by the API layer.

The public entry point is `scan_local_models()`.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, TypedDict

log = logging.getLogger(__name__)


class LocalModelCandidate(TypedDict):
    source: str          # "claude-code" | "codex" | "cc-switch"
    source_label: str    # human-friendly, e.g. "CC Switch · claude"
    code: str            # suggested unique model code
    provider: str        # "anthropic" | "openai-compatible"
    model_id: str
    base_url: str | None
    api_key: str | None  # None when the source stored a placeholder / managed token
    needs_key: bool      # True when api_key is missing or a known placeholder


# Tokens that are placeholders / proxy-managed rather than real credentials.
_PLACEHOLDER_KEYS = {
    "", "proxy_managed", "vllm_api_key", "123", "your_api_key",
    "your-api-key", "sk-xxx", "changeme", "none", "null",
}


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _clean_key(raw: str | None) -> tuple[str | None, bool]:
    """Return (usable_key, needs_key). Placeholder tokens map to (None, True)."""
    if not raw:
        return None, True
    if raw.strip().lower() in _PLACEHOLDER_KEYS:
        return None, True
    return raw.strip(), False


# ── Claude Code: ~/.claude/settings.json ────────────────────────────────────
def _scan_claude_code() -> list[LocalModelCandidate]:
    out: list[LocalModelCandidate] = []
    path = _home() / ".claude" / "settings.json"
    if not path.is_file():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.debug("claude-code settings.json parse failed", exc_info=True)
        return out
    env = (data.get("env") or {}) if isinstance(data, dict) else {}
    base_url = env.get("ANTHROPIC_BASE_URL")
    key, needs_key = _clean_key(env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY"))
    model_keys = [
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_MODEL",
    ]
    seen: set[str] = set()
    for mk in model_keys:
        mid = env.get(mk)
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(LocalModelCandidate(
            source="claude-code",
            source_label="Claude Code",
            code=f"claude-code-{mid}",
            provider="anthropic",
            model_id=mid,
            base_url=base_url,
            api_key=key,
            needs_key=needs_key,
        ))
    return out


# ── Codex: ~/.codex/config.toml + ~/.codex/auth.json ─────────────────────────
def _scan_codex() -> list[LocalModelCandidate]:
    out: list[LocalModelCandidate] = []
    cfg_path = _home() / ".codex" / "config.toml"
    if not cfg_path.is_file():
        return out
    try:
        try:
            import tomllib  # py3.11+
        except ModuleNotFoundError:  # pragma: no cover
            import tomli as tomllib  # type: ignore
        cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        log.debug("codex config.toml parse failed", exc_info=True)
        return out

    model_id = cfg.get("model")
    if not model_id:
        return out
    provider_key = cfg.get("model_provider")
    providers = cfg.get("model_providers") or {}
    prov_cfg = providers.get(provider_key) if provider_key else None
    base_url = (prov_cfg or {}).get("base_url")

    key: str | None = None
    auth_path = _home() / ".codex" / "auth.json"
    if auth_path.is_file():
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
            key = auth.get("OPENAI_API_KEY")
        except Exception:
            log.debug("codex auth.json parse failed", exc_info=True)
    api_key, needs_key = _clean_key(key)

    out.append(LocalModelCandidate(
        source="codex",
        source_label="Codex",
        code=f"codex-{model_id}",
        provider="openai-compatible",
        model_id=model_id,
        base_url=base_url,
        api_key=api_key,
        needs_key=needs_key,
    ))
    return out


# ── CC Switch: ~/.cc-switch/cc-switch.db (SQLite, read-only) ─────────────────
def _cc_switch_db_paths() -> list[Path]:
    """Candidate DB locations across platforms."""
    paths = [_home() / ".cc-switch" / "cc-switch.db"]
    appdata = os.environ.get("APPDATA")
    if appdata:  # Windows
        paths.append(Path(appdata) / "cc-switch" / "cc-switch.db")
    paths.append(_home() / "Library" / "Application Support" / "cc-switch" / "cc-switch.db")
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in paths:
        if p.is_file() and str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def _parse_cc_switch_config(app_type: str, name: str, cfg: dict) -> "LocalModelCandidate | None":
    """Map one cc-switch provider `settings_config` blob to a candidate."""
    # Claude-style: {"env": {"ANTHROPIC_BASE_URL":..., "ANTHROPIC_AUTH_TOKEN":..., ...}}
    env = cfg.get("env") if isinstance(cfg, dict) else None
    if isinstance(env, dict) and any(k.startswith("ANTHROPIC_") for k in env):
        base_url = env.get("ANTHROPIC_BASE_URL")
        key, needs_key = _clean_key(env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY"))
        model_id = (
            env.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
            or env.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
            or env.get("ANTHROPIC_MODEL")
            or name
        )
        return LocalModelCandidate(
            source="cc-switch",
            source_label=f"CC Switch · {app_type}",
            code=f"ccswitch-{app_type}-{name}",
            provider="anthropic",
            model_id=model_id,
            base_url=base_url,
            api_key=key,
            needs_key=needs_key,
        )
    # OpenAI-completions style (openclaw etc.): {"baseUrl":..., "apiKey":..., "models":[{"id":...}]}
    base_url = cfg.get("baseUrl") if isinstance(cfg, dict) else None
    if base_url:
        key, needs_key = _clean_key(cfg.get("apiKey"))
        models = cfg.get("models") or []
        model_id = None
        if isinstance(models, list) and models:
            first = models[0]
            model_id = first.get("id") if isinstance(first, dict) else None
        model_id = model_id or name
        return LocalModelCandidate(
            source="cc-switch",
            source_label=f"CC Switch · {app_type}",
            code=f"ccswitch-{app_type}-{name}",
            provider="openai-compatible",
            model_id=model_id,
            base_url=base_url,
            api_key=key,
            needs_key=needs_key,
        )
    return None


def _scan_cc_switch() -> list[LocalModelCandidate]:
    out: list[LocalModelCandidate] = []
    for db_path in _cc_switch_db_paths():
        # Open strictly read-only + immutable so we never touch the file / WAL
        # and never contend with the running cc-switch process.
        uri = f"file:{db_path}?mode=ro&immutable=1"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=1.0)
        except Exception:
            log.debug("cc-switch db open failed: %s", db_path, exc_info=True)
            continue
        try:
            cur = conn.execute("SELECT app_type, name, settings_config FROM providers")
            for app_type, name, settings_config in cur.fetchall():
                try:
                    cfg = json.loads(settings_config)
                except Exception:
                    continue
                cand = _parse_cc_switch_config(str(app_type), str(name), cfg)
                if cand:
                    out.append(cand)
        except Exception:
            log.debug("cc-switch providers read failed", exc_info=True)
        finally:
            conn.close()
    return out


def scan_local_models() -> list[LocalModelCandidate]:
    """Scan all known local LLM tool configs. Read-only, never raises.

    Candidates are de-duplicated by (provider, base_url, model_id). When
    duplicates differ only by key availability, the one carrying a real key wins.
    """
    candidates: list[LocalModelCandidate] = []
    for scanner in (_scan_claude_code, _scan_codex, _scan_cc_switch):
        try:
            candidates.extend(scanner())
        except Exception:
            log.exception("local model scanner %s failed", scanner.__name__)

    deduped: dict[tuple, LocalModelCandidate] = {}
    for c in candidates:
        if not c["model_id"]:
            continue
        dkey = (c["provider"], (c["base_url"] or "").rstrip("/"), c["model_id"])
        prev = deduped.get(dkey)
        if prev is None or (prev["needs_key"] and not c["needs_key"]):
            deduped[dkey] = c
    return list(deduped.values())
