# 技术方案：任务产物文件卡片（生成 → 卡片展示 → 预览/下载）

> 适用范围：本文整理 h3c-agent 项目中「系统执行 Skill/任务时生成的多类型文件，如何以文件卡片 UI 形式展示在聊天窗口中，并支持预览与下载」的完整实现逻辑，供移植到其他项目使用。
>
> 整理日期：2026-09-01

---

## 整体架构总览

```
┌────────────────────────── 后端 ──────────────────────────┐
│  Skill/MCP/脚本执行产出文件 (4 个入口，全部收敛)            │
│      ↓                                                    │
│  文件落盘到 storage/outputs/<user_id>/ 共享会话工作区       │
│      ↓                                                    │
│  register_file() → 生成短期下载令牌 DownloadToken (DB)      │
│      ↓                                                    │
│  文件元信息 append 到 runner._saved_files                  │
│      ↓                                                    │
│  AgentRunner 在 tool_result 之后 / done 之前               │
│  yield StreamEvent("file", info)  ← 去重                  │
│      ↓                                                    │
│  chat.py SSE 循环: 边推流边收集 saved_files                │
│      ↓                                                    │
│  持久化到 Message.content_json["files"] (历史回放用)        │
└───────────────────────────────────────────────────────────┘
┌────────────────────────── 前端 ──────────────────────────┐
│  chat store SSE 解析: type==='file' → push m._files       │
│      ↓                                                    │
│  Chat.vue: 合并 _files / content_json.files, 分组渲染      │
│      ↓                                                    │
│  FileCard.vue 卡片 (图标/类型/预览/下载按钮)                │
│      ├─ 预览 → PreviewPanel (iframe/文本/Office解析)       │
│      └─ 打开/下载 → /api/downloads/{token}                │
│           └─ token 过期 → /api/downloads/refresh 换新token │
└───────────────────────────────────────────────────────────┘
```

---

## 一、后端：文件产出的 4 个入口（全部收敛到同一管线）

代码位置：`backend/app/runtime/agent_runner.py`

### 入口 1：模型主动调用 `create_file_card` 工具（主路径）

Runner 在构造工具列表时**始终注册**这个工具（agent_runner.py 行 588-655），工具有两种模式：

- **path 模式**（优先）：文件已由脚本/命令落盘，只传路径 → `_create_file_card_from_path()`
- **content 模式**：内容还在模型上下文中没落盘，传 `filename + content`（二进制用 base64）→ `_save_output_file()`

工具描述中明确约束模型行为（关键的产品化细节）：

> "优先传 path……不要再读取文件内容重写一遍"；"严禁在回复里写下载链接"

### `_save_output_file()` 的关键逻辑（行 1550-1775）

```python
# 1. 解包 widget JSON —— 模型有时把 {"title":..., "widget_code":"<html>..."} 
#    当 content 传进来，直接保存会得到不可预览的 .txt。
#    系统解出内层代码，并根据内容嗅探改扩展名 (.html/.svg)，
#    甚至补 DOCTYPE、把 <script> 移到 </body> 前避免 TDZ 报错

# 2. 文件名安全化 —— 保留目录结构（sources/slide-01.html），
#    逐段清洗：去掉 ..、绝对路径前缀、非法字符
raw_parts = [p for p in filename.split("/") if p not in ("", ".", "..")]
cleaned = re.sub(r"[^\w\.\-]+", "_", part).strip("._-")

# 3. 写入共享会话工作区 (storage/outputs/<user_id>/ 下)
target = self._safe_session_path(rel_name)   # 防 path traversal
# 二进制格式且非 base64 → 拒绝，防止模型把二进制当文本存坏
# 单文件上限 20MB，写后检查

# 4. 注册下载令牌
async with SessionLocal() as db:
    tok = await register_file(db, file_path=str(target), file_name=safe,
                              user_id=self._user_id, mime=mime)
    download_url = f"/api/downloads/{tok.token}"

# 5. 计算稳定的 output_path（相对路径，令牌过期后仍可凭它换新令牌）
info = {
    "name": safe, "size": size, "mime": mime, "ext": ext,
    "download_url": f"/api/downloads/{tok.token}",
    "preview_url": download_url,
    "local_path": str(target),
    "output_path": "5/abcd1234-report.html",   # 相对 outputs 根
}
self._saved_files.append(info)   # ← 副作用：待发射队列
```

