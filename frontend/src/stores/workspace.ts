import { defineStore } from 'pinia'
import { api } from '@/api'

export interface Workspace {
  id: number
  name: string
  path: string
  default_agent_id: number | null
  permission_mode: string
  icon?: string | null
  color?: string | null
  pinned: boolean
  sort: number
  last_opened_at?: string | null
}

export interface TreeEntry {
  name: string
  path: string
  type: 'file' | 'directory'
  size: number
  ext: string
  mtime?: number
}

const IS_DESKTOP = typeof window !== 'undefined' && (window as any).desktop?.isDesktop === true
const HTML_EXTS = new Set(['html', 'htm'])

function fileExt(file: any): string {
  return String(file?.ext || String(file?.name || '').split('.').pop() || '').toLowerCase().replace(/^\./, '')
}

function withAccessToken(url: string): string {
  if (!url || typeof window === 'undefined') return url
  const tok = window.localStorage?.getItem('access_token') || ''
  if (!tok) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}t=${encodeURIComponent(tok)}`
}

function getAuthHeader(): Record<string, string> {
  if (typeof window === 'undefined') return {}
  const tok = window.localStorage?.getItem('access_token') || ''
  return tok ? { Authorization: `Bearer ${tok}` } : {}
}

async function fetchArtifactText(file: any): Promise<{ text: string; downloadUrl: string }> {
  let downloadUrl = String(file?.download_url || '')
  if (!downloadUrl) throw new Error('missing download url')
  let r = await fetch(downloadUrl, { headers: getAuthHeader() })
  if ((r.status === 410 || r.status === 404 || r.status === 403) && file?.output_path) {
    const refreshed = await api.refreshDownload(file.output_path)
    if (refreshed?.download_url) {
      downloadUrl = refreshed.download_url
      file.download_url = refreshed.download_url
      r = await fetch(downloadUrl, { headers: getAuthHeader() })
    }
  }
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return { text: await r.text(), downloadUrl }
}

export const useWorkspace = defineStore('workspace', {
  state: () => ({
    list: [] as Workspace[],
    currentId: null as number | null,
    loaded: false,
    // file panel state for the current workspace
    tree: [] as TreeEntry[],          // root-level entries
    expanded: {} as Record<string, TreeEntry[]>, // path → children
    treeLoading: false,
    searchResults: [] as TreeEntry[],
    searching: false,
    // read-only file preview (right panel overlay)
    preview: null as null | { path: string; name: string; ext: string; content: string; truncated: boolean; is_binary: boolean; size: number },
    activeWorkspaceFile: null as any | null,
    sideTabs: [] as Array<any>,
    activeSideTabId: '' as string,
    sideMode: 'files' as 'files' | 'browser' | 'term' | 'artifacts',
    browserUrl: '',
    browserBlobUrls: [] as string[],
  }),
  getters: {
    current(state): Workspace | null {
      return state.list.find((w) => w.id === state.currentId) || null
    },
    isDesktop: () => IS_DESKTOP,
  },
  actions: {
    async load() {
      this.list = await api.workspaces().catch(() => [])
      this.loaded = true
    },
    /** Open the OS folder picker (desktop) and register a new workspace. */
    async addViaPicker(): Promise<Workspace | null> {
      if (!IS_DESKTOP) return null
      const dir = await (window as any).desktop.openFolder({ title: '选择项目目录' })
      if (!dir) return null
      const ws = await api.createWorkspace({ path: dir })
      const existing = this.list.find((w) => w.id === ws.id)
      if (!existing) this.list.unshift(ws)
      else Object.assign(existing, ws)
      await this.select(ws.id)
      return ws
    },
    async select(id: number | null) {
      this.currentId = id
      this.tree = []
      this.expanded = {}
      this.searchResults = []
      this.activeWorkspaceFile = null
      if (id != null) {
        api.touchWorkspace(id).catch(() => {})
        await this.loadTree()
      }
    },
    async loadTree() {
      if (this.currentId == null) return
      this.treeLoading = true
      try {
        const r = await api.wsTree(this.currentId, '')
        this.tree = r.entries || []
      } finally {
        this.treeLoading = false
      }
    },
    async expandDir(path: string) {
      if (this.currentId == null) return
      if (this.expanded[path]) { delete this.expanded[path]; return } // toggle closed
      const r = await api.wsTree(this.currentId, path)
      this.expanded[path] = r.entries || []
    },
    async search(q: string) {
      if (this.currentId == null || !q.trim()) { this.searchResults = []; return }
      this.searching = true
      try {
        const r = await api.wsSearch(this.currentId, q.trim())
        this.searchResults = r.results || []
      } finally {
        this.searching = false
      }
    },
    async newFile(path: string) {
      if (this.currentId == null) return
      await api.wsCreateFile(this.currentId, path)
      await this.loadTree()
    },
    async newDir(path: string) {
      if (this.currentId == null) return
      await api.wsCreateDir(this.currentId, path)
      await this.loadTree()
    },
    async readFile(path: string) {
      if (this.currentId == null) return null
      return await api.wsFile(this.currentId, path)
    },
    closePreview() { this.preview = null },
    openWorkspaceFile(file: any) {
      this.activeWorkspaceFile = file
      this.sideMode = 'files'
      return file
    },
    async openSideFile(file: any) {
      if (HTML_EXTS.has(fileExt(file)) && file?.download_url) {
        this.sideMode = 'browser'
        try {
          const { text, downloadUrl } = await fetchArtifactText(file)
          const url = URL.createObjectURL(new Blob([text], { type: 'text/html;charset=utf-8' }))
          file.download_url = downloadUrl
          return this.openBrowserTab(url)
        } catch {
          return this.openBrowserTab(withAccessToken(file.download_url))
        }
      }
      const id = String(file?.id || file?.output_path || file?.download_url || file?.path || file?.name || Date.now())
      const existing = this.sideTabs.find((t) => t.id === id)
      if (existing) {
        this.activeSideTabId = id
        this.sideMode = 'artifacts'
        if (existing.kind === 'browser' && existing.url) this.browserUrl = existing.url
        return existing
      }
      const tab = { id, kind: 'file', ...file }
      this.sideTabs.push(tab)
      this.activeSideTabId = id
      this.sideMode = 'artifacts'
      return tab
    },
    openBrowserTab(url = '') {
      const prevUrl = this.browserUrl
      if (prevUrl && prevUrl.startsWith('blob:') && prevUrl !== url) {
        URL.revokeObjectURL(prevUrl)
        this.browserBlobUrls = this.browserBlobUrls.filter((u) => u !== prevUrl)
      }
      if (url.startsWith('blob:') && !this.browserBlobUrls.includes(url)) {
        this.browserBlobUrls.push(url)
      }
      const id = 'browser'
      const existing = this.sideTabs.find((t) => t.id === id)
      if (existing) {
        Object.assign(existing, { kind: 'browser', url })
      } else {
        this.sideTabs.push({ id, kind: 'browser', name: '浏览器', url })
      }
      this.activeSideTabId = id
      this.sideMode = 'browser'
      this.browserUrl = url
    },
    openTerminalTab() {
      const id = 'terminal'
      const existing = this.sideTabs.find((t) => t.id === id)
      if (!existing) this.sideTabs.push({ id, kind: 'terminal', name: '终端' })
      this.activeSideTabId = id
      this.sideMode = 'term'
    },
    closeSideTab(id: string) {
      const idx = this.sideTabs.findIndex((t) => t.id === id)
      if (idx < 0) return
      const kind = this.sideTabs[idx]?.kind
      this.sideTabs.splice(idx, 1)
      if (this.activeSideTabId === id) {
        this.activeSideTabId = this.sideTabs[Math.max(0, idx - 1)]?.id || this.sideTabs[0]?.id || ''
        if (kind === 'browser' || kind === 'terminal') this.sideMode = 'files'
      }
      if (!this.sideTabs.some((t) => t.kind === 'browser')) this.browserUrl = ''
    },
    clearSideTabs() {
      this.browserBlobUrls.forEach((u) => URL.revokeObjectURL(u))
      this.browserBlobUrls = []
      this.sideTabs = []
      this.activeSideTabId = ''
      this.sideMode = 'files'
      this.browserUrl = ''
      this.activeWorkspaceFile = null
    },
    async remove(id: number) {
      await api.deleteWorkspace(id)
      this.list = this.list.filter((w) => w.id !== id)
      if (this.currentId === id) await this.select(null)
    },
  },
})
