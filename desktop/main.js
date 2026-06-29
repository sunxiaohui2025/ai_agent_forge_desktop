'use strict';
/**
 * H3C Agent — Electron main process.
 *
 * Responsibilities:
 *  1. Resolve a per-user data dir (passed to the backend as H3C_AGENT_DATA_DIR).
 *  2. Launch the Python FastAPI backend as a sidecar on a stable local port.
 *  3. Repair PATH (GUI apps don't inherit the user's shell PATH).
 *  4. Wait for /api/health, then load the renderer (vite dev URL or built dist).
 */
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const net = require('net');

const IS_DEV = process.env.ELECTRON_DEV === '1';
const ROOT = path.resolve(__dirname, '..');        // repo root
const BACKEND_DIR = path.join(ROOT, 'backend');
// Stable candidate ports — keep localStorage origin stable across launches.
const STABLE_PORTS = [47900, 47901, 47902, 47903, 47904];

let mainWindow = null;
let backendProc = null;
let backendPort = 0;

// ── Data dir ─────────────────────────────────────────────────────
function dataDir() {
  const dir = path.join(app.getPath('home'), '.h3c-agent');
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

// ── PATH repair ──────────────────────────────────────────────────
function repairedEnv() {
  const home = app.getPath('home');
  const isWin = process.platform === 'win32';
  const extra = isWin
    ? [
        path.join(home, 'AppData', 'Local', 'Programs', 'Python', 'Python312'),
        path.join(home, 'AppData', 'Local', 'Programs', 'Python', 'Python311'),
        path.join(home, 'AppData', 'Local', 'Programs', 'Python', 'Python310'),
        path.join(home, '.local', 'bin'),
      ]
    : [
        '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin',
        path.join(home, '.local', 'bin'),
        path.join(home, '.claude', 'bin'),
        path.join(home, '.npm-global', 'bin'),
      ];
  const cur = process.env.PATH || '';
  const delimiter = isWin ? ';' : ':';
  const merged = Array.from(new Set([...cur.split(delimiter), ...extra].filter(Boolean))).join(delimiter);
  return { ...process.env, PATH: merged };
}

// ── Python interpreter resolution ────────────────────────────────
function resolvePython() {
  const isWin = process.platform === 'win32';
  const venvPy = isWin
    ? path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe')
    : path.join(BACKEND_DIR, '.venv', 'bin', 'python');
  if (fs.existsSync(venvPy)) return venvPy;
  if (process.env.H3C_PYTHON && fs.existsSync(process.env.H3C_PYTHON)) return process.env.H3C_PYTHON;
  return isWin ? 'python' : 'python3';
}

// ── Port probing ─────────────────────────────────────────────────
function isPortFree(port) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.once('error', () => resolve(false));
    srv.listen(port, '127.0.0.1', () => srv.close(() => resolve(true)));
  });
}
async function pickPort() {
  // Dev orchestrator pins a port and hands the same value to Vite's proxy.
  if (process.env.H3C_FORCE_PORT) return parseInt(process.env.H3C_FORCE_PORT, 10);
  for (const p of STABLE_PORTS) {
    if (await isPortFree(p)) return p;
  }
  return 0;
}

// ── Backend lifecycle ────────────────────────────────────────────
async function startBackend() {
  backendPort = await pickPort();
  const env = {
    ...repairedEnv(),
    H3C_AGENT_DATA_DIR: dataDir(),
    DESKTOP_MODE: 'true',
    PYTHONUNBUFFERED: '1',
  };

  let cmd, args, cwd;
  if (app.isPackaged) {
    // Production: launch the PyInstaller-frozen backend binary bundled under
    // resources/backend/. No system Python required on the user's machine.
    const exeName = process.platform === 'win32' ? 'h3c-agent-backend.exe' : 'h3c-agent-backend';
    const backendRoot = path.join(process.resourcesPath, 'backend');
    cmd = path.join(backendRoot, exeName);
    args = ['--port', String(backendPort)];
    cwd = backendRoot;
    // Serve the bundled Vue dist from the backend (same-origin SPA).
    env.H3C_FRONTEND_DIR = path.join(process.resourcesPath, 'frontend');
  } else {
    // Dev: run uvicorn from the project venv.
    cmd = resolvePython();
    args = ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(backendPort)];
    cwd = BACKEND_DIR;
  }

  console.log(`[backend] ${cmd} ${args.join(' ')} (cwd=${cwd})`);
  backendProc = spawn(cmd, args, { cwd, env });
  backendProc.stdout.on('data', (d) => process.stdout.write(`[backend] ${d}`));
  backendProc.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`));
  backendProc.on('exit', (code) => console.log(`[backend] exited code=${code}`));
}

function waitForHealth(timeoutMs = 30000) {
  const url = `http://127.0.0.1:${backendPort}/api/health`;
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      http.get(url, (res) => {
        if (res.statusCode === 200) { res.resume(); return resolve(); }
        res.resume(); retry();
      }).on('error', retry);
    };
    const retry = () => {
      if (Date.now() - start > timeoutMs) return reject(new Error('backend health timeout'));
      setTimeout(tick, 400);
    };
    tick();
  });
}

