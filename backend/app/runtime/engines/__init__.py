"""Pluggable runtime engines.

Importing this package registers every built-in engine. Third-party or
future engines register themselves the same way — call `register(...)`
at import time and make sure the module is imported once at startup.

Public surface:
    - RuntimeEngine, EngineCapabilities  (the contract)
    - register, get, select, all_engines  (the registry)
"""
from __future__ import annotations

from .base import EngineCapabilities, RuntimeEngine, _BaseEngine
from .builtin import build_builtin_engines
from .registry import (
    all_engines,
    get,
    get_global_default,
    register,
    resolve_name,
    select,
    set_global_default,
)

# Register built-ins exactly once on first import.
for _eng in build_builtin_engines():
    register(_eng)

# Future out-of-process engines (guarded so a missing optional dependency or
# absent CLI binary never breaks startup — they simply don't register):
try:  # pragma: no cover - optional
    from .cli_engines import build_cli_engines  # type: ignore

    for _eng in build_cli_engines():
        register(_eng)
except Exception:  # noqa: BLE001
    pass

__all__ = [
    "RuntimeEngine",
    "EngineCapabilities",
    "_BaseEngine",
    "register",
    "get",
    "select",
    "resolve_name",
    "all_engines",
    "get_global_default",
    "set_global_default",
]
