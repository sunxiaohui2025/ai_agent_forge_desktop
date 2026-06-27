"""Interactive permission approval for the Claude Agent SDK.

The SDK calls our ``can_use_tool`` callback whenever a tool is NOT auto-approved
by the active permission mode / allow rules. That callback runs *inside* the
SDK's message-iteration coroutine, so it must be able to:

  1. classify the tool request's risk,
  2. honour session-level "allow this kind for the rest of the session" grants,
  3. otherwise push a ``permission_request`` event out to the UI and block until
     the user answers via the decision endpoint.

This module owns the cross-coroutine plumbing (a request registry keyed by an
opaque ``request_id`` resolved with ``asyncio.Future``) and the risk classifier.

Modes (set per conversation in the composer dropdown):

  * ask  → every write / exec / network tool prompts the user; read-only tools
           are pre-approved by the allow list and never reach the callback.
  * auto → routine edits + safe shell commands auto-run; only HIGH-risk commands
           (rm -rf, sudo, mkfs, force push, drop database, writes outside the
           workspace, ...) prompt.
  * full → nothing prompts (SDK ``bypassPermissions``); a deny list still blocks
           the genuinely catastrophic commands.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field


# ── Risk classification ──────────────────────────────────────────────
# HIGH-risk shell patterns. These prompt even in `auto` mode and are the set a
# `full`-mode deny list should mirror. Kept deliberately conservative to avoid
# false positives on everyday commands.
_HIGH_RISK_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("递归强制删除 (rm -rf)", re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*-?[a-zA-Z]*[rf][a-zA-Z]*\b")),
    ("提权执行 (sudo / su)", re.compile(r"\b(sudo|su)\b")),
    ("磁盘格式化/写盘 (mkfs / dd)", re.compile(r"\b(mkfs(\.\w+)?|dd)\b")),
    ("写入设备节点 (> /dev/)", re.compile(r">\s*/dev/")),
    ("强制推送 (git push --force)", re.compile(r"git\s+push\b.*(--force|-f)\b")),
    ("重置工作区 (git reset --hard / clean -f)", re.compile(r"git\s+(reset\s+--hard|clean\s+-[a-zA-Z]*f)")),
    ("删除数据库 (DROP / TRUNCATE)", re.compile(r"\b(drop\s+(database|table|schema)|truncate\s+table)\b", re.I)),
    ("修改全局权限 (chmod -R 777 /)", re.compile(r"chmod\s+-R\s+777\s+/")),
    ("递归改属主 (chown -R ... /)", re.compile(r"chown\s+-R\b.*\s/(?:\s|$)")),
    ("关机/重启", re.compile(r"\b(shutdown|reboot|halt|poweroff)\b")),
    ("管道执行远程脚本 (curl|wget ... | sh)", re.compile(r"(curl|wget)\b.*\|\s*(sudo\s+)?(sh|bash|zsh)\b")),
    ("结束进程 (kill -9 / killall)", re.compile(r"\b(kill\s+-9|killall|pkill)\b")),
    ("清空文件系统根 (:(){ fork bomb } / > /)", re.compile(r":\(\)\s*\{|>\s*/(?:\s|$)")),
]

# Catastrophic commands that `full` mode must still refuse. These become SDK
# `disallowed_tools` Bash-scoped deny rules (blocked in EVERY mode incl. bypass).
CATASTROPHIC_DENY = [
    "Bash(rm -rf /*)",
    "Bash(rm -rf /)",
    "Bash(:(){ :|:& };:)",
    "Bash(mkfs*)",
    "Bash(dd if=*of=/dev/*)",
]

# Tool → risk level for non-Bash tools.
_WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}
_NET_TOOLS = {"WebFetch"}


@dataclass
class RiskInfo:
    level: str          # "low" | "medium" | "high"
    reason: str         # human-readable why
    summary: str        # short one-line description of the operation


def classify(tool_name: str, tool_input: dict) -> RiskInfo:
    """Classify a tool request's risk and produce a UI-friendly summary.

    Handles both the Claude Agent SDK tool names (Bash / Write / Edit / WebFetch)
    and the OpenAI-compatible workspace tool names (run_command / write_file)."""
    ti = tool_input or {}
    if tool_name in ("Bash", "run_command"):
        cmd = str(ti.get("command", "")).strip()
        desc = str(ti.get("description", "")).strip()
        summary = cmd if len(cmd) <= 300 else cmd[:300] + " …"
        for reason, pat in _HIGH_RISK_PATTERNS:
            if pat.search(cmd):
                return RiskInfo("high", reason, summary)
        return RiskInfo("medium", desc or "执行 Shell 命令", summary)
    if tool_name in _WRITE_TOOLS:
        path = str(ti.get("file_path", "") or ti.get("notebook_path", ""))
        verb = "覆盖写入" if tool_name == "Write" else "修改"
        return RiskInfo("medium", f"{verb}文件", path or tool_name)
    if tool_name == "write_file":
        return RiskInfo("medium", "写入文件", str(ti.get("path", "") or "write_file"))
    if tool_name in _NET_TOOLS:
        return RiskInfo("medium", "访问网络", str(ti.get("url", "") or "网络请求"))
    # MCP / connected-app / unknown tools: treat as medium so `ask` still gates them.
    return RiskInfo("medium", "调用工具", tool_name)


# Tools the OpenAI path must gate (mutating/exec). Read-only tools (read_file,
# list_dir) and pure UI tools are never gated.
OPENAI_GATED_TOOLS = frozenset({"run_command", "write_file"})


# ── Pending-request registry (cross-coroutine resolution) ────────────
@dataclass
class _Pending:
    future: "asyncio.Future[dict]"
    conversation_id: int | None
    tool_name: str


# request_id → _Pending
_PENDING: dict[str, _Pending] = {}

# conversation_id → set of "session-allow" grant keys (e.g. "Bash", "Write").
# Cleared implicitly when the backend restarts; good enough for a desktop app.
_SESSION_GRANTS: dict[int, set[str]] = {}


def session_grant_key(tool_name: str) -> str:
    """The bucket a 'allow for this session' decision applies to."""
    return tool_name


def has_session_grant(conversation_id: int | None, tool_name: str) -> bool:
    if conversation_id is None:
        return False
    return session_grant_key(tool_name) in _SESSION_GRANTS.get(conversation_id, set())


def add_session_grant(conversation_id: int | None, tool_name: str) -> None:
    if conversation_id is None:
        return
    _SESSION_GRANTS.setdefault(conversation_id, set()).add(session_grant_key(tool_name))


def register(conversation_id: int | None, tool_name: str) -> tuple[str, "asyncio.Future[dict]"]:
    """Create a pending approval and return (request_id, future)."""
    request_id = uuid.uuid4().hex
    fut: "asyncio.Future[dict]" = asyncio.get_running_loop().create_future()
    _PENDING[request_id] = _Pending(future=fut, conversation_id=conversation_id, tool_name=tool_name)
    return request_id, fut


def resolve(request_id: str, decision: dict) -> bool:
    """Resolve a pending approval from the decision endpoint.

    ``decision`` = {"behavior": "allow"|"deny", "scope": "once"|"session",
                    "message": str?}. Returns True if a pending request matched.
    """
    p = _PENDING.pop(request_id, None)
    if p is None:
        return False
    if decision.get("behavior") == "allow" and decision.get("scope") == "session":
        add_session_grant(p.conversation_id, p.tool_name)
    if not p.future.done():
        p.future.set_result(decision)
    return True


def cancel(request_id: str, message: str = "请求已取消") -> None:
    """Cancel a pending approval (e.g. the SSE client disconnected)."""
    p = _PENDING.pop(request_id, None)
    if p is None:
        return
    if not p.future.done():
        p.future.set_result({"behavior": "deny", "message": message})


def cleanup_conversation(conversation_id: int | None) -> None:
    """Drop session grants for a finished/cleared conversation."""
    if conversation_id is not None:
        _SESSION_GRANTS.pop(conversation_id, None)
