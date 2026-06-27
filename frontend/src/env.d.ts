/// <reference types="vite/client" />
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const c: DefineComponent<{}, {}, any>
  export default c
}

// Desktop (Electron) bridge — injected by desktop/preload.js as window.desktop.
// Present only when running inside the Electron shell.
interface DesktopAPI {
  isDesktop: true
  platform: string
  getBackendPort: () => Promise<number>
  getDataDir: () => Promise<string>
  getInfo: () => Promise<{ version: string; electron: string; node: string; chrome: string; platform: string; arch: string; backendPort: number }>
  checkUpdate: () => Promise<{ current: string; latest: string; hasUpdate: boolean; url?: string; error?: string }>
  openFolder: (opts?: { defaultPath?: string; title?: string }) => Promise<string | null>
  openURL: (url: string) => Promise<{ ok: boolean; error?: string }>
  openPath: (p: string) => Promise<string>
  showItemInFolder: (p: string) => Promise<void>
  term: {
    create: (opts: { id: string; cwd: string | null; cols: number; rows: number }) => Promise<{ ok: boolean }>
    write: (id: string, data: string) => void
    resize: (id: string, cols: number, rows: number) => Promise<{ ok: boolean }>
    kill: (id: string) => Promise<{ ok: boolean }>
    onData: (cb: (d: { id: string; data: string }) => void) => () => void
    onExit: (cb: (d: { id: string; code: number }) => void) => () => void
  }
}

interface Window {
  desktop?: DesktopAPI
}
