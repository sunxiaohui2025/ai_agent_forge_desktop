"""Connected-apps (CLI tool applications) catalog + host detection."""
from __future__ import annotations
import asyncio
import os
import shutil
from typing import Any, TypedDict


class CliAppDef(TypedDict, total=False):
    app_key: str
    name: str
    icon: str
    summary: str
    bin_names: list[str]
    install_command: str
    categories: list[str]
    homepage: str
    needs_auth: bool
    example_prompts: list[str]


CLI_APPS_CATALOG: list[CliAppDef] = [
    {
        "app_key": "ffmpeg", "name": "FFmpeg", "icon": "🎬",
        "summary": "音视频处理瑞士军刀，支持转码、剪辑、合并、流处理",
        "bin_names": ["ffmpeg", "ffprobe"],
        "install_command": "brew install ffmpeg",
        "categories": ["媒体"], "homepage": "https://ffmpeg.org",
        "example_prompts": ["把 input.mov 转成 MP4，保持原画质", "从视频里提取音频存成 MP3"],
    },
    {
        "app_key": "yt-dlp", "name": "yt-dlp", "icon": "⬇️",
        "summary": "强大的视频下载工具，支持数千个网站",
        "bin_names": ["yt-dlp"],
        "install_command": "brew install yt-dlp",
        "categories": ["下载", "媒体"], "homepage": "https://github.com/yt-dlp/yt-dlp",
        "example_prompts": ["下载这个视频的最高画质版本", "只下载音频并转成 MP3"],
    },
    {
        "app_key": "imagemagick", "name": "ImageMagick", "icon": "🖼️",
        "summary": "强大的图片处理工具，支持格式转换、缩放、裁剪、特效",
        "bin_names": ["magick", "convert"],
        "install_command": "brew install imagemagick",
        "categories": ["媒体"], "homepage": "https://imagemagick.org",
        "example_prompts": ["把文件夹里的图片批量缩放到 800px 宽", "给图片加文字水印"],
    },
    {
        "app_key": "pandoc", "name": "Pandoc", "icon": "📄",
        "summary": "通用文档格式转换器，支持 Markdown/HTML/PDF/DOCX 等",
        "bin_names": ["pandoc"],
        "install_command": "brew install pandoc",
        "categories": ["文档"], "homepage": "https://pandoc.org",
        "example_prompts": ["把 README.md 转成 PDF", "把网页 HTML 转成 Markdown"],
    },
    {
        "app_key": "jq", "name": "jq", "icon": "🧰",
        "summary": "轻量级 JSON 处理器，支持查询、过滤、转换",
        "bin_names": ["jq"],
        "install_command": "brew install jq",
        "categories": ["数据"], "homepage": "https://jqlang.github.io/jq/",
        "example_prompts": ["从 package.json 提取所有依赖名称", "过滤 JSON 数组里 status=active 的项"],
    },
    {
        "app_key": "ripgrep", "name": "ripgrep", "icon": "🔎",
        "summary": "极速文本搜索工具，比 grep 快数倍",
        "bin_names": ["rg"],
        "install_command": "brew install ripgrep",
        "categories": ["搜索"], "homepage": "https://github.com/BurntSushi/ripgrep",
        "example_prompts": ["在项目里搜索所有 TODO 注释", "查某个函数在哪些文件里被调用"],
    },
    {
        "app_key": "gh", "name": "GitHub CLI", "icon": "🐙",
        "summary": "GitHub 官方命令行，管理仓库、PR、Issue、Release",
        "bin_names": ["gh"],
        "install_command": "brew install gh",
        "categories": ["开发"], "homepage": "https://cli.github.com",
        "needs_auth": True,
        "example_prompts": ["列出我仓库里的 open PR", "创建一个新的 issue"],
    },
    {
        "app_key": "stripe", "name": "Stripe CLI", "icon": "💳",
        "summary": "支付集成命令行工具，资源管理、Webhook 调试、日志监控",
        "bin_names": ["stripe"],
        "install_command": "brew install stripe/stripe-cli/stripe",
        "categories": ["效率"], "homepage": "https://stripe.com/docs/stripe-cli",
        "needs_auth": True,
        "example_prompts": ["把 Webhook 事件转发到本地服务器", "触发一个 checkout.session.completed 事件"],
    },
    {
        "app_key": "lark-cli", "name": "飞书 Lark CLI", "icon": "🐦",
        "summary": "飞书开放平台命令行，覆盖消息、文档、多维表格、日历等 200+ 命令",
        "bin_names": ["lark-cli"],
        "install_command": "npm install -g @larksuite/cli",
        "categories": ["效率"], "homepage": "https://github.com/larksuite/cli",
        "needs_auth": True,
        "example_prompts": ["给某个群聊发一条消息", "查看我今天的日程安排"],
    },
    {
        "app_key": "wecom-cli", "name": "企业微信 CLI", "icon": "💼",
        "summary": "企业微信开放接口命令行，支持发送应用消息、群机器人推送、通讯录与日程管理",
        "bin_names": ["wecom-cli", "wecom", "qywx-cli"],
        "install_command": "npm install -g wecom-cli",
        "categories": ["效率"], "homepage": "https://developer.work.weixin.qq.com",
        "needs_auth": True,
        "example_prompts": ["给运维群推送一条告警消息", "查询某个成员的部门信息"],
    },
]


def get_catalog_entry(app_key: str) -> CliAppDef | None:
    return next((a for a in CLI_APPS_CATALOG if a["app_key"] == app_key), None)


def _detect_sync(bin_names: list[str]) -> dict[str, Any]:
    extra = [
        "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.npm-global/bin"),
    ]
    env_path = os.environ.get("PATH", "")
    merged = os.pathsep.join(dict.fromkeys([*env_path.split(os.pathsep), *extra]))
    for bin_name in bin_names or []:
        resolved = shutil.which(bin_name, path=merged)
        if not resolved:
            continue
        version = None
        try:
            import subprocess
            proc = subprocess.run(
                [resolved, "--version"], capture_output=True, text=True, timeout=5,
                env={**os.environ, "PATH": merged},
            )
            text = (proc.stdout or proc.stderr or "").strip()
            import re
            first = text.split("\n")[0] if text else ""
            m = re.search(r"(\d+\.\d+[\w.\-]*)", first)
            if m:
                version = m.group(1)
        except Exception:
            pass
        return {"status": "installed", "version": version, "bin_path": resolved}
    return {"status": "not_installed", "version": None, "bin_path": None}


async def detect_cli_app(bin_names: list[str]) -> dict[str, Any]:
    return await asyncio.to_thread(_detect_sync, bin_names)
