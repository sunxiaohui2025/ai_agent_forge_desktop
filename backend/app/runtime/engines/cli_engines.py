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

import asyncio
import json
import shutil
from typing import TYPE_CHECKING, Any, AsyncIterator

from .base import EngineCapabilities, _BaseEngine

if TYPE_CHECKING:
    from ..agent_runner import AgentRunner, StreamEvent


def _resolve_binary(name: str) -> str | None:
    """Find a CLI binary on PATH or in the common install dirs the SDK uses."""
    from pathlib import Path

    if (p := shutil.which(name)):
        return p
    home = Path.home()
    for cand in (
        home / ".local/bin" / name,
        home / ".npm-global/bin" / name,
        home / "node_modules/.bin" / name,
        Path("/usr/local/bin") / name,
        Path("/opt/homebrew/bin") / name,
    ):
        if cand.exists():
            return str(cand)
    return None


async def _collect_stderr(stream: Any, chunks: list[bytes]) -> None:
    if stream is None:
        return
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            return
        chunks.append(chunk)
        if sum(map(len, chunks)) > 64 * 1024:
            del chunks[:-8]


async def _stop_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


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


class ClaudeCodeCliEngine(_BaseEngine):
    """Drives the local `claude` CLI in headless streaming mode (B-plan).

    Model source: the CLI's OWN mounted account/model. We do NOT pass the
    agent's model / api_key / base_url — the model belongs to whatever the
    local `claude` login is configured with. That's why `self_managed_model`
    is True and the UI hides model selection for agents on this engine.

    Uses `claude -p <prompt> --output-format stream-json --verbose` and
    translates the emitted JSON events into our StreamEvents.
    """

    def supports(self, ctx: Any) -> bool:  # noqa: F821
        return self.is_available()

    async def stream(
        self, runner: "AgentRunner", user_text: str, files: list[dict[str, Any]]
    ) -> "AsyncIterator[StreamEvent]":
        from ..agent_runner import StreamEvent  # local import avoids cycle

        binary = _resolve_binary(self.required_binary or "claude")
        if not binary:
            yield StreamEvent("error", {"message": f"未找到本机 {self.required_binary} 命令"})
            return

        prompt = user_text
        if files:
            prompt += runner._render_attachments(files)

        mode = (runner.ctx.permission_mode or "ask").lower()
        cli_mode = {"auto": "acceptEdits", "full": "bypassPermissions"}.get(mode, "default")
        argv = [binary, "-p", prompt, "--output-format", "stream-json",
                "--verbose", "--include-partial-messages", "--permission-mode", cli_mode]
        cwd = (runner.ctx.workspace_dir or None)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,  # never block waiting on stdin
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        except Exception as e:  # noqa: BLE001
            yield StreamEvent("error", {"message": f"启动 {self.label} 失败: {e}"})
            return

        # Track whether we've seen incremental text_delta chunks. When partial
        # messages stream in, the CLI ALSO emits a final full `assistant` block
        # at end-of-turn — we must not replay that (it would duplicate the text).
        streamed_text = {"seen": False}
        assert proc.stdout is not None
        stderr_chunks: list[bytes] = []
        stderr_task = asyncio.create_task(_collect_stderr(proc.stderr, stderr_chunks))
        try:
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except Exception:
                    yield StreamEvent("text", {"text": line})
                    continue
                async for out in self._translate(evt, streamed_text):
                    yield out
            await proc.wait()
        finally:
            await _stop_process(proc)
            await stderr_task
        if proc.returncode not in (0, None):
            err = b"".join(stderr_chunks).decode("utf-8", "replace")
            if err.strip():
                yield StreamEvent("error", {
                    "message": f"{self.label} 退出码 {proc.returncode}: {err.strip()[:400]}",
                })

    async def _translate(
        self, evt: dict[str, Any], streamed_text: dict[str, bool] | None = None
    ) -> "AsyncIterator[StreamEvent]":
        """Translate one claude stream-json event into our StreamEvents.

        With --include-partial-messages the CLI emits `stream_event` wrappers
        carrying Anthropic's native SSE (content_block_delta with a text_delta)
        — those give us TRUE token-by-token streaming. It still emits a final
        full `assistant` block at end-of-turn; once we've streamed deltas we
        skip that block's text to avoid duplication (but still surface tool_use).

        Other typed events: system(init), user(tool_result), result(usage).
        """
        from ..agent_runner import StreamEvent  # local import avoids cycle

        etype = evt.get("type")
        if etype == "stream_event":
            # Anthropic native streaming event nested under `event`.
            inner = evt.get("event") or {}
            if inner.get("type") == "content_block_delta":
                delta = inner.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    if streamed_text is not None:
                        streamed_text["seen"] = True
                    yield StreamEvent("text", {"text": delta["text"]})
            return
        if etype == "assistant":
            msg = evt.get("message") or {}
            for block in (msg.get("content") or []):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text" and block.get("text"):
                    # Skip if we already streamed this text via deltas.
                    if streamed_text and streamed_text.get("seen"):
                        continue
                    yield StreamEvent("text", {"text": block["text"]})
                elif btype == "tool_use":
                    yield StreamEvent("tool_use", {
                        "id": block.get("id") or "",
                        "name": block.get("name") or "",
                        "input": block.get("input") or {},
                    })
        elif etype == "user":
            msg = evt.get("message") or {}
            for block in (msg.get("content") or []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content = block.get("content")
                    if isinstance(content, list):
                        content = " ".join(
                            b.get("text", "") for b in content if isinstance(b, dict)
                        )
                    yield StreamEvent("tool_result", {
                        "tool_use_id": block.get("tool_use_id") or "",
                        "content": content if isinstance(content, str) else str(content),
                    })
        elif etype == "result":
            usage = evt.get("usage") or {}
            if usage:
                yield StreamEvent("usage", {
                    "tokens_in": usage.get("input_tokens") or 0,
                    "tokens_out": usage.get("output_tokens") or 0,
                })


class CodexCliEngine(_BaseEngine):
    """Drives the local `codex` CLI in headless streaming mode (B-plan).

    Model source: the CLI's OWN mounted account/model (whatever `codex login`
    is configured with). We do NOT pass the agent's model / api_key — that's why
    `self_managed_model` is True and the UI hides model selection here.

    Uses `codex exec --json` which prints JSONL events to stdout, and translates
    them into our StreamEvents. Runs read-only sandboxed so a chat-mode turn can
    never gain unintended write/shell access; `--skip-git-repo-check` lets it run
    in a plain workspace dir that isn't a git repo.
    """

    def supports(self, ctx: Any) -> bool:  # noqa: F821
        return self.is_available()

    async def stream(
        self, runner: "AgentRunner", user_text: str, files: list[dict[str, Any]]
    ) -> "AsyncIterator[StreamEvent]":
        from ..agent_runner import StreamEvent  # local import avoids cycle

        binary = _resolve_binary(self.required_binary or "codex")
        if not binary:
            yield StreamEvent("error", {"message": f"未找到本机 {self.required_binary} 命令"})
            return

        prompt = user_text
        if files:
            prompt += runner._render_attachments(files)

        mode = (runner.ctx.permission_mode or "ask").lower()
        sandbox = {"auto": "workspace-write", "full": "danger-full-access"}.get(mode, "read-only")
        argv = [binary, "exec", "--json", "--skip-git-repo-check",
                "-s", sandbox, prompt]
        cwd = (runner.ctx.workspace_dir or None)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,  # never block waiting on stdin
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        except Exception as e:  # noqa: BLE001
            yield StreamEvent("error", {"message": f"启动 {self.label} 失败: {e}"})
            return

        assert proc.stdout is not None
        # Per-item cursor of already-emitted agent_message text. codex may send
        # item.updated (incremental) before item.completed; we emit only the
        # NEW suffix each time so text streams in and is never duplicated.
        emitted: dict[str, int] = {}
        stderr_chunks: list[bytes] = []
        stderr_task = asyncio.create_task(_collect_stderr(proc.stderr, stderr_chunks))
        try:
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                async for out in self._translate(evt, emitted):
                    yield out
            await proc.wait()
        finally:
            await _stop_process(proc)
            await stderr_task
        if proc.returncode not in (0, None):
            err = b"".join(stderr_chunks).decode("utf-8", "replace")
            if err.strip():
                yield StreamEvent("error", {
                    "message": f"{self.label} 退出码 {proc.returncode}: {err.strip()[:400]}",
                })

    async def _translate(
        self, evt: dict[str, Any], emitted: dict[str, int] | None = None
    ) -> "AsyncIterator[StreamEvent]":
        """Translate one codex JSONL event into our StreamEvents.

        codex emits: thread.started / turn.started (ignored), item.updated
        (incremental, on newer builds) and item.completed (final) for each item —
        agent_message = text, command/tool items = tool_use/tool_result —
        turn.completed (usage), error.

        For agent_message we stream by SUFFIX: `emitted` tracks how many chars of
        each item we've already sent, so an item.updated followed by a longer
        item.completed only yields the newly-added tail (true streaming when the
        build supports item.updated, single-shot otherwise — never duplicated).
        """
        from ..agent_runner import StreamEvent  # local import avoids cycle

        etype = evt.get("type")
        if etype in ("item.updated", "item.completed"):
            item = evt.get("item") or {}
            itype = item.get("type")
            if itype == "agent_message":
                text = item.get("text") or ""
                if text and emitted is not None:
                    key = item.get("id") or "_"
                    sent = emitted.get(key, 0)
                    if len(text) > sent:
                        emitted[key] = len(text)
                        yield StreamEvent("text", {"text": text[sent:]})
                elif text:
                    yield StreamEvent("text", {"text": text})
            elif itype in ("command_execution", "local_shell_call", "function_call") \
                    and etype == "item.completed":
                cmd = item.get("command") or item.get("name") or ""
                yield StreamEvent("tool_use", {
                    "id": item.get("id") or "",
                    "name": itype,
                    "input": {"command": cmd} if cmd else (item.get("arguments") or {}),
                })
                out = item.get("aggregated_output") or item.get("output") or ""
                if out:
                    yield StreamEvent("tool_result", {
                        "tool_use_id": item.get("id") or "",
                        "content": out if isinstance(out, str) else str(out),
                    })
        elif etype == "turn.completed":
            usage = evt.get("usage") or {}
            if usage:
                yield StreamEvent("usage", {
                    "tokens_in": usage.get("input_tokens") or 0,
                    "tokens_out": usage.get("output_tokens") or 0,
                })
        elif etype == "error":
            msg = evt.get("message") or evt.get("error") or "codex error"
            yield StreamEvent("error", {"message": str(msg)})


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
        ClaudeCodeCliEngine(
            name="claude-code-cli",
            label="Claude Code CLI",
            required_binary="claude",
            install_hint="npm install -g @anthropic-ai/claude-code",
            install_url="https://docs.anthropic.com/claude-code",
            install_manager="npm",
            install_package="@anthropic-ai/claude-code",
            capabilities=EngineCapabilities(
                native_skills=True, native_mcp=True, permission_gating=False,
                thinking_budget=True, workspace_fs=True, out_of_process=True,
                self_managed_model=True,  # uses the local claude login's model
                notes="本机 Claude Code 命令行；使用其自身挂载的模型/账号，不使用应用内配置的模型。",
            ),
        ),
        _PendingCliEngine and None  # (kept above as a template for future engines)
        or CodexCliEngine(
            name="codex-cli",
            label="Codex CLI",
            required_binary="codex",
            install_hint="npm install -g @openai/codex",
            install_url="https://github.com/openai/codex",
            install_manager="npm",
            install_package="@openai/codex",
            capabilities=EngineCapabilities(
                native_mcp=True, workspace_fs=True, out_of_process=True,
                permission_gating=False, self_managed_model=True,
                notes="OpenAI Codex 命令行；使用其自身挂载的模型/账号，不使用应用内配置的模型。",
            ),
        ),
    ]
