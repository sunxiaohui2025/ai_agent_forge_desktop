"""Provider presets — one-click model vendor configuration.

Each preset captures a vendor's protocol + base_url + default model list so the
user only needs to paste an API key. China-focused (GLM/DeepSeek/Kimi/Qwen/
Volcengine/MiniMax) plus international and self-hosted options.

The frontend reads these via GET /api/admin/models/presets to drive a
"select vendor → fill key → pick model" form. `protocol` maps to the runner's
provider field: 'anthropic' or 'openai-compatible'.
"""
from __future__ import annotations

PROVIDER_PRESETS: list[dict] = [
    # ── 国内主流（China mainstream） ──
    {
        "key": "zhipu-glm",
        "name": "智谱 GLM",
        "group": "国内",
        "protocol": "openai-compatible",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4.6", "glm-4.5", "glm-4.5-air", "glm-4-flash"],
        "api_key_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "icon": "zhipu",
    },
    {
        "key": "deepseek",
        "name": "DeepSeek 深度求索",
        "group": "国内",
        "protocol": "openai-compatible",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "api_key_url": "https://platform.deepseek.com/api_keys",
        "icon": "deepseek",
    },
    {
        "key": "moonshot-kimi",
        "name": "Kimi 月之暗面",
        "group": "国内",
        "protocol": "openai-compatible",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-k2-0905-preview", "moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k"],
        "api_key_url": "https://platform.moonshot.cn/console/api-keys",
        "icon": "moonshot",
    },
    {
        "key": "qwen-dashscope",
        "name": "通义千问（阿里）",
        "group": "国内",
        "protocol": "openai-compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen3-max"],
        "api_key_url": "https://bailian.console.aliyun.com/?apiKey=1",
        "icon": "qwen",
    },
    {
        "key": "volcengine-doubao",
        "name": "豆包（火山方舟）",
        "group": "国内",
        "protocol": "openai-compatible",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": ["doubao-pro-32k", "doubao-pro-128k", "doubao-1.5-pro-32k"],
        "api_key_url": "https://console.volcengine.com/ark",
        "icon": "volcengine",
        "note": "model_id 需填写火山方舟的「接入点 Endpoint ID」（ep-xxx）",
    },
    {
        "key": "minimax",
        "name": "MiniMax",
        "group": "国内",
        "protocol": "openai-compatible",
        "base_url": "https://api.minimaxi.com/v1",
        "models": ["MiniMax-Text-01", "abab6.5s-chat"],
        "api_key_url": "https://platform.minimaxi.com/user-center/basic-information/interface-key",
        "icon": "minimax",
    },
    {
        "key": "baichuan",
        "name": "百川 Baichuan",
        "group": "国内",
        "protocol": "openai-compatible",
        "base_url": "https://api.baichuan-ai.com/v1",
        "models": ["Baichuan4", "Baichuan3-Turbo"],
        "api_key_url": "https://platform.baichuan-ai.com/console/apikey",
        "icon": "baichuan",
    },
    {
        "key": "siliconflow",
        "name": "硅基流动 SiliconFlow",
        "group": "国内",
        "protocol": "openai-compatible",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-R1"],
        "api_key_url": "https://cloud.siliconflow.cn/account/ak",
        "icon": "siliconflow",
    },

    # ── 国际（International） ──
    {
        "key": "anthropic",
        "name": "Anthropic（官方）",
        "group": "国际",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com",
        "models": ["claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"],
        "api_key_url": "https://console.anthropic.com/settings/keys",
        "icon": "anthropic",
    },
    {
        "key": "openai",
        "name": "OpenAI（官方）",
        "group": "国际",
        "protocol": "openai-compatible",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "o3-mini"],
        "api_key_url": "https://platform.openai.com/api-keys",
        "icon": "openai",
    },
    {
        "key": "openrouter",
        "name": "OpenRouter（聚合）",
        "group": "国际",
        "protocol": "openai-compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["anthropic/claude-sonnet-4.5", "openai/gpt-4o", "google/gemini-2.0-flash-exp"],
        "api_key_url": "https://openrouter.ai/keys",
        "icon": "openrouter",
    },

    # ── 自部署（Self-hosted） ──
    {
        "key": "ollama",
        "name": "Ollama（本地）",
        "group": "自部署",
        "protocol": "openai-compatible",
        "base_url": "http://localhost:11434/v1",
        "models": ["qwen2.5", "llama3.1", "deepseek-r1"],
        "icon": "ollama",
        "note": "需本地运行 Ollama；API Key 可随意填写",
    },
    {
        "key": "custom-openai",
        "name": "自定义（OpenAI 兼容）",
        "group": "自部署",
        "protocol": "openai-compatible",
        "base_url": "",
        "models": [],
        "icon": "custom",
        "note": "填写你自部署服务的地址、密钥和模型名",
    },
    {
        "key": "custom-anthropic",
        "name": "自定义（Anthropic 兼容）",
        "group": "自部署",
        "protocol": "anthropic",
        "base_url": "",
        "models": [],
        "icon": "custom",
        "note": "填写 Anthropic 兼容网关的地址、密钥和模型名",
    },
]
