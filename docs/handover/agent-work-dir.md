> 产品思考见 [docs/insights/why-agent-work-dir.md](../insights/why-agent-work-dir.md)

# 专家默认工作目录（Agent.work_dir）

## 背景
此前专家只有在对话被绑定到「项目 / Workspace」时才拥有本地工作目录与文件工具（list_dir / read_file / write_file / run_command）。某些专家天生就服务于固定目录（如某个代码库、某个资料库），每次对话都要用户手动选目录，体验割裂。本特性允许在「专家管理」新增 / 编辑专家时配置一个默认工作目录。

## 数据层
`agents` 表新增列：

| 列 | 类型 | 说明 |
|---|---|---|
| `work_dir` | `VARCHAR(1024)`，可空 | 专家默认本地工作目录的绝对路径。留空 = 不绑定本地目录 |

- 模型定义：`backend/app/db/models.py` → `Agent.work_dir`
- 幂等迁移：`backend/app/db/init_db.py` → `ALTER TABLE agents ADD COLUMN IF NOT EXISTS work_dir VARCHAR(1024)`
- Schema：`backend/app/schemas/__init__.py` → `AgentIn.work_dir` / `AgentOut.work_dir`（均 `str | None = None`）

## 工作目录解析优先级
调用专家时，最终生效的工作目录按以下优先级确定（实现于 `backend/app/api/chat.py`）：

1. **用户在首页对话框选择的工作目录**（会话绑定的 `Conversation.workspace_id` → `Workspace.path`）——最高优先级
2. **专家配置的默认工作目录**（`Agent.work_dir`）——当会话没有绑定 workspace 时回退到此
3. **都没有** → 传空，专家进入普通对话模式（无本地文件系统工具）

核心回退逻辑集中在 `_load_agent_context()`：当传入的 `workspace_dir` 为空且 `Agent.work_dir` 非空时，用 `work_dir` 兜底，并将 `permission_mode` 默认置为 `ask`（用户在会话里显式选择的权限仍优先生效）。

> 安全兜底：`AgentRunner` 对所有工作目录文件工具都用 `_os_isdir(ws_dir)` 守卫。若 `work_dir` 配置了但目录在磁盘上不存在，等价于「传空」，专家退回普通对话，不会报错。

## 各调用入口的覆盖情况
- `POST /api/conversations/{cid}/messages`（`api/chat.py`，首页对话）：workspace > work_dir > 空
- 定时任务（`services/task_runner.py`）：任务专家若配置了 `work_dir`，则任务在该目录内执行
- Bridge 渠道（`services/bridge_manager.py`）：经由 `_load_agent_context` 自动获得 `work_dir` 回退

## 前端
`frontend/src/views/admin/Agents.vue`：
- 新建 / 编辑专家弹窗在「思考深度」与「专家能力」之间新增「工作目录」表单项
- 桌面端（`window.desktop.isDesktop`）提供「选择目录」按钮，调用 `window.desktop.openFolder()` OS 目录选择器；Web 端可手动粘贴路径
- 字段：`form.work_dir`，随表单一起提交到 `createAgent` / `updateAgent`，留空提交空字符串
