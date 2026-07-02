"""Runtime engine abstraction.

The goal: the rest of the app talks to a *stable* streaming contract
(`AgentRunner.stream()` yielding `StreamEvent`s) and never cares which
underlying agent runtime actually executes the turn. New engines
(Claude Code CLI, Codex CLI, or whatever appears next) plug in by
implementing `RuntimeEngine` and registering themselves — no changes to
chat.py / task_runner.py / bridge_manager.py are required.

Design pillars
--------------
1. Protocol, not inheritance — an engine is anything with `name`,
   `capabilities` and an async `stream(runner, user_text, files)` that
   yields our canonical `StreamEvent`s.
2. Capability matrix — engines advertise what they natively support
   (skills / mcp / permission gating / thinking budget …). The runner
   and adapters consult this instead of hard-coding provider names, so
   feature gaps are filled by adapters rather than by `if provider == …`.
3. Config is the source of truth — every engine receives the same
   `AgentContext` (model / skills / mcps / packs / workspace). Reusing
   your model management + plugins across engines is just a matter of
   each engine mapping that context into its own launch format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Protocol, runtime_checkable

if TYPE_CHECKING:  # avoid a runtime import cycle with agent_runner
    from ..agent_runner import AgentRunner, StreamEvent


@dataclass(frozen=True)
class EngineCapabilities:
    """What an engine can do natively.

    Anything set to False means "the engine can't do this on its own";
    the runner/adapters decide whether to emulate it (e.g. expose skills
    as MCP tools) or to degrade gracefully.
    """

    # Executes path-based Skills (.claude/skills + SKILL.md) natively.
    native_skills: bool = False
    # Speaks MCP directly (can be handed our MCP server configs).
    native_mcp: bool = False
    # Has an interactive per-tool permission/approval mechanism.
    permission_gating: bool = False
    # Supports an extended-thinking / reasoning-effort budget.
    thinking_budget: bool = False
    # Can operate inside a bound local working directory (task mode).
    workspace_fs: bool = False
    # Runs as an out-of-process CLI (subprocess) rather than in-process.
    out_of_process: bool = False
    # The engine uses its OWN pre-configured model (e.g. the local `claude` /
    # `codex` CLI's mounted account/model). When True, the app does NOT pass the
    # agent's model/api_key to it — the model choice belongs to the CLI, so the
    # UI hides model selection for agents on this engine.
    self_managed_model: bool = False
    # Free-form notes for operators / UIs.
    notes: str = ""


@runtime_checkable
class RuntimeEngine(Protocol):
    """A pluggable execution engine for an agent turn.

    Implementations receive the fully-built `AgentRunner` (which owns the
    `AgentContext`, token counters, file-registration helpers, permission
    queue, etc.) and yield canonical `StreamEvent`s. Keeping the runner as
    the argument means engines can reuse every existing helper
    (`_save_output_file`, `_register_mcp_files`, `_build_openai_tools` …)
    without duplicating that logic.
    """

    #: Stable identifier used for registration + agent.engine_kind lookup.
    name: str

    #: Human-facing label for admin UIs.
    label: str

    #: Native feature matrix (see EngineCapabilities).
    capabilities: EngineCapabilities

    def supports(self, ctx: "AgentContext") -> bool:  # noqa: F821
        """Return True if this engine can run the given context.

        Lets the registry pick a fallback when, say, a CLI binary is
        missing on the host. Default engines just return True.
        """
        ...

    def stream(
        self,
        runner: "AgentRunner",
        user_text: str,
        files: list[dict[str, Any]],
    ) -> "AsyncIterator[StreamEvent]":
        """Yield canonical StreamEvents for one agent turn."""
        ...


@dataclass
class _BaseEngine:
    """Convenience base so concrete engines only implement `stream`.

    Provides sane defaults for `supports`, availability detection and an
    install hint. In-process engines are always available; out-of-process
    engines override `required_binary` so availability is probed on the
    host with `shutil.which`.
    """

    name: str
    label: str
    capabilities: EngineCapabilities = field(default_factory=EngineCapabilities)
    #: CLI executable this engine drives. Empty → in-process (always available).
    required_binary: str = ""
    #: Shown in the UI when the engine is NOT available, so a user on a fresh
    #: machine knows how to install it (e.g. an npm one-liner).
    install_hint: str = ""
    #: Optional docs URL for the install instructions.
    install_url: str = ""
    #: Package manager used for auto-install ("npm" | "" ). Empty → no auto-install.
    install_manager: str = ""
    #: Exact package name to install (validated against a whitelist server-side).
    install_package: str = ""

    def is_available(self) -> bool:
        """True if this engine can actually run on THIS host.

        In-process engines: always. Out-of-process engines: only when their
        CLI binary is discoverable on PATH (or the common ~/.local, npm-global
        install locations).
        """
        if not self.required_binary:
            return True
        import shutil
        from pathlib import Path

        if shutil.which(self.required_binary):
            return True
        # Mirror the locations Claude Agent SDK / npm global installs use, so a
        # binary present but not on the server process PATH still counts.
        home = Path.home()
        candidates = [
            home / ".local/bin" / self.required_binary,
            home / ".npm-global/bin" / self.required_binary,
            home / "node_modules/.bin" / self.required_binary,
            Path("/usr/local/bin") / self.required_binary,
            Path("/opt/homebrew/bin") / self.required_binary,
        ]
        return any(p.exists() for p in candidates)

    def supports(self, ctx: Any) -> bool:  # pragma: no cover - trivial
        # The registry uses this to decide whether to fall back. An engine that
        # needs a missing binary shouldn't be selected.
        return self.is_available()