### `_create_file_card_from_path()`（行 1459-1547）

- 在候选路径中查找真实文件（绝对路径 / 会话工作区相对路径）
- **安全约束**：文件必须位于 `outputs/` 或 `uploads/` 允许根下；否则**复制一份**到会话工作区再注册（不直接暴露任意路径）
- 同样走 `register_file()`，追加到 `_saved_files`

### 入口 2：Skill 执行结果自带 `_files`

`_register_skill_files()`（行 1101-1134）：Skill 返回 `{"_files": [{path, name, mime}]}` 时自动注册。注意一个巧妙的细节——**从返回给模型的结果中剥掉 `download_url`**，只留描述字段：

```python
result["files"] = [
    {k: v for k, v in item.items() if k not in ("download_url",)}
    for item in registered
]
```

原因：把 URL 暴露给模型会导致模型把链接写进回复文本，变成失效的 markdown 链接（浏览器直接 GET 没有 Bearer 头）。卡片 URL 只走 UI 层的 SSE 事件。

### 入口 3：MCP 工具返回 `_files`

`_register_mcp_files()`（行 1139-1240）：兼容三种内容来源，按序尝试：

1. `path` — 本机绝对路径（同机 MCP）
2. `content_b64` — base64 编码字节
3. `content` — 纯文本字符串

写入 `outputs/<user_id>/<uuid前8位>-<name>`，注册令牌并追加 `_saved_files`。另有 `_maybe_register_files_from_tool_result()` 处理 Anthropic SDK 路径下 tool_result 是原始 JSON 字符串的情况。

### 入口 4：`run_skill_script` 脚本产物自动发现（行 2085-2166）

脚本执行后按优先级探测产物路径：

```python
if isinstance(result, str) and _Path(result).exists():        # 返回了路径字符串
elif isinstance(result, dict):
    # 探测 output / output_path / html_path / path 字段
    # 以及 result["file"]["path"] 等
if produced is None and target_path.exists():                  # 平台注入了 --output
    produced = target_path
# 写到别处的文件 → move/copy 到注入的 target_path 再注册
```

### 入口 5（兜底）：`_extract_fallback_files()`（行 1779-1812）

流结束时如果模型**没有调工具而是把大段代码贴在回复文本里**，用正则提取 ` ```lang ... ``` ` 围栏（≥2048 字节），自动落盘为 `output-1.html` 等并生成卡片。保证用户体验永不落空。

---

## 二、下载令牌服务（安全核心）

代码位置：

- `backend/app/services/downloads.py`（令牌注册/解析）
- `backend/app/api/downloads.py`（HTTP 端点）
- DB 模型 `DownloadToken`

### 令牌模型

```python
tok = DownloadToken(
    token=secrets.token_urlsafe(32),     # 不透明随机令牌，真实路径永不下发
    user_id=owner_id,                    # 属主，下载时校验
    file_path=str(real),                 # 服务器端真实路径
    file_name=..., mime=..., size=...,
    expires_at=now + 72h,                # TTL
    max_downloads=0,                     # 可选下载次数上限
)
```

`register_file()` 注册前做两道校验：

1. 文件真实存在
2. **路径包含校验**：真实路径必须在 `UPLOADS_DIR` 或 `STORAGE_ROOT/outputs` 允许根内（防 path traversal）

### 下载端点 `GET /api/downloads/{token}`

鉴权采用**双通道**（浏览器下载的关键设计）：

```python
# Authorization: Bearer <jwt>  OR  ?t=<jwt>
# 因为 <a download>、<img src>、window.open 无法携带自定义 header
if payload.get("type") != "access": raise HTTPException(401, ...)
```

`resolve_token()` 依次校验：令牌存在 → 未过期 → 属主匹配 → 未超下载次数 → 路径仍在允许根内 → 文件仍存在。错误映射为 HTTP 状态码（404/410/403/400）。每次下载写 `AuditLog` 并累加计数，然后 `FileResponse` 流式返回。

### 令牌续期 `POST /api/downloads/refresh?output_path=...`

72 小时 TTL 过期后（历史消息里的卡片必然过期），前端凭**稳定的相对路径** `output_path` 换新令牌：

- `output_path` 相对路径校验（拒绝 `..`），resolve 后必须在 outputs 根内
- **属主判定**：outputs 按 `<user_id>/` 目录隔离，路径首段必须等于当前用户 id（admin/operator 豁免）
- 重新 mint 令牌返回新的 `download_url`

