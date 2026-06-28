import { defineStore } from 'pinia'
import { reactive } from 'vue'
import { api } from '@/api'
import { useSpace } from './space'
import { resolveToolMeta } from '@/lib/toolDisplay'

// Live AbortControllers for in-flight streams, keyed by conversation id. Kept
// OUTSIDE the reactive store so Vue doesn't try to proxy them — we only need
// them to cancel a running fetch.
const streamControllers = new Map<number, AbortController>()

// One-line summary for a tool step (shown on the action row so the user sees
// WHAT each action targets without expanding). Mirrors the helper that used to
// live in Chat.vue; moved here so the stream loop can run in the store.
function stepSummary(name: string, input: any): string {
  if (!input) return ''
  let a = input
  if (typeof a === 'string') { try { a = JSON.parse(a) } catch { return '' } }
  if (typeof a !== 'object' || !a) return ''
  switch (name) {
    case 'write_file':
    case 'read_file':
    case 'list_dir':
      return a.path || ''
    case 'run_command':
      return a.command || ''
    case 'save_output_file':
      return a.filename || ''
    case 'Read': case 'Edit': case 'Write':
      return a.file_path || a.path || ''
    case 'Bash':
      return a.command || ''
    case 'Grep': case 'Glob':
      return a.pattern || a.query || ''
    default:
      return ''
  }
}

// Apply one streamed SSE event to the assistant placeholder message. Pure data
// mutation (no DOM side-effects) so it can run in the store while the chat view
// is unmounted. The view re-renders reactively from these mutations.
function applyStreamEvent(m: any, ev: { type: string; data: any }) {
  const { type, data } = ev
  if (type === 'meta') {
    m._meta = data
  } else if (type === 'text') {
    m.content_json.text += data.text || ''
  } else if (type === 'thinking') {
    m._thinking += data.text || ''
  } else if (type === 'tool_use') {
    const id = data.id || data.name
    const existingIdx = m._stepIndex[id]
    if (existingIdx != null) {
      const s = m._steps[existingIdx]
      if (data.input && (typeof data.input !== 'object' || Object.keys(data.input).length)) {
        s.input = data.input
        s.summary = stepSummary(s.name, data.input)
      }
      return
    }
    const idx = m._steps.length
    m._stepIndex[id] = idx
    const meta = resolveToolMeta(data.name || '')
    m._steps.push({
      kind: meta.kind,
      name: data.name || '(tool)',
      label: meta.label,
      serverName: meta.serverName,
      input: data.input,
      summary: stepSummary(data.name, data.input),
      status: 'running',
      _start: performance.now(),
    })
  } else if (type === 'tool_result') {
    const id = data.tool_use_id
    let idx = id != null ? m._stepIndex[id] : undefined
    if (idx == null) idx = m._steps.length - 1
    const s = m._steps[idx]
    if (s) {
      s.output = data.content
      s.status = 'done'
      if (s._start) s.duration_ms = Math.round(performance.now() - s._start)
    }
  } else if (type === 'file') {
    m._files = Array.isArray(m._files) ? [...m._files, data] : [data]
  } else if (type === 'ui') {
    m._uis = Array.isArray(m._uis) ? [...m._uis, data] : [data]
  } else if (type === 'permission_request') {
    const reqs = Array.isArray(m._perms) ? m._perms : []
    reqs.push({
      request_id: data.request_id,
      tool_name: data.tool_name,
      risk: data.risk,
      reason: data.reason,
      summary: data.summary,
      mode: data.mode,
      status: 'pending',
      _collapsed: false,
    })
    m._perms = reqs
  } else if (type === 'error') {
    m.content_json.text += `\n\n[错误] ${data.message}`
  }
}

