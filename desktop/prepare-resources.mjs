// Stage built artifacts into desktop/resources/ for electron-builder.
//   resources/backend   ← PyInstaller onedir output (backend/dist/h3c-agent-backend)
//   resources/frontend  ← Vue production build (frontend/dist)
import { existsSync, rmSync, cpSync } from 'node:fs';
import { join, resolve } from 'node:path';

const ROOT = resolve(import.meta.dirname, '..');
const out = join(import.meta.dirname, 'resources');
const backendSrc = join(ROOT, 'backend', 'dist', 'h3c-agent-backend');
const frontendSrc = join(ROOT, 'frontend', 'dist');

function need(p, hint) {
  if (!existsSync(p)) {
    console.error(`[prepare] missing ${p}\n          → ${hint}`);
    process.exit(1);
  }
}
need(backendSrc, 'run: cd backend && .venv/bin/pyinstaller sidecar.spec --noconfirm');
need(frontendSrc, 'run: cd frontend && npm run build');

rmSync(out, { recursive: true, force: true });
// IMPORTANT: verbatimSymlinks keeps symlinks exactly as-is. Without it, Node's
// cpSync resolves each symlink to an ABSOLUTE realpath on *this* machine
// (e.g. /Users/sun/.../dist/...). PyInstaller emits RELATIVE symlinks for its
// bundled dylibs (libpq.5.dylib → psycopg_binary/.dylibs/...) and the Python
// framework; rewriting them to absolute paths breaks the app on every other
// machine — the backend sidecar can't load its dylibs, /api/health never
// comes up, and the Electron window shows a blank white screen.
const symlinkOpts = { recursive: true, verbatimSymlinks: true };
cpSync(backendSrc, join(out, 'backend'), symlinkOpts);
cpSync(frontendSrc, join(out, 'frontend'), symlinkOpts);
console.log('[prepare] staged resources/backend and resources/frontend (symlinks preserved)');
