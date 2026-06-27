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
      const data = await api.wsFile(this.currentId, path)
      this.preview = data
      return data
    },
    closePreview() { this.preview = null },
    async remove(id: number) {
      await api.deleteWorkspace(id)
      this.list = this.list.filter((w) => w.id !== id)
      if (this.currentId === id) await this.select(null)
    },
  },
})