// ── Renderer ─────────────────────────────────────────────────────
function rendererURL() {
  if (IS_DEV) return process.env.VITE_DEV_URL || 'http://localhost:5173';
  // Production: the backend serves the bundled Vue SPA at its own origin, so
  // relative /api calls + history routing work without a proxy.
  return `http://127.0.0.1:${backendPort}/`;
}

function createWindow() {
  const isMac = process.platform === 'darwin';
  const winOpts = {
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    title: 'H3C Agent',
    backgroundColor: '#ffffff',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  };
  // macOS-only window chrome
  if (isMac) {
    winOpts.titleBarStyle = 'hiddenInset';
    winOpts.trafficLightPosition = { x: 18, y: 16 };
    winOpts.title = '';
  }
  mainWindow = new BrowserWindow(winOpts);
  mainWindow.loadURL(rendererURL());
  // DevTools off by default — it floods the console with harmless internal
  // warnings (Unknown VE context / Autofill.enable). Opt in via H3C_DEVTOOLS=1.
  if (process.env.H3C_DEVTOOLS === '1') mainWindow.webContents.openDevTools({ mode: 'detach' });
  mainWindow.on('closed', () => { mainWindow = null; });
}

// ── IPC: minimal desktop capabilities ────────────────────────────
function registerIpc() {
  ipcMain.handle('app:get-backend-port', () => backendPort);
  ipcMain.handle('app:get-data-dir', () => dataDir());
  ipcMain.handle('app:get-info', () => ({
    version: app.getVersion(),
    electron: process.versions.electron,
    node: process.versions.node,
    chrome: process.versions.chrome,
    platform: process.platform,
    arch: process.arch,
    backendPort,
  }));
  // ── Update helpers ────────────────────────────────────────────
  function _updateRepo() {
    // Default to the public release repo; override via env if needed.
    return process.env.H3C_UPDATE_REPO || 'sunxiaohui2025/ai_agent_forge_desktop';
  }
  function _matchPlatformAsset(assets /* [{name,url,size}] */) {
    if (!assets || !assets.length) return null;
    const lower = (s) => (s || '').toLowerCase();
    if (process.platform === 'darwin') {
      // Prefer dmg, then zip
      const dmg = assets.find(a => lower(a.name).endsWith('.dmg'));
      if (dmg) return dmg;
      const zip = assets.find(a => lower(a.name).endsWith('.zip') && !lower(a.name).includes('win') && !lower(a.name).includes('linux'));
      if (zip) return zip;
    } else if (process.platform === 'win32') {
      const exe = assets.find(a => lower(a.name).endsWith('.exe'));
      if (exe) return exe;
      const zip = assets.find(a => lower(a.name).endsWith('.zip'));
      if (zip) return zip;
    } else if (process.platform === 'linux') {
      const appImage = assets.find(a => lower(a.name).endsWith('.appimage'));
      if (appImage) return appImage;
      const deb = assets.find(a => lower(a.name).endsWith('.deb'));
      if (deb) return deb;
      const zip = assets.find(a => lower(a.name).endsWith('.zip') && !lower(a.name).includes('mac') && !lower(a.name).includes('win'));
      if (zip) return zip;
    }
    // Fallback: first asset
    return assets[0] || null;
  }

  ipcMain.handle('app:check-update', async () => {
    try {
      const current = app.getVersion();
      const repo = _updateRepo();
      if (!repo) {
        return { current, latest: current, hasUpdate: false, error: '未配置更新源 (H3C_UPDATE_REPO)' };
      }
      const r = await new Promise((resolve, reject) => {
        const req = https.get(
          { hostname: 'api.github.com', path: `/repos/${repo}/releases/latest`,
            headers: { 'User-Agent': 'h3c-agent' }, timeout: 8000 },
          (res) => { let b = ''; res.on('data', (c) => (b += c)); res.on('end', () => resolve(b)); });
        req.on('error', reject);
        req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
      });
      const data = JSON.parse(r);
      const latest = (data.tag_name || '').replace(/^v/, '') || current;
      const assets = (data.assets || []).map(a => ({
        name: a.name, url: a.browser_download_url, size: a.size
      }));
      const platformAsset = _matchPlatformAsset(assets);
      return {
        current, latest,
        hasUpdate: latest !== current && !!data.tag_name,
        url: data.html_url || '',
        releaseNotes: (data.body || '').slice(0, 2000),
        assets,
        downloadUrl: platformAsset ? platformAsset.url : null,
        downloadName: platformAsset ? platformAsset.name : null,
        downloadSize: platformAsset ? platformAsset.size : 0,
      };
    } catch (e) {
      return { current: app.getVersion(), latest: app.getVersion(), hasUpdate: false, error: String(e.message || e) };
    }
  });

  // Download the update installer with progress reporting to renderer.
  let _updateDownload = null; // { req, dest, total }
  ipcMain.handle('app:download-update', async (_e, { url }) => {
    if (_updateDownload) {
      return { ok: false, error: '已有下载任务进行中' };
    }
    const downloadsDir = app.getPath('downloads');
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const filename = `H3C-Agent-Update-${ts}${path.extname(url.split('?')[0]) || '.dmg'}`;
    const destPath = path.join(downloadsDir, filename);

    // Helper: download with redirect following.
    const doDownload = (dlUrl) => {
      return new Promise((resolve, reject) => {
        const file = fs.createWriteStream(destPath);
        const req = https.get(dlUrl, { timeout: 0 }, (res) => {
          // Follow redirect (GitHub release assets redirect to CDN)
          if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
            file.close();
            try { fs.unlinkSync(destPath); } catch (_) {}
            res.resume();
            return resolve(doDownload(res.headers.location));
          }
          const total = parseInt(res.headers['content-length'] || '0', 10);
          let downloaded = 0;
          _updateDownload = { req, dest: destPath, total };

          res.on('data', (chunk) => {
            downloaded += chunk.length;
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow.webContents.send('update:download-progress', {
                total, downloaded,
                percent: total ? Math.round(downloaded / total * 100) : 0,
              });
            }
          });
          res.on('end', () => { _updateDownload = null; });
          res.pipe(file);
        });

        req.on('error', (e) => {
          _updateDownload = null;
          file.close();
          try { fs.unlinkSync(destPath); } catch (_) {}
          reject(e);
        });

        file.on('finish', () => {
          file.close();
          resolve({ ok: true, path: destPath, filename });
        });
        file.on('error', (e) => {
          _updateDownload = null;
          try { fs.unlinkSync(destPath); } catch (_) {}
          reject(e);
        });
      });
    };
    return doDownload(url);
  });

  ipcMain.handle('app:cancel-download', () => {
    if (_updateDownload) {
      try { _updateDownload.req.destroy(); } catch (_) {}
      try { fs.unlinkSync(_updateDownload.dest); } catch (_) {}
      _updateDownload = null;
    }
    return { ok: true };
  });

  ipcMain.handle('app:install-update', async (_e, { path: filePath }) => {
    if (!fs.existsSync(filePath)) return { ok: false, error: '安装文件不存在' };
    const r = await shell.openPath(filePath);
    return { ok: true, error: r || '' };
  });
  ipcMain.handle('dialog:open-folder', async (_e, opts = {}) => {
    const r = await dialog.showOpenDialog(mainWindow, {
      properties: ['openDirectory', 'createDirectory'],
      defaultPath: opts.defaultPath,
      title: opts.title || '选择工作目录',
    });
    return r.canceled ? null : r.filePaths[0];
  });
  ipcMain.handle('shell:open-url', async (_e, url) => {
    const u = String(url || '');
    if (!/^https?:\/\//i.test(u)) return { ok: false, error: 'unsupported url' };
    await shell.openExternal(u);
    return { ok: true };
  });
  ipcMain.handle('shell:open-path', async (_e, p) => shell.openPath(p));
  ipcMain.handle('shell:show-item', async (_e, p) => shell.showItemInFolder(p));
  registerTerminalIpc();
}

