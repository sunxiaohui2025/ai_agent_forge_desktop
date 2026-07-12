# Repository Guidelines

## Project Structure & Module Organization

This repository contains three cooperating applications:

- `backend/app/`: FastAPI backend. API routes live in `api/`, agent execution in `runtime/`, business logic in `services/`, and SQLAlchemy models/migrations in `db/`.
- `frontend/src/`: Vue 3 and TypeScript UI. Put pages in `views/`, reusable UI in `components/`, Pinia state in `stores/`, and HTTP clients in `api/`.
- `desktop/`: Electron shell, Python sidecar packaging, and platform build configuration.
- `storage/`: runtime uploads, outputs, and installed skills. Preserve `.gitkeep`; do not commit generated user data.
- `docs/`: implementation handovers and architectural notes.

## Build, Test, and Development Commands

- `./start.sh`: start the backend on port 8000 and Vite on port 5173.
- `cd backend && pip install -e .`: install backend dependencies in the active Python 3.11+ environment.
- `cd backend && uvicorn app.main:app --reload --port 8000`: run only the API.
- `cd frontend && npm install && npm run dev`: run the web UI with hot reload.
- `cd frontend && npm run build`: run `vue-tsc` and produce the Vite production bundle.
- `cd desktop && npm install && npm run dev`: launch Vite, Electron, and the Python sidecar together.
- `docker compose up --build`: run the containerized stack.

## Coding Style & Naming Conventions

Use four spaces in Python and two spaces in Vue/TypeScript. Follow existing patterns: `snake_case` for Python functions/modules, `camelCase` for TypeScript values, and `PascalCase` for Vue components. Keep API endpoints thin and move reusable behavior into `services/` or `runtime/`. Prefer explicit TypeScript types for component props and store state. No repository-wide formatter is configured; match surrounding code and keep diffs focused.

## Testing Guidelines

No automated test suite is currently committed. Every change must at least pass `cd frontend && npm run build`. For backend changes, start the API and exercise the affected endpoint or stream manually. For desktop, widget, file-preview, or side-panel changes, verify the complete interaction in Electron. Add focused tests under `backend/tests/` or colocated `*.spec.ts` files when introducing test infrastructure.

## Commit & Pull Request Guidelines

Recent commits use short, imperative Chinese summaries such as `优化侧边产物栏目`; keep each commit scoped to one behavior. Pull requests should explain the user-visible outcome, affected modules, validation performed, and any migration or configuration impact. Include screenshots or recordings for UI changes and link the relevant issue when available. Never commit API keys, local databases, uploads, build outputs, or `.env` files.
