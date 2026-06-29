'use strict';
/**
 * Cross-platform PyInstaller builder.
 * Resolves the Python venv interpreter and runs PyInstaller from it.
 */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const ROOT = path.resolve(__dirname, '..');
const BACKEND_DIR = path.join(ROOT, 'backend');
const isWin = process.platform === 'win32';

// ── Resolve Python from venv ──────────────────────────────────────
function resolvePython() {
  const py = isWin
    ? path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe')
    : path.join(BACKEND_DIR, '.venv', 'bin', 'python');
  if (fs.existsSync(py)) return py;
  console.error('[build-backend] venv Python not found:', py);
  console.error('[build-backend] Run: cd backend && python -m venv .venv && .venv/.../pip install pyinstaller');
  process.exit(1);
}

const python = resolvePython();
const pyinstallerArgs = ['-m', 'PyInstaller', 'sidecar.spec', '--noconfirm'];

console.log(`[build-backend] ${python} ${pyinstallerArgs.join(' ')}`);
console.log(`[build-backend] cwd: ${BACKEND_DIR}`);

const proc = spawn(python, pyinstallerArgs, {
  cwd: BACKEND_DIR,
  stdio: 'inherit',
  shell: isWin,
});

proc.on('exit', (code) => {
  if (code !== 0) {
    console.error(`[build-backend] PyInstaller exited with code ${code}`);
    process.exit(code || 1);
  }
  console.log('[build-backend] Done.');
});
