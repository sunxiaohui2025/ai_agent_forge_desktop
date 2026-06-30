> 产品思考见 [docs/insights/why-skill-market-install.md](../insights/why-skill-market-install.md)

# 从市场安装技能（SkillHub）

## 背景
此前技能库只有两种入库方式：手动新建（填 path/callable/YAML）和上传本地 zip 包。要扩充技能得先在别处拿到包。本特性在「技能」管理页新增「从市场安装技能」入口，直接在应用内浏览 / 搜索腾讯 SkillHub 的公开技能目录并一键安装到本地技能库，装完即可挂载给各专家。

## 关键设计：直连 HTTP API，不用 CLI
腾讯的 `skillhub` 命令行工具本质上只是公开 HTTP API（`api.skillhub.cn`）的封装，且 CLI 会全局安装到 `~/.skillhub`、面向 OpenClaw 风格的 `skills/` 目录布局——这与本项目「Electron + 打包 FastAPI sidecar + 自有 SKILLS_DIR」的形态不匹配。因此我们**直接调用其 HTTP API**：无需全局 CLI、无子进程、dev 与打包构建行为一致。

下载回来的 zip 包根目录即含 `SKILL.md`，与现有上传流程期望的结构完全一致，因此**安装完全复用上传的落盘链路**。

## SkillHub API 契约（实测确认）
- 默认浏览：`GET /api/v1/showcase/{hot|featured|newest|recommended|trending}` → `{section, skills:[...], total}`（返回全量，分页在后端本地切片）
- 关键词搜索：`GET /api/v1/search?q=&page=&limit=` → `{results:[...]}`（服务端分页）
- 详情：`GET /api/v1/skills/{slug}` → `{latestVersion:{version,changelog}, owner, securityReports:{keen,sanbu}}`
- 下载：`GET /api/v1/download?slug=` → `application/zip`（root 含 SKILL.md）

字段名在 search 与 showcase 间不一致（`icon_url` vs `iconUrl`、`owner_name` vs `ownerName`），由 `normalize_item` 归一成统一前端契约。

## 后端
### 新增 `backend/app/services/skill_market.py`
封装 SkillHub 客户端：`list_skills` / `search_skills` / `detail` / `download_zip`，以及 `normalize_item`。带 TTL 内存缓存（默认 600s）规避频繁外呼；下载校验 Content-Type 与体积上限。

### `backend/app/api/admin/skills.py`
- 把原 `upload_skill` 的核心步骤抽成共享函数 `_install_from_zip_bytes(...)`：解压 → 定位 SKILL.md → 静态安全扫描（`scan_skill_dir`）→ 落盘 `SKILLS_DIR/<code>/` → 入库 atomic Skill → 后台 `summarize_skill`。上传与市场安装共用此函数。
  - 支持 `overwrite`：覆盖前把旧目录移到 `.__bak_<code>`，失败回滚、成功后删除备份。
  - `source_json` 记录来源：`{path, origin, origin_slug, origin_version}`，为后续「检查更新」留口子。
  - 命中安全规则默认拦截，返回 `findings`，前端展示后由管理员勾选 `force` 强制安装。
- 新增路由（沿用 `require_admin_or_operator` 鉴权）：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/admin/skills/market` | 列表：`q` 走搜索、否则按 `section` 浏览；标注 `installed`/`installed_id` |
| GET | `/api/admin/skills/market/{slug}` | 详情：版本、作者、SkillHub 安全报告链接 |
| POST | `/api/admin/skills/market/{slug}/install` | 下载→扫描→落盘→入库；body `{name,description,force,overwrite}` |

- `_slug_to_code(slug)`：把市场 slug 清洗成合法 code（仅 `a-z0-9_-`、字母开头，否则加 `skill-` 前缀，截断 64）。

### 配置（`core/config.py` + `.env.example`）
`SKILLHUB_ENABLED` / `SKILLHUB_API_BASE` / `SKILLHUB_CACHE_TTL` / `SKILLHUB_MAX_PACKAGE_MB` / `SKILLHUB_TIMEOUT_SEC`。内网隔离环境可置 `SKILLHUB_ENABLED=false`，前端入口仍在但接口返回 503。

## 前端
### `frontend/src/api/index.ts`
新增 `marketSkills` / `marketSkillDetail` / `installMarketSkill`（install 用 `skipErrorToast` 以便内联展示安全 findings）。

### `frontend/src/views/admin/Skills.vue`
- 「新建 Skill」按钮后新增「从市场安装技能」（图标 `Shop`）。
- 市场抽屉（`el-drawer`，size 980）：顶部搜索框 + 分类 tab（热门/精选/最新/推荐/趋势），卡片网格展示图标/名称/作者/下载量/星标/版本，已安装项标灰；底部上一页/下一页分页。
- 安装确认弹窗：展示描述、版本、本地映射 code、SkillHub 安全报告链接；已安装时提示「覆盖（旧目录会备份）」；命中本地安全扫描时内联展示 findings + 强制安装勾选。

## 验证
- `cd frontend && npx vue-tsc --noEmit` 通过。
- 后端直连实测：`list/search/detail/download` 均正常；以真实 slug `ppt` 跑通「下载→解压→定位 SKILL.md→安全扫描(0 findings)→code 映射」全链路。

## 已知限制
- 列表的「已安装」判定基于 `origin_slug` 或 code 匹配；手动改名的本地技能可能识别不到对应市场项。
- showcase 接口返回全量后本地切片分页，依赖远端单次返回量；search 走服务端分页。
- 仅记录了 `origin_version`，「检查更新 / 升级」UI 尚未实现，留作后续。
