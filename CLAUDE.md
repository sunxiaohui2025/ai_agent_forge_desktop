# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language & conventions

- Reply in Chinese (中文); keep technical terms in English where natural.
- UI design follows Google's design language (Material 3 tokens live in `frontend/src/styles.css`).

## Commands

Run from the repo root unless noted.

```bash
# Full desktop stack (Python sidecar :47900 + Vite + Electron window)
cd desktop && npm install && npm run dev

# Backend + frontend separately, no Electron
./start.sh                          # uvicorn :8000 + vite :5173, logs in /tmp/agent-forge-*.log
cd backend && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev          # Vite :5173, proxies /api → :8000

# Verify a frontend change (this is the ONLY automated check in the repo)
cd frontend && npx vue-tsc --noEmit # type-check; npm run build does tsc + vite build

# Package installers (PyInstaller-freeze backend + bundle)
cd desktop && npm run dist:mac      # or dist:win (must run on Windows), dist:linux
```

There is no test suite, linter, or formatter configured (`backend/tests/` is empty; no pytest/ruff/eslint in deps). The backend uses SQLite and **auto-creates tables + seeds on startup** — `alembic/` is empty, so there are no migrations to run.

## Architecture

This is a **local-first desktop AI agent** (Electron shell + FastAPI sidecar + Vue 3 SPA). All data lives in `~/.h3c-agent` (SQLite + storage). The README has an exhaustive feature/API/schema reference; this section covers only what spans multiple files.

### Two streaming execution paths (the core abstraction)

`backend/app/runtime/agent_runner.py` is the heart of the system and branches on the model provider:

- **Anthropic path** — Claude Agent SDK with `include_partial_messages=True` for true token streaming. Tools are whitelisted (Read/Glob/Grep/Skill/WebSearch/`mcp__*`); **Bash/Write/Edit are globally disabled** here.
- **OpenAI-compatible path** (deepseek/qwen/glm/openai/openai-compatible) — `/v1/chat/completions` stream with a multi-turn `tool_calls` loop. MCP tools and Skills are both translated into OpenAI function tools and routed at runtime. Includes auto-repair of malformed tool-call JSON and hard timeouts on MCP calls (20s enumerate / 90s call).

Both paths emit the same SSE event vocabulary to the frontend: `meta`, `thinking`, `text`, `tool_use`, `tool_result`, `file`, `error`, `done`. The frontend reassembles these in `frontend/src/stores/chat.ts` (`applyEvent`) and renders them in `frontend/src/views/chat/Chat.vue`.

### Per-agent Skill sandbox

Skills are stored in `storage/skills/<code>/`. On each request, only the Skills selected for the active agent are **symlinked** into a per-request temp `tmp/.claude/skills/` directory used as cwd. This is a physical sandbox — even Read/Bash can't reach Skills the agent didn't select. Three Skill types: `path` (ZIP with SKILL.md), `callable` (`module:func`), and `composite` (YAML DAG executed by `runtime/dag_executor.py`).

### Storage & download model

- Uploads: `storage/uploads/<user_id>/`, served via `/api/files/{id}/raw`.
- Agent/Skill outputs: `storage/outputs/<user_id>/`, registered in the `download_tokens` table and served via one-time `/api/downloads/{token}` URLs (24h expiry, path-escape blocked).
- Browser `<a download>` and iframes can't set auth headers, so downloads accept the JWT via a `?t=<jwt>` query param in addition to the `Authorization` header (`backend/app/api/downloads.py`).
- When a token expires (410), the frontend mints a fresh one via `/api/downloads/refresh` using the stable `output_path` handle. `FileCard.vue` and `PreviewPanel.vue` both implement this refresh-on-expiry dance.

### File preview routing

Previewable types (html/pdf/md/svg/text/code/images) render in the right-side split panel (`PreviewPanel.vue`); Office/archive types are download-only. The `PREVIEWABLE` set is duplicated in `FileCard.vue`, `PreviewPanel.vue`'s `kind` computed, and `Chat.vue`'s `PREVIEWABLE_EXT` — keep them in sync when adding a type. HTML must load via a blob URL into a sandboxed iframe (not as raw text), see `WsFilePreview.vue` and `PreviewPanel.vue`.

### Frontend API layer

`frontend/src/api/http.ts` is a single axios instance with a response interceptor that handles silent 401 token-refresh and shows a global error toast for other failures. Callers can opt out of the toast with `{ skipErrorToast: true }` on the request config (used by skill upload, which renders 400 security findings inline instead).

### Security layering

"Being able to execute" is gated by layers (full detail in README §3.5): tool whitelist → injected `system_prompt` safety prefix → input regex filter (`core/security_rules.py`) → Skill upload AST scan (`services/skill_scan.py`) → per-agent cwd sandbox → workspace permission mode → download tokens. API keys and channel secrets are Fernet-encrypted at rest (`core/crypto.py`); the frontend only ever sees `has_api_key`.

### Desktop runtime

`desktop/main.js` launches the PyInstaller-frozen Python backend as a sidecar on a stable port (47900, falling back through 47901–47904 to keep the localStorage origin stable), waits for `/api/health`, then loads the renderer. Single-user mode falls back to user `id=1`.

## Documentation workflow (required after notable features)

After a new feature or significant iteration, update three docs:

1. **Technical handover** in `docs/handover/` — structure, data flow, DB schema, API routes, key design decisions; list MCP tool names/params/auto-approval and Skill names/descriptions where relevant.
2. **Product insight** in `docs/insights/` — what user problem it solves, why this design over alternatives, known limitations.
3. **README.md** — keep the feature/API/schema reference current for large features.

The handover and insight docs must cross-link each other at the top (`> 产品思考见 …` / `> 技术实现见 …`).
