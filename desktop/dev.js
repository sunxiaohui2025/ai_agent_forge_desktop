'use strict';
/**
 * Dev orchestrator: starts Vite (frontend) and Electron together.
 *
 * The Electron main process owns the Python backend sidecar and picks a stable
 * port (47900+). We start Vite first (it proxies /api → backend), then launch
 * Electron in dev mode pointing at the Vite URL.
 *
 * Backend port handoff: Electron picks the port at runtime, but Vite's proxy
 * needs to know it at startup. For dev we pin both sides to 47900 via
 * H3C_BACKEND_PORT so the proxy target matches the sidecar.
 */
const { spawn } = require('child_process');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const FRONTEND_DIR = path.join(ROOT, 'frontend');
const DEV_BACKEND_PORT = process.env.H3C_BACKEND_PORT || '47900';

function run(cmd, args, opts) {
  const p = spawn(cmd, args, { stdio: 'inherit', ...opts });
  p.on('exit', (code) => {
    if (code && code !== 0) console.error(`[dev] ${cmd} exited ${code}`);
  });
  return p;
}

console.log(`[dev] backend port pinned to ${DEV_BACKEND_PORT}`);

// 1. Vite dev server (proxies /api to the backend port)
const vite = run('npm', ['run', 'dev'], {
  cwd: FRONTEND_DIR,
  env: { ...process.env, H3C_BACKEND_PORT: DEV_BACKEND_PORT },
});

// 2. Electron (owns the Python sidecar; pins the same port)
const electron = run('npx', ['electron', '.'], {
  cwd: __dirname,
  env: {
    ...process.env,
    ELECTRON_DEV: '1',
    H3C_FORCE_PORT: DEV_BACKEND_PORT,
    VITE_DEV_URL: 'http://localhost:5173',
  },
});

function shutdown() {
  try { vite.kill(); } catch (_) {}
  try { electron.kill(); } catch (_) {}
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
electron.on('exit', shutdown);