---

## 三、SSE 事件发射与持久化

### AgentRunner 发射（去重）

`_saved_files` 是"待发射队列"，发射点有三处（每次工具调用后、流结束时、UI_ACTION 短路路径中），全部带 URL 去重：

```python
for f in self._saved_files:
    url = str(f.get("download_url") or "")
    if url and url in self._emitted_file_urls:
        continue
    if url:
        self._emitted_file_urls.add(url)
    yield StreamEvent("file", f)     # ← SSE 事件 type="file"
yield StreamEvent("done", {..., "files": list(self._saved_files)})
```

发射时机：在 `tool_result` 事件**之后**、`done` **之前**，保证前端先看到工具步骤完成，再看到文件卡片出现在消息底部。

### chat.py SSE 层（backend/app/api/chat.py 行 668-700）

```python
async for ev in runner.stream(clean_text, files):
    payload_json = {"type": ev.type, "data": ev.data}
    yield f"data: {json.dumps(payload_json, ensure_ascii=False)}\n\n"
    ...
    elif ev.type == "file":
        saved_files.append(ev.data)      # ← 边推流边收集
finally:
    content_payload["files"] = saved_files   # ← 持久化进 assistant 消息
    am = Message(conversation_id=cid, role="assistant",
                 content_json=content_payload, ...)
```

**这是历史回放的关键**：实时看是 SSE `file` 事件 → `m._files`；刷新页面后从 DB 读 `content_json.files`，同一份数据结构。

---

## 四、前端实现

### 1. SSE 解析（frontend/src/stores/chat.ts 行 86-87）

```typescript
} else if (type === 'file') {
    m._files = Array.isArray(m._files) ? [...m._files, data] : [data]
}
```

`applyStreamEvent` 是纯数据变更函数，视图响应式更新。SSE 手工解析：`fetch` + `ReadableStream` reader，按 `\n\n` 分帧。

### 2. 渲染与分组（frontend/src/views/chat/Chat.vue）

```typescript
// 实时流优先用 _files，历史回放退回 content_json.files
function outputFilesOf(m: any): any[] {
  return m?._files?.length ? m._files : (m?.content_json?.files || [])
}

// ≥2 个代码文件自动折叠成"代码变更包"，其余逐个渲染卡片
function groupedOutputFiles(m: any) {
  const code = files.filter(f => CODE_OUTPUT_EXT.has(fileExt(f)))
  const rest = files.filter(f => !CODE_OUTPUT_EXT.has(fileExt(f)))
  if (code.length >= 2) groups.push({ kind: 'code', files: code })
  ...
}
```

卡片渲染在消息**正文之后**（生成物落在消息底部，不用回滚查找）。用户消息的附件则渲染为小 chip（`msg-file-chip`），可点击预览。

### 3. FileCard.vue（frontend/src/components/FileCard.vue）

- **类型分类**：按扩展名分 image/code/text/document/office/archive，决定图标、配色、徽标
- **可预览白名单**：`PREVIEWABLE` 集合（html/pdf/office/md/文本/代码/图片…），决定是否显示"预览"按钮
- **令牌保鲜**（行 88-107）——点击前主动探测过期：

```typescript
async function ensureFreshToken(): Promise<string> {
  const r = await fetch(url, { headers: getAuthHeader() })
  if (r.ok) return url
  if (r.status === 410 || 404 || 403) {
    const fresh = await api.refreshDownload(props.file.output_path)  // ← 凭稳定路径换新
    props.file.download_url = fresh.download_url   // 原地变异量，历史消息也同步更新
    return fresh.download_url
  }
}
```

- **双端适配**：桌面端（Electron）走 `window.desktop.openPath(local_path)` 用本机默认应用打开；Web 端走 `window.open(url + '?t=' + accessToken)` 新窗口打开

### 4. PreviewPanel.vue（右侧分屏预览）

多标签设计（文件/终端/浏览器 tab）。按文件类型路由渲染器：

- html/pdf/svg/图片 → `iframe src=download_url`
- 代码/文本 → 内联渲染
- Office（docx/pptx/xlsx）→ `GET /api/downloads/{token}/preview`，后端 `office_preview.py` 用 python-docx / zipfile+XML 解出结构化 JSON（段落/表格/幻灯片文本），前端绘制轻量预览——不依赖 Office 套件

