"""Agent runtime: bridges our config to the Claude Agent SDK.

This file isolates the SDK call so the rest of the app stays decoupled from SDK API
changes. The streaming generator yields events the API layer turns into SSE messages.

Note: claude-agent-sdk's exact public surface evolves. We use a thin facade so we can
adapt without rewriting callers.
"""
from __future__ import annotations
import asyncio
import json
import os
import time
import yaml
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator
from ..db.models import Agent, Skill, MCPConnector, Model, Message
from ..core.crypto import decrypt_str
from .dag_executor import DAGExecutor
from .mcp_manager import build_mcp_servers

_log = logging.getLogger(__name__)


def _os_isdir(p: str) -> bool:
    try:
        return os.path.isdir(p)
    except Exception:
        return False


def _parse_tool_arguments(raw: str | None) -> tuple[dict[str, Any], str]:
    """Parse a streamed tool-call ``arguments`` string into a dict + canonical JSON.

    Some models emit slightly malformed JSON when an argument carries a long body
    (e.g. a whole 公文/document passed to ``run_skill_script``): an unescaped inner
    quote or raw newline produces ``Expecting ',' delimiter`` errors. If we echo
    that broken string back to the gateway in the replayed assistant ``tool_calls``,
    the *next* request is rejected with HTTP 400. So we always re-serialize from a
    parsed object to guarantee valid JSON on the wire.

    Returns ``(args_dict, canonical_json_str)``. On total failure we wrap the raw
    text as ``{"raw": <text>}`` so downstream code still gets a clean string.
    """
    s = (raw or "").strip()
    if not s:
        return {}, "{}"
    # Fast path: already valid.
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj, json.dumps(obj, ensure_ascii=False)
    except Exception:
        pass
    # Repair path: escape raw control chars (newlines/tabs) that appear *inside*
    # JSON string values — the most common cause of model-emitted broken JSON.
    repaired = _repair_json_control_chars(s)
    try:
        obj = json.loads(repaired)
        if isinstance(obj, dict):
            return obj, json.dumps(obj, ensure_ascii=False)
    except Exception:
        pass
    # Last resort: forward the raw text under a single key so the wire stays valid.
    return {"raw": s}, json.dumps({"raw": s}, ensure_ascii=False)


