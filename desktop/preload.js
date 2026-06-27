'use strict';
const { contextBridge, ipcRenderer } = require('electron');

// Whitelisted desktop API surfaced to the Vue renderer as window.desktop.
// Keep this minimal — only what the UI genuinely needs.
contextBridge.exposeInMainWorld('desktop', {
  isDesktop: true,
  platform: process.platform,
  getBackendPort: () => ipcRenderer.invoke('app:get-backend-port'),
  getDataDir: () => ipcRenderer.invoke('app:get-data-dir'),
  getInfo: () => ipcRenderer.invoke('app:get-info'),
  checkUpdate: () => ipcRenderer.invoke('app:check-update'),
  downloadUpdate: (url) => ipcRenderer.invoke('app:download-update', { url }),
  cancelDownload: () => ipcRenderer.invoke('app:cancel-download'),
  installUpdate: (filePath) => ipcRenderer.invoke('app:install-update', { path: filePath }),
  onDownloadProgress: (cb) => {
    const l = (_e, d) => cb(d);
    ipcRenderer.on('update:download-progress', l);
    return () => ipcRenderer.removeListener('update:download-progress', l);
  },
  openFolder: (opts) => ipcRenderer.invoke('dialog:open-folder', opts),
  openURL: (url) => ipcRenderer.invoke('shell:open-url', url),
  openPath: (p) => ipcRenderer.invoke('shell:open-path', p),
  showItemInFolder: (p) => ipcRenderer.invoke('shell:show-item', p),

  // Integrated terminal (node-pty)
  term: {
    create: (opts) => ipcRenderer.invoke('term:create', opts),
    write: (id, data) => ipcRenderer.send('term:write', { id, data }),
    resize: (id, cols, rows) => ipcRenderer.invoke('term:resize', { id, cols, rows }),
    kill: (id) => ipcRenderer.invoke('term:kill', id),
    onData: (cb) => {
      const l = (_e, d) => cb(d);
      ipcRenderer.on('term:data', l);
      return () => ipcRenderer.removeListener('term:data', l);
    },
    onExit: (cb) => {
      const l = (_e, d) => cb(d);
      ipcRenderer.on('term:exit', l);
      return () => ipcRenderer.removeListener('term:exit', l);
    },
  },
});
