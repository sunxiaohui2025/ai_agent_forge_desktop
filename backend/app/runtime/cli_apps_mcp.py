"""In-process MCP server exposing connected CLI apps to the agent.

When an agent has connected apps, we register an SDK MCP server named
`connected-apps` with two tools:
  • connected_apps_list  — enumerate the apps the agent may drive
  • connected_apps_run   — execute one connected app's CLI with args

Only apps explicitly connected to the agent (or selected for the turn) are
runnable, and only their declared binary may be invoked — the model passes
args, never an arbitrary command, so this can't become a generic shell.
"""
from __future__ import annotations
import asyncio
import os
import shlex
from typing import Any

from ..db.models import CliApp

MCP_SERVER_NAME = "connected-apps"


def _expanded_path() -> str:
    extra = [
        "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.npm-global/bin"),
    ]
    return os.pathsep.join(dict.fromkeys([*os.environ.get("PATH", "").split(os.pathsep), *extra]))


def cli_apps_system_prompt(apps: list[CliApp]) -> str:
    """A system-prompt block telling the model what apps it can drive."""
    usable = [a for a in apps if a.enabled and a.status == "installed"]
    if not usable:
        return ""
    lines = [
        "\n## 已连接的命令行应用（连接应用）",
        "你已连接以下本机命令行应用。当用户的问题适合用某个应用完成时，"
        "**调用 `connected_apps_run` 工具**实际执行它（传 app_key 和参数 args），不要只给操作教程：",
    ]
    for a in usable:
        ver = f" v{a.version}" if a.version else ""
        lines.append(f"- `{a.app_key}` — {a.name}{ver}：{a.summary or a.bin_name}")
    lines.append("先用 `connected_apps_list` 查看可用应用与状态；执行后把关键输出转述给用户。")
    return "\n".join(lines)


async def _run_cli(app: CliApp, args: list[str], workdir: str | None, timeout: float) -> dict[str, Any]:
    bin_path = app.bin_path or app.bin_name
    env = {**os.environ, "PATH": _expanded_path()}
    cwd = workdir if (workdir and os.path.isdir(workdir)) else None
    try:
        proc = await asyncio.create_subprocess_exec(
            bin_path, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=env, cwd=cwd,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": (out or b"").decode("utf-8", "replace")[-8000:],
            "stderr": (err or b"").decode("utf-8", "replace")[-4000:],
        }
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"执行超时（>{int(timeout)}s）"}
    except FileNotFoundError:
        return {"ok": False, "error": f"未找到可执行文件：{bin_path}，请先在「连接应用」里安装/检测"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def build_cli_apps_mcp_server(apps: list[CliApp], workspace_dir: str | None = None):
    """Create the SDK MCP server config, or None if no runnable apps."""
    usable = [a for a in apps if a.enabled and a.status == "installed"]
    if not usable:
        return None
    try:
        from claude_agent_sdk import create_sdk_mcp_server, tool
    except Exception:
        return None

    by_key = {a.app_key: a for a in usable}

    @tool(
        "connected_apps_list",
        "列出当前可调用的「连接应用」（命令行应用）及其状态。返回每个应用的 app_key、名称、用途说明。",
        {},
    )
    async def list_apps(args: dict[str, Any]) -> dict[str, Any]:
        lines = ["可调用的连接应用："]
        for a in usable:
            ver = f" v{a.version}" if a.version else ""
            lines.append(f"- {a.app_key} — {a.name}{ver}: {a.summary or a.bin_name}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "connected_apps_run",
        "执行一个已连接的命令行应用。app_key 为应用标识（来自 connected_apps_list）；"
        "args 为传给该命令的参数数组（不含命令本身），例如 ffmpeg 用 [\"-i\",\"a.mov\",\"a.mp4\"]。"
        "也可传字符串形式的 args，会按 shell 规则拆分。返回 stdout/stderr/exit_code。",
        {"app_key": str, "args": list, "workdir": str},
    )
    async def run_app(args: dict[str, Any]) -> dict[str, Any]:
        app_key = str(args.get("app_key") or "").strip()
        app = by_key.get(app_key)
        if not app:
            return {"content": [{"type": "text",
                    "text": f"应用 {app_key} 未连接或不可用。先调用 connected_apps_list 查看。"}],
                    "is_error": True}
        raw = args.get("args") or []
        if isinstance(raw, str):
            try:
                argv = shlex.split(raw)
            except ValueError:
                argv = raw.split()
        elif isinstance(raw, list):
            argv = [str(x) for x in raw]
        else:
            argv = []
        result = await _run_cli(app, argv, args.get("workdir") or workspace_dir, timeout=180.0)
        import json as _json
        return {
            "content": [{"type": "text", "text": _json.dumps(result, ensure_ascii=False)}],
            "is_error": not result.get("ok", False),
        }

    return create_sdk_mcp_server(name=MCP_SERVER_NAME, version="1.0.0",
                                 tools=[list_apps, run_app])
