# H3C Agent Desktop (Electron shell)

Electron shell that launches the Python FastAPI backend as a sidecar and loads
the Vue frontend. Single-user desktop mode (no login).

## Architecture

```
Electron main (main.js)
├── spawns Python sidecar: uvicorn app.main:app  (stable port 47900+)
│     env: H3C_AGENT_DATA_DIR=~/.h3c-agent, DESKTOP_MODE=true
├── waits for /api/health
└── loads renderer
      dev  → http://localhost:5173 (Vite, proxies /api → sidecar)
      prod → frontend/dist/index.html
preload.js → exposes window.desktop (openFolder, paths, shell)
```

## Dev

Prereqs: `backend/.venv` with deps installed (incl. aiosqlite), Node 18+.

```bash
cd desktop
npm install            # one-time (uses ELECTRON_MIRROR if behind GFW)
npm run dev            # starts Vite + Electron + Python sidecar together
```

The dev orchestrator (dev.js) pins the backend port to 47900 and hands it to
both Vite's proxy and the Electron sidecar.

## Data location

All local data lives in `~/.h3c-agent/`:
- `app.db` — SQLite database (WAL mode)

Override with `H3C_AGENT_DATA_DIR`.

## Notes

- Behind the GFW, install Electron via the mirror:
  `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ npm install`
- Packaging (electron-builder + PyInstaller sidecar) is a later phase.

## 回答用中文