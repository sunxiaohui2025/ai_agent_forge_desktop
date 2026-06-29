# Agent Forge Desktop · 个人桌面智能体

一款装在你自己电脑上的 AI 智能体桌面应用，基于 [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk) 深度开发。把它想成你专属的 WorkBuddy —— 帮你读文件、跑技能、调工具、做自动化，所有数据都留在本机（`~/.h3c-agent`），开箱即用，无需服务器、无需公网。

它和普通聊天框最大的不同，是**能动手干活**：装载技能（Skill）、连接 MCP 工具、接入本地命令行（CLI），在你授权的工作目录里读写文件、执行脚本。而这一切都跑在一套分层的本地安全沙箱之上——工具白名单、输入过滤、技能静态扫描、目录级隔离、密钥本地加密——让"能执行"和"可控、安全"并存。

## 下载安装

最新版本：**v0.1.0** — [全部下载与更新日志](https://github.com/sunxiaohui2025/ai_agent_forge_desktop/releases/tag/v0.1.0)

| 平台 | 安装包 | 说明 |
|---|---|---|
| macOS (Apple Silicon) | [Agent.Forge-0.1.0-arm64.dmg](https://github.com/sunxiaohui2025/ai_agent_forge_desktop/releases/download/v0.1.0/Agent.Forge-0.1.0-arm64.dmg) | M1/M2/M3 等 ARM 芯片 |
| macOS (Intel) | [Agent.Forge-0.1.0-x64.dmg](https://github.com/sunxiaohui2025/ai_agent_forge_desktop/releases/download/v0.1.0/Agent.Forge-0.1.0-x64.dmg) | Intel 芯片 Mac |
| Windows (x64) | [H3C Agent-Setup-0.1.0.exe](https://github.com/sunxiaohui2025/ai_agent_forge_desktop/releases/download/v0.1.0/H3C-Agent-Setup-0.1.0.exe) | NSIS 安装向导，支持自定义安装路径 |

> macOS 安装包未签名，首次打开请**右键 →「打开」**，或在「系统设置 → 隐私与安全性」中放行。
> Windows 未签名安装包首次运行可能被 Windows Defender 拦截，点击「更多信息 → 仍要运行」即可。
> 装好后，应用内「设置 → 检查更新」会自动比对最新 Release 版本并引导下载。

## 核心特点

- **本地优先，数据自留**：SQLite 数据库 + 本地 storage，全部在 `~/.h3c-agent`，不上传云端，升级不丢数据。
- **安全可控的执行能力**：智能体能调用工具、跑技能、读写工作目录，但每一层都有约束——默认禁危险操作、输入正则拦截、技能上传 AST 扫描、按智能体隔离的文件沙箱。
- **插件化能力装配**：技能（Skill）、MCP 连接器、连接应用（CLI）三类能力随取随用，几分钟搭出一个专业智能体，业务与技术解耦。
- **动态 UI 流式渲染**：类 Claude 官网的实时渲染，生成图表 / 网页 / 表单的过程可见，思考过程独立成卡片，真·token-by-token 流式。
- **自动化与多渠道**：内置定时任务（cron / 一次性 / 手动），远程桥接（飞书、企业微信里直接对话本地智能体），连接应用（接入本地 CLI 工具）。
- **文档智能解析**：上传 PDF / Word / Excel / 图片 → MinerU 云端或私有化解析 → 失败回退本地库 → Markdown 注入对话。

技术栈：

- **后端**：FastAPI · SQLAlchemy 2.0 (async) · SQLite · Claude Agent SDK · OpenAI Python SDK
- **前端**：Vue 3 · Vite · TypeScript · Pinia · Element Plus
- **桌面壳**：Electron（Python 后端作为 sidecar 进程，稳定端口 47900；前端由后端同源托管）
- **AI 解析**：[MinerU](https://mineru.net) 云端 / 私有化双模式 + 本地 Python 库 fallback
- **多渠道桥接**：飞书长连接（[lark-oapi](https://github.com/larksuite/oapi-sdk-python)，仅需 App ID/Secret，无需公网回调）、企业微信加密回调（自建应用，可在企业微信 App 里直接对话）

---
## 系统预览图
| 功能模块 | 功能模块 |
| :---: | :---: |
| 分层安全权限执行<br><img width="100%" alt="权限管控@2x" src="https://github.com/user-attachments/assets/c95411d8-29ee-48d8-9248-90007cf4d78d" /> | 支持技能和CLI连接<br><img width="100%" alt="截屏2026-06-27 14 41 01" src="https://github.com/user-attachments/assets/8ee7312d-25bc-46ce-b9d0-41f37fa973eb" /> |
| 支持skills/mcp/cli<br><img width="100%" alt="截屏2026-06-27 14 41 32" src="https://github.com/user-attachments/assets/5711fb93-5b19-407c-a0bc-e8375b509cbe" /> | 首页对话-支持本地文件工作目录<br><img width="100%" alt="首页文件目录界面" src="https://github.com/user-attachments/assets/495f8c9d-cd9a-420e-87f6-2eec5b5e29dd" /> |
| 支持飞书、企业微信等多种功能渠道<br><img width="100%" alt="截屏2026-06-27 14 42 32" src="https://github.com/user-attachments/assets/e9510352-1fbf-4afa-97f5-458b34ef668a" /> | 支持用量统计<br><img width="100%" alt="截屏2026-06-27 14 42 15" src="https://github.com/user-attachments/assets/3299fd0e-8299-42ec-95ed-f1e8580c0cec" /> |
| 智能体动态配置<br><img width="100%" alt="截屏2026-06-27 14 41 53" src="https://github.com/user-attachments/assets/2ffaf3aa-b9c1-495e-bc5c-bb31fac4b57f" /> | 中间产物在线打开渲染<br><img width="100%" alt="企业微信20260627-153944@2x" src="https://github.com/user-attachments/assets/e6b37e15-0aa3-475f-a1d2-06aa9cfeff0a" /> |


## 一、功能总览

| 模块 | 关键能力 |
|---|---|
| **智能体** | 多智能体 / 默认智能体 / 模型 + 降级模型 / 挂载 Skill 与 MCP / 文件上传策略 / system_prompt / 默认工作目录 / max_turns / effort |
| **模型管理** | Anthropic / DeepSeek / Qwen / GLM / OpenAI / 任意 OpenAI 兼容,API Key Fernet 本地加密存储,extra_params 透传(如关思考),一键测试 |
| **Skill 仓库** | path 型(SKILL.md 包)/ composite(YAML DAG)/ callable(Python 函数)三种类型;ZIP 包上传 + 静态扫描;在线浏览文件树 + Markdown 在线编辑保存;按 Agent 文件级隔离(per-agent .claude/skills/ 沙箱);跨路径调度(`save_output_file` / `_read_skill_file` / `run_skill_script`) |
| **MCP 连接器** | stdio / SSE / Streamable-HTTP 三种 transport;实时连接 + 列举工具 + 输入 schema 展示;按 Agent 隔离;运行时按需注入 |
| **聊天与流式** | 多会话 + 历史持久化 + 多轮上下文(默认 30 条)+ 真·token-by-token 流式(Claude Agent SDK partial messages);思考过程独立 thinking 卡片(支持 DeepSeek-Reasoner reasoning_content);工具/MCP/Skill 调用步骤卡片实时展示;对话框可临时挂载「技能」与「连接应用」 |
| **定时任务(自动化)** | cron / 一次性 / 手动触发;每任务独立调度协程 + 并发策略(skip);运行产物落库成可回看会话;超时强制中断 + 启动自动回收孤儿运行;成功/失败可邮件 + 站内通知 |
| **远程桥接** | 飞书长连接(WebSocket)接入,仅需 App ID/Secret,**无需公网地址、无需回调 URL**;企业微信加密回调(webhook)接入,可在企业微信 App 里直接对话;在 IM App 里与本地智能体多轮对话;每会话绑定持久 Conversation;密钥 Fernet 加密 |
| **连接应用(CLI Apps)** | 把本地命令行工具(如 Claude Code 等)接入智能体,在进程内以 MCP 形式调用;一键安装检测 + 启停;对话框可临时连接 |
| **工作空间** | 选择本地目录作为智能体读写沙箱(任务模式);按目录配置权限模式(询问/自动/全权) |
| **文件上传与解析** | 在对话框上传 → 异步解析 → MinerU 云端/私有化 → 失败回退本地库(pypdf/python-docx/openpyxl/bs4)→ Markdown 注入 prompt;支持多次引用、解析中可见状态、失败可重试;支持原始文件直传(不解析) |
| **文件预览与下载** | 类 Gemini Canvas 右侧分屏;HTML / PDF / Markdown / SVG / 图片 / 文本代码 在线预览;Word / PPT / Excel 仅下载;一次性 token URL,过期/路径穿越全 block;Skill 产物自动登记下载链接 |
| **收藏与通知** | 收藏问答(含产物快照);站内通知中心(任务结果等) |
| **生成式 UI** | Skill 输出嵌入式 Widget 渲染(向智能体回拨消息);右侧分屏可拖动尺寸 |
| **安全加固** | Anthropic 路径默认禁 Bash/Write/Edit;system_prompt 注入安全规则;输入正则过滤(injection / shell);Skill 上传静态扫描(AST 级危险 import 黑名单);文件级 cwd 沙箱(per-agent symlink);工具调用 / 文件操作全埋点审计 |
| **审计与日志** | `call_logs`(token/延迟/状态)+ `audit_logs`(工具调用 / 安全拦截 / 文件下载)双表,可筛选查询 |
| **生命周期** | 文件 30 天未引用自动清理;Conversation 删除级联消息;UploadedFile last_used_at 跟踪 |
| **打包形态** | Electron 打包,Python 后端 PyInstaller 冻结为 sidecar + SQLite,用户无需安装 Python,数据全在 `~/.h3c-agent` |

---

## 二、目录结构

```
agent-forge-desktop/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── auth.py                  本地账号登录 / 刷新 / me
│   │   │   ├── chat.py                  会话 / 消息 / SSE 流式
│   │   │   ├── files.py                 上传 / 异步解析 / 状态查询 / 重试 / raw 直链
│   │   │   ├── downloads.py             token URL 下载(Skill 产物)
│   │   │   ├── tasks.py                 定时任务(自动化)+ 运行历史 / 手动触发 / 取消
│   │   │   ├── bridge.py                远程桥接渠道配置(飞书 / 企业微信)
│   │   │   ├── workspaces.py            工作空间(本地目录沙箱)
│   │   │   ├── favorites.py             收藏问答
│   │   │   ├── notifications.py         站内通知
│   │   │   └── admin/
│   │   │       ├── models.py            模型管理 + 测试
│   │   │       ├── mcp.py               MCP 连接器 + 工具列表
│   │   │       ├── skills.py            Skill ZIP 上传 / 文件树 / 在线编辑 / 静态扫描
│   │   │       ├── agents.py            Agent 配置 (含上传策略)
│   │   │       ├── cli_apps.py          连接应用(CLI 工具)
│   │   │       └── logs.py              call/audit 日志
│   │   ├── core/
│   │   │   ├── config.py                env 配置(SQLite / MinerU / JWT / 上传等)
│   │   │   ├── crypto.py                Fernet 加密(API Key / 渠道密钥)
│   │   │   ├── security.py              JWT / bcrypt
│   │   │   └── security_rules.py        SAFETY_PREFIX + 输入过滤正则
│   │   ├── runtime/
│   │   │   ├── agent_runner.py          双路径流式(Anthropic SDK + OpenAI 兼容);Skill/MCP/file 编排;widget 协议;tool-use 状态卡;MCP 调用硬超时
│   │   │   ├── skill_loader.py          composite YAML 校验 + DAG 拓扑
│   │   │   ├── dag_executor.py          DAG 并行执行 + 模板变量
│   │   │   ├── mcp_manager.py           MCP 客户端工厂(stdio/SSE/HTTP)
│   │   │   ├── cli_apps_catalog.py      连接应用静态目录
│   │   │   ├── cli_apps_mcp.py          进程内 CLI MCP 适配
│   │   │   └── widget_guidelines.py     生成式 UI 指南
│   │   ├── services/
│   │   │   ├── audit.py                 审计辅助
│   │   │   ├── downloads.py             下载令牌登记 / 校验(tz-safe)
│   │   │   ├── file_cleanup.py          30 天 orphan 清理(后台 task)
│   │   │   ├── file_parser.py           解析路由(text / MinerU / 本地库)
│   │   │   ├── mineru_client.py         MinerU 云端/本地双模式
│   │   │   ├── task_runner.py           任务调度协程 + 执行 + 孤儿运行回收 + 通知
│   │   │   ├── bridge_manager.py        飞书长连接中继(WebSocket → AgentRunner)
│   │   │   ├── wecom_crypto.py          企业微信回调 AES 加解密 + 主动发消息客户端
│   │   │   ├── capability_summarizer.py Skill/MCP 能力中文摘要
│   │   │   ├── mailer.py                SMTP 邮件通知
│   │   │   └── skill_scan.py            shell + Python AST 扫描
│   │   ├── db/
│   │   │   ├── models.py                业务表
│   │   │   └── session.py               async engine(SQLite)+ Base
│   │   ├── schemas/                     Pydantic
│   │   ├── deps.py                      JWT 依赖(桌面单用户回落 id=1)
│   │   └── main.py                      入口 + lifespan(迁移 / 种子 / 清理 / 调度 / 桥接)
│   ├── sidecar.spec                     PyInstaller 打包描述
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── chat/Chat.vue            对话页(50/50 分屏 / 思考块 / 步骤卡 / 文件 chip / 技能·连接应用 picker / 预览面板)
│   │   │   ├── tasks/                   定时任务列表 + 运行历史
│   │   │   ├── space/                   工作空间
│   │   │   ├── settings/                设置(通用 / 远程桥接 / 用量 / 桌面伙伴 / 关于)
│   │   │   ├── admin/                   配置页(模型 / MCP / 技能 / Agent / 连接应用 / 日志)
│   │   │   ├── Plugins.vue              插件中心(技能 / MCP / 连接应用 三 Tab)
│   │   │   ├── DesktopLayout.vue        桌面端布局
│   │   │   └── Login.vue                Glassmorphism 登录页
│   │   ├── components/
│   │   │   ├── FileCard.vue             文件卡片(下载 / 预览)
│   │   │   ├── PreviewPanel.vue         右侧分屏多类型渲染
│   │   │   └── WidgetRenderer.vue       生成式 UI Widget
│   │   ├── api/                         统一 axios 封装 + 拦截
│   │   ├── stores/                      Pinia(auth + chat)
│   │   ├── router/                      路由
│   │   └── styles.css                   Material 3 token
│   └── vite.config.ts                   含 SSE 反代禁缓冲
├── desktop/                            Electron 桌面壳(main.js sidecar + preload + 打包配置 + BUILD.md)
└── storage/
    ├── uploads/<user_id>/               上传文件(物理隔离)
    ├── outputs/<user_id>/               Skill / 工具产物
    └── skills/<code>/                   path 型 Skill 包
```

---

## 三、核心机制

### 3.1 双流式路径

**Anthropic 路径**(provider=anthropic)
- 使用 Claude Agent SDK,`include_partial_messages=True` 走 `content_block_delta` 真流式
- 文件级 Skill 沙箱:`<tmp>/.claude/skills/` 仅符号链接当前 Agent 选中的 Skill
- 工具白名单:Read / Glob / Grep / Skill / WebSearch / `mcp__<server>` —— Bash/Write/Edit 全局禁

**OpenAI 兼容路径**(provider=deepseek/qwen/glm/openai/openai-compatible)
- `/v1/chat/completions` stream + `tool_calls`
- 多轮 function-calling 循环(默认 15 轮,按 Agent 的 `max_turns` 配置)
- DeepSeek-Reasoner `reasoning_content` 自动回传
- MCP / Skill 都翻译成 OpenAI function tools,运行时路由
- 工具参数自动修复:模型偶尔吐出非法 JSON(长正文未转义)时,会重新规范化后再回传,避免网关 400
- MCP 调用全程硬超时(枚举 20s / 调用 90s),慢渠道不会把会话或任务挂死

### 3.2 Skill 三态

| 类型 | 形态 | 执行方式 |
|---|---|---|
| **path 型 atomic** | ZIP 上传 → SKILL.md + 资源文件 | Anthropic SDK 通过 cwd 文件级加载;OpenAI 路径模型先调 `_read_skill_file` 加载 SKILL.md,再用 `run_skill_script` 调内含 Python(in-process,无 Bash) |
| **callable atomic** | source_json.callable: `module.path:func` | 直接 import 调用(有 audit) |
| **composite (YAML DAG)** | 步骤 + depends_on + 模板变量 | DAGExecutor 拓扑分层 + 同层并行,变量替换不走 eval |

每次请求:`storage/skills/<code>/` 的 Skill 按 Agent 选择 symlink 进 `tmp/.claude/skills/` —— 物理沙箱,Read/Bash 也跨不到别的 Skill。

### 3.3 文件解析

```
TXT/MD/CSV/JSON/HTML/...  → 直接读
PDF/DOCX/PPTX/XLSX/PNG/JPG → MinerU(云端/私有化)→ 失败回退本地库
其它                       → 标记 failed,可重试
```

- MinerU 云端流程:申请预签名 URL → PUT 上传 → 轮询 batch 结果 → 拿 markdown
- 私有化部署只改三个配置(`MINERU_MODE=local`、`MINERU_BASE_URL`、`MINERU_API_KEY`),业务代码零侵入

#### 原始文件直传（parse_mode=never）

针对盖章 PDF / 视觉模型 / 二进制专用格式等场景，Agent 可关闭自动解析，把原文件交给工具处理。

- Agent 编辑页 → **文件解析模式** → 选「不解析,原始文件直传工具」
- 上传时 `parse_status="skipped"`，不做 OCR / 文本提取
- 发送消息时后端为该文件签发 60 分钟短期 token，prompt 中给出本地路径（供 skill 读）+ 签名 URL（供 MCP 拉取）
- 解析硬上限 20K 字符,超长截头尾省中间

### 3.4 文件下载与预览

- 上传文件:`/api/files/{id}/raw` + 双通道鉴权(Bearer 头 / `?t=<jwt>` query)
- Skill / 工具产物:`download_tokens` 表登记 + `/api/downloads/{token}` 短 URL
- 过期 / 路径穿越 全部 block
- 右侧分屏渲染:HTML iframe / PDF 浏览器原生 / Markdown 渲染 / 文本代码块 / SVG 内嵌 / 图片;Office 仅下载

### 3.5 安全加固(分层)

桌面端虽然是单用户、本地运行,但"能执行"本身就需要边界。这是它区别于普通聊天框的核心——分层约束让智能体的动手能力始终可控:

1. **工具白名单**(运行时层):Anthropic 路径默认禁 Bash/Write/Edit
2. **system_prompt 安全前缀**(模型层):每个 Agent 强制注入,反 prompt injection
3. **输入正则过滤**(网关层):shell 命令、injection 套路、敏感路径模式 → 直接 400 + 审计
4. **Skill 静态扫描**(上传时):shell pattern + Python AST(eval/exec/subprocess/os.system 黑名单)
5. **文件 cwd 沙箱**(SDK 层):per-agent 临时 dir,模型物理上看不到别的 Skill
6. **工作目录权限模式**(出口层):本地目录读写按「询问 / 自动 / 全权」三档授权
7. **下载令牌**(出口层):一次性 token / 24h 过期 / 路径穿越拒绝
8. **API Key 本地加密**:Fernet 存本机 SQLite,前端只看到 `has_api_key`,不出本机

### 3.6 审计

| 表 | 用途 |
|---|---|
| `audit_logs` | 工具调用 + 文件上传/下载/重解析 + 输入过滤命中 + Skill 上传拦截 |
| `call_logs` | 每次对话:token in/out / 延迟 / 状态 / 错误 / 模型 |

日志页支持按 Agent 筛选 + 翻页 + 详情 JSON 展开。

### 3.7 定时任务(自动化)

- 调度类型:`cron`(标准 5 段表达式)/ `once`(一次性)/ `manual`(手动触发)
- 每个启用任务一个独立 asyncio 协程,sleep 到下次触发时间;不依赖 apscheduler
- 并发策略 `skip`:上次还在 running 时跳过本次,避免叠加
- 每次运行新建一个 `[任务] xxx` 会话,产物落库成可回看的对话(含 thinking / 工具轨迹 / 文件)
- `max_runtime_seconds` 超时强制中断 → 标记 `timeout`
- **孤儿运行回收**:进程重启后,启动时自动把残留的 `running`/`pending` 运行收尾为 `failed`,避免任务被 skip 策略永久卡死
- 结果通过站内通知 / 邮件推送(可配 `notify_on=always/success/failure`)

### 3.8 远程桥接(飞书 / 企业微信)

- **飞书**：走**长连接(WebSocket)**,只填 App ID / App Secret,**无需公网地址、无需回调 URL、无需 verification_token / encrypt_key**
- lark-oapi ws 客户端在守护线程内运行,入站消息经 `run_coroutine_threadsafe` 交回主事件循环执行 AgentRunner,再用 REST 回复
- **企业微信**：走**加密回调(webhook)**,自建应用『接收消息』推送加密 POST 到 `/api/bridge/wecom/webhook`;后端 AES-CBC(WXBizMsgCrypt)解密+sha1 签名校验,立即 200 应答后**异步**跑专家,再用 `access_token` + `/message/send` 主动把回答推回用户;回调地址需公网可达(桌面可用 cpolar/frp 穿透 47900)
- 每个外部会话绑定一个持久本地 Conversation,多轮上下文延续
- 渠道密钥 Fernet 加密存库;保存即热重载连接,状态(已连接/错误)实时写回

### 3.9 连接应用(CLI Apps)

- 把本地命令行工具(如 Claude Code 等)接入智能体,在**进程内**以 MCP 形式暴露,无需独立 MCP server
- 静态目录(`runtime/cli_apps_catalog.py`)+ 安装检测 + 启停;对话框可临时连接,仅本轮生效

### 3.10 桌面端运行架构

- Electron 主进程拉起 Python 后端作为 sidecar(稳定端口 47900),等待 `/api/health` 后加载前端
- 数据库默认 SQLite(`~/.h3c-agent/app.db`),storage 同目录;单机用户回落为 id=1
- 启动时幂等建表 + 种子(默认账号 / 默认智能体),开箱即用（模型需用户在管理界面自行添加）
- 生产打包:Python 后端经 PyInstaller 冻结为单目录可执行文件,用户无需安装 Python;前端构建后由后端同源托管

---

## 四、快速开始

桌面端不依赖服务器与 Docker，只需 Python（≥3.11）+ Node.js（≥18）即可本地跑起来。

### 4.1 环境准备（一次性）

**macOS**

```bash
# 后端：Python 虚拟环境 + 依赖
cd backend
python3 -m venv .venv && source .venv/bin/activate
cp .env.example .env          # 填 JWT_SECRET / ENCRYPTION_KEY 等（缺省也能跑）
pip install -e .

# 前端
cd ../frontend
npm install

# 桌面壳
cd ../desktop
npm install
```

**Windows（PowerShell）**

```powershell
# 后端：Python 虚拟环境 + 依赖
cd backend
python -m venv .venv
.venv\Scripts\activate
copy .env.example .env        # 填 JWT_SECRET / ENCRYPTION_KEY 等（缺省也能跑）
pip install -e .

# 前端
cd ..\frontend
npm install

# 桌面壳
cd ..\desktop
npm install
```

### 4.2 开发模式（一键拉起，推荐先跑通）

同时在 Electron 窗口里跑前后端，数据和浏览器环境一样（Vite HMR 热更新也生效）。

**macOS**

```bash
cd desktop
npm run dev
```

**Windows（PowerShell）**

```powershell
cd desktop
npm run dev
```

这会自动启动：
1. Vite 前端开发服务器 → `http://localhost:5173`
2. Python FastAPI 后端 → 端口 `47900`
3. Electron 窗口 → 加载 Vite 页面

数据全部保存在 `~/.h3c-agent`（SQLite + storage），无需登录服务器，离线可用。首次启动自动创建数据库表 + 种子账号（`admin` / `admin123`）。

### 4.3 纯后端 / 前端分开调试

不需要 Electron 窗口时，可以在浏览器里调试前端，方便排查网络请求等问题。

**macOS**

```bash
# 终端1：后端（FastAPI :8000，SQLite 自动建表）
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# 终端2：前端（Vite :5173，API 请求反代到 8000）
cd frontend && npm run dev
```

**Windows（PowerShell）**

```powershell
# 终端1：后端
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000

# 终端2：前端
cd frontend
npm run dev
```

然后浏览器访问 `http://localhost:5173`。

### 4.4 打包安装程序

桌面应用把 Electron 壳 + PyInstaller 冻结的 Python 后端 + Vue 前端一起塞进安装包，用户**无需安装 Python**。

> ⚠️ **PyInstaller 不支持交叉编译**：打包哪个平台就必须在哪个平台上执行。

**macOS 打包**

```bash
cd desktop

# 初次打包需先装好 PyInstaller
cd ../backend && source .venv/bin/activate && pip install pyinstaller && deactivate
cd ../desktop

npm run dist:mac
# 产物：desktop/release/H3C Agent-<版本>-arm64.dmg  和  -x64.dmg
```

**Windows 打包（必须在 Windows 上执行）**

```powershell
cd desktop

# 初次打包需先装好 PyInstaller
cd ..\backend
.venv\Scripts\activate
pip install pyinstaller
deactivate
cd ..\desktop

npm run dist:win
# 产物：desktop\release\H3C Agent-Setup-<版本>.exe（NSIS 安装向导）
```

打包脚本 `npm run dist:win` 分 4 步自动执行：

| 步骤 | 命令 | 说明 |
|------|------|------|
| `build:frontend` | `cd ../frontend && npm run build` | Vue 生产构建 → `frontend/dist` |
| `build:backend` | `node build-backend.js` | PyInstaller 冻结 → `backend/dist/h3c-agent-backend` |
| `prepare:resources` | `node prepare-resources.mjs` | 拷贝产物到 `desktop/resources/` |
| electron-builder | `electron-builder --win` | 打包 NSIS 安装程序 |

打包完成后双击 `desktop\release\H3C Agent-Setup-<版本>.exe` 即可安装。

> **NSIS 安装器特性**：支持自定义安装路径、桌面快捷方式、开始菜单快捷方式。未签名安装包首次运行可能会被 Windows Defender 拦截，点击「更多信息 → 仍要运行」即可。
>
> 完整打包说明（代码签名 / 公证 / 图标）见 [`desktop/BUILD.md`](desktop/BUILD.md)。

### 4.4 关键配置（`backend/.env`，均可选）

> 所有真实凭证只放 `backend/.env`（已 gitignored）。缺省值能直接启动，按需补齐。

```bash
# ── 鉴权 ───────────────────────────────────────────────
JWT_SECRET=<48字节随机串>             # python3 -c "import secrets; print(secrets.token_urlsafe(48))"
ENCRYPTION_KEY=<Fernet 32字节>        # python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ACCESS_TOKEN_EXPIRE_MINUTES=720
REFRESH_TOKEN_EXPIRE_DAYS=2

# ── 初始账号（首次登录后请修改）────────────────────────
SEED_ADMIN_USERNAME=admin
SEED_ADMIN_PASSWORD=admin123

# ── MinerU 文档解析（可选，留空则仅本地库解析）─────────
MINERU_MODE=cloud              # cloud | local | disabled
MINERU_BASE_URL=https://mineru.net
MINERU_API_KEY=<token>         # mineru.net 注册后申请
MINERU_TIMEOUT_SEC=60
PARSED_MARKDOWN_HARD_LIMIT=20000
# 私有化部署只需改以下三项，业务代码零侵入:
#   MINERU_MODE=local
#   MINERU_BASE_URL=http://10.0.0.50:8000
#   MINERU_API_KEY=（通常不需要）

# ── SMTP 邮件通知（可选，全部留空则禁用）──────────────
SMTP_HOST=smtp.qq.com
SMTP_PORT=587
SMTP_USER=xxx@qq.com
SMTP_PASSWORD=<QQ授权码>       # QQ 邮箱设置 → IMAP/SMTP → 生成授权码（不是登录密码）
SMTP_FROM=显示名 <xxx@qq.com>  # QQ 要求邮箱部分必须等于 SMTP_USER
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

---

## 五、API 速查

### 用户端

```
POST   /api/auth/login                              本地账号登录
POST   /api/auth/refresh                            刷新 token
GET    /api/auth/me                                 当前用户

GET    /api/agents                                  可用的 Agent
GET    /api/agents/default                          默认 Agent
GET    /api/agents/{id}/capabilities                Agent 能力(模型/Skill/MCP)
GET    /api/agents/{id}/mcps/{mid}/tools            实时拉取该 Agent 某 MCP 的工具列表

GET    /api/conversations                           会话列表
POST   /api/conversations                           新建会话
PATCH  /api/conversations/{id}                      重命名
DELETE /api/conversations/{id}                      删除
GET    /api/conversations/{id}/messages             消息列表(自动 hydrate 文件)
POST   /api/conversations/{id}/messages             发消息(SSE 流)

POST   /api/files/upload                            上传文件(后台异步解析)
GET    /api/files/{id}                              查解析状态
POST   /api/files/{id}/reparse                      重试解析
DELETE /api/files/{id}                              删除
GET    /api/files/{id}/raw                          原始文件流(支持 ?t= 直链)
GET    /api/downloads/{token}                       Skill 产物下载(token URL)

GET    /api/tasks                                   定时任务列表
POST   /api/tasks                                   新建任务
PATCH  /api/tasks/{id}                              编辑
POST   /api/tasks/{id}/run                          手动触发一次
POST   /api/tasks/{id}/toggle                       启用 / 停用
GET    /api/tasks/{id}/runs                         运行历史
POST   /api/task-runs/{rid}/cancel                  取消运行

GET    /api/bridge/channels                         远程桥接渠道(飞书 / 企业微信)
PUT    /api/bridge/channels/{ch}                    保存渠道配置(热重载)
POST   /api/bridge/channels/{ch}/test               检查连接状态
GET    /api/bridge/wecom/webhook                    企业微信回调 URL 验证(回显 echostr)
POST   /api/bridge/wecom/webhook                    企业微信消息接收(加密回调,异步回复)

GET    /api/workspaces                              工作空间(本地目录)
GET    /api/favorites                               收藏问答
GET    /api/notifications                           站内通知
```

### 配置端(`/api/admin/`)

```
models                                              # 模型 + /test
mcp              + /{id}/ping  + /{id}/tools        # MCP
skills           + /upload  + /{id}/files  + /{id}/file (PUT 在线编辑)
agents
cli-apps         + /catalog                         # 连接应用
logs/calls       logs/audit                         # 双日志
```

### SSE 事件类型

```
meta          首次响应,带 agent/model/provider
thinking      思考过程 token(可折叠)
text          正文 token(流式)
tool_use      工具调用开始(状态卡)
tool_result   工具返回(状态卡 done)
file          文件产物登记(下载卡片)
error         流式错误
done          结束 + token 用量 + 延迟
```

---

## 六、数据模型(主要表)

```
users                                本地账号(单用户回落 id=1)

models                               provider + api_key_enc + extra_params
mcp_connectors                       transport + config_json + 工具摘要缓存
skills                               type ∈ {atomic, composite}
cli_apps                             连接应用(已安装 CLI 工具)

agents                               default_model_id + system_prompt + upload_policy_json + max_turns + effort + work_dir(默认工作目录)
agent_skills, agent_mcps, agent_cli_apps   多对多

conversations                        agent (+ workspace_id / permission_mode)
messages                             content_json(text/thinking/files) + tool_calls_json
workspaces                           本地目录沙箱 + 权限模式
favorites                            收藏问答(含 files_json 产物快照)
notifications                        站内通知

tasks                                定时任务(schedule_type/value + 并发策略 + 通知配置)
task_runs                            每次运行(status/started/finished/tokens/summary)

channel_configs                      远程桥接渠道(飞书 / 企业微信,config_enc 加密)
channel_bindings                     外部会话 → 本地 Conversation 绑定

uploaded_files                       parse_status / parsed_markdown / parsed_chars / last_used_at
download_tokens                      token + expires_at + user_id

audit_logs                           工具调用 / action / target / detail_json
call_logs                            tokens / latency / status
```

---

## 七、二次开发指引

| 我想... | 改这里 |
|---|---|
| 接新模型供应商 | `agent_runner.py:_stream_via_openai` provider 路由(已通 OpenAI 兼容协议)+ 前端 `Models.vue` PROVIDERS 数组 |
| 加新文件类型解析 | `services/file_parser.py:_local_for_ext` + `MINERU_EXTS` |
| 私有化 MinerU | 改配置;若接口形状不同,改 `services/mineru_client.py` 单文件 |
| 新增 Skill 工具 | `agent_runner.py:_build_openai_tools` 加 function 定义 + `_exec_skill` 加分派 |
| 加自定义安全规则 | `core/security_rules.py` 加正则 |
| 新增预览类型 | `components/PreviewPanel.vue` + `FileCard.vue` PREVIEWABLE 集合 |

---

## 八、敏感信息安全

**绝不提交到代码库**:

- `backend/.env`(已 gitignored) — 所有真实凭证只放这里
- `.history/`、`.vscode/`、`.idea/`(已 gitignored) — IDE 本地快照,可能含中间密码
- 任何含 `*_API_KEY` / `*_PASSWORD` / `*_SECRET` 的真值
- `.pem` / `.key` 私钥文件、`*.db` / `*.sqlite` 本地数据库

提交前自检:

```bash
git diff --staged | grep -iE 'password|api[_-]?key|secret|token' | grep -v 'placeholder\|example\|change-me'
```

如果有真值,**立即**:
1. 不要 push;`git reset HEAD <file>` 把改动撤回工作区,改成从 `.env` 读
2. 已 push 的话,先去对应服务平台(QQ 邮箱、各 LLM provider、…) **吊销密码 / 轮换 key**,再考虑 `git filter-repo` 重写历史

---

## 九、版本规划

**已完成**
- 双路径流式 / Skill 三态 / MCP 三 transport / MinerU 解析 / 文件预览 / 分层安全加固 / 审计
- 桌面端单机模式(Electron + SQLite,PyInstaller 冻结后端)
- 定时任务(自动化)+ 运行历史 + 通知
- 远程桥接(飞书长连接 + 企业微信加密回调)
- 连接应用(CLI Apps)+ 工作空间 + 收藏
- 应用内检查更新(GitHub Releases)

**规划中**
- 子 Agent 委托(主-从架构)
- 配额 / 成本控制
- Skill 市场(导出/导入)
- 更多桥接渠道(QQ / 微信公众号 / 钉钉)
- 桌面伙伴(Pet)交互增强

---

## 十、致谢

- [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk) — 智能体核心
- [MinerU](https://mineru.net) — 文档解析
- [Element Plus](https://element-plus.org) — UI 组件
- [lark-oapi](https://github.com/larksuite/oapi-sdk-python) — 飞书长连接
- [pycryptodome](https://www.pycryptodome.org) — 企业微信回调 AES 加解密

---

## License  许可协议

Business Source License 1.1 (BSL-1.1)
- [商业源代码许可协议 1.1 (BSL-1.1)](LICENCE.MD)

Personal / academic / non-profit use: free and unrestricted
Commercial use: requires a separate license — contact @扶摇Sun on 小红书
Change date: 2029-03-16 — after which the code converts to Apache 2.0
