"""Engine registry — the single extension point for new runtimes.

Adding a future engine is a two-step, zero-core-change operation:

    from .base import _BaseEngine, EngineCapabilities
    from .registry import register

    class MyFutureEngine(_BaseEngine):
        async def stream(self, runner, user_text, files):
            ...  # yield StreamEvent

    register(MyFutureEngine(name="my-future", label="My Future Engine",
                            capabilities=EngineCapabilities(...)))

The runner asks `select(ctx)` for the right engine; nothing else in the
codebase needs to know the engine exists.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import RuntimeEngine

if TYPE_CHECKING:
    from ..agent_runner import AgentContext

_log = logging.getLogger(__name__)

# name -> engine instance
_ENGINES: dict[str, RuntimeEngine] = {}

# Maps a Model.provider string to a default engine name. This preserves the
# current behaviour (provider drives routing) while we migrate toward an
# explicit `agent.engine_kind`. Extend this map when a new provider should
# default to a new engine.
_PROVIDER_DEFAULT_ENGINE: dict[str, str] = {
    "anthropic": "claude-agent-sdk",
    # everything OpenAI-compatible falls through to the openai loop engine
}

# Engine used when neither engine_kind nor provider yields a match.
_FALLBACK_ENGINE = "openai-compat"

# Process-wide global default engine. When set (non-empty), it takes priority
# over per-agent engine_kind and provider inference — this is what powers the
# "一键切换所有智能体" global selector. None/"" → fall back to per-agent logic.
# Cached in-process; the admin API refreshes it via `set_global_default` and it
# is re-hydrated from SystemSetting on startup.
_GLOBAL_DEFAULT: str | None = None


def set_global_default(name: str | None) -> None:
    """Set (or clear) the process-wide global default engine name."""
    global _GLOBAL_DEFAULT
    _GLOBAL_DEFAULT = (name or "").strip() or None


def get_global_default() -> str | None:
    return _GLOBAL_DEFAULT


def register(engine: RuntimeEngine, *, override: bool = False) -> None:
    """Register an engine instance under its `name`."""
    if engine.name in _ENGINES and not override:
        _log.warning("engine %r already registered; ignoring duplicate", engine.name)
        return
    _ENGINES[engine.name] = engine
    _log.info("registered runtime engine: %s (%s)", engine.name, engine.label)


def get(name: str) -> RuntimeEngine | None:
    return _ENGINES.get(name)


def all_engines() -> list[RuntimeEngine]:
    return list(_ENGINES.values())


def resolve_name(ctx: "AgentContext") -> str:
    """Decide which engine name should run this context.

    Priority (two-level model — a per-agent override always beats the default):
      1. explicit `agent.engine_kind` (this agent deviates from the default)
      2. process-wide global default (the app-wide 默认执行引擎), if registered
      3. provider → default-engine map (legacy behaviour)
      4. global fallback
    """
    engine_kind = (getattr(ctx.agent, "engine_kind", None) or "").strip().lower()
    if engine_kind and engine_kind in _ENGINES:
        return engine_kind
    if _GLOBAL_DEFAULT and _GLOBAL_DEFAULT in _ENGINES:
        return _GLOBAL_DEFAULT
    provider = ((ctx.model.provider if ctx.model else "") or "").strip().lower()
    if provider in _PROVIDER_DEFAULT_ENGINE:
        return _PROVIDER_DEFAULT_ENGINE[provider]
    return _FALLBACK_ENGINE


def select(ctx: "AgentContext") -> RuntimeEngine:
    """Return the engine that should execute this context.

    Falls back to the OpenAI-compatible engine when the chosen engine is
    unavailable on this host (e.g. a CLI binary isn't installed), so a
    missing optional engine never hard-fails a chat turn.
    """
    name = resolve_name(ctx)
    engine = _ENGINES.get(name)
    if engine is not None and engine.supports(ctx):
        return engine

    # Chosen engine missing or unusable (wrong protocol, missing binary, …).
    # Degrade intelligently: prefer the provider's default engine if it can run
    # this context, then any registered engine that supports it, then the
    # hard fallback. This guarantees we never hand back an engine that can't
    # drive the model (e.g. the OpenAI loop for a pure Anthropic model).
    if engine is None:
        _log.warning("engine %r not registered; searching for a compatible one", name)
    else:
        _log.warning("engine %r cannot run this context; searching for a compatible one", name)

    provider = ((ctx.model.provider if ctx.model else "") or "").strip().lower()
    provider_default = _PROVIDER_DEFAULT_ENGINE.get(provider)
    if provider_default:
        cand = _ENGINES.get(provider_default)
        if cand is not None and cand.supports(ctx):
            return cand

    for cand in _ENGINES.values():
        if cand.supports(ctx):
            return cand

    fallback = _ENGINES.get(_FALLBACK_ENGINE)
    if fallback is None:
        raise RuntimeError(
            f"No runtime engine available (wanted {name!r}, fallback "
            f"{_FALLBACK_ENGINE!r} not registered)."
        )
    return fallback