export const useChat = defineStore('chat', {
  state: () => ({
    agents: [] as any[],
    defaultAgent: null as any,
    currentAgent: null as any,
    convs: [] as any[],
    currentConvId: null as number | null,
    messages: [] as any[],
    pendingFiles: [] as any[],
    loaded: false,
    // In-flight streaming turns keyed by conversation id. Present while a turn
    // is running; removed when it ends. Living in the store (a singleton) means
    // the turn survives the chat view being unmounted — switching menus/convs
    // and coming back keeps the task running and re-attaches its live message.
    live: {} as Record<number, { placeholder: any }>,
    // Bumped on every applied stream event so the view can react (auto-scroll)
    // without deep-watching the whole message tree.
    streamTick: 0,
  }),
  getters: {
    // Is a given conversation (default: the active one) currently streaming?
    isStreaming: (state) => (cid?: number | null) => {
      const id = cid ?? state.currentConvId
      return id != null && !!state.live[id]
    },
  },
  actions: {
    async loadInit() {
      const [as, def, cs] = await Promise.all([
        api.myAgents().catch(() => []),
        api.myDefaultAgent().catch(() => null),
        api.conversations().catch(() => []),
      ])
      this.agents = as
      this.defaultAgent = def
      this.convs = cs
      if (!this.currentAgent) this.currentAgent = def || as[0] || null
      this.loaded = true
    },
    selectAgent(a: any) {
      const switched = a?.id !== this.currentAgent?.id
      this.currentAgent = a
      // Switching agent → drop the active conv from local state so the welcome
      // screen for the new agent is shown. The previous conv still exists in
      // the sidebar list (and DB) and can be re-opened by clicking it.
      if (switched) {
        this.currentConvId = null
        this.messages = []
        this.pendingFiles = []
      }
    },
    reset() {
      this.agents = []
      this.defaultAgent = null
      this.currentAgent = null
      this.convs = []
      this.currentConvId = null
      this.messages = []
      this.pendingFiles = []
      this.loaded = false
      useSpace().reset()
    },
    /** "New conversation" UX action — local-only reset that surfaces the
     *  welcome screen for the current agent. We deliberately do NOT call the
     *  create-conversation API here, so users who switch agents and click
     *  around without sending anything don't accumulate empty conversations
     *  in their history. The real DB row is created lazily by `ensureConv()`
     *  on the first send. */
    async newConv() {
      this.currentConvId = null
      this.messages = []
      this.pendingFiles = []
      return null
    },
    /** Lazy creator: ensures a real DB conversation exists before the first
     *  message is sent. Returns the existing conv if one is already active.
     *  When `workspaceId` is set the conversation is created as a "task"
     *  bound to that project; otherwise it's a plain "chat". */
    async ensureConv(workspaceId?: number | null, opts: { model_id?: number | null; permission_mode?: string } = {}) {
      if (this.currentConvId) {
        return this.convs.find((x) => x.id === this.currentConvId) || null
      }
      if (!this.currentAgent) return null
      const c = await api.createConversation({
        agent_id: this.currentAgent.id,
        workspace_id: workspaceId ?? undefined,
        model_id: opts.model_id ?? undefined,
        permission_mode: opts.permission_mode,
      })
      this.convs.unshift(c)
      this.currentConvId = c.id
      this.messages = []
      // keep pendingFiles — user may have attached files before sending
      return c
    },
    async selectConv(c: any) {
      this.currentConvId = c.id
      const a = this.agents.find((x) => x.id === c.agent_id)
      if (a) this.currentAgent = a
      this.messages = await api.messages(c.id)
      // Re-attach a background turn: if this conversation is still streaming
      // (started before we navigated away), its live assistant placeholder is
      // tracked in `this.live` but not yet persisted to the DB, so the freshly
      // loaded history doesn't include it. Push it back so the user sees the
      // task continue right where it left off. The user message IS persisted on
      // send, so it's already in the loaded list — only the assistant needs it.
      const live = this.live[c.id]
      if (live && live.placeholder && !this.messages.includes(live.placeholder)) {
        this.messages.push(live.placeholder)
      }
      this.pendingFiles = []
      // Refresh which assistant messages are favorited so star icons render.
      const ids = this.messages
        .filter((m: any) => m.role === 'assistant' && Number.isFinite(m.id))
        .map((m: any) => m.id as number)
      useSpace().loadForMessages(ids)
    },
    async renameConv(c: any, title: string) {
      const updated = await api.renameConversation(c.id, { title })
      Object.assign(c, updated)
    },
    async deleteConv(c: any) {
      // Abort any in-flight turn for this conversation before removing it.
      this.stopStream(c.id)
      await api.deleteConversation(c.id)
      this.convs = this.convs.filter((x) => x.id !== c.id)
      if (this.currentConvId === c.id) {
        this.currentConvId = null
        this.messages = []
      }
    },

    /** Run one streaming turn for a conversation. The fetch loop lives HERE (in
     *  the store singleton) rather than in the chat view, so the turn keeps
     *  running when the user switches menus/conversations and unmounts the view.
     *  `placeholder` must be the reactive assistant message proxy already pushed
     *  into `messages` — we mutate it in place as events arrive.
     *  Returns when the turn ends (or is aborted). */
    async streamTurn(cid: number, body: any, placeholder: any) {
      const token = localStorage.getItem('access_token')
      const controller = new AbortController()
      streamControllers.set(cid, controller)
      this.live[cid] = { placeholder }
      try {
        const resp = await fetch(`/api/conversations/${cid}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(body),
          signal: controller.signal,
        })
        if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)
        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const lines = buf.split('\n\n')
          buf = lines.pop() || ''
          for (const line of lines) {
            if (!line.startsWith('data:')) continue
            let json: any
            try { json = JSON.parse(line.slice(5).trim()) } catch { continue }
            applyStreamEvent(placeholder, json)
            // Bump so the view can react (auto-scroll) without deep-watching.
            this.streamTick++
          }
        }
      } catch (e: any) {
        if (e.name !== 'AbortError') {
          placeholder.content_json.text += `\n\n[网络错误] ${e.message}`
        }
      } finally {
        streamControllers.delete(cid)
        placeholder._steps?.forEach((s: any) => { if (s.status === 'running') s.status = 'done' })
        placeholder._streaming = false
        delete this.live[cid]
        this.streamTick++
      }
    },

    /** Abort the in-flight turn for a conversation (default: the active one). */
    stopStream(cid?: number | null) {
      const id = cid ?? this.currentConvId
      if (id == null) return
      streamControllers.get(id)?.abort()
    },
  },
})
