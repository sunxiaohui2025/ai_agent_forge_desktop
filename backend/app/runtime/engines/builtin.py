"""Built-in engines that wrap the existing AgentRunner streaming paths.

These are thin adapters: they delegate to the already-battle-tested
`_stream_via_sdk` and `_stream_via_openai` methods on AgentRunner. Wrapping
(rather than moving) that code keeps this refactor behaviour-preserving and
fully reversible — the engines are just a dispatch shell around what the
runner already does.

New out-of-process engines (Claude Code CLI, Codex CLI, …) live in their own
modules and follow the same shape, but launch a subprocess and translate its
event stream into StreamEvents instead of delegating inward.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator

from .base import EngineCapabilities, _BaseEngine

if TYPE_CHECKING:
    from ..agent_runner import AgentContext, AgentRunner, StreamEvent


def _provider_of(ctx: "AgentContext") -> str:
    """Lower-cased provider string of the context's model ("" if unknown)."""
    model = getattr(ctx, "model", None)
    return ((getattr(model, "provider", None) or "") if model else "").strip().lower()


class ClaudeAgentSDKEngine(_BaseEngine):
    """Anthropic path — drives Claude Code via the Claude Agent SDK.

    Full native support for Skills, MCP, interactive permission gating and
    an extended-thinking budget. This is the current default for
    `provider == "anthropic"`.

    Protocol constraint: the SDK spawns the `claude` CLI, which only speaks the
    Anthropic API protocol. Pointing it at an OpenAI-compatible model (Kimi /
    DeepSeek / GLM …) makes the CLI fail immediately (exit 1). So this engine
    only supports Anthropic-protocol models; for others the registry falls back
    to the OpenAI-compatible engine.
    """

    def supports(self, ctx: "AgentContext") -> bool:  # noqa: F821
        return _provider_of(ctx) == "anthropic"

    async def stream(
        self, runner: "AgentRunner", user_text: str, files: list[dict[str, Any]]
    ) -> "AsyncIterator[StreamEvent]":
        async for ev in runner._stream_via_sdk(user_text, files):
            yield ev


class OpenAICompatEngine(_BaseEngine):
    """OpenAI-compatible chat-completions loop (DeepSeek/Qwen/GLM/Kimi/…).

    Our own tool loop. Skills/MCP/workspace tools/built-in interaction tools
    are emulated via the function-calling bridge in `_build_openai_tools`, so
    every plugin you configured still works here — just executed in-process
    rather than by a native agent runtime.

    Protocol constraint: this loop talks the OpenAI chat-completions protocol,
    so it can't drive a pure Anthropic-protocol model. It accepts every
    non-Anthropic provider (and is the universal fallback).
    """

    def supports(self, ctx: "AgentContext") -> bool:  # noqa: F821
        return _provider_of(ctx) != "anthropic"

    async def stream(
        self, runner: "AgentRunner", user_text: str, files: list[dict[str, Any]]
    ) -> "AsyncIterator[StreamEvent]":
        async for ev in runner._stream_via_openai(user_text, files):
            yield ev


def build_builtin_engines() -> list[_BaseEngine]:
    """Instantiate the two engines that ship with the framework today.

    Both are IN-PROCESS: they're packaged inside the app (the Python SDK lib +
    our own OpenAI loop), so they're always available on any machine with no
    extra install. Out-of-process CLI engines (Claude Code / Codex) live in
    cli_engines.py and are detected from the local machine instead.
    """
    return [
        ClaudeAgentSDKEngine(
            name="claude-agent-sdk",
            label="Claude Agent SDK（内置默认）",
            capabilities=EngineCapabilities(
                native_skills=True,
                native_mcp=True,
                permission_gating=True,
                thinking_budget=True,
                workspace_fs=True,
                out_of_process=True,  # SDK spawns the Claude Code CLI
                notes="随应用打包的默认引擎，原生 Skills/MCP/权限门控。",
            ),
        ),
        OpenAICompatEngine(
            name="openai-compat",
            label="OpenAI 兼容循环（内置）",
            capabilities=EngineCapabilities(
                native_skills=False,   # emulated via function-calling bridge
                native_mcp=False,      # tools proxied in-process
                permission_gating=True,  # via _gate_openai_tool
                thinking_budget=True,    # via reasoning_effort mapping
                workspace_fs=True,       # via _exec_workspace_tool
                out_of_process=False,
                notes="随应用打包的自研工具循环，兼容任意 OpenAI 协议模型；插件通过函数调用桥接复用。",
            ),
        ),
    ]