---

## 五、移植到其他项目的清单

### 必须迁移的模块（按依赖顺序）

| # | 模块 | 说明 |
|---|------|------|
| 1 | `DownloadToken` 表 + `services/downloads.py` | 令牌注册/解析/清理，可几乎原样照搬 |
| 2 | `api/downloads.py` | 3 个端点：下载、Office 预览、refresh 续期 |
| 3 | Runner 的产物收集管线 | `_saved_files` 队列 + `_emitted_file_urls` 去重 + `create_file_card` 工具 schema 与两个实现函数 |
| 4 | SSE `file` 事件 + 消息持久化 `content_json["files"]` | 保证实时/历史一致 |
| 5 | 前端 `FileCard.vue` / `PreviewPanel.vue` / store 的 `type==='file'` 分支 / Chat.vue 的 `outputFilesOf` + `groupedOutputFiles` | 可直接复制 |

### 移植时必须保留的设计要点

1. **统一收敛**：无论 Skill、MCP、脚本还是模型贴文本，所有产物都汇入同一个 `_saved_files` 队列，一次发射逻辑、一套去重。
2. **模型与 UI 数据分离**：`download_url` 永远不进模型上下文（用 `strip download_url` + 工具描述禁止），否则模型会写出失效链接。工具 result 只回 `{"ok": true, "file": {...}, "message": "前端会显示本地文件卡片"}`。
3. **双标识**：每张卡片同时带短期 `download_url`（令牌）和长期 `output_path`（稳定相对路径），令牌过期可无状态续期——不需要单独的 outputs 表。
4. **双通道鉴权**：下载端点必须同时接受 `Bearer` 头和 `?t=` 查询参数（浏览器直链场景），属主校验 + 路径包含校验缺一不可。
5. **安全防线**：文件名逐段清洗（拒 `..`/绝对路径）、落盘后路径包含复验、二进制格式拒绝文本保存、单文件 20MB 上限、refresh 的属主判定靠 `<user_id>/` 目录前缀。
6. **发射时序**：`file` 事件在 `tool_result` 后、`done` 前发出，卡片出现在消息底部。
7. **兜底提取**：`_extract_fallback_files` 兜住模型不调工具直接贴代码的场景（阈值 2048 字节，且本回合已有文件则跳过防重复）。
8. **持久化即回放**：`content_json["files"]` 存的是与 SSE 事件完全相同的结构，前端两个数据源二选一即可。

### 技术栈适配说明

如果目标项目技术栈不同（比如 React 而非 Vue，或非 SSE 而是 WebSocket），只有第 4、5 项需要改写传输层和渲染层，第 1-3 项的后端管线（令牌服务 + 收集/发射管线）可以原样移植。

---

## 附：关键代码位置索引

| 功能 | 文件 | 位置 |
|------|------|------|
| `create_file_card` 工具 schema | `backend/app/runtime/agent_runner.py` | 行 588-655 |
| path 模式注册 | 同上 `_create_file_card_from_path` | 行 1459-1547 |
| content 模式落盘 | 同上 `_save_output_file` | 行 1550-1775 |
| 兜底代码块提取 | 同上 `_extract_fallback_files` | 行 1779-1812 |
| Skill `_files` 注册 | 同上 `_register_skill_files` | 行 1101-1134 |
| MCP `_files` 注册 | 同上 `_register_mcp_files` | 行 1139-1240 |
| 脚本产物探测 | 同上 `_run_skill_script` 尾部 | 行 2085-2166 |
| file 事件发射（3 处） | 同上 | 行 2395-2401 / 2530-2538 / 3030-3034 |
| SSE 收集与持久化 | `backend/app/api/chat.py` | 行 668-700 |
| 令牌注册/解析 | `backend/app/services/downloads.py` | 全文 |
| 下载/预览/续期端点 | `backend/app/api/downloads.py` | 全文 |
| Office 轻量预览 | `backend/app/services/office_preview.py` | 全文 |
| SSE 前端解析 | `frontend/src/stores/chat.ts` | 行 44-106 |
| 卡片组件 | `frontend/src/components/FileCard.vue` | 全文 |
| 预览分屏 | `frontend/src/components/PreviewPanel.vue` | 全文 |
| 渲染与分组 | `frontend/src/views/chat/Chat.vue` | 行 187-217 / 1384-1402 |