// ── IPC: integrated terminal (node-pty) ──────────────────────────
const terminals = new Map(); // id → pty process
function registerTerminalIpc() {
  let pty;
  try { pty = require('@lydell/node-pty'); }
  catch (e) { console.warn('[term] node-pty unavailable:', e.message); return; }

  ipcMain.handle('term:create', (_e, { id, cwd, cols, rows }) => {
    if (terminals.has(id)) return { ok: true };
    const shell = process.env.SHELL || (process.platform === 'win32' ? 'powershell.exe' : 'bash');
    const proc = pty.spawn(shell, [], {
      name: 'xterm-color',
      cols: cols || 80,
      rows: rows || 24,
      cwd: cwd && fs.existsSync(cwd) ? cwd : app.getPath('home'),
      env: repairedEnv(),
    });
    proc.onData((data) => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('term:data', { id, data });
    });
    proc.onExit(({ exitCode }) => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('term:exit', { id, code: exitCode });
      terminals.delete(id);
    });
    terminals.set(id, proc);
    return { ok: true };
  });
  ipcMain.on('term:write', (_e, { id, data }) => {
    const p = terminals.get(id); if (p) p.write(data);
  });
  ipcMain.handle('term:resize', (_e, { id, cols, rows }) => {
    const p = terminals.get(id); if (p) { try { p.resize(cols, rows); } catch (_) {} }
    return { ok: true };
  });
  ipcMain.handle('term:kill', (_e, id) => {
    const p = terminals.get(id); if (p) { try { p.kill(); } catch (_) {} terminals.delete(id); }
    return { ok: true };
  });
}

