"""Out-of-process CLI engines (template + future home).

This module is the blueprint for plugging a *new* agent runtime into the
framework — e.g. Codex CLI, Gemini CLI, or whatever appears next — WITHOUT
touching agent_runner.py, chat.py, task_runner.py or the frontend.

An out-of-process engine differs from the built-in in-process engines in one
way: instead of delegating inward to an AgentRunner method, it launches a
subprocess, feeds it the prompt, and translates the subprocess's event stream
back into our canonical `StreamEvent`s.

To ship a real engine you implement four adapters, each reusing config the
framework already owns (so your model management + plugins carry over):

  1. Launch mapping   — AgentContext.model → env vars / CLI flags / config file
                        (api_key via decrypt_str, base_url, model_id).
  2. MCP mapping      — build_mcp_servers(ctx.mcps) → the engine's MCP config
                        (.mcp.json / config.toml). MCP is the most portable layer.
  3. Skill mapping    — path-based Skills → the engine's native skill dir if it
                        has one, else expose them as MCP tools / prompt injection.
  4. Event adapter    — parse the engine's stream (JSON lines, etc.) into
                        StreamEvent(type="text"|"tool_use"|"tool_result"|"usage"|"done").

Also map the engine's sandbox/approval model onto ctx.permission_mode so a
chat-mode turn can never gain unintended disk/shell access.

`build_cli_engines()` returns [] by default — no CLI engine is active until you
implement one and flip its availability check. The __init__ import is guarded,
so this file never breaks startup.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator

from .base import EngineCapabilities, _BaseEngine

if TYPE_CHECKING:
    from ..agent_runner import AgentRunner, StreamEvent


class _CliEngineTemplate(_BaseEngine):
    """Reference skeleton for a subprocess-backed engine.

    Copy this class, implement the four adapters described in the module
    docstring, and register it in `build_cli_engines()`. Availability is probed
    via `required_binary` on the base class (`shutil.which` + common install
    dirs), so an engine only offers itself when its CLI is actually installed.
    """

    async def stream(
        self, runner: "AgentRunner", user_text: str, files: list[dict[str, Any]]
    ) -> "AsyncIterator[StreamEvent]":
        # Real implementation outline:
        #   1. cfg = self._map_launch(runner.ctx)      # env/flags/config file
        #   2. self._write_mcp_config(runner.ctx)      # build_mcp_servers → file
        #   3. self._stage_skills(runner.ctx)          # skills → native dir / MCP
        #   4. proc = await asyncio.create_subprocess_exec(self.binary, *args, ...)
        #   5. async for line in proc.stdout: yield self._to_stream_event(line)
        #   6. reuse runner._save_output_file / _register_mcp_files for artifacts
        raise NotImplementedError(
            f"{self.name} engine is a template; implement stream() before registering."
        )


class _PendingCliEngine(_BaseEngine):
    """A detected-but-not-yet-wired CLI engine.

    Purpose: make locally-installed runtimes (Claude Code CLI, Codex) VISIBLE
    in the admin "执行引擎" page with correct availability + install hints,
    WITHOUT pretending they can already execute a turn. If a user switches to
    one before its adapter ships, we emit a clear, friendly error instead of
    crashing — and `supports()` returns False so the registry auto-falls-back
    to a working engine, keeping chat functional.
    """

    def supports(self, ctx: Any) -> bool:  # noqa: F821
        # Never auto-selected for real execution yet → registry falls back.
        return False

    async def stream(
        self, runner: "AgentRunner", user_text: str, files: list[dict[str, Any]]
    ) -> "AsyncIterator[StreamEvent]":
        from ..agent_runner import StreamEvent  # local import avoids cycle
        yield StreamEvent("error", {
            "message": (
                f"「{self.label}」引擎已在本机检测到，但执行适配仍在开发中。"
                f"已自动使用内置默认引擎继续。"
            ),
        })


def build_cli_engines() -> list[_BaseEngine]:
    """Return CLI engines to register at startup.

    These are OUT-OF-PROCESS engines read from the LOCAL machine — they are NOT
    bundled into the app. On a fresh machine they show as 未安装 with an install
    hint; once the user installs the CLI they flip to 可用 automatically (the
    base class probes `required_binary`).

    Currently registered as *pending* (visible + detectable, execution adapter
    in progress). To make one truly executable, subclass `_CliEngineTemplate`,
    implement `stream()` + the four adapters, and swap it in here.
    """
    return [
        _PendingCliEngine(
            name="claude-code-cli",
            label="Claude Code CLI",
            required_binary="claude",
            install_hint="npm install -g @anthropic-ai/claude-code",
            install_url="https://docs.anthropic.com/claude-code",
            install_manager="npm",
            install_package="@anthropic-ai/claude-code",
            capabilities=EngineCapabilities(
                native_skills=True, native_mcp=True, permission_gating=True,
                thinking_budget=True, workspace_fs=True, out_of_process=True,
                notes="本机 Claude Code 命令行；与内置 SDK 同源，直连 CLI 更贴近原生行为。",
            ),
        ),
        _PendingCliEngine(
            name="codex-cli",
            label="Codex CLI",
            required_binary="codex",
            install_hint="npm install -g @openai/codex",
            install_url="https://github.com/openai/codex",
            install_manager="npm",
            install_package="@openai/codex",
            capabilities=EngineCapabilities(
                native_mcp=True, workspace_fs=True, out_of_process=True,
                permission_gating=True,
                notes="OpenAI Codex 命令行；Skill 经 MCP 桥接，权限映射到 --sandbox。",
            ),
        ),
    ]