def _repair_json_control_chars(s: str) -> str:
    """Escape literal control characters that occur inside JSON string values.

    Walks the text tracking whether we're inside a quoted string and whether the
    previous char was a backslash, replacing raw newlines / carriage returns / tabs
    with their escaped forms. Characters outside strings are left untouched.
    """
    out: list[str] = []
    in_str = False
    escaped = False
    for ch in s:
        if in_str:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_str = False
                out.append(ch)
                continue
            if ch == "\n":
                out.append("\\n"); continue
            if ch == "\r":
                out.append("\\r"); continue
            if ch == "\t":
                out.append("\\t"); continue
            out.append(ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    return "".join(out)

from .widget_guidelines import (
    WIDGET_SYSTEM_PROMPT,
    WIDGET_TOOL_DEFINITION,
    handle_widget_tool_call,
)

# Widget guidance — Skills take priority. Only injected when the user is
# asking for a visualization AND the agent has no skills loaded that might
# already handle it (e.g. `jiagoutu`). When skills are present, the model
# follows the skill's own SKILL.md instructions; widgets are the fallback
# path for agents that have no drawing skill configured.
_WIDGET_GUIDANCE = """
## 可视化输出指引（在没有更合适的 Skill 时使用）

当用户请求可视化（可视化 / 流程图 / 架构图 / 示意图 / SVG / 图表 / HTML / 网页 / 表单），
且你**没有更合适的 Skill** 来完成此任务时，且判断用户该任务的的预期答案是否更合适用可视化展示更清晰，更容易让人理解，上述这些情况下请使用 `show-widget` 围栏在聊天里直接渲染：

```show-widget
{"title":"标题","widget_code":"<svg ...>...</svg>"}
```

widget_code 是 JSON 字符串：所有引号转义为 `\\"`，换行转义为 `\\n`，不要 DOCTYPE/html/head/body。

### 使用 widget 时的要求
- **首要任务**：调用 `load_widget_guidelines` 后，必须使用 `show-widget` 围栏在聊天里直接渲染——这是用户看到的"动态生图过程"
- 不要在普通 ` ``` ` 代码块里输出 `<svg>` 源码（前端不会渲染）
- 渲染完成后，请在围栏外补充 2-4 句中文文字说明图的要点，让回答有完整闭环
- **可选**：渲染完成后，如果用户后续可能下载，可以再调用 `save_output_file` 把同一份代码存成 .html / .svg 文件（系统会自动识别 widget JSON 包裹并解出真实的 HTML / SVG，不会保存成不可预览的 .txt）；不需要下载时不必调用
- 顺序：调用 `load_widget_guidelines` → 输出 ` ```show-widget ` 围栏 → 围栏闭合后再写文字 → （可选）调用 `save_output_file` 提供下载

### 何时该走 Skill 而不是 widget
- 当智能体命中或者已加载了画图相关的 Skill（如 `jiagoutu`），按 Skill 自身的 SKILL.md 指令执行，此时Skill是主导，widget是辅助手段（比如 Skill 产出图的源码，交给 widget 渲染）
- 当用户明确要求"生成文件 / 下载 / .svg / .html 文件"时，按文件产出走 Skill 工作流
"""


# Keywords that indicate the user wants a visualization / widget. When a recent
# user turn matches, we inject WIDGET_SYSTEM_PROMPT + override into the system
# message. Otherwise we skip them — saves tokens and avoids biasing the model
# toward widgets on non-viz turns.
_VIZ_KEYWORDS_GENERAL = (
    "可视化", "visualize", "visualization",
    "图表", "chart", "graph", "plot",
    "流程图", "flowchart", "diagram", "时序图", "sequence",
    "架构图", "architecture",
    "示意图", "illustration",
    "曲线图", "折线图", "柱状图", "bar chart", "pie chart",
    "svg", "饼图",
    "widget", "interactive",
    "画一个", "画个", "draw", "create a chart", "render",
)
_VIZ_KEYWORDS_HTML = (
    "html", "html文件", "网页", "页面",
    "表单", "form",
    "标签页", "tabs", "accordion",
    "表格", "table", "grid",
    "交互", "interactive ui",
    "浏览器页面", "系统界面",
    "页面 demo", "页面demo",
    "解释下","说明下","讲解下","分析下",
)


def _wants_widget(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(k.lower() in low for k in _VIZ_KEYWORDS_GENERAL + _VIZ_KEYWORDS_HTML)


# Short hint describing the two built-in user-interaction tools so the model
# knows they exist. The tool schemas carry the full description; this block
# exists so the model reaches for them at the right time.
_USER_INTERACTION_GUIDANCE = """
## 需要用户参与决策时或者需要澄清一些需求（重要 · 强制规则）

`ask_user_pick` 和 `ask_user_form` 是平台**内置的用户交互工具**，**不是 Skill 也不是业务工具**。
即便用户说"不要使用 Skill / 不要使用工具"，你**仍然必须**调用这两个内置工具来向用户收集信息——
它们只是把"问问题"换成更友好的卡片/表单 UI，本质上等同于你"开口提问"，不属于 skill 范畴。

### 强制触发规则
- 需要用户从 ≥2 个候选里挑选 → **必须**调用 `ask_user_pick`；**禁止**让用户回复数字或文字。
- 需要用户补充 ≥2 个结构化字段（如：场景 / 目标用户 / 覆盖范围）才能继续 → **必须**调用
  `ask_user_form`；**禁止**用 Markdown 表格、有序列表或文字罗列问题让用户挨个回答。
- 只问 1 个简单字段时（如"您叫什么名字"），可以用文字问，不必动用工具。

### 调用后的行为
工具调用本身就是这一轮的输出。调用完**立即停止说话**（不要在 tool_call 之后继续追问文字）。
等用户在 UI 上提交，你会收到一条经过模板渲染的用户消息（包含字段值），再基于此继续推理。

### 反例（绝对不要这样做）
> 「在开始编写前，请先告诉我以下几个关键信息：
> | 问题 | 您的答案 |
> | --- | --- |
> | 应用场景 | … |
> | 目标用户 | … |」
（出现这种"列若干问题让用户回填"的形态时，**应当改为调用 `ask_user_form`**）

### 正例
调用 `ask_user_form(title="政务智能体方案 · 基础信息", fields=[
  {"id":"scenario", "label":"应用场景", "type":"Textarea", "required":true,
   "placeholder":"如：面向市民的社保咨询服务"},
  {"id":"target_user", "label":"目标用户", "type":"Input", "required":true},
  {"id":"scope", "label":"覆盖范围", "type":"Input"},
  {"id":"pain_point", "label":"核心痛点", "type":"Textarea"},
])`
"""

# Effort level → per-provider tuning.
# Canonical levels: low / medium / high / xhigh / max.
# For Anthropic (Claude Agent SDK): mapped to extended-thinking token budget.
# For OpenAI-compatible providers: mapped to `reasoning_effort`.
_EFFORT_THINKING_BUDGET: dict[str, int] = {
    "low": 2000,
    "medium": 8000,
    "high": 16000,
    "xhigh": 32000,
    "max": 64000,
}

_EFFORT_OPENAI_REASONING: dict[str, str] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}


def _effort_to_thinking_budget(effort: str) -> int | None:
    return _EFFORT_THINKING_BUDGET.get((effort or "medium").lower())


def _effort_to_openai_reasoning(effort: str) -> str | None:
    return _EFFORT_OPENAI_REASONING.get((effort or "medium").lower())


# Keywords in a Skill's name / code / description that indicate it already
# handles SVG/HTML diagram generation and would conflict with the widget
# pipeline. When matched, we DON'T inject the widget guidance — the model
# follows that Skill's own instructions instead.
#
# Keep this list narrow! Generic terms like "ppt" or "report" or the single
# character "画" are too aggressive — a PPT generator doesn't conflict with
# diagram rendering; they're different output categories. Only list things
# that are TRULY about drawing diagrams to disk.
_DRAWING_SKILL_HINTS = (
    "画图", "绘图", "架构图", "流程图", "时序图",
    "示意图", "可视化生成", "diagram generator", "svg generator",
)


def _agent_has_drawing_skill(skills: list[Skill]) -> bool:
    for s in skills or []:
        haystack = " ".join(filter(None, [s.code, s.name, s.description])).lower()
        if any(h.lower() in haystack for h in _DRAWING_SKILL_HINTS):
            return True
    return False


def _move_scripts_to_end(html: str) -> str:
    """Move every <script>...</script> block to just before </body>.

    Mirrors the widget iframe receiver's "DOM first, scripts last" strategy.
    Without this, a saved standalone .html file breaks when the model wrote
    its <script> at the top of the body — DOM elements referenced via
    document.getElementById are not yet in the tree, and onclick handlers
    can fire before the script's let/const declarations finish.

    Idempotent: if there's no <body>, returns html unchanged.
    """
    import re as _re
    if "<body" not in html.lower():
        return html
    # Extract all <script>...</script> blocks (with their attrs)
    script_pattern = _re.compile(r"<script\b[^>]*>[\s\S]*?</script>", _re.IGNORECASE)
    scripts = script_pattern.findall(html)
    if not scripts:
        return html
    stripped = script_pattern.sub("", html)
    # Insert scripts just before </body>; if no </body>, append at end.
    body_close = _re.search(r"</body\s*>", stripped, _re.IGNORECASE)
    block = "\n" + "\n".join(scripts) + "\n"
    if body_close:
        i = body_close.start()
        return stripped[:i] + block + stripped[i:]
    return stripped + block


def _prefix_mcp_actions(ui_schema: dict[str, Any], mcp_name: str) -> None:
    """Rewrite `action.tool` entries from bare names to `mcp__<server>__<tool>`.

    MCP authors often write `tool: "init_booking"` in their UI Schema actions
    without knowing about our `mcp__<server>__` namespacing. We rewrite in-place
    so the [UI_ACTION] router resolves back to THIS MCP, not a same-named tool
    elsewhere. Already-prefixed tool names (any `mcp__...`) are left alone.
    """
    prefix = f"mcp__{mcp_name}__"
    for a in (ui_schema.get("actions") or []):
        if not isinstance(a, dict):
            continue
        t = a.get("tool")
        if isinstance(t, str) and t and not t.startswith("mcp__"):
            a["tool"] = prefix + t


@dataclass
class AgentContext:
    agent: Agent
    skills: list[Skill]
    mcps: list[MCPConnector]
    packs: list[Any]  # SolutionPack rows
    model: Model | None
    fallback_model: Model | None
    history: list[Message]
    # Connected CLI apps the agent may drive (CliApp rows).
    cli_apps: list[Any] = None  # type: ignore[assignment]
    # Desktop "task" mode: when set, the agent operates inside this local
    # directory and gains file-system tools (Read/Write/Edit/Bash) governed
    # by `permission_mode`. None → plain chat (read-only safe tools).
    workspace_dir: str | None = None
    # ask / auto / full → SDK permission_mode. Only meaningful when
    # workspace_dir is set. None → fall back to "ask".
    permission_mode: str | None = None


@dataclass
class StreamEvent:
    type: str  # "text" | "tool_use" | "tool_result" | "error" | "done" | "usage"
    data: Any


class AgentRunner:
    """Wraps Claude Agent SDK invocation with our skill/MCP/model config."""

    def __init__(self, ctx: AgentContext, user_id: int | None = None):
        self.ctx = ctx
        self._tokens_in = 0
        self._tokens_out = 0
        self._cache_hit_tokens = 0
        self._user_id = user_id
        self._conversation_id: int | None = None
        # Interactive permission gating (set per-run in _stream_via_sdk).
        self._perm_mode: str = "chat"
        self._perm_active: bool = False
        self._perm_queue: "asyncio.Queue | None" = None
        self._pending_request_ids: set[str] = set()
        # Files saved during this run (to surface as file events to the UI)
        self._saved_files: list[dict[str, Any]] = []
        self._emitted_file_urls: set[str] = set()
        # UI Schemas emitted during this run (for chat.py to persist into history)
        self._saved_ui: list[dict[str, Any]] = []
        # Buffer of assistant text used by the stream-tail fallback extractor
        self._fallback_text_buf: list[str] = []
        # Single shared session workspace (lazily created). Lives UNDER
        # storage/outputs/<user>/ so every artifact is both (a) reachable as a
        # plain file by later skill scripts and (b) directly download-registrable
        # without copying. `save_output_file` and `run_skill_script` both write
        # here, so a file produced in one tool call (e.g. sources/slide-01.html)
        # is visible to a script in a later call (e.g. merge_deck.py) within the
        # same conversation — no need to re-pass content via the `files` param.
        self._session_workspace: str | None = None
        # Set to True the moment the model calls `load_widget_guidelines` —
        # signals "I'm rendering via widget pipeline this turn", so any later
        # save_output_file with widget-shaped content is rejected to avoid
        # the duplicated output-1.txt file card next to the rendered widget.
        self._widget_pipeline_active: bool = False

    async def _run_atomic_skill(self, skill: Skill, input_data: dict[str, Any]) -> dict[str, Any]:
        """Invoke an atomic skill out-of-band (used by composite DAG only)."""
        src = skill.source_json or {}
        if "callable" in src:
            # dotted path import: module.submod:func
            import importlib
            mod_path, _, func_name = src["callable"].partition(":")
            mod = importlib.import_module(mod_path)
            func = getattr(mod, func_name)
            result = func(**input_data) if not asyncio.iscoroutinefunction(func) else await func(**input_data)
            if not isinstance(result, dict):
                result = {"value": result}
            return result
        # path-based atomic skill: in MVP we only return a placeholder; real execution
        # happens via the SDK when the agent invokes it directly.
        return {"note": "atomic skill executed via SDK", "skill": skill.code, "input": input_data}

    async def _run_skill_by_code(self, skill_code: str, input_data: dict[str, Any]) -> dict[str, Any]:
        skill = next((s for s in self.ctx.skills if s.code == skill_code), None)
        if not skill:
            return {"error": f"skill not found: {skill_code}"}
        if skill.type == "atomic":
            return await self._run_atomic_skill(skill, input_data)
        # composite (nested)
        definition = yaml.safe_load(skill.source_json.get("yaml", "")) or {}
        executor = DAGExecutor(self._run_skill_by_code)
        return await executor.execute(definition, input_data)

    def _system_prompt(self, user_text: str | None = None) -> str:
        from ..core.security_rules import SAFETY_PREFIX
        # SAFETY_PREFIX is mandatory and comes first — per-agent prompts cannot weaken it.
        parts = [SAFETY_PREFIX]
        # Skills come first. We only inject the widget capability + guidance
        # when (1) the user is asking for a visualization AND (2) the agent
        # has no drawing-related Skill loaded. If a drawing Skill exists,
        # the model follows that Skill's own SKILL.md — widget is the
        # fallback path for skill-less agents.
        wants_viz = _wants_widget(user_text or "")
        has_drawing_skill = _agent_has_drawing_skill(self.ctx.skills)
        if wants_viz and not has_drawing_skill:
            parts.append(WIDGET_SYSTEM_PROMPT)
            parts.append(_WIDGET_GUIDANCE)
        if self.ctx.agent.system_prompt:
            parts.append(self.ctx.agent.system_prompt)
        # Task mode: tell the agent it has a working directory it can read/write.
        ws_dir = (self.ctx.workspace_dir or "").strip()
        if ws_dir and _os_isdir(ws_dir):
            mode = (self.ctx.permission_mode or "ask").lower()
            mode_zh = {"ask": "需谨慎", "auto": "可自动编辑", "full": "完全自主"}.get(mode, "需谨慎")
            parts.append(
                f"\n## 工作目录（重要）\n你**已经连接**到本地项目目录：`{ws_dir}`\n"
                f"你**拥有以下工具**，可以直接操作该目录中的文件，无需让用户手动操作，也不要说自己无法访问文件系统：\n"
                f"- `list_dir`：列出目录下的文件（查看“当前文件夹有什么”时直接调用它，参数 path 留空即可）\n"
                f"- `read_file`：读取文件内容（参数 path）\n"
                f"- `write_file`：创建或覆盖文件（参数 path、content）\n"
                f"- `run_command`：在该目录执行 shell 命令（参数 command）\n"
                f"所有路径都相对于该目录，禁止操作目录之外的文件。\n"
                f"当用户让你查看/创建/修改文件或运行命令时，**必须实际调用上述工具**完成，而不是给出操作教程。\n"
                f"当前执行权限：{mode_zh}。"
            )
        if self.ctx.skills:
            parts.append("\n## 你可使用的 Skills\n")
            for s in self.ctx.skills:
                tag = "组合" if s.type == "composite" else "原子"
                parts.append(f"- **{s.code}** ({tag}): {s.description or '(无描述)'}")
        # Built-in user-interaction guidance — always available, low overhead.
        parts.append(_USER_INTERACTION_GUIDANCE)
        # Connected CLI apps the agent may drive this turn.
        cli_apps = getattr(self.ctx, "cli_apps", None) or []
        if cli_apps:
            from .cli_apps_mcp import cli_apps_system_prompt
            block = cli_apps_system_prompt(cli_apps)
            if block:
                parts.append(block)
        return "\n".join(parts).strip()

    def _build_openai_tools(self, user_text: str | None = None) -> list[dict[str, Any]]:
        """Expose every enabled skill as an OpenAI function-calling tool.

        - composite           → executes the YAML DAG
        - atomic.callable     → invokes the Python function
        - atomic.path         → returns SKILL.md content + directory file listing,
                                so the model learns the skill's instructions and can
                                follow them in the same conversation. (mirrors Anthropic
                                Skill's "load-on-demand" semantics for OpenAI providers)

        `save_output_file` and `run_skill_script` are always registered so the
        user gets a downloadable file card whenever the model calls them. The
        widget pipeline still owns the in-chat rendering — for widget content
        the save handler unwraps the JSON envelope into a real .html/.svg.
        """
        tools: list[dict[str, Any]] = []
        # ── Workspace file tools (task mode only) ──
        # When the conversation is bound to a local working directory, expose
        # file-system tools to OpenAI-compatible models (GLM/DeepSeek/Kimi/…)
        # so they can actually read/write files and run commands — mirroring
        # the Anthropic SDK's Read/Write/Edit/Bash. Every call streams as a
        # tool_use/tool_result event so the user sees each action.
        ws_dir = (self.ctx.workspace_dir or "").strip()
        if ws_dir and _os_isdir(ws_dir):
            tools.append({
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "在当前工作目录中创建或覆盖一个文本文件。path 为相对工作目录的路径。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "相对工作目录的文件路径,如 abc.txt 或 src/main.py"},
                            "content": {"type": "string", "description": "完整文件内容"},
                        },
                        "required": ["path", "content"],
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "读取当前工作目录中某个文件的文本内容。",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string", "description": "相对工作目录的文件路径"}},
                        "required": ["path"],
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "list_dir",
                    "description": "列出当前工作目录(或其子目录)下的文件和文件夹。",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string", "description": "相对子目录,留空表示根目录"}},
                    },
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "在当前工作目录中执行一条 shell 命令并返回输出(stdout/stderr)。用于构建、测试、git 等操作。",
                    "parameters": {
                        "type": "object",
                        "properties": {"command": {"type": "string", "description": "要执行的 shell 命令"}},
                        "required": ["command"],
                    },
                },
            })
        for s in self.ctx.skills:
            tools.append({
                "type": "function",
                "function": {
                    "name": s.code,
                    "description": s.description or s.name,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input": {
                                "type": "object",
                                "description": "Skill 输入。对于路径式 atomic Skill,首次调用通常无需参数即可加载指令;之后再次调用可携带具体参数",
                            },
                        },
                        "additionalProperties": True,
                    },
                },
            })
        # Helper tool for reading additional files inside a path-based skill bundle
        if any(s.type == "atomic" and (s.source_json or {}).get("path") for s in self.ctx.skills):
            tools.append({
                "type": "function",
                "function": {
                    "name": "_read_skill_file",
                    "description": "读取已加载 Skill 目录下的具体资源文件(模板、脚本、参考资料等)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill": {"type": "string", "description": "Skill 的 code"},
                            "path": {"type": "string", "description": "相对 Skill 根目录的路径,如 templates/foo.html"},
                        },
                        "required": ["skill", "path"],
                    },
                },
            })
        # Universal output-file save tool — always available so the user gets
        # a downloadable file card whenever the model calls it. For widget JSON
        # content the save handler unwraps to a real .html/.svg automatically.
        tools.append({
            "type": "function",
            "function": {
                "name": "save_output_file",
                "description": (
                    "保存生成的文件并返回下载链接。"
                    "适用于 PPT(.html)、文档(.md/.docx)、PDF、代码、报告等任何需要交付给用户的产物。"
                    "调用本工具后,前端会显示一张文件卡片,用户可下载或在右侧分屏预览。"
                    "禁止把大段 HTML/Markdown/代码直接打字给用户 —— 一律改为调用本工具保存。"
                    "文件会写入本会话的共享工作区,后续 run_skill_script 可直接按相同相对路径读取本工具产生的文件。"
                    "因此制作多文件产物(如 PPT 的 sources/slide-01.html 等分页)时,可先用本工具逐个保存,"
                    "再调用对应 Skill 的合并/生成脚本读取它们,无需把内容重复塞进 run_skill_script 的 files 参数。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": (
                                "文件名,带扩展名,可包含子目录(相对路径)。"
                                "如 'agent-intro.html'、'report.md'、'sources/slide-01.html'。"
                                "不能以 / 开头,不能包含 .. 。同名再次保存视为覆盖(重新生成)。"
                            ),
                        },
                        "content": {
                            "type": "string",
                            "description": "完整文件内容(文本)。二进制请用 base64 编码并将 mime 设置正确。",
                        },
                        "mime": {
                            "type": "string",
                            "description": "可选,MIME 类型。留空自动按扩展名推断",
                        },
                        "encoding": {
                            "type": "string",
                            "description": "content 编码: 'utf-8' (默认) 或 'base64'",
                        },
                    },
                    "required": ["filename", "content"],
                },
            },
        })
        # Run a python script that's bundled inside a path-based atomic skill.
        # We call it as an in-process function (no Bash needed). The script must
        # expose a callable named `generate` or `run`; we run
        # it inside a sandboxed namespace so we don't pollute the parent process.
        if any(s.type == "atomic" and (s.source_json or {}).get("path") for s in self.ctx.skills):
            tools.append({
                "type": "function",
                "function": {
                    "name": "run_skill_script",
                    "description": (
                        "安全运行已加载 Skill 目录下的 Python 脚本。"
                        "脚本可导出 generate(**kwargs) 或 run(**kwargs)。"
                        "平台会注入可选的 output/output_path 供产物型脚本写文件；"
                        "也支持只返回结构化 JSON 的校验/计算型脚本。"
                        "脚本运行在本会话的共享工作区(workspace/workdir/cwd 均已注入其绝对路径),"
                        "因此可以直接读取本会话中 save_output_file 或先前 run_skill_script 产生的文件——"
                        "用相同的相对路径(如 sources/slide-01.html)即可,无需重复通过 files 传内容。"
                        "当 Skill 文档要求由脚本生成最终产物时,必须优先调用本工具,不要手动拼接最终文件。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill": {"type": "string", "description": "Skill 的 code"},
                            "script": {"type": "string",
                                        "description": "相对 Skill 根目录的脚本路径,如 scripts/merge_deck.py"},
                            "kwargs": {"type": "object",
                                        "description": "传给脚本 generate/run(**kwargs) 的参数字典"},
                            "files": {
                                "type": "array",
                                "description": (
                                    "可选。运行脚本前临时写入共享工作区的输入文件列表。"
                                    "仅在内容尚未通过 save_output_file 落盘时才需要;若文件已在本会话保存过,"
                                    "直接用相对路径引用即可,不必重复传。"
                                    "path 必须是相对路径,不能以 / 开头,不能包含 ..。"
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "path": {"type": "string", "description": "工作区内相对路径,如 sources/slide-01.html"},
                                        "content": {"type": "string", "description": "文件内容。文本默认 utf-8,二进制可 base64"},
                                        "encoding": {"type": "string", "description": "utf-8 或 base64,默认 utf-8"},
                                    },
                                    "required": ["path", "content"],
                                },
                            },
                            "workdir": {
                                "type": "string",
                                "description": "可选。脚本输入工作目录的相对路径,如 ai-tech-deck。会映射到共享工作区内的绝对路径。",
                            },
                            "output_filename": {"type": "string",
                                        "description": "可选。产物型脚本希望最终交付给用户的文件名,如 'slides.html'。"},
                        },
                        "required": ["skill", "script", "kwargs"],
                    },
                },
            })
        # Solution Packs: exposed as special async tools `run_pack__<pack_code>`.
        # LLM sees them alongside Skills/MCP and decides when a whole workflow is
        # more appropriate than a single Skill. Execution is synchronous for MVP:
        # tool_result returns only after the Pack finishes (or pauses on approval).
        for p in (self.ctx.packs or []):
            spec = p.spec_json or {}
            in_props = {}
            required = []
            for k, cfg in (spec.get("inputs") or {}).items():
                typ = (cfg or {}).get("type") or "string"
                json_type = {
                    "string": "string", "number": "number", "boolean": "boolean",
                    "list": "array", "object": "object", "daterange": "string",
                }.get(typ, "string")
                desc = (cfg or {}).get("description") or k
                in_props[k] = {"type": json_type, "description": desc}
                if (cfg or {}).get("required"):
                    required.append(k)
            tools.append({
                "type": "function",
                "function": {
                    "name": f"run_pack__{p.code}",
                    "description": (
                        f"执行方案包『{p.name}』。{p.description or ''} "
                        "适用于需要完整业务流程编排的场景,比单个 Skill 更适合。"
                    ).strip(),
                    "parameters": {
                        "type": "object",
                        "properties": in_props,
                        "required": required,
                    },
                },
            })
        # Generative-UI widget guidelines loader (always available)
        tools.append(WIDGET_TOOL_DEFINITION)

        # Built-in user-interaction tools (always available).
        # These are how the model can pause and ask the user something with
        # a clickable UI surface; the click submits a synthetic user message
        # the model picks up on the next turn.
        tools.append({
            "type": "function",
            "function": {
                "name": "ask_user_pick",
                "description": (
                    "向用户弹一个可点选的选项卡片列表，让用户从若干候选里挑一个（或多个）。"
                    "用户点击后，前端会把用户的选择以普通用户消息的形式提交给你（消息已模板化），"
                    "你在下一轮看到结果后再决定如何继续。"
                    "适用于『你找到了多个候选，需要用户挑一个再继续推理』的场景。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "卡片列表的标题，例如 '请选择城市'"},
                        "question": {"type": "string", "description": "可选，给用户的提示文案"},
                        "options": {
                            "type": "array",
                            "description": "候选项数组",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string", "description": "显示在卡片上的主标题"},
                                    "value": {"description": "选项的内部值（任意类型，原样回传给你）"},
                                    "description": {"type": "string", "description": "卡片副标题/简短说明"},
                                },
                                "required": ["label"],
                            },
                        },
                        "multi_select": {
                            "type": "boolean",
                            "description": "是否允许多选；默认 false",
                        },
                        "follow_up_template": {
                            "type": "string",
                            "description": (
                                "用户点击后回传给你的消息模板，支持 {{label}} {{value}} 占位符。"
                                "缺省为 '我选「{{label}}」'。"
                            ),
                        },
                    },
                    "required": ["title", "options"],
                },
            },
        })
        tools.append({
            "type": "function",
            "function": {
                "name": "ask_user_form",
                "description": (
                    "向用户弹出一个表单，让用户填若干字段后提交。"
                    "用户提交后，前端会把表单内容以普通用户消息的形式提交给你（消息已模板化），"
                    "你在下一轮看到结果后再决定如何继续。"
                    "适用于『需要用户先补充几条结构化信息才能继续』的场景。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "表单标题"},
                        "fields": {
                            "type": "array",
                            "description": "字段定义",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string", "description": "字段名（提交时用作 key）"},
                                    "label": {"type": "string", "description": "字段显示名"},
                                    "type": {
                                        "type": "string",
                                        "description": "Input / Textarea / InputNumber / Select / DatePicker / Radio / Checkbox",
                                    },
                                    "required": {"type": "boolean"},
                                    "placeholder": {"type": "string"},
                                    "default": {"description": "缺省值"},
                                    "options": {
                                        "type": "array",
                                        "description": "Select / Radio / Checkbox 的选项 [{label,value}]",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "label": {"type": "string"},
                                                "value": {},
                                            },
                                        },
                                    },
                                },
                                "required": ["id", "label", "type"],
                            },
                        },
                        "submit_label": {"type": "string", "description": "提交按钮文案，默认 '提交'"},
                        "follow_up_template": {
                            "type": "string",
                            "description": (
                                "表单提交后回传给你的消息模板。支持 {{字段名}} 占位符；"
                                "若不提供，前端会把整个表单 JSON 序列化后回传。"
                            ),
                        },
                    },
                    "required": ["title", "fields"],
                },
            },
        })
        # Connected CLI apps (连接应用) → expose run/list tools for OpenAI-compatible
        # models so a user question can trigger the app's CLI execution.
        cli_apps = getattr(self.ctx, "cli_apps", None) or []
        usable_apps = [a for a in cli_apps if a.enabled and a.status == "installed"]
        if usable_apps:
            tools.append({
                "type": "function",
                "function": {
                    "name": "connected_apps_list",
                    "description": "列出当前可调用的「连接应用」（命令行应用）及其状态。",
                    "parameters": {"type": "object", "properties": {}},
                },
            })
            tools.append({
                "type": "function",
                "function": {
                    "name": "connected_apps_run",
                    "description": (
                        "执行一个已连接的命令行应用。app_key 为应用标识；args 为传给命令的参数数组"
                        "（不含命令本身），如 ffmpeg 用 [\"-i\",\"a.mov\",\"a.mp4\"]。返回 stdout/stderr/exit_code。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "app_key": {"type": "string", "description": "连接应用的标识，来自 connected_apps_list"},
                            "args": {"type": "array", "items": {"type": "string"}, "description": "参数数组（不含命令本身）"},
                            "workdir": {"type": "string", "description": "可选，执行目录"},
                        },
                        "required": ["app_key"],
                    },
                },
            })
        return tools

    async def _pack_runner_factory(self, user_id: int | None = None, agent_id: int | None = None,
                                   conversation_id: int | None = None, override_agent_code: str | None = None):
        """Factory used by PackEngine to reuse existing skill/MCP execution helpers.

        MVP: just returns self, but a future version may construct a dedicated
        sub-runner or sub-agent based on override_agent_code.
        """
        self._conversation_id = conversation_id
        return self

    async def _exec_workspace_tool(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a workspace file/command tool inside the bound working dir.

        All paths are validated to stay within the workspace root. Returns a
        compact dict the model sees as the tool result; the streaming layer
        surfaces each call to the user as a tool_use/tool_result event.
        """
        from pathlib import Path as _Path
        import subprocess as _sp
        base_str = (self.ctx.workspace_dir or "").strip()
        if not base_str or not _os_isdir(base_str):
            return {"ok": False, "error": "未绑定有效的工作目录"}
        base = _Path(base_str).resolve()

        def _safe(rel: str) -> _Path:
            target = (base / (rel or "")).resolve()
            target.relative_to(base)  # raises ValueError on escape
            return target

        try:
            if tool == "write_file":
                rel = str(args.get("path") or "").strip()
                if not rel:
                    return {"ok": False, "error": "缺少 path"}
                target = _safe(rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                content = args.get("content")
                target.write_text(content if isinstance(content, str) else str(content or ""), encoding="utf-8")
                return {"ok": True, "path": rel, "bytes": target.stat().st_size,
                        "message": f"已写入 {rel}"}

            if tool == "read_file":
                target = _safe(str(args.get("path") or ""))
                if not target.is_file():
                    return {"ok": False, "error": "文件不存在"}
                data = target.read_text(encoding="utf-8", errors="replace")
                if len(data) > 60000:
                    data = data[:60000] + "\n…(已截断)"
                return {"ok": True, "path": str(args.get("path")), "content": data}

            if tool == "list_dir":
                target = _safe(str(args.get("path") or ""))
                if not target.is_dir():
                    return {"ok": False, "error": "目录不存在"}
                entries = []
                for name in sorted(os.listdir(target)):
                    full = target / name
                    entries.append({"name": name, "type": "dir" if full.is_dir() else "file"})
                return {"ok": True, "entries": entries}

            if tool == "run_command":
                cmd = str(args.get("command") or "").strip()
                if not cmd:
                    return {"ok": False, "error": "缺少 command"}
                proc = await asyncio.to_thread(
                    _sp.run, cmd, shell=True, cwd=str(base),
                    capture_output=True, text=True, timeout=120,
                )
                out = (proc.stdout or "")[-8000:]
                err = (proc.stderr or "")[-4000:]
                return {"ok": proc.returncode == 0, "exit_code": proc.returncode,
                        "stdout": out, "stderr": err}
        except ValueError:
            return {"ok": False, "error": "路径越界,已拒绝"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "未知工具"}

    async def _exec_connected_app(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Run a connected CLI app (连接应用) for OpenAI-compatible models."""
        import shlex as _shlex
        from .cli_apps_mcp import _run_cli
        apps = [a for a in (getattr(self.ctx, "cli_apps", None) or [])
                if a.enabled and a.status == "installed"]
        if tool == "connected_apps_list":
            if not apps:
                return {"apps": [], "note": "当前没有可用的连接应用"}
            return {"apps": [
                {"app_key": a.app_key, "name": a.name,
                 "version": a.version, "summary": a.summary or a.bin_name}
                for a in apps
            ]}
        # connected_apps_run
        app_key = str(args.get("app_key") or "").strip()
        app = next((a for a in apps if a.app_key == app_key), None)
        if not app:
            return {"ok": False, "error": f"应用 {app_key} 未连接或不可用，先调用 connected_apps_list 查看"}
        raw = args.get("args") or []
        if isinstance(raw, str):
            try:
                argv = _shlex.split(raw)
            except ValueError:
                argv = raw.split()
        elif isinstance(raw, list):
            argv = [str(x) for x in raw]
        else:
            argv = []
        workdir = args.get("workdir") or (self.ctx.workspace_dir or None)
        return await _run_cli(app, argv, workdir, timeout=180.0)

    async def _exec_skill(self, skill_code: str, args: dict[str, Any]) -> dict[str, Any]:
        # built-in helper for reading skill bundle files
        if skill_code == "_read_skill_file":
            return await self._read_skill_file(args.get("skill", ""), args.get("path", ""))

        # Workspace file tools (task mode, OpenAI-compatible path)
        if skill_code in ("write_file", "read_file", "list_dir", "run_command"):
            return await self._exec_workspace_tool(skill_code, args)

        # Universal output saver
        if skill_code == "save_output_file":
            return await self._save_output_file(
                filename=str(args.get("filename") or "output"),
                content=args.get("content") or "",
                mime=args.get("mime") or None,
                encoding=args.get("encoding") or "utf-8",
            )

        # Built-in user-interaction tools — produce a UI Schema with submit_as='message'
        # so a user click sends a synthetic user message back to the LLM next turn.
        if skill_code == "ask_user_pick":
            return self._build_ask_user_pick(args)
        if skill_code == "ask_user_form":
            return self._build_ask_user_form(args)

        # Connected CLI apps (连接应用) — run/list on the OpenAI-compatible path.
        if skill_code in ("connected_apps_list", "connected_apps_run"):
            return await self._exec_connected_app(skill_code, args)

        # Run a bundled Skill python script
        if skill_code == "run_skill_script":
            return await self._run_skill_script(
                skill=str(args.get("skill") or ""),
                script=str(args.get("script") or ""),
                kwargs=args.get("kwargs") or {},
                output_filename=args.get("output_filename") or None,
                files=args.get("files") or None,
                workdir=args.get("workdir") or None,
            )

        # Solution Pack runner (special tool injected as run_pack__<pack_code>)
        if skill_code.startswith("run_pack__"):
            from .pack_engine import PackEngine
            pack_code = skill_code.replace("run_pack__", "", 1)
            engine = PackEngine(runner_factory=self._pack_runner_factory)
            final = None
            async for ev in engine.start(pack_code, inputs=args or {},
                                         user_id=self._user_id,
                                         agent_id=getattr(self.ctx.agent, 'id', None),
                                         conversation_id=getattr(self, '_conversation_id', None)):
                final = ev.data
                if ev.type == 'pack_waiting_approval':
                    return {
                        'status': 'waiting_approval',
                        'run_id': ev.data.get('run_id'),
                        'pack_id': ev.data.get('pack_id'),
                        'message': ev.data.get('message') or '方案包等待审批',
                    }
                if ev.type == 'pack_error':
                    return {
                        'status': 'failed',
                        'run_id': ev.data.get('run_id'),
                        'pack_id': ev.data.get('pack_id'),
                        'error': ev.data.get('error'),
                    }
            return {
                'status': 'success',
                'run_id': (final or {}).get('run_id'),
                'pack_id': (final or {}).get('pack_id'),
                'outputs': (final or {}).get('outputs') or {},
                'trace': (final or {}).get('trace') or [],
            }

        # generative-UI widget guidelines loader
        if skill_code == "load_widget_guidelines":
            self._widget_pipeline_active = True
            return {"guidelines": handle_widget_tool_call(args)}

        skill = next((s for s in self.ctx.skills if s.code == skill_code), None)
        if not skill:
            return {"error": f"unknown skill: {skill_code}"}

        # path-based atomic skill: return SKILL.md + file listing so the model can follow instructions
        if skill.type == "atomic" and (skill.source_json or {}).get("path"):
            return await self._load_skill_bundle(skill)

        # callable / composite: actually execute
        trigger = args.get("input") if isinstance(args, dict) and "input" in args else args
        if not isinstance(trigger, dict):
            trigger = {"value": trigger}
        # Tasks are strictly per-user, but a callable Skill only sees the
        # model-supplied args. Inject the owner so 自动化任务生成器 can persist a
        # Task owned by the current user (the model never sees this field).
        if skill_code == "create_task":
            trigger = {**trigger, "_owner_user_id": self._user_id}
        result = await self._run_skill_by_code(skill_code, trigger)
        result = await self._register_skill_files(result)
        return result

    async def _register_skill_files(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            return result
        files = result.get("_files")
        if not isinstance(files, list) or not files:
            return result
        from pathlib import Path as _P
        from ..core.config import settings
        from ..db.session import SessionLocal
        from ..services.downloads import register_file
        outputs_root = (_P(settings.STORAGE_ROOT) / "outputs").resolve()
        registered = []
        async with SessionLocal() as db:
            for f in files:
                try:
                    fp = f.get("path") or ""
                    tok = await register_file(
                        db,
                        file_path=fp,
                        file_name=f.get("name") or "",
                        user_id=self._user_id,
                        mime=f.get("mime") or "application/octet-stream",
                    )
                    await db.commit()
                    item = {
                        "name": tok.file_name, "size": tok.size, "mime": tok.mime,
                        "download_url": f"/api/downloads/{tok.token}",
                    }
                    try:
                        rp = _P(fp).resolve().relative_to(outputs_root)
                        item["output_path"] = str(rp)
                    except (ValueError, OSError):
                        pass
                    registered.append(item)
                except Exception as e:  # noqa: BLE001
                    registered.append({"error": f"register failed: {e}"})
        result.pop("_files", None)
        # Expose only descriptive fields to the model; download_url is for the
        # UI file-card layer and would be rendered as broken markdown links.
        result["files"] = [
            {k: v for k, v in item.items() if k not in ("download_url",)}
            for item in registered
        ]
        return result

    async def _register_mcp_files(self, result: dict[str, Any]) -> dict[str, Any]:
        """Register files produced by an MCP tool call so they surface as
        downloadable cards in the chat UI.

        Each entry in `_files` may supply the content in one of three ways
        (tried in order):
          1. path       — absolute local path (same-host MCP only)
          2. content    — plain text string (written as UTF-8)
          3. content_b64 — base64-encoded bytes (written as binary)

        Looks for `_files` at the top level of `result` or nested under
        `result["data"]` (where `_call_mcp_tool_once` places parsed JSON).
        """
        if not isinstance(result, dict):
            return result
        candidates: list[tuple[dict, str]] = []
        if isinstance(result.get("_files"), list):
            candidates.append((result, "_files"))
        data = result.get("data")
        if isinstance(data, dict) and isinstance(data.get("_files"), list):
            candidates.append((data, "_files"))
        if not candidates:
            return result

        import base64 as _b64
        import mimetypes as _mt
        import uuid as _uuid
        from pathlib import Path as _P
        from ..core.config import settings
        from ..db.session import SessionLocal
        from ..services.downloads import register_file

        registered: list[dict[str, Any]] = []
        for container, key in candidates:
            files = container.get(key) or []
            async with SessionLocal() as db:
                for f in files:
                    if not isinstance(f, dict):
                        continue
                    name = str(f.get("name") or "file").strip()
                    mime = f.get("mime") or _mt.guess_type(name)[0] or "application/octet-stream"
                    try:
                        # ---- resolve content bytes ----
                        file_bytes: bytes | None = None
                        fp = str(f.get("path") or "").strip()
                        if fp:
                            abs_p = _P(fp).expanduser().resolve()
                            if abs_p.is_file():
                                file_bytes = abs_p.read_bytes()
                        if file_bytes is None and f.get("content_b64"):
                            file_bytes = _b64.b64decode(f["content_b64"])
                        if file_bytes is None and f.get("content") is not None:
                            file_bytes = str(f["content"]).encode("utf-8")
                        if file_bytes is None:
                            registered.append({"error": f"no content for file: {name}"})
                            continue

                        # ---- write to outputs dir ----
                        out_root = _P(settings.STORAGE_ROOT) / "outputs" / str(self._user_id or "anon")
                        out_root.mkdir(parents=True, exist_ok=True)
                        safe = _P(name).name or "output"
                        target = out_root / f"{_uuid.uuid4().hex[:8]}-{safe}"
                        target.write_bytes(file_bytes)

                        # ---- register download token ----
                        tok = await register_file(
                            db,
                            file_path=str(target),
                            file_name=name,
                            user_id=self._user_id,
                            mime=mime,
                        )
                        await db.commit()
                        info = {
                            "name": tok.file_name, "size": tok.size, "mime": tok.mime,
                            "download_url": f"/api/downloads/{tok.token}",
                            "preview_url": f"/api/downloads/{tok.token}",
                        }
                        registered.append(info)
                        self._saved_files.append(info)
                    except Exception as e:  # noqa: BLE001
                        registered.append({"error": f"register failed: {e}"})
            container.pop(key, None)
        if registered:
            # Strip download/preview URLs from what the model sees — the UI
            # renders file cards via _saved_files SSE events. Exposing raw
            # /api/downloads/ URLs causes the model to write them into reply
            # text as markdown links, which break when opened in the browser
            # without an auth header.
            result["files"] = [
                {k: v for k, v in f.items() if k not in ("download_url", "preview_url")}
                for f in registered
            ]
        return result

    async def _maybe_register_files_from_tool_result(self, content: str) -> None:
        """Anthropic-SDK path: tool_result content is a raw string. If the MCP
        tool returned JSON with a `_files` array, parse it and register the
        files so they appear as download cards. No-op for non-JSON content."""
        if not content or not self._user_id:
            return
        s = content.strip()
        if not (s.startswith("{") and s.endswith("}")):
            return
        try:
            import json as _json
            parsed = _json.loads(s)
        except Exception:
            return
        if not isinstance(parsed, dict):
            return
        await self._register_mcp_files(parsed)

    async def _load_skill_bundle(self, skill) -> dict[str, Any]:
        from pathlib import Path as _Path
        root = _Path(skill.source_json["path"])
        if not root.exists() or not root.is_dir():
            return {"error": f"skill directory missing: {root}"}
        skill_md_path = root / "SKILL.md"
        instructions = ""
        if skill_md_path.exists():
            try:
                instructions = skill_md_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:  # noqa: BLE001
                instructions = f"(failed to read SKILL.md: {e})"
        files: list[str] = []
        for p in root.rglob("*"):
            if p.is_file() and p.name != "SKILL.md":
                files.append(str(p.relative_to(root)))
                if len(files) >= 200:
                    break
        return {
            "skill": skill.code,
            "instructions": instructions,
            "files": files,
            "hint": ("阅读 instructions 中的 SKILL.md 指令并按要求继续执行任务。"
                     "如需读取其它文件,调用 _read_skill_file(skill, path)。"),
        }

    # ---------- Built-in user-interaction tools ----------
    def _build_ask_user_pick(self, args: dict[str, Any]) -> dict[str, Any]:
        """Build a CardList UI Schema for `ask_user_pick`.

        Each option becomes a card; clicking submits a synthetic user message
        rendered from `follow_up_template` (default: 我选「{{label}}」).
        """
        title = str(args.get("title") or "请选择")
        question = args.get("question")
        options = args.get("options") or []
        if not isinstance(options, list) or not options:
            return {"error": "ask_user_pick: options 不能为空"}
        multi = bool(args.get("multi_select"))
        # NOTE: multi-select via card click is awkward (no native checkbox state in
        # CardList). For the MVP we honor multi_select by switching to a form with
        # a checkbox group instead. Single-select is the common case.
        if multi:
            return self._build_ask_user_form({
                "title": title,
                "fields": [{
                    "id": "selected",
                    "label": question or title,
                    "type": "Checkbox",
                    "required": True,
                    "options": [{"label": str(o.get("label", "")), "value": o.get("value", o.get("label"))}
                                for o in options if isinstance(o, dict)],
                }],
                "follow_up_template": str(args.get("follow_up_template") or "我选了：{{selected}}"),
                "submit_label": "提交",
            })

        items = []
        for i, o in enumerate(options):
            if not isinstance(o, dict):
                continue
            items.append({
                "id": str(o.get("value", i)),
                "title": str(o.get("label", "")),
                "subtitle": str(o.get("description") or ""),
                "_label": str(o.get("label", "")),
                "_value": o.get("value", o.get("label", "")),
            })

        tpl = str(args.get("follow_up_template") or "用户通过 ask_user_pick 选择了「{{label}}」（value={{value}}），请基于此继续。")
        ui = {
            "message_type": "ui",
            "component_type": "CardList",
            "title": title,
            "data_model": {"items": items, "total": len(items)},
            "actions": [{
                "name": "pick",
                "label": "选择",
                "trigger": "card_click",
                "agent_call": True,
                "submit_as": "message",
                "params_from": "/items/{index}",
                "params_map": {"label": "/_label", "value": "/_value"},
                "message_template": tpl,
            }],
        }
        # __halt__ tells the multi-turn loop to stop here and wait for the user's
        # next message (the form / pick submission). Without this the LLM sees a
        # tool_result and merrily continues the conversation while the UI is still
        # waiting for the user to click — which looks like the model "self-answered".
        return {"__ui__": ui, "__halt__": True, "ok": True,
                "note": "已展示选项卡片，等待用户选择后再继续；本轮到此为止。"}

    def _build_ask_user_form(self, args: dict[str, Any]) -> dict[str, Any]:
        """Build a DynamicForm UI Schema for `ask_user_form`."""
        title = str(args.get("title") or "请填写")
        fields = args.get("fields") or []
        if not isinstance(fields, list) or not fields:
            return {"error": "ask_user_form: fields 不能为空"}
        components = []
        defaults: dict[str, Any] = {}
        for f in fields:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            fid = str(f["id"])
            ftype = str(f.get("type") or "Input")
            props: dict[str, Any] = {
                "label": f.get("label") or fid,
                "required": bool(f.get("required")),
            }
            if f.get("placeholder"):
                props["placeholder"] = f.get("placeholder")
            if f.get("options"):
                props["options"] = f.get("options")
            components.append({"id": fid, "type": ftype, "props": props})
            if "default" in f:
                defaults[fid] = f["default"]

        # Default template: render every field as `key=value` joined by 空格.
        # If user provided one, use it directly.
        tpl = args.get("follow_up_template")
        if not tpl:
            placeholders = "\n".join(f"- {c['id']}={{{{{c['id']}}}}}" for c in components)
            tpl = (
                "用户已通过 ask_user_form 表单提交了以下内容，请基于这些字段继续完成上一步说要做的任务（不要再次让用户填表单）：\n"
                + placeholders
            )
        submit_label = str(args.get("submit_label") or "提交")

        ui = {
            "message_type": "ui",
            "component_type": "DynamicForm",
            "title": title,
            "data_model": defaults,
            "components": components,
            "actions": [{
                "name": "submit",
                "label": submit_label,
                "trigger": "form_submit",
                "agent_call": True,
                "submit_as": "message",
                "params_from": "/",
                "message_template": tpl,
                "style": "primary",
            }],
        }
        return {"__ui__": ui, "__halt__": True, "ok": True,
                "note": "已展示表单，等待用户提交后再继续；本轮到此为止。"}

    def _get_session_workspace(self):
        """Return (and lazily create) the single shared session workspace.

        Path: storage/outputs/<user_id>/_session/<conversation_id or runner uuid>/
        Living under outputs/ means files here are directly download-registrable
        (see services.downloads._allowed_roots) AND visible to skill scripts as
        plain files, so multi-step skills can chain artifacts across tool calls.
        """
        from pathlib import Path as _Path
        import uuid as _uuid
        from ..core.config import settings
        if self._session_workspace:
            ws = _Path(self._session_workspace)
            ws.mkdir(parents=True, exist_ok=True)
            return ws
        conv = getattr(self, "_conversation_id", None)
        # Stable per-conversation key when available so files persist across
        # turns; fall back to a per-runner uuid for ad-hoc/no-conversation runs.
        key = str(conv) if conv is not None else _uuid.uuid4().hex[:12]
        ws = (
            _Path(settings.STORAGE_ROOT)
            / "outputs"
            / str(self._user_id or "anon")
            / "_session"
            / key
        ).resolve()
        ws.mkdir(parents=True, exist_ok=True)
        self._session_workspace = str(ws)
        return ws

    def _safe_session_path(self, rel: str, *, allow_missing: bool = True):
        """Resolve a workspace-relative path, rejecting absolute paths and `..`
        traversal. Returns an absolute Path guaranteed to live inside the
        session workspace."""
        from pathlib import Path as _Path
        ws = self._get_session_workspace()
        rel_text = str(rel or "").strip()
        if not rel_text:
            raise ValueError("workspace path is empty")
        rel_path = _Path(rel_text)
        if rel_path.is_absolute() or any(part == ".." for part in rel_path.parts):
            raise ValueError(f"unsafe workspace path: {rel_text}")
        resolved = (ws / rel_path).resolve()
        try:
            resolved.relative_to(ws)
        except ValueError as exc:
            raise ValueError(f"workspace path escape rejected: {rel_text}") from exc
        if not allow_missing and not resolved.exists():
            raise FileNotFoundError(f"workspace path does not exist: {rel_text}")
        return resolved

    async def _save_output_file(
        self, filename: str, content: str, mime: str | None = None,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        """Persist an artifact and return a download URL.

        File goes to storage/outputs/<user_id>/<uuid>-<safe_name>.
        Side effect: appends to self._saved_files so the SSE layer can emit a `file` event.
        """
        # Unwrap widget JSON: if the model passed `{"title":"...","widget_code":"..."}`
        # as content (it does this when it wants both render + download), extract
        # the inner widget_code, sniff its type, and save THAT as the file. The
        # raw JSON envelope is just a chat-rendering wrapper — saving it produces
        # an unpreviewable .txt file with escaped HTML inside.
        try:
            stripped = (content or "").lstrip()
            if stripped.startswith("{") and '"widget_code"' in stripped[:500]:
                parsed = json.loads(stripped)
                inner = parsed.get("widget_code")
                if isinstance(inner, str) and inner.strip():
                    content = inner
                    # Re-derive extension from the inner content
                    sniff = inner.lstrip()[:200].lower()
                    if sniff.startswith("<svg"):
                        new_ext = ".svg"
                    elif sniff.startswith("<!doctype html") or sniff.startswith("<html"):
                        new_ext = ".html"
                    elif "<style" in sniff or "<div" in sniff or "<canvas" in sniff:
                        new_ext = ".html"
                    else:
                        new_ext = None
                    if new_ext and not (filename or "").lower().endswith(new_ext):
                        # If the model named it foo.txt, rename to foo.html / foo.svg
                        from pathlib import Path as _P
                        base = _P(filename or "output").stem or "output"
                        filename = base + new_ext
                        if new_ext == ".html":
                            mime = "text/html"
                        elif new_ext == ".svg":
                            mime = "image/svg+xml"
                    # If it's a bare SVG, wrap in a tiny HTML harness so it
                    # opens nicely in the browser preview.
                    if new_ext == ".svg":
                        # keep raw SVG — browsers preview SVG natively
                        pass
                    elif new_ext == ".html" and "<!doctype" not in sniff and "<html" not in sniff:
                        content = (
                            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                            "<title>" + (parsed.get("title") or "widget") + "</title>"
                            "</head><body style='margin:0'>" + content + "</body></html>"
                        )
                    # Reorder scripts: move every <script>...</script> to
                    # just before </body>. The widget iframe receiver does
                    # this implicitly (DOM first, scripts appended last).
                    # Without reordering, models that put a <script> at the
                    # top of the body (typical pattern) will fail in a saved
                    # standalone file because onclick="foo()" handlers fire
                    # before `foo` is defined OR `let`/`const` vars are in TDZ.
                    if new_ext == ".html":
                        content = _move_scripts_to_end(content)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # fall through to normal save

        from pathlib import Path as _Path
        import re as _re
        import uuid as _uuid
        import base64 as _base64
        import mimetypes as _mt
        from ..core.config import settings
        from ..db.session import SessionLocal
        from ..services.downloads import register_file

        if not filename or not content:
            return {"error": "filename and content are required"}

        # Sanitize into a SAFE RELATIVE PATH. We preserve directory structure
        # (e.g. "sources/slide-01.html") so a later skill script can consume the
        # file by name from the shared session workspace. Each path segment is
        # cleaned individually; absolute paths and `..` traversal are stripped.
        raw_parts = [p for p in str(filename or "").replace("\\", "/").split("/") if p not in ("", ".", "..")]
        clean_parts = []
        for part in raw_parts:
            cleaned = _re.sub(r"[^\w\.\-]+", "_", part).strip("._-")
            if cleaned:
                clean_parts.append(cleaned)
        if not clean_parts:
            clean_parts = ["output"]
        # Cap the final segment length only (keep dir names intact).
        if len(clean_parts[-1]) > 120:
            clean_parts[-1] = clean_parts[-1][-120:]
        rel_name = "/".join(clean_parts)
        safe = clean_parts[-1]
        ext = _Path(safe).suffix.lower()
        if not mime:
            mime = _mt.guess_type(safe)[0] or "application/octet-stream"

        # Guardrail for PPT HTML skills: if the model tries to save a hand-built
        # deck, reject it before it reaches the user. Valid decks generated by
        # the bundled merge/generate scripts contain these runtime markers.
        if encoding != "base64" and ext == ".html" and isinstance(content, str):
            has_ppt_skill = any(
                (s.source_json or {}).get("path")
                and ((_Path((s.source_json or {}).get("path", "")) / "scripts" / "validate_deck_contract.py").exists())
                and ("ppt" in (s.code or "").lower() or "slide" in (s.code or "").lower() or "keynote" in (s.code or "").lower())
                for s in self.ctx.skills
            )
            lower_sample = content[:20000].lower()
            looks_like_deck = (
                'class="slide' in lower_sample
                or "class='slide" in lower_sample
                or "slide-stage" in lower_sample
                or "overviewgrid" in lower_sample
                or "edittoolbar" in lower_sample
            )
            if has_ppt_skill and looks_like_deck:
                required_markers = (
                    'id="overviewGrid"',
                    'id="editToolbar"',
                    'id="pageText"',
                    'id="prevBtn"',
                    'id="nextBtn"',
                    "slide-stage",
                    "data-source=",
                    "iframe.srcdoc",
                    "deckStyleClass",
                )
                missing = [m for m in required_markers if m not in content]
                escaped_runtime = "\\`" in content or "\\${" in content
                bare_slides: list[int] = []
                layout_token_re = _re.compile(
                    r"^(layout-|text-page-clean$|split$|stack-vertical$|full-image$|icons-grid$|"
                    r"cards-[23]$|grid-4$|multi-columns$|compare-2$|table$|timeline-[hv]$|"
                    r"flow$|branch$|tree$|radial$|nested$|chart-card$|problem-solution$|"
                    r"goal-plan$|statement-stage$|thanks$)"
                )
                section_tags = _re.findall(r"<section\b[^>]*>", content, flags=_re.S | _re.I)
                slide_index = 0
                for tag in section_tags:
                    class_match = _re.search(r"class=([\"'])(.*?)\1", tag, flags=_re.S)
                    tokens = class_match.group(2).split() if class_match else []
                    if "slide" not in tokens:
                        continue
                    slide_index += 1
                    if not any(layout_token_re.search(token) for token in tokens):
                        bare_slides.append(slide_index)
                if missing or escaped_runtime or bare_slides:
                    return {
                        "error": (
                            "检测到这是 PPT/slide HTML,但缺少 canonical runtime 或存在转义脚本。"
                            "或者部分页面没有明确模板布局类。请不要手动拼接最终 HTML;调用 run_skill_script 执行当前 PPT skill 的 "
                            "scripts/generate_deck.py,并设置 output_filename 生成最终文件。"
                        ),
                        "missing_markers": missing,
                        "escaped_runtime": escaped_runtime,
                        "bare_slide_numbers": bare_slides[:20],
                    }

        # Write into the SHARED session workspace (under outputs/, so it's both
        # download-registrable and visible to later skill scripts). We write to
        # the model-supplied relative path verbatim so scripts can find it by
        # name. Re-saving the same name overwrites (treated as regeneration).
        try:
            target = self._safe_session_path(rel_name)
        except Exception as e:  # noqa: BLE001
            return {"error": f"invalid output path: {e}"}
        target.parent.mkdir(parents=True, exist_ok=True)

        # Decode content
        try:
            if encoding == "base64":
                target.write_bytes(_base64.b64decode(content))
            else:
                target.write_text(content, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            return {"error": f"write failed: {e}"}

        # Cap individual file size to 20 MB (best-effort post-write check)
        size = target.stat().st_size
        if size > 20 * 1024 * 1024:
            target.unlink(missing_ok=True)
            return {"error": "file too large (>20MB)"}

        # Register download token
        async with SessionLocal() as db:
            tok = await register_file(
                db, file_path=str(target), file_name=safe,
                user_id=self._user_id, mime=mime,
            )
            await db.commit()
            download_url = f"/api/downloads/{tok.token}"

        # Stable handle: relative path under STORAGE_ROOT/outputs. Survives token expiry —
        # frontend can ask /api/downloads/refresh for a fresh token using this.
        try:
            output_path = str(target.relative_to(_Path(settings.STORAGE_ROOT) / "outputs"))
        except ValueError:
            output_path = None

        info = {
            "name": safe, "size": size, "mime": mime, "ext": ext,
            "download_url": download_url, "preview_url": download_url,
        }
        if output_path:
            info["output_path"] = output_path
        self._saved_files.append(info)
        return {
            "ok": True,
            "file": {"name": safe, "size": size, "mime": mime},
            "message": f"已保存 {safe} ({size} bytes)。前端会显示文件卡片,无需把内容再粘贴给用户。",
        }

    async def _extract_fallback_files(self, full_text: str) -> None:
        """Stream-tail safety net: if the model pasted a large code block to text
        instead of calling save_output_file, persist it ourselves so the user can
        download it. Only triggers for blocks >= MIN_BYTES."""
        import re as _re
        if not full_text or not self._user_id:
            return
        # If the model already saved files this turn, don't double-extract
        if self._saved_files:
            return
        MIN_BYTES = 2048
        # Match fenced code blocks: ```lang\n...\n```
        pattern = _re.compile(r"```([a-zA-Z0-9+\-]*)\s*\n(.*?)\n```", _re.DOTALL)
        idx = 0
        for m in pattern.finditer(full_text):
            lang = (m.group(1) or "").lower()
            body = m.group(2) or ""
            if len(body.encode("utf-8")) < MIN_BYTES:
                continue
            ext = {
                "html": "html", "htm": "html",
                "markdown": "md", "md": "md",
                "json": "json", "yaml": "yaml", "yml": "yaml",
                "python": "py", "py": "py",
                "javascript": "js", "js": "js", "typescript": "ts", "ts": "ts",
                "css": "css", "sql": "sql", "xml": "xml",
                "svg": "svg",
            }.get(lang, "txt")
            idx += 1
            await self._save_output_file(filename=f"output-{idx}.{ext}", content=body)

    async def _run_skill_script(
        self,
        skill: str,
        script: str,
        kwargs: dict[str, Any],
        output_filename: str | None = None,
        files: list[dict[str, Any]] | None = None,
        workdir: str | None = None,
    ) -> dict[str, Any]:
        """Execute a bundled Skill python script as an in-process function call.

        Contract: the script must define `generate(**kwargs)` or `run(**kwargs)`.
        It may return a produced file path, write to the injected output path, or
        return a structured JSON-serializable result for validation/calculation tasks.

        Security:
        - Script must live inside the skill directory (no escapes).
        - Skill must be enabled and bound to this agent.
        - Output is forced into outputs/<user_id>/, then registered as a download token.
        - Runs in the parent process (no Bash). For untrusted code use a separate
          subprocess sandbox in a future iteration.
        """
        from pathlib import Path as _Path
        import importlib.util as _ilu
        import sys as _sys
        import uuid as _uuid
        import re as _re
        import asyncio as _asyncio
        import inspect as _inspect
        import mimetypes as _mt
        import base64 as _base64
        from ..core.config import settings
        from ..db.session import SessionLocal
        from ..services.downloads import register_file

        skill_row = next((s for s in self.ctx.skills if s.code == skill), None)
        if not skill_row or skill_row.type != "atomic":
            return {"error": f"unknown or non-atomic skill: {skill}"}
        root = _Path((skill_row.source_json or {}).get("path", ""))
        if not root.exists():
            return {"error": "skill root missing"}
        script_path = (root / script).resolve()
        try:
            script_path.relative_to(root.resolve())
        except ValueError:
            return {"error": "script path escape rejected"}
        if not script_path.exists() or script_path.suffix.lower() != ".py":
            return {"error": f"script not found or not .py: {script}"}

        # The shared session workspace is the single source of truth. Output
        # files land here too (under outputs/), so they're both download-
        # registrable AND visible to later skill scripts in the same run.
        workspace_root = self._get_session_workspace()

        # Prepare the output target inside the workspace. Even validation-only
        # scripts receive this path, but they are not required to use it.
        safe = _re.sub(r"[^\w\.\-]+", "_", output_filename or "output.bin").strip("._-") or "output.bin"
        if len(safe) > 120:
            safe = safe[-120:]
        target_path = workspace_root / f"{_uuid.uuid4().hex[:8]}-{safe}"

        # Normalize kwargs early so misplaced files/workdir can still create a
        # workspace. Models often put these fields inside kwargs despite the
        # top-level schema.
        if isinstance(kwargs, dict):
            call_kwargs = dict(kwargs)
        else:
            return {"error": "kwargs must be an object"}
        if files is None:
            nested_files = (
                call_kwargs.pop("files", None)
                or call_kwargs.pop("_files", None)
                or call_kwargs.pop("input_files", None)
                or call_kwargs.pop("workspace_files", None)
            )
            if nested_files is not None:
                files = nested_files
        if workdir is None:
            nested_workdir = call_kwargs.pop("workdir", None) or call_kwargs.pop("cwd", None)
            if nested_workdir is not None:
                workdir = str(nested_workdir)

        # Path-like kwargs whose workspace-relative values get rewritten to
        # absolute paths so scripts (e.g. merge_deck.py) can consume them
        # without depending on process-wide chdir.
        path_like_keys = {
            "deck",
            "deck_folder",
            "folder",
            "input",
            "input_file",
            "input_path",
            "source",
            "source_file",
            "source_path",
            "target",
            "target_file",
            "target_path",
        }

        def _safe_workspace_path(rel: str, *, allow_missing: bool = True) -> _Path:
            return self._safe_session_path(rel, allow_missing=allow_missing)

        written_files: list[str] = []
        if files:
            if isinstance(files, dict):
                files = [{"path": name, "content": content} for name, content in files.items()]
            if not isinstance(files, list):
                return {"error": "files must be an array/dict of workspace file payloads"}
            if len(files) > 300:
                return {"error": "too many workspace files (>300)"}
            total_bytes = 0
            try:
                for item in files:
                    if not isinstance(item, dict):
                        return {"error": "each files item must be an object"}
                    rel_path = str(item.get("path") or item.get("filename") or item.get("name") or "")
                    if workdir and rel_path and not _Path(rel_path).is_absolute() and not rel_path.startswith(str(workdir).rstrip("/") + "/"):
                        first_part = _Path(rel_path).parts[0] if _Path(rel_path).parts else ""
                        if first_part in {"sources", "src", "input", "inputs"}:
                            rel_path = f"{str(workdir).rstrip('/')}/{rel_path}"
                    content = item.get("content")
                    if content is None:
                        content = item.get("html")
                    if content is None:
                        content = item.get("text")
                    encoding = str(item.get("encoding") or "utf-8").lower()
                    if content is None:
                        return {"error": f"workspace file missing content: {rel_path}"}
                    dest = _safe_workspace_path(rel_path)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if encoding == "base64":
                        data = _base64.b64decode(str(content))
                        dest.write_bytes(data)
                        total_bytes += len(data)
                    elif encoding in ("utf-8", "utf8", "text"):
                        text = str(content)
                        total_bytes += len(text.encode("utf-8"))
                        dest.write_text(text, encoding="utf-8")
                    else:
                        return {"error": f"unsupported workspace file encoding: {encoding}"}
                    if total_bytes > 25 * 1024 * 1024:
                        return {"error": "workspace files too large (>25MB)"}
                    written_files.append(str(dest.relative_to(workspace_root)))
            except Exception as e:  # noqa: BLE001
                return {"error": f"failed to prepare workspace files: {e}"}

        # Expose the workspace to the script. Default cwd/workdir to the
        # session root so scripts that read relative paths (or chdir) just work.
        call_kwargs.setdefault("workspace", str(workspace_root))
        call_kwargs.setdefault("workspace_dir", str(workspace_root))
        if workdir:
            try:
                resolved_workdir = _safe_workspace_path(workdir)
            except Exception as e:  # noqa: BLE001
                return {"error": f"invalid workdir: {e}"}
            resolved_workdir.mkdir(parents=True, exist_ok=True)
            call_kwargs.setdefault("workdir", str(resolved_workdir))
            call_kwargs.setdefault("cwd", str(resolved_workdir))
        else:
            call_kwargs.setdefault("workdir", str(workspace_root))
            call_kwargs.setdefault("cwd", str(workspace_root))

        # Rewrite workspace-relative path kwargs to absolute paths so existing
        # scripts such as merge_deck.py can consume them without depending on
        # process-wide chdir.
        for key, value in list(call_kwargs.items()):
            if key in {"output", "output_path", "out", "outfile"}:
                continue
            if key not in path_like_keys or not isinstance(value, str):
                continue
            value_text = value.strip()
            if not value_text or "://" in value_text or _Path(value_text).is_absolute():
                continue
            try:
                call_kwargs[key] = str(_safe_workspace_path(value_text))
            except Exception as e:  # noqa: BLE001
                return {"error": f"invalid workspace path for kwarg {key}: {e}"}

        for k in ("output", "output_path", "out", "outfile"):
            call_kwargs.setdefault(k, str(target_path))

        # Dynamically import the script as a fresh module
        mod_name = f"_h3c_skill_{skill}_{script_path.stem}_{_uuid.uuid4().hex[:6]}"
        spec = _ilu.spec_from_file_location(mod_name, script_path)
        if spec is None or spec.loader is None:
            return {"error": "failed to load script spec"}
        mod = _ilu.module_from_spec(spec)
        # Allow the script to import sibling modules from its directory
        _sys.path.insert(0, str(script_path.parent))
        try:
            try:
                spec.loader.exec_module(mod)
            except Exception as e:  # noqa: BLE001
                return {"error": f"script import failed: {e}"}
            fn = getattr(mod, "generate", None)
            fn_name = "generate"
            if not callable(fn):
                fn = getattr(mod, "run", None)
                fn_name = "run"
            if not callable(fn):
                return {"error": "script must define a callable `generate(**kwargs)` or `run(**kwargs)`"}
            # Filter kwargs to only those accepted by the chosen callable.
            try:
                sig = _inspect.signature(fn)
                if not any(p.kind == _inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    accepted = {n: v for n, v in call_kwargs.items() if n in sig.parameters}
                else:
                    accepted = call_kwargs
            except (TypeError, ValueError):
                accepted = call_kwargs
            try:
                if _asyncio.iscoroutinefunction(fn):
                    result = await fn(**accepted)
                else:
                    result = await _asyncio.to_thread(lambda: fn(**accepted))
            except TypeError as e:
                return {"error": f"argument mismatch calling {fn_name}: {e}", "expected_kwargs": list(sig.parameters.keys()) if 'sig' in dir() else None}
            except Exception as e:  # noqa: BLE001
                return {"error": f"script execution failed: {e}"}
        finally:
            try:
                _sys.path.remove(str(script_path.parent))
            except ValueError:
                pass

        # Resolve which path actually got the output. Some skills return a path
        # string, some write to the injected output path, and newer scripts may
        # return a dict such as {"output_path": "..."} or {"html_path": "..."}.
        produced: _Path | None = None
        if isinstance(result, str) and _Path(result).exists():
            produced = _Path(result).resolve()
        elif isinstance(result, dict):
            candidate_values = [
                result.get("output"),
                result.get("output_path"),
                result.get("html_path"),
                result.get("path"),
            ]
            file_info = result.get("file")
            if isinstance(file_info, dict):
                candidate_values.extend([
                    file_info.get("path"),
                    file_info.get("output_path"),
                    file_info.get("html_path"),
                ])
            for value in candidate_values:
                if isinstance(value, str) and _Path(value).exists():
                    produced = _Path(value).resolve()
                    break
        elif target_path.exists():
            produced = target_path

        if produced is None or not produced.exists():
            if isinstance(result, dict) and result.get("ok"):
                return {
                    "ok": True,
                    "result": result,
                    "message": "脚本执行成功,未生成下载文件。",
                }
            if result is not None and not isinstance(result, str):
                return {
                    "ok": True,
                    "result": result,
                    "message": "脚本执行成功,返回了结构化结果。",
                }
            return {"error": "script ran but no output file produced"}

        # If script wrote elsewhere (e.g. inside skill dir), move/copy to target_path
        if produced != target_path:
            try:
                produced.replace(target_path)
                produced = target_path
            except OSError:
                import shutil as _sh
                _sh.copy2(str(produced), str(target_path))
                produced = target_path

        mime = _mt.guess_type(safe)[0] or "application/octet-stream"
        size = produced.stat().st_size
        async with SessionLocal() as db:
            tok = await register_file(
                db, file_path=str(produced), file_name=safe,
                user_id=self._user_id, mime=mime,
            )
            await db.commit()
            download_url = f"/api/downloads/{tok.token}"

        try:
            output_path = str(produced.relative_to(_Path(settings.STORAGE_ROOT) / "outputs"))
        except ValueError:
            output_path = None

        info = {
            "name": safe, "size": size, "mime": mime,
            "ext": _Path(safe).suffix.lower(),
            "download_url": download_url, "preview_url": download_url,
        }
        if output_path:
            info["output_path"] = output_path
        info["workspace"] = str(workspace_root)
        info["workspace_files"] = written_files
        self._saved_files.append(info)
        return {"ok": True, "file": info, "message": f"已生成 {safe} ({size} bytes)。前端会显示文件卡片。"}

    async def _read_skill_file(self, skill_code: str, rel_path: str) -> dict[str, Any]:
        from pathlib import Path as _Path
        skill = next((s for s in self.ctx.skills if s.code == skill_code), None)
        if not skill or skill.type != "atomic":
            return {"error": f"unknown skill: {skill_code}"}
        root = _Path((skill.source_json or {}).get("path", ""))
        if not root.exists():
            return {"error": "skill root missing"}
        target = (root / rel_path).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            return {"error": "path escape rejected"}
        if not target.exists() or not target.is_file():
            return {"error": "file not found"}
        if target.stat().st_size > 512 * 1024:
            return {"error": "file too large (>512KB)"}
        try:
            content = target.read_text(encoding="utf-8")
            return {"path": rel_path, "content": content}
        except UnicodeDecodeError:
            return {"path": rel_path, "content": "(binary file)", "binary": True}

    async def exec_ui_action(self, tool: str, params: dict[str, Any]) -> AsyncIterator[StreamEvent]:
        """Execute a single tool call directly (no LLM), used for [UI_ACTION] routing.

        Streams tool_use → tool_result/ui → done. Cheap: no model tokens spent.
        Caller MUST validate `tool` against the agent's whitelist before calling.
        """
        import json as _json
        import time as _t
        start = _t.time()
        if self.ctx.model:
            yield StreamEvent("meta", {
                "agent_name": self.ctx.agent.name,
                "agent_code": self.ctx.agent.code,
                "model_code": self.ctx.model.code,
                "model_id": self.ctx.model.model_id,
                "provider": self.ctx.model.provider,
                "ui_action": True,
            })
        call_id = f"ui_{int(_t.time()*1000)}"
        yield StreamEvent("tool_use", {"id": call_id, "name": tool, "input": params})
        try:
            # Resolve MCP tool first (UI may target an MCP-exposed tool)
            mcp_match = None
            for m in self.ctx.mcps:
                # Names like mcp__<server>__<raw>
                if tool.startswith(f"mcp__{m.name}__"):
                    raw = tool[len(f"mcp__{m.name}__"):]
                    mcp_match = (m, raw)
                    break
            if mcp_match:
                m, raw = mcp_match
                result = await self._call_mcp_tool_once(m, raw, params)
                result = await self._register_mcp_files(result)
            else:
                result = await self._exec_skill(tool, params)
        except Exception as e:  # noqa: BLE001
            result = {"error": str(e)}

        from ..ui_schema.types import extract_ui_schema, strip_ui_for_model
        ui_schema = extract_ui_schema(result, tool_name=tool)
        if ui_schema:
            yield StreamEvent("ui", ui_schema)
            self._saved_ui.append(ui_schema)
            result = strip_ui_for_model(result)
        yield StreamEvent("tool_result", {"tool_use_id": call_id, "content": _json.dumps(result, ensure_ascii=False, default=str)})
        # Surface any saved files registered during execution
        for f in self._saved_files:
            url = str(f.get("download_url") or "")
            if url and url in self._emitted_file_urls:
                continue
            if url:
                self._emitted_file_urls.add(url)
            yield StreamEvent("file", f)
        yield StreamEvent("done", {
            "tokens_in": 0, "tokens_out": 0, "cache_hit_tokens": 0,
            "latency_ms": int((_t.time() - start) * 1000),
            "ui_action": True,
        })

    async def stream(self, user_text: str, files: list[dict[str, Any]] | None = None) -> AsyncIterator[StreamEvent]:
        """Yield streaming events.

        Routes by provider:
        - anthropic                         → Claude Agent SDK (full Skills/MCP support)
        - deepseek/qwen/glm/openai/openai-compatible → OpenAI-compatible chat-completions stream
        """
        start = time.time()
        # Always emit a meta event first so the frontend knows which agent/model is being used
        if self.ctx.model:
            yield StreamEvent("meta", {
                "agent_name": self.ctx.agent.name,
                "agent_code": self.ctx.agent.code,
                "model_code": self.ctx.model.code,
                "model_id": self.ctx.model.model_id,
                "provider": self.ctx.model.provider,
            })
        # Resolve which runtime engine executes this turn. The registry picks by
        # agent.engine_kind first (future-proof), then falls back to provider →
        # engine mapping (current behaviour). New engines plug in here with zero
        # changes to this method — see app/runtime/engines/.
        from .engines import select as _select_engine
        engine = _select_engine(self.ctx)
        yield StreamEvent("engine", {"name": engine.name, "label": engine.label})
        primary_failed: tuple[type, str] | None = None
        primary_streamed_text = False
        try:
            try:
                inner = engine.stream(self, user_text, files or [])
                async for ev in inner:
                    # Accumulate text for the fallback extractor (runs in finally)
                    if ev.type == "text":
                        txt = ev.data.get("text", "") if isinstance(ev.data, dict) else ""
                        self._fallback_text_buf.append(txt)
                        if txt:
                            primary_streamed_text = True
                    yield ev
            except ImportError as e:
                yield StreamEvent("error", {"message": f"SDK 未安装: {e}"})
            except Exception as e:  # noqa: BLE001
                # Some exceptions (e.g. cryptography.fernet.InvalidToken) have an
                # empty str(), which would render as "主模型调用失败（）" and hide
                # the real cause. Fall back to the type name, and translate the
                # common API-key-decryption failure into an actionable message.
                detail = str(e).strip()
                if not detail:
                    detail = type(e).__name__
                if type(e).__name__ == "InvalidToken":
                    detail = ("模型 API Key 解密失败（加密密钥不匹配）。"
                              "请到 设置 → 模型 重新填写该模型的 API Key 并保存。")
                primary_failed = (type(e), detail)

            # Fallback: only if the primary call errored AND it hadn't yet streamed
            # any visible text/tool output to the user. Mid-stream model swaps look
            # broken (the user already saw partial output from model A), so we skip
            # the swap in that case and surface the original error.
            if primary_failed is not None:
                fb = self.ctx.fallback_model
                if fb and not primary_streamed_text:
                    yield StreamEvent("text", {
                        "text": f"\n\n> ⚠️ 主模型调用失败（{primary_failed[1][:120]}），已自动切换到降级模型 **{fb.code}** 重试…\n\n",
                    })
                    # Swap model + reset per-call counters so usage attribution makes
                    # sense for the retry. Provider may differ → re-route SDK/OpenAI path.
                    self.ctx.model = fb
                    self._tokens_in = 0
                    self._tokens_out = 0
                    self._cache_hit_tokens = 0
                    yield StreamEvent("meta", {
                        "agent_name": self.ctx.agent.name,
                        "agent_code": self.ctx.agent.code,
                        "model_code": fb.code,
                        "model_id": fb.model_id,
                        "provider": fb.provider,
                        "fallback": True,
                    })
                    # Re-select engine for the fallback model (its provider may
                    # differ → a different engine may be appropriate).
                    fb_engine = _select_engine(self.ctx)
                    yield StreamEvent("engine", {"name": fb_engine.name,
                                                 "label": fb_engine.label, "fallback": True})
                    try:
                        fb_inner = fb_engine.stream(self, user_text, files or [])
                        async for ev in fb_inner:
                            if ev.type == "text":
                                self._fallback_text_buf.append(ev.data.get("text", "") if isinstance(ev.data, dict) else "")
                            yield ev
                    except Exception as e2:  # noqa: BLE001
                        yield StreamEvent("error", {
                            "message": f"降级模型也失败: {e2}（原始错误: {primary_failed[1][:120]}）",
                        })
                else:
                    yield StreamEvent("error", {"message": f"agent 执行错误: {primary_failed[1]}"})
        finally:
            # Cancel any approval requests still pending (e.g. the client aborted
            # the stream while a permission card was waiting) so no callback /
            # gate coroutine is left blocked on its Future forever.
            if self._pending_request_ids:
                from .permissions import cancel as _cancel
                for rid in list(self._pending_request_ids):
                    _cancel(rid, "对话已结束")
                self._pending_request_ids.clear()
            # If we are being torn down (GeneratorExit) or cancelled, do NOT run
            # async cleanup or `yield` here: an async generator that awaits/yields
            # while unwinding a GeneratorExit raises "async generator ignored
            # GeneratorExit" and refuses to finish cancelling. That is exactly what
            # left scheduled task runs wedged in "running" until the external
            # watchdog reaped them (~budget+grace) with a blank conversation. When
            # torn down we release the light sync state above and return quietly;
            # the consumer already stopped reading.
            import sys as _sys
            _exc = _sys.exc_info()[0]
            if _exc is not None and issubclass(_exc, (GeneratorExit, asyncio.CancelledError)):
                return
            # If the model dumped a large code block to text instead of calling
            # save_output_file, extract & persist it as a fallback.
            if self._fallback_text_buf:
                await self._extract_fallback_files("".join(self._fallback_text_buf))
            # Emit any saved files BEFORE done so the UI gets file cards in order
            for f in self._saved_files:
                url = str(f.get("download_url") or "")
                if url and url in self._emitted_file_urls:
                    continue
                if url:
                    self._emitted_file_urls.add(url)
                yield StreamEvent("file", f)
            yield StreamEvent("done", {
                "tokens_in": self._tokens_in,
                "tokens_out": self._tokens_out,
                "cache_hit_tokens": self._cache_hit_tokens,
                "latency_ms": int((time.time() - start) * 1000),
                "files": list(self._saved_files),
            })

    PROVIDER_BASE_URL: dict[str, str] = {
        "deepseek": "https://api.deepseek.com/v1",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "glm": "https://open.bigmodel.cn/api/paas/v4",
    }

    def _render_attachments(self, files: list[dict[str, Any]]) -> str:
        """Render uploaded files as a structured attachment block for the model.

        Per-Agent length cap:
          * agent.parsed_content_limit  — explicit override (None = use global)
          * settings.PARSED_MARKDOWN_HARD_LIMIT — global default
          * limit == 0  → no truncation (inject full markdown verbatim)
        """
        if not files:
            return ""
        from ..core.config import settings as _settings
        limit_override = getattr(self.ctx.agent, "parsed_content_limit", None)
        if limit_override is None:
            cap = int(_settings.PARSED_MARKDOWN_HARD_LIMIT or 0)
        else:
            cap = int(limit_override)
        sections: list[str] = []
        for f in files:
            name = f.get("name") or "file"
            status = f.get("parse_status") or "unknown"
            md = f.get("parsed_markdown")
            chars = len(md) if isinstance(md, str) else 0
            head = f"### 📎 {name}"
            if chars:
                head += f"  · {chars} 字符"
            if status == "skipped":
                # Raw passthrough: do not extract; expose path + signed URL so
                # the model can forward them to skill / MCP tools as arguments.
                lp = f.get("path") or ""
                # Resolve to an absolute path — UPLOADS_DIR can be relative
                # ("../storage/uploads"), which would be meaningless to MCP
                # tools running in a different cwd.
                if lp:
                    from pathlib import Path as _P
                    try:
                        lp = str(_P(lp).resolve())
                    except Exception:
                        pass
                ru = f.get("raw_url") or ""
                mime = f.get("mime") or ""
                size = f.get("size") or 0
                parts = [f"{head}  · 原始文件直传 (mime={mime}, size={size}B)"]
                if ru:
                    parts.append(f"- 下载 URL(**推荐**,MCP / 远程工具均可拉取): `{ru}`")
                if lp:
                    parts.append(f"- 本地绝对路径(仅当工具与后端在同一文件系统时可用): `{lp}`")
                parts.append("- 调用工具时优先把 URL 作为参数;只有确认工具能直接读本地磁盘时才用 path。不要尝试在对话中读取该文件内容。")
                sections.append("\n".join(parts))
            elif status == "done" and md:
                from ..services.file_parser import clip_for_prompt as _clip
                body_md = _clip(md, cap)
                if cap > 0 and chars > cap:
                    head += f" (按 Agent 配置截取至 {cap} 字符)"
                sections.append(f"{head}\n\n```\n{body_md}\n```")
            elif status == "parsing":
                sections.append(f"{head}\n\n(文件正在解析中,本轮无法读取内容)")
            elif status == "failed":
                err = f.get("parse_error") or "未知错误"
                sections.append(f"{head}\n\n(文件解析失败: {err})")
            else:
                sections.append(f"{head}\n\n(文件未解析,可向用户说明)")
        body = "\n\n".join(sections)
        return ("\n\n---\n\n# 用户上传的附件(已解析的文本可直接引用;标注为'原始文件直传'的需把 path/url 当作工具参数)\n\n"
                f"{body}\n\n---\n")

    @staticmethod
    def normalize_base_url(url: str | None) -> str | None:
        """Append /v1 if base_url has no version suffix (common user mistake)."""
        if not url:
            return url
        import re
        u = url.rstrip("/")
        # already has /vN or a known API path -> leave alone
        if re.search(r"/v\d+$", u) or "/api/" in u or "/compatible-mode" in u:
            return u
        return u + "/v1"

    async def _gate_openai_tool(self, tool_name: str, args: dict[str, Any]):
        """Interactive approval for the OpenAI-compatible path.

        Yields zero or more StreamEvents (a permission_request when the user must
        decide) and finally yields a 1-tuple ``(decision,)`` where decision is
        "allow" or a deny-result dict. Unlike the SDK path this runs in the same
        generator as the dispatch loop, so we can yield + await inline.
        """
        from . import permissions as perm
        mode = getattr(self, "_perm_mode", "chat")
        # Only gate in ask/auto task mode, and only the mutating/exec tools.
        if mode not in ("ask", "auto") or tool_name not in perm.OPENAI_GATED_TOOLS:
            yield ("allow",)
            return
        risk = perm.classify(tool_name, args)
        # Full-mode catastrophic guard also applies here (defense in depth).
        if mode == "auto" and risk.level != "high":
            yield ("allow",)
            return
        conv_id = getattr(self, "_conversation_id", None)
        if perm.has_session_grant(conv_id, tool_name):
            yield ("allow",)
            return
        request_id, fut = perm.register(conv_id, tool_name)
        self._pending_request_ids.add(request_id)
        yield StreamEvent("permission_request", {
            "request_id": request_id,
            "tool_name": tool_name,
            "risk": risk.level,
            "reason": risk.reason,
            "summary": risk.summary,
            "mode": mode,
        })
        try:
            decision = await fut
        finally:
            self._pending_request_ids.discard(request_id)
        if decision.get("behavior") == "allow":
            yield ("allow",)
        else:
            yield ({"denied": True, "message": decision.get("message") or "用户拒绝了此操作"},)

    async def _stream_via_openai(self, user_text: str, files: list[dict[str, Any]]) -> AsyncIterator[StreamEvent]:
        from openai import AsyncOpenAI
        from contextlib import AsyncExitStack
        import json as _json

        # Wall-clock start so the `done` event can report latency_ms even when
        # we hit the halt-after-tools branch (which references `start` below).
        start = time.time()

        model = self.ctx.model
        if not model:
            yield StreamEvent("error", {"message": "尚未配置任何模型，请前往 设置 → 模型 添加一个模型后再开始对话"})
            return
        api_key = decrypt_str(model.api_key_enc) if model.api_key_enc else ""
        if not api_key:
            yield StreamEvent("error", {"message": "模型 API Key 未配置"})
            return
        base_url = model.base_url or self.PROVIDER_BASE_URL.get(model.provider.lower())
        base_url = self.normalize_base_url(base_url)
        # Bound each HTTP call so a stalled connection (server accepted the
        # request but never streams a token) fails fast instead of hanging until
        # the SDK default (~10min). Without this a scheduled task whose model
        # stream stalls stays "running" for the full runtime budget, blocking
        # every subsequent cron fire under the `skip` concurrency policy and
        # leaving the conversation blank. 300s read budget + short connect.
        from httpx import Timeout as _HxTimeout
        _timeout = _HxTimeout(connect=15.0, read=300.0, write=60.0, pool=15.0)
        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=_timeout, max_retries=1)

        system = self._system_prompt(user_text) or "You are a helpful assistant."
        prompt = user_text
        if files:
            prompt += self._render_attachments(files)

        tools = self._build_openai_tools(user_text)
        _ws = (self.ctx.workspace_dir or "").strip()
        # Interactive permission gating (OpenAI-compatible path). Mirror the SDK
        # path: only meaningful in task mode (a bound, existing workspace dir).
        if _ws and _os_isdir(_ws):
            self._perm_mode = (self.ctx.permission_mode or "ask").lower()
            self._perm_active = self._perm_mode in ("ask", "auto")
        else:
            self._perm_mode = "chat"
            self._perm_active = False
        _log.info(
            "[openai-stream] provider=%s model=%s workspace=%s tools=%s",
            (self.ctx.model.provider if self.ctx.model else "?"),
            (self.ctx.model.model_id if self.ctx.model else "?"),
            _ws or "(none)",
            [t["function"]["name"] for t in tools],
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        # Replay prior turns so the model has conversation context.
        # Important: for assistant turns that called tools (esp. interactive ones
        # like ask_user_form / ask_user_pick), we MUST replay the tool_calls
        # and their tool responses so the model understands why the next user
        # message is a form submission / pick selection and not a fresh query.
        for h in (self.ctx.history or []):
            cj = h.content_json if isinstance(h.content_json, dict) else {}
            text = cj.get("text") or ""
            if h.role == "user":
                if text:
                    messages.append({"role": "user", "content": text})
            elif h.role == "assistant":
                trace = []
                if isinstance(h.tool_calls_json, dict):
                    trace = h.tool_calls_json.get("trace") or []
                # Collect tool_use entries on this assistant turn, in order.
                tool_uses: list[dict[str, Any]] = []
                tool_results_by_id: dict[str, Any] = {}
                for t in trace:
                    if not isinstance(t, dict):
                        continue
                    tt = t.get("type"); d = t.get("data") or {}
                    if tt == "tool_use":
                        tid = d.get("id") or d.get("name") or f"t_{len(tool_uses)}"
                        tool_uses.append({
                            "id": tid, "name": d.get("name") or "",
                            "arguments": d.get("input") or {},
                        })
                    elif tt == "tool_result":
                        tid = d.get("tool_use_id")
                        if tid is not None:
                            tool_results_by_id[str(tid)] = d.get("content")
                if tool_uses:
                    messages.append({
                        "role": "assistant",
                        "content": text or None,
                        "tool_calls": [
                            {
                                "id": str(tu["id"]),
                                "type": "function",
                                "function": {
                                    "name": tu["name"],
                                    "arguments": _json.dumps(tu["arguments"] or {}, ensure_ascii=False),
                                },
                            }
                            for tu in tool_uses
                        ],
                    })
                    for tu in tool_uses:
                        result = tool_results_by_id.get(str(tu["id"]), "")
                        if not isinstance(result, str):
                            result = _json.dumps(result, ensure_ascii=False, default=str)
                        # Cap individual tool_result to avoid bloating the context
                        # window when replaying history (e.g. MCP returning large docs).
                        if len(result) > 6000:
                            result = result[:6000] + f"…[历史摘要已截断, 原始长度 {len(result)} 字符]"
                        messages.append({"role": "tool", "tool_call_id": str(tu["id"]), "content": result})
                elif text:
                    messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": prompt})

        # ---- MCP integration: cached tool list + parallel fallback ----
        # Hot path: read each MCP's tool list from `tool_summaries_json` (admin
        # populates this via "重新生成介绍" / on connector save). This avoids
        # per-request connect+initialize+list_tools handshakes which dominate
        # TTFT when an agent has multiple MCP servers.
        # If a server's cache is empty/missing, fall back to real-time list —
        # but parallelized across MCPs so we pay max(latency) instead of sum.
        mcp_tool_routes: dict[str, tuple[str, "MCPConnector"]] = {}  # exposed -> (raw_tool, mcp row)

        def _ingest_tool_list(mcp, tools_list: list[dict[str, Any]]) -> None:
            for t in tools_list:
                name = t.get("name")
                if not name:
                    continue
                exposed = self._mcp_tool_name(mcp.name, name)
                mcp_tool_routes[exposed] = (name, mcp)
                # Prefer raw_description (live tool description) for the
                # function-calling system; fall back to the LLM-rewritten
                # `description` if no raw is cached.
                desc = t.get("raw_description") or t.get("description") or name
                tools.append({
                    "type": "function",
                    "function": {
                        "name": exposed,
                        "description": f"[MCP:{mcp.name}] {desc}",
                        "parameters": t.get("input_schema") or {"type": "object"},
                    },
                })

        mcps_needing_live: list = []
        for mcp in self.ctx.mcps:
            cache = (mcp.tool_summaries_json or {}).get("items") if mcp.tool_summaries_json else None
            # Only trust cache entries that include input_schema — older caches
            # without it can't drive function calls; force a live refresh.
            usable_cache = (
                isinstance(cache, list)
                and cache
                and any(isinstance(it, dict) and it.get("input_schema") for it in cache)
            )
            if usable_cache:
                _ingest_tool_list(mcp, [it for it in cache if isinstance(it, dict)])
            else:
                mcps_needing_live.append(mcp)

        if mcps_needing_live:
            async def _safe_list(m):
                try:
                    return m, await self._list_mcp_tools_once(m), None
                except Exception as e:  # noqa: BLE001
                    return m, [], e
            results = await asyncio.gather(*[_safe_list(m) for m in mcps_needing_live])
            for m, tools_list, err in results:
                if err is not None:
                    _log.warning("MCP %s tool enumeration failed: %s", m.name, err)
                    continue
                _ingest_tool_list(m, tools_list)

        # multi-turn loop: model may call skill / mcp tools, we execute and feed results back
        # max_turns is None → 不限制轮次；用一个很大的安全上限兜底,防止真正死循环。
        _mt = getattr(self.ctx.agent, "max_turns", None)
        MAX_ITER = max(1, int(_mt)) if _mt else 100_000
        # Effort → reasoning_effort (OpenAI / DeepSeek / Qwen reasoning models honor
        # this; ignored by providers that don't). xhigh/max fall back to "high"
        # for OpenAI compat since only low/medium/high are universally accepted.
        effort_oa = _effort_to_openai_reasoning(
            (getattr(self.ctx.agent, "effort", "medium") or "medium").lower()
        )
        for _ in range(MAX_ITER):
                create_kwargs: dict[str, Any] = {
                    "model": model.model_id,
                    "messages": messages,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
                if tools:
                    create_kwargs["tools"] = tools
                if model.extra_params_json:
                    create_kwargs["extra_body"] = model.extra_params_json
                # reasoning_effort is only supported by OpenAI and DeepSeek.
                # Local / openai-compatible servers (vllm, ollama, etc.) return 500
                # on unknown parameters, so only send it to known providers.
                _REASONING_EFFORT_PROVIDERS = {"openai", "deepseek"}
                if effort_oa and (model.provider or "").lower() in _REASONING_EFFORT_PROVIDERS:
                    create_kwargs["reasoning_effort"] = effort_oa

                stream = await client.chat.completions.create(**create_kwargs)

                # accumulate this turn
                text_buf = ""
                reasoning_buf = ""
                tool_calls_acc: dict[int, dict[str, Any]] = {}
                emitted_starts: set[str] = set()
                finish_reason: str | None = None

                async for chunk in stream:
                    if chunk.usage:
                        self._tokens_in += chunk.usage.prompt_tokens or 0
                        self._tokens_out += chunk.usage.completion_tokens or 0
                        pt_details = getattr(chunk.usage, "prompt_tokens_details", None)
                        if pt_details:
                            self._cache_hit_tokens += getattr(pt_details, "cached_tokens", 0) or 0
                    for choice in chunk.choices or []:
                        delta = getattr(choice, "delta", None)
                        if delta:
                            # Reasoning models expose their chain-of-thought under
                            # different field names: DeepSeek/OpenAI use
                            # `reasoning_content`, while some OpenAI-compatible
                            # gateways (e.g. this qwen3.5 endpoint) stream it as
                            # plain `reasoning`. The SDK drops unknown fields into
                            # `model_extra`, so check there too. Missing this just
                            # silently discarded all thinking output.
                            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                            if reasoning is None:
                                _extra = getattr(delta, "model_extra", None) or {}
                                reasoning = _extra.get("reasoning_content") or _extra.get("reasoning")
                            if reasoning:
                                reasoning_buf += reasoning
                                yield StreamEvent("thinking", {"text": reasoning})
                            if delta.content:
                                text_buf += delta.content
                                yield StreamEvent("text", {"text": delta.content})
                            for tc in getattr(delta, "tool_calls", None) or []:
                                idx = tc.index if tc.index is not None else 0
                                slot = tool_calls_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                                if tc.id:
                                    slot["id"] = tc.id
                                fn = getattr(tc, "function", None)
                                if fn:
                                    if fn.name:
                                        slot["name"] = fn.name
                                    if fn.arguments:
                                        slot["arguments"] += fn.arguments
                                if slot["id"] and slot["name"] and slot["id"] not in emitted_starts:
                                    yield StreamEvent("tool_use", {
                                        "id": slot["id"], "name": slot["name"], "input": {},
                                    })
                                    emitted_starts.add(slot["id"])
                        if choice.finish_reason:
                            finish_reason = choice.finish_reason

                if not tool_calls_acc:
                    return

                # Parse + canonicalize each tool call's arguments ONCE. Models can
                # emit malformed JSON for large argument bodies (e.g. a whole 公文
                # passed to run_skill_script); echoing that raw string back to the
                # gateway triggers an HTTP 400 ("Expecting ',' delimiter"). We store
                # both the parsed dict (for execution) and a guaranteed-valid JSON
                # string (for the replayed assistant message on the wire).
                for slot in tool_calls_acc.values():
                    parsed_args, canon = _parse_tool_arguments(slot.get("arguments"))
                    slot["parsed_args"] = parsed_args
                    slot["arguments"] = canon

                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": text_buf or None,
                    "tool_calls": [
                        {
                            "id": s["id"], "type": "function",
                            "function": {"name": s["name"], "arguments": s["arguments"] or "{}"},
                        }
                        for s in sorted(tool_calls_acc.values(), key=lambda x: x.get("id", ""))
                        if s.get("id") and s.get("name")
                    ],
                }
                if reasoning_buf:
                    assistant_msg["reasoning_content"] = reasoning_buf
                messages.append(assistant_msg)

                # execute each tool call (route MCP tools to MCP server, others to skill executor)
                halt_after_tools = False
                for slot in tool_calls_acc.values():
                    if not (slot.get("id") and slot.get("name")):
                        continue
                    args = slot.get("parsed_args")
                    if args is None:
                        args, _canon = _parse_tool_arguments(slot.get("arguments"))
                    yield StreamEvent("tool_use", {"id": slot["id"], "name": slot["name"], "input": args})
                    # Interactive approval gate: pause for user confirmation on
                    # mutating/exec tools (run_command / write_file) when in
                    # ask/auto task mode. Denied → skip execution, feed the model
                    # a refusal so it can react instead of silently running.
                    _denied = None
                    if getattr(self, "_perm_active", False):
                        async for _g in self._gate_openai_tool(slot["name"], args or {}):
                            if isinstance(_g, StreamEvent):
                                yield _g
                            elif isinstance(_g, tuple):
                                if _g[0] != "allow":
                                    _denied = _g[0]
                    if _denied is not None:
                        result = {"ok": False, "error": _denied.get("message", "用户拒绝了此操作"),
                                  "denied_by_user": True}
                        result_str = _json.dumps(result, ensure_ascii=False, default=str)
                        yield StreamEvent("tool_result", {"tool_use_id": slot["id"], "content": result_str})
                        messages.append({"role": "tool", "tool_call_id": slot["id"], "content": result_str})
                        continue
                    try:
                        if slot["name"] in mcp_tool_routes:
                            raw_tool, mcp_row = mcp_tool_routes[slot["name"]]
                            result = await self._call_mcp_tool_once(mcp_row, raw_tool, args)
                            result = await self._register_mcp_files(result)
                        else:
                            result = await self._exec_skill(slot["name"], args)
                    except Exception as e:  # noqa: BLE001
                        result = {"error": str(e)}
                    # If the tool result carries a UI Schema, surface it directly to the
                    # frontend ComponentRegistry. The model still sees a small summary
                    # so it knows a UI was rendered; we don't feed back the whole schema.
                    from ..ui_schema.types import extract_ui_schema, strip_ui_for_model
                    ui_schema = extract_ui_schema(result, tool_name=slot["name"])
                    # Capture halt intent BEFORE strip (which scrubs runtime-only flags).
                    halts_loop = bool(isinstance(result, dict) and result.get("__halt__"))
                    if ui_schema:
                        yield StreamEvent("ui", ui_schema)
                        self._saved_ui.append(ui_schema)
                        result = strip_ui_for_model(result)
                    # `__halt__` tools (ask_user_pick / ask_user_form) must stop the
                    # loop immediately so the user can actually interact — otherwise
                    # the model sees the tool_result and cheerfully self-answers
                    # while the UI is still waiting for a click.
                    if halts_loop:
                        halt_after_tools = True
                    result_str = _json.dumps(result, ensure_ascii=False, default=str)
                    yield StreamEvent("tool_result", {"tool_use_id": slot["id"], "content": result_str})
                    if isinstance(result, dict) and isinstance(result.get("file"), dict):
                        file_info = result["file"]
                        url = str(file_info.get("download_url") or "")
                        if url and url not in self._emitted_file_urls:
                            self._emitted_file_urls.add(url)
                            yield StreamEvent("file", file_info)
                    messages.append({
                        "role": "tool", "tool_call_id": slot["id"],
                        "content": result_str,
                    })
                if halt_after_tools:
                    # End this turn. The next user action (form submit / pick) will
                    # come in as a fresh [UI_MSG] and the model picks up the thread
                    # with full tool_calls + tool_result history replayed.
                    yield StreamEvent("done", {
                        "tokens_in": self._tokens_in,
                        "tokens_out": self._tokens_out,
                        "cache_hit_tokens": self._cache_hit_tokens,
                        "latency_ms": int((time.time() - start) * 1000),
                        "files": list(self._saved_files),
                    })
                    return

        yield StreamEvent("error", {"message": f"工具调用循环超过 {MAX_ITER} 轮,已强制中断"})

    @staticmethod
    def _mcp_tool_name(server: str, tool: str) -> str:
        # OpenAI function names allow [a-zA-Z0-9_-], must be <= 64 chars.
        import re as _re
        clean = _re.sub(r"[^a-zA-Z0-9_-]", "_", f"mcp__{server}__{tool}")
        return clean[:64]

    async def _open_mcp_session(self, stack, mcp):
        """Open an MCP ClientSession for the given MCPConnector row."""
        from mcp import ClientSession
        cfg = mcp.config_json or {}
        if mcp.transport == "stdio":
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(
                command=cfg.get("command") or "",
                args=cfg.get("args", []) or [],
                env=cfg.get("env") or None,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        elif mcp.transport == "sse":
            from mcp.client.sse import sse_client
            read, write = await stack.enter_async_context(
                sse_client(cfg.get("url"), headers=cfg.get("headers") or None)
            )
        elif mcp.transport == "http":
            from mcp.client.streamable_http import streamablehttp_client
            ctx = await stack.enter_async_context(
                streamablehttp_client(cfg.get("url"), headers=cfg.get("headers") or None)
            )
            read, write = ctx[0], ctx[1]
        else:
            raise ValueError(f"unsupported transport: {mcp.transport}")
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return session

    @staticmethod
    async def _call_mcp_tool(session, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        # Drop the OpenAI-style {"input": {...}} wrapper if the model added one
        call_args = args.get("input") if isinstance(args, dict) and "input" in args and len(args) == 1 else args
        if not isinstance(call_args, dict):
            call_args = {"value": call_args}
        result = await session.call_tool(tool_name, call_args)
        # Convert MCP CallToolResult → JSON-serialisable dict
        out_parts: list[str] = []
        for c in (result.content or []):
            text = getattr(c, "text", None)
            if text is not None:
                out_parts.append(text)
            else:
                out_parts.append(str(c))
        return {
            "isError": bool(getattr(result, "isError", False)),
            "content": "\n".join(out_parts),
        }


    @staticmethod
    async def _with_mcp_session(mcp, fn, *, timeout: float = 45.0):
        """Open + initialize an MCP session, run `fn(session)`, close. All in one task.

        Avoids the anyio "cancel scope in different task" error that occurs when an
        AsyncExitStack is held across an async generator's lifetime in FastAPI streams.

        A hard `timeout` (seconds) wraps the entire connect→initialize→fn→close
        cycle so a slow or hanging MCP server (common with remote HTTP MCPs) can
        never wedge an agent run indefinitely. On timeout we raise TimeoutError,
        which callers turn into a tool error / skipped enumeration rather than a
        permanently "running" task.
        """
        from contextlib import AsyncExitStack
        from mcp import ClientSession

        async def _run():
            cfg = mcp.config_json or {}
            async with AsyncExitStack() as stack:
                if mcp.transport == "stdio":
                    from mcp import StdioServerParameters
                    from mcp.client.stdio import stdio_client
                    params = StdioServerParameters(
                        command=cfg.get("command") or "",
                        args=cfg.get("args", []) or [],
                        env=cfg.get("env") or None,
                    )
                    read, write = await stack.enter_async_context(stdio_client(params))
                elif mcp.transport == "sse":
                    from mcp.client.sse import sse_client
                    read, write = await stack.enter_async_context(
                        sse_client(cfg.get("url"), headers=cfg.get("headers") or None)
                    )
                elif mcp.transport == "http":
                    from mcp.client.streamable_http import streamablehttp_client
                    ctx = await stack.enter_async_context(
                        streamablehttp_client(cfg.get("url"), headers=cfg.get("headers") or None)
                    )
                    read, write = ctx[0], ctx[1]
                else:
                    raise ValueError(f"unsupported transport: {mcp.transport}")
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                return await fn(session)

        return await asyncio.wait_for(_run(), timeout=timeout)

    @classmethod
    async def _list_mcp_tools_once(cls, mcp) -> list[dict[str, Any]]:
        """One-shot: connect, list tools, disconnect."""
        async def _do(session):
            tools_resp = await session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": getattr(t, "inputSchema", None) or {},
                }
                for t in tools_resp.tools
            ]
        return await cls._with_mcp_session(mcp, _do, timeout=20.0)

    @classmethod
    async def _call_mcp_tool_once(cls, mcp, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """One-shot: connect, call tool, disconnect."""
        # Drop the OpenAI-style {"input": {...}} wrapper if the model added one
        call_args = args.get("input") if isinstance(args, dict) and "input" in args and len(args) == 1 else args
        if not isinstance(call_args, dict):
            call_args = {"value": call_args}

        async def _do(session):
            import json as _json
            result = await session.call_tool(tool_name, call_args)
            out_parts: list[str] = []
            for c in (result.content or []):
                text = getattr(c, "text", None)
                if text is not None:
                    out_parts.append(text)
                else:
                    out_parts.append(str(c))
            content_str = "\n".join(out_parts)
            wrapped: dict[str, Any] = {
                "isError": bool(getattr(result, "isError", False)),
                "content": content_str,
            }
            # If the tool returned JSON whose top-level dict contains __ui__,
            # lift the schema (and surface fields) so the runtime's
            # extract_ui_schema() sees it. Tools may return JSON or plain text.
            stripped = content_str.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed = _json.loads(stripped)
                    if isinstance(parsed, dict):
                        if "__ui__" in parsed:
                            ui = parsed["__ui__"]
                            # Auto-prefix bare tool names in actions with mcp__<server>__
                            # so the [UI_ACTION] route resolves to THIS server, not a
                            # same-named tool from another MCP / Skill.
                            if isinstance(ui, dict):
                                _prefix_mcp_actions(ui, mcp.name)
                            wrapped["__ui__"] = ui
                        wrapped["data"] = {k: v for k, v in parsed.items() if k != "__ui__"}
                except Exception:
                    pass
            return wrapped
        return await cls._with_mcp_session(mcp, _do, timeout=90.0)


    def _build_skill_sandbox(self) -> "Path | None":
        """Per-Agent Skill sandbox for the Anthropic SDK path.

        Per the official docs (https://code.claude.com/docs/en/agent-sdk/skills) the
        SDK discovers skills via filesystem scanning of `<cwd>/.claude/skills/` (when
        `setting_sources` includes `"project"`). To isolate skills per-agent we build
        a temporary cwd whose `.claude/skills/` only contains symlinks to the skills
        selected for THIS agent. Other agents' skill directories are NOT linked, so
        the model has no path to reach them — even via Read/Bash.

        Composite/callable skills are not filesystem-based; they're surfaced via the
        system prompt only on the Anthropic path.

        Returns the sandbox root, or None if there are no path-based skills (caller
        will skip the cwd/setting_sources options entirely).
        Caller must rmtree the returned path when the SDK call completes.
        """
        from pathlib import Path as _Path
        import tempfile
        path_skills = [s for s in self.ctx.skills
                       if s.type == "atomic" and (s.source_json or {}).get("path")]
        if not path_skills:
            return None
        sandbox = _Path(tempfile.mkdtemp(prefix=f"h3c-agent-{self.ctx.agent.id}-"))
        skills_root = sandbox / ".claude" / "skills"
        skills_root.mkdir(parents=True, exist_ok=True)
        for s in path_skills:
            src = _Path(s.source_json["path"]).resolve()
            if not src.exists() or not src.is_dir():
                continue
            link = skills_root / src.name
            try:
                link.symlink_to(src)
            except FileExistsError:
                pass
            except OSError:
                # Fallback: filesystem doesn't allow symlinks → copy
                import shutil as _sh
                _sh.copytree(src, link, symlinks=False, dirs_exist_ok=True)
        return sandbox

    def _link_skills_into(self, ws_dir: str, sandbox: "Path | None") -> None:
        """Make this agent's skills discoverable from the project working dir.

        In task mode the SDK cwd is the user's project directory, so skill
        discovery scans `<ws>/.claude/skills/`. We symlink each selected skill
        there (creating the dir if needed) without disturbing the user's own
        files. Best-effort: failures are non-fatal (the agent just runs without
        that skill on disk).
        """
        from pathlib import Path as _Path
        path_skills = [s for s in self.ctx.skills
                       if s.type == "atomic" and (s.source_json or {}).get("path")]
        if not path_skills:
            return
        skills_root = _Path(ws_dir) / ".claude" / "skills"
        try:
            skills_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        for s in path_skills:
            src = _Path(s.source_json["path"]).resolve()
            if not src.exists() or not src.is_dir():
                continue
            link = skills_root / src.name
            if link.exists():
                continue
            try:
                link.symlink_to(src)
            except (OSError, FileExistsError):
                pass

    async def _stream_via_sdk(self, user_text: str, files: list[dict[str, Any]]) -> AsyncIterator[StreamEvent]:
        from claude_agent_sdk import query, ClaudeAgentOptions  # type: ignore
        import shutil as _shutil

        model = self.ctx.model
        if not model:
            yield StreamEvent("error", {"message": "尚未配置任何模型，请前往 设置 → 模型 添加一个模型后再开始对话"})
            return

        # Build SDK options
        mcp_servers = build_mcp_servers(self.ctx.mcps)

        # Connected CLI apps → an in-process MCP server the model can call to
        # actually run the app's binary when a user question triggers it.
        cli_apps = getattr(self.ctx, "cli_apps", None) or []
        cli_apps_server = None
        if cli_apps:
            try:
                from .cli_apps_mcp import build_cli_apps_mcp_server, MCP_SERVER_NAME as _CLI_MCP_NAME
                cli_apps_server = build_cli_apps_mcp_server(
                    cli_apps, workspace_dir=(self.ctx.workspace_dir or None))
                if cli_apps_server is not None:
                    mcp_servers = {**(mcp_servers or {}), _CLI_MCP_NAME: cli_apps_server}
            except Exception as _e:  # noqa: BLE001
                _log.warning("[cli-apps] failed to build mcp server: %s", _e)

        # Per-Agent Skill sandbox (filesystem isolation per official SDK docs).
        sandbox = self._build_skill_sandbox()

        # === Tool whitelist + permission policy ===
        # Two operating modes:
        #
        #  • Chat mode (no workspace_dir): read-only safe tools only. Bash/Write/
        #    Edit are GLOBALLY DENIED so a chat turn can never touch the disk.
        #
        #  • Task mode (workspace_dir set): the agent works inside a local project
        #    directory and gains file tools. The permission_mode chosen by the
        #    user governs how intrusive it is:
        #       ask  → SDK "default"        (CLI/host prompts before each write/exec)
        #       auto → SDK "acceptEdits"    (auto-accept edits; risky cmds still gated)
        #       full → SDK "bypassPermissions" (fully autonomous)
        ws_dir = (self.ctx.workspace_dir or "").strip() or None
        is_task = ws_dir is not None and _os_isdir(ws_dir)

        allowed_tools: list[str] = ["Read", "Glob", "Grep", "Skill", "WebSearch"]
        for mcp in self.ctx.mcps:
            if mcp.enabled:
                allowed_tools.append(f"mcp__{mcp.name}")
        if cli_apps_server is not None:
            # Allow the in-process connected-apps tools even in chat mode (they
            # run the user-connected binaries, not an arbitrary shell).
            allowed_tools.append("mcp__connected-apps")

        if is_task:
            # Unlock file-system + execution tools for the working directory.
            # How they're governed depends on the user-chosen permission mode:
            #
            #   ask  → SDK "default". Write/Edit/Bash/WebFetch are NOT pre-approved,
            #          so every one of them falls through to our can_use_tool
            #          callback and prompts the user. Read/Glob/Grep stay on the
            #          allow list and run silently.
            #   auto → SDK "default" too, but Write/Edit/NotebookEdit ARE pre-approved
            #          (routine edits run silently). Bash/WebFetch still hit the
            #          callback, which auto-allows low/medium risk and only prompts
            #          on HIGH-risk commands (rm -rf, sudo, ...).
            #   full → SDK "bypassPermissions". Nothing prompts; a Bash-scoped deny
            #          list still blocks catastrophic commands in every mode.
            from .permissions import CATASTROPHIC_DENY
            exec_tools = ["Write", "Edit", "NotebookEdit", "Bash", "WebFetch"]
            mode = (self.ctx.permission_mode or "ask").lower()
            disallowed_tools: list[str] = list(CATASTROPHIC_DENY)
            if mode == "full":
                allowed_tools += exec_tools
                permission_mode = "bypassPermissions"
            elif mode == "auto":
                # Pre-approve edits; Bash/WebFetch route through the callback.
                allowed_tools += ["Write", "Edit", "NotebookEdit"]
                permission_mode = "default"
            else:  # "ask"
                # Nothing extra pre-approved → all exec tools prompt.
                permission_mode = "default"
            self._perm_mode = mode
            self._perm_active = mode in ("ask", "auto")
        else:
            disallowed_tools = ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch"]
            permission_mode = "bypassPermissions"  # auto-approve the safe read-only set
            self._perm_mode = "chat"
            self._perm_active = False

        options_kwargs: dict[str, Any] = {
            "model": model.model_id,
            "system_prompt": self._system_prompt(user_text),
            "include_partial_messages": True,
            "permission_mode": permission_mode,
            "allowed_tools": allowed_tools,
            "disallowed_tools": disallowed_tools,
        }
        # max_turns is None → 不限制轮次,不向 SDK 传该参数（使用 SDK 默认/无限）。
        _mt = getattr(self.ctx.agent, "max_turns", None)
        if _mt:
            options_kwargs["max_turns"] = max(1, int(_mt))
        if mcp_servers:
            options_kwargs["mcp_servers"] = mcp_servers
        # Interactive approval: when the mode is ask/auto, register a can_use_tool
        # callback. The SDK invokes it for any tool not pre-approved by the allow
        # list; it classifies risk, honours session grants, and otherwise pushes a
        # `permission_request` event to the UI and blocks on a Future until the
        # user answers via the decision endpoint. Python streaming-mode requires a
        # PreToolUse keepalive hook returning {"continue_": True}, otherwise the
        # stream closes before the callback fires.
        if getattr(self, "_perm_active", False):
            from claude_agent_sdk import HookMatcher  # type: ignore
            options_kwargs["can_use_tool"] = self._make_can_use_tool()
            options_kwargs["hooks"] = {
                "PreToolUse": [HookMatcher(matcher=None, hooks=[self._perm_keepalive_hook])],
            }
        # Working directory:
        #   • Task mode → the user's project dir (so Read/Write/Bash operate there).
        #     Skills are linked into <ws>/.claude/skills via the sandbox merge below.
        #   • Chat mode → the per-agent skill sandbox (read-only skill discovery).
        if is_task:
            options_kwargs["cwd"] = ws_dir
            options_kwargs["setting_sources"] = ["project"]
            self._link_skills_into(ws_dir, sandbox)
        elif sandbox is not None:
            options_kwargs["cwd"] = str(sandbox)
            options_kwargs["setting_sources"] = ["project"]
        if model.api_key_enc:
            options_kwargs["api_key"] = decrypt_str(model.api_key_enc)
        if model.base_url:
            options_kwargs["base_url"] = model.base_url

        # Effort → extended-thinking budget. The SDK exposes this via env var or
        # an `extra_args` passthrough depending on version, so we set it on
        # both options and an env hint for the spawned CLI process.
        effort = (getattr(self.ctx.agent, "effort", "medium") or "medium").lower()
        thinking_budget = _effort_to_thinking_budget(effort)
        if thinking_budget:
            options_kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
            try:
                import os as _os
                _os.environ.setdefault("CLAUDE_THINKING_BUDGET", str(thinking_budget))
            except Exception:
                pass

        # Filter to only kwargs the installed SDK actually accepts
        sdk_arg_names = ClaudeAgentOptions.__init__.__code__.co_varnames
        options = ClaudeAgentOptions(**{k: v for k, v in options_kwargs.items() if k in sdk_arg_names})

        prompt = user_text
        if files:
            prompt += self._render_attachments(files)

        # Prepend prior conversation as a transcript so the model has context.
        # (Claude Agent SDK's query() takes a single prompt; we concatenate.)
        if self.ctx.history:
            transcript_parts = []
            for h in self.ctx.history:
                txt = (h.content_json or {}).get("text") if isinstance(h.content_json, dict) else None
                if not txt:
                    continue
                role = "用户" if h.role == "user" else "助手"
                transcript_parts.append(f"{role}: {txt}")
            if transcript_parts:
                transcript = "\n\n".join(transcript_parts)
                prompt = (
                    "以下是此前的对话历史(供你理解上下文,不要在回答里重复):\n\n"
                    f"{transcript}\n\n---\n\n用户: {prompt}"
                )

        # Track current streaming tool_use block (id-keyed input JSON accumulator).
        # Held in a dict so the shared translator can mutate it across messages.
        tstate: dict[str, Any] = {"id": None, "name": None, "buf": ""}

        if getattr(self, "_perm_active", False):
            # Permission-gated path. The can_use_tool callback blocks inside the
            # query() iteration, so we can't yield permission_request from the same
            # coroutine. Run the SDK in a background pump task feeding a queue; the
            # callback pushes its permission_request into the SAME queue.
            async for ev in self._stream_via_sdk_gated(prompt, options, tstate, sandbox):
                yield ev
            return

        try:
            async for msg in query(prompt=prompt, options=options):
                async for ev in self._translate_sdk_msg(msg, tstate):
                    yield ev
        finally:
            if sandbox is not None:
                _shutil.rmtree(sandbox, ignore_errors=True)

    async def _translate_sdk_msg(self, msg: Any, tstate: dict[str, Any]) -> AsyncIterator["StreamEvent"]:
        """Translate one SDK message into StreamEvents. ``tstate`` carries the
        in-progress tool_use accumulator across calls."""
        mtype = type(msg).__name__

        # ---- partial streaming events (token-level) ----
        if mtype == "StreamEvent" or mtype == "SDKPartialAssistantMessage":
            event = getattr(msg, "event", None) or {}
            et = event.get("type")
            if et == "content_block_start":
                cb = event.get("content_block", {}) or {}
                if cb.get("type") == "tool_use":
                    tstate["id"] = cb.get("id")
                    tstate["name"] = cb.get("name")
                    tstate["buf"] = ""
                    yield StreamEvent("tool_use", {
                        "id": tstate["id"], "name": tstate["name"], "input": {},
                    })
                elif cb.get("type") == "thinking":
                    pass
            elif et == "content_block_delta":
                delta = event.get("delta", {}) or {}
                dt = delta.get("type")
                if dt == "text_delta":
                    chunk = delta.get("text", "")
                    if chunk:
                        yield StreamEvent("text", {"text": chunk})
                elif dt == "thinking_delta":
                    chunk = delta.get("thinking", "")
                    if chunk:
                        yield StreamEvent("thinking", {"text": chunk})
                elif dt == "input_json_delta":
                    tstate["buf"] += delta.get("partial_json", "")
            elif et == "content_block_stop":
                if tstate["id"] is not None:
                    try:
                        import json as _json
                        parsed = _json.loads(tstate["buf"]) if tstate["buf"] else {}
                    except Exception:
                        parsed = {"raw": tstate["buf"]}
                    yield StreamEvent("tool_use", {
                        "id": tstate["id"], "name": tstate["name"], "input": parsed,
                    })
                    tstate["id"] = None
                    tstate["name"] = None
                    tstate["buf"] = ""

        # ---- user-side messages carry tool results from SDK's tool execution loop ----
        elif mtype == "UserMessage":
            for block in getattr(msg, "content", []) or []:
                if type(block).__name__ == "ToolResultBlock":
                    tr_content = str(getattr(block, "content", ""))
                    await self._maybe_register_files_from_tool_result(tr_content)
                    yield StreamEvent("tool_result", {
                        "tool_use_id": getattr(block, "tool_use_id", ""),
                        "content": tr_content,
                    })

        # ---- complete assistant message: fallback if partials were skipped ----
        elif mtype == "AssistantMessage":
            for block in getattr(msg, "content", []) or []:
                if type(block).__name__ == "ToolResultBlock":
                    tr_content = str(getattr(block, "content", ""))
                    await self._maybe_register_files_from_tool_result(tr_content)
                    yield StreamEvent("tool_result", {
                        "tool_use_id": getattr(block, "tool_use_id", ""),
                        "content": tr_content,
                    })

        elif mtype == "ResultMessage":
            usage = getattr(msg, "usage", None) or {}
            if isinstance(usage, dict):
                self._tokens_in = usage.get("input_tokens", 0)
                self._tokens_out = usage.get("output_tokens", 0)
                self._cache_hit_tokens = usage.get("cache_read_input_tokens", 0) or usage.get("cache_creation_input_tokens", 0)

    async def _stream_via_sdk_gated(self, prompt: str, options: Any, tstate: dict[str, Any],
                                    sandbox: Any) -> AsyncIterator["StreamEvent"]:
        """Permission-gated SDK driver. Pumps query() in a background task so the
        can_use_tool callback (which blocks awaiting a user decision) can push a
        `permission_request` event through the shared queue without deadlocking
        the consumer."""
        from claude_agent_sdk import query  # type: ignore
        queue: asyncio.Queue = asyncio.Queue()
        self._perm_queue = queue
        _DONE = object()

        async def _prompt_stream():
            # Streaming-input mode is required for can_use_tool in Python.
            yield {"type": "user", "message": {"role": "user", "content": prompt}}

        async def _pump():
            try:
                async for msg in query(prompt=_prompt_stream(), options=options):
                    async for ev in self._translate_sdk_msg(msg, tstate):
                        await queue.put(ev)
            except Exception as e:  # surfaced to the consumer as an error event
                await queue.put(StreamEvent("error", {"message": f"agent 执行错误: {e}"}))
            finally:
                await queue.put(_DONE)

        pump_task = asyncio.create_task(_pump())
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                yield item
        finally:
            self._perm_queue = None
            # Cancel any approval requests still pending for this conversation so a
            # disconnect/abort doesn't leave the callback blocked forever.
            for rid in list(self._pending_request_ids):
                from .permissions import cancel as _cancel
                _cancel(rid, "对话已结束")
            self._pending_request_ids.clear()
            if not pump_task.done():
                pump_task.cancel()
                try:
                    await pump_task
                except (asyncio.CancelledError, Exception):
                    pass
            if sandbox is not None:
                import shutil as _shutil
                _shutil.rmtree(sandbox, ignore_errors=True)

    async def _perm_keepalive_hook(self, input_data, tool_use_id, context):
        """PreToolUse keepalive — required so the Python streaming session stays
        open long enough for can_use_tool to be invoked."""
        return {"continue_": True}

    def _make_can_use_tool(self):
        """Build the can_use_tool callback bound to this runner's mode + queue."""
        from claude_agent_sdk.types import (  # type: ignore
            PermissionResultAllow, PermissionResultDeny,
        )
        from . import permissions as perm

        async def can_use_tool(tool_name: str, tool_input: dict, context: Any):
            conv_id = getattr(self, "_conversation_id", None)
            mode = getattr(self, "_perm_mode", "ask")
            risk = perm.classify(tool_name, tool_input)

            # auto mode: only HIGH-risk operations prompt; everything else runs.
            if mode == "auto" and risk.level != "high":
                return PermissionResultAllow(updated_input=tool_input)

            # Honour an earlier "allow for this session" grant.
            if perm.has_session_grant(conv_id, tool_name):
                return PermissionResultAllow(updated_input=tool_input)

            # Otherwise ask the user: push a permission_request event and block.
            request_id, fut = perm.register(conv_id, tool_name)
            self._pending_request_ids.add(request_id)
            queue = getattr(self, "_perm_queue", None)
            if queue is not None:
                await queue.put(StreamEvent("permission_request", {
                    "request_id": request_id,
                    "tool_name": tool_name,
                    "risk": risk.level,
                    "reason": risk.reason,
                    "summary": risk.summary,
                    "mode": mode,
                }))
            try:
                decision = await fut
            finally:
                self._pending_request_ids.discard(request_id)
            if decision.get("behavior") == "allow":
                return PermissionResultAllow(updated_input=tool_input)
            return PermissionResultDeny(message=decision.get("message") or "用户拒绝了此操作")

        return can_use_tool