// ── Backend readiness ────────────────────────────────────────────
// Ensure the backend sidecar is alive and healthy. On macOS the app keeps
// running after the window is closed, so a relaunch (dock/Activate) may find a
// stale/dead backend — restart it transparently before showing the window.
async function ensureBackend() {
  const alive = backendProc && !backendProc.killed && backendProc.exitCode === null;
  if (!alive) {
    await startBackend();
  }
  await waitForHealth();
}

// ── Boot ─────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  registerIpc();
  try {
    await startBackend();
    await waitForHealth();
    console.log(`[main] backend ready on :${backendPort}`);
  } catch (e) {
    console.error('[main] backend failed to start:', e);
    dialog.showErrorBox('启动失败', `后端服务未能启动：\n${e.message}`);
  }
  createWindow();
  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length > 0) return;
    // Re-opening from the dock/tray: make sure the backend is healthy again so
    // the SPA reconnects with its persisted session instead of hitting a dead
    // origin (which surfaced as a login screen + "Network Error").
    try {
      await ensureBackend();
    } catch (e) {
      console.error('[main] backend failed to restart on activate:', e);
      dialog.showErrorBox('启动失败', `后端服务未能启动：\n${e.message}`);
    }
    createWindow();
  });
});

function stopBackend() {
  if (backendProc && !backendProc.killed) {
    try {
      if (process.platform === 'win32') {
        // On Windows, SIGTERM isn't supported; use taskkill to cleanly stop the
        // process tree (PyInstaller may spawn children).
        spawn('taskkill', ['/pid', String(backendProc.pid), '/f', '/t'], { stdio: 'ignore' });
      } else {
        backendProc.kill('SIGTERM');
      }
    } catch (_) {}
  }
  backendProc = null;
}
// IMPORTANT: do not stop the backend on window close. On macOS the app stays
// resident; killing the backend here breaks the next launch. Only tear it down
// when the app is genuinely quitting.
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', stopBackend);
app.on('quit', stopBackend);
