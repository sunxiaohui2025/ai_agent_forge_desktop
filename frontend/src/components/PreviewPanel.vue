<template>
  <aside class="preview-panel">
    <div v-if="showTabs" class="preview-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="['preview-tab', { active: tab.id === activeId }]"
        @click="$emit('select', tab.id)"
      >
        <el-icon :size="14"><component :is="tabIcon(tab)" /></el-icon>
        <span class="tab-name" :title="tab.name">{{ tab.name || tabLabel(tab) }}</span>
        <button class="tab-close" @click.stop="$emit('closeTab', tab.id)">
          <el-icon :size="12"><Close /></el-icon>
        </button>
      </button>
      <el-dropdown trigger="click" placement="bottom-end" popper-class="preview-new-menu" @command="onNewTab">
        <button class="new-tab-btn" title="新选项卡">
          <el-icon :size="16"><Plus /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="terminal">
              <el-icon><Monitor /></el-icon>
              <span>终端</span>
              <kbd>⌘T</kbd>
            </el-dropdown-item>
            <el-dropdown-item command="browser">
              <el-icon><Compass /></el-icon>
              <span>浏览器</span>
              <kbd>⌘B</kbd>
            </el-dropdown-item>
            <el-dropdown-item command="file">
              <el-icon><FolderOpened /></el-icon>
              <span>文件</span>
              <kbd>⌘P</kbd>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <button class="panel-close" @click="$emit('close')" title="关闭侧栏">
        <el-icon :size="15"><Close /></el-icon>
      </button>
    </div>

    <template v-if="activeTab?.kind === 'browser'">
      <div class="browser-bar">
        <button class="nav-btn" disabled>‹</button>
        <button class="nav-btn" disabled>›</button>
        <button class="nav-btn" @click="browserUrl = ''"><el-icon :size="14"><Refresh /></el-icon></button>
        <input v-model="browserUrl" class="url-input" placeholder="输入 URL" @keydown.enter="commitBrowserUrl" />
      </div>
      <iframe v-if="activeBrowserUrl" class="renderer-frame" :src="activeBrowserUrl" />
      <div v-else class="state subtle">
        <el-icon :size="30"><Compass /></el-icon>
        <div>新建浏览器标签</div>
        <span>输入 URL 后按 Enter 打开</span>
      </div>
    </template>

    <template v-else>
      <div class="preview-head" :class="{ 'flat-head': flatHeader || !showHeaderTitle }">
        <div v-if="showHeaderTitle" class="head-left">
          <span class="kind-dot" :class="`kind-${kind}`" />
          <span class="file-name" :title="file?.name">{{ file?.name || '文件预览' }}</span>
          <span class="file-type">{{ extLabel }}</span>
        </div>
        <div class="head-right">
          <a v-if="tokenizedUrl" class="head-btn" :href="tokenizedUrl" :download="file?.name" title="下载">
            <el-icon :size="16"><Download /></el-icon>
          </a>
          <button v-if="tokenizedUrl" class="head-btn" @click="openInNewTab" title="新窗口打开">
            <el-icon :size="16"><Promotion /></el-icon>
          </button>
          <button v-if="showHeaderClose" class="head-btn" @click="$emit('close')" title="关闭预览">
            <el-icon :size="16"><Close /></el-icon>
          </button>
        </div>
      </div>
      <div class="preview-body">
        <div v-if="loading" class="state">
          <el-icon :size="22" class="spin"><Loading /></el-icon>
          <span>加载中...</span>
        </div>
        <div v-else-if="error" class="state error">
          <el-icon :size="22"><WarningFilled /></el-icon>
          <span>{{ error }}</span>
        </div>
        <div v-else-if="file?.is_binary" class="state">
          <el-icon :size="30"><Document /></el-icon>
          <div>二进制文件暂不支持预览</div>
          <span>可以在本地应用中打开，或切换其它文本/图片/PDF 文件</span>
        </div>

        <iframe v-else-if="kind === 'html' && blobUrl" class="renderer-frame" sandbox="allow-scripts allow-popups" :src="blobUrl" />
        <iframe v-else-if="kind === 'pdf' && blobUrl" class="renderer-frame" :src="blobUrl" />
        <div v-else-if="kind === 'svg' && textContent" class="svg-body" v-html="textContent"></div>
        <div v-else-if="kind === 'md'" class="md-body" v-html="mdHtml"></div>
        <pre v-else-if="kind === 'code'" class="code-body">{{ textContent }}</pre>
        <pre v-else-if="kind === 'plain'" class="plain-body">{{ textContent }}</pre>
        <div v-else-if="kind === 'image' && blobUrl" class="image-body">
          <img :src="blobUrl" :alt="file?.name" />
        </div>
        <div v-else class="state">
          <el-icon :size="30"><Document /></el-icon>
          <div>该文件类型建议下载查看</div>
          <span>Word、PPT、Excel、压缩包等复杂格式暂不在线解析</span>
          <a v-if="tokenizedUrl" class="download-link" :href="tokenizedUrl" :download="file?.name">
            <el-icon :size="14"><Download /></el-icon> 下载文件
          </a>
        </div>
      </div>
    </template>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import MarkdownIt from 'markdown-it'
import { api } from '@/api'

const props = defineProps<{
  tabs?: any[]
  activeId?: string
  file?: any | null
  showTabs?: boolean
  showHeaderTitle?: boolean
  flatHeader?: boolean
  showHeaderClose?: boolean
}>()
const emit = defineEmits<{
  (e: 'select', id: string): void
  (e: 'closeTab', id: string): void
  (e: 'close'): void
  (e: 'newTab', kind: 'browser' | 'terminal' | 'file'): void
}>()

const md = new MarkdownIt({ breaks: true, linkify: true, html: false })
const loading = ref(false)
const error = ref('')
const textContent = ref('')
const mdHtml = ref('')
const blobUrl = ref<string>('')
const activeUrl = ref<string>('')
const browserUrl = ref('')
const activeBrowserUrl = ref('')
const showTabs = computed(() => props.showTabs !== false)
const showHeaderTitle = computed(() => props.showHeaderTitle !== false)
const flatHeader = computed(() => props.flatHeader === true)
const showHeaderClose = computed(() => props.showHeaderClose !== false)

const tabs = computed(() => props.tabs?.length ? props.tabs : (props.file ? [{ id: 'single', kind: 'file', ...props.file }] : []))
const activeTab = computed(() => tabs.value.find((t) => t.id === props.activeId) || tabs.value[0] || null)
const file = computed(() => activeTab.value?.kind === 'file' || !activeTab.value?.kind ? activeTab.value : null)

const ext = computed(() => {
  if (!file.value) return ''
  return (file.value.ext || (file.value.name || '').split('.').pop() || '').toLowerCase().replace(/^\./, '')
})
const extLabel = computed(() => ext.value ? ext.value.toUpperCase() : 'FILE')

const CODE_EXTS = new Set(['json', 'xml', 'js', 'ts', 'tsx', 'jsx', 'vue', 'css', 'scss', 'less', 'py', 'python', 'sql', 'yml', 'yaml', 'sh', 'bash', 'zsh', 'toml', 'ini', 'env'])

const kind = computed<'html' | 'pdf' | 'md' | 'code' | 'plain' | 'image' | 'svg' | 'other'>(() => {
  const e = ext.value
  if (['html', 'htm'].includes(e)) return 'html'
  if (e === 'pdf') return 'pdf'
  if (['md', 'markdown'].includes(e)) return 'md'
  if (e === 'svg') return 'svg'
  if (CODE_EXTS.has(e)) return 'code'
  if (['txt', 'text', 'log', 'csv'].includes(e)) return 'plain'
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(e)) return 'image'
  return 'other'
})

watch(() => ({
  url: file.value?.download_url || '',
  content: file.value?.content,
  path: file.value?.path || file.value?.name || '',
  binary: file.value?.is_binary,
}), async ({ url, content, binary }) => {
  if (blobUrl.value) { URL.revokeObjectURL(blobUrl.value); blobUrl.value = '' }
  loading.value = false
  error.value = ''
  textContent.value = ''
  mdHtml.value = ''
  if (!file.value) { activeUrl.value = ''; return }
  if (binary) { activeUrl.value = ''; return }
  const k = kind.value
  if (typeof content === 'string' && (k === 'md' || k === 'code' || k === 'plain' || k === 'svg')) {
    activeUrl.value = ''
    textContent.value = content
    if (k === 'md') mdHtml.value = md.render(content)
    return
  }
  if (!url) { activeUrl.value = ''; return }
  activeUrl.value = url
  loading.value = true
  try {
    let r = await fetch(activeUrl.value, { headers: getAuthHeader() })
    if ((r.status === 410 || r.status === 404 || r.status === 403) && file.value?.output_path) {
      try {
        const refreshed = await api.refreshDownload(file.value.output_path)
        if (refreshed?.download_url) {
          activeUrl.value = refreshed.download_url
          file.value.download_url = refreshed.download_url
          r = await fetch(activeUrl.value, { headers: getAuthHeader() })
        }
      } catch {}
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    if (k === 'md' || k === 'code' || k === 'plain' || k === 'svg') {
      const txt = await r.text()
      textContent.value = txt
      if (k === 'md') mdHtml.value = md.render(txt)
    } else if (k === 'html' || k === 'pdf' || k === 'image') {
      const blob = await r.blob()
      blobUrl.value = URL.createObjectURL(blob)
    }
  } catch (e: any) {
    error.value = e.message || '加载失败'
  } finally { loading.value = false }
}, { immediate: true })

watch(() => activeTab.value?.id, () => {
  if (activeTab.value?.kind === 'browser') {
    browserUrl.value = activeTab.value.url || ''
    activeBrowserUrl.value = activeTab.value.url || ''
  }
})

onBeforeUnmount(() => { if (blobUrl.value) URL.revokeObjectURL(blobUrl.value) })

function getAuthHeader(): Record<string, string> {
  const t = localStorage.getItem('access_token')
  return t ? { Authorization: `Bearer ${t}` } : {}
}

const tokenizedUrl = computed(() => {
  const url = activeUrl.value || file.value?.download_url || ''
  if (!url) return ''
  const tok = localStorage.getItem('access_token') || ''
  if (!tok) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}t=${encodeURIComponent(tok)}`
})

function openInNewTab() {
  if (tokenizedUrl.value) window.open(tokenizedUrl.value, '_blank')
}

function tabIcon(tab: any) {
  if (tab.kind === 'browser') return 'Compass'
  if (tab.kind === 'terminal') return 'Monitor'
  const e = (tab.ext || (tab.name || '').split('.').pop() || '').toLowerCase()
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(e)) return 'Picture'
  if (['js', 'ts', 'tsx', 'jsx', 'vue', 'css', 'py', 'json', 'html'].includes(e)) return 'DocumentCopy'
  return 'Document'
}
function tabLabel(tab: any) {
  if (tab.kind === 'browser') return '浏览器'
  if (tab.kind === 'terminal') return '终端'
  return '打开文件'
}
function onNewTab(kind: 'browser' | 'terminal' | 'file') {
  emit('newTab', kind)
}
function commitBrowserUrl() {
  let url = browserUrl.value.trim()
  if (!url) return
  if (!/^https?:\/\//i.test(url)) url = `https://${url}`
  activeBrowserUrl.value = url
  if (activeTab.value) {
    activeTab.value.url = url
    activeTab.value.name = new URL(url).hostname
  }
}
</script>

<style scoped>
.preview-panel {
  height: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-left: 1px solid rgba(28,28,26,.10);
}
.preview-tabs {
  height: 42px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 5px 8px;
  border-bottom: 1px solid rgba(28,28,26,.08);
  background: #fff;
}
.preview-tab {
  height: 31px;
  max-width: 170px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 7px 0 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: #6f6e66;
  cursor: pointer;
}
.preview-tab.active {
  background: #f1f1ee;
  color: #242421;
  box-shadow: inset 0 0 0 1px rgba(28,28,26,.05);
}
.tab-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.tab-close {
  width: 18px; height: 18px;
  display: inline-flex; align-items: center; justify-content: center;
  border: 0; border-radius: 6px; background: transparent; color: #aaa9a2; cursor: pointer;
}
.tab-close:hover { background: rgba(28,28,26,.08); color: #56554e; }
.new-tab-btn,
.panel-close,
.head-btn,
.nav-btn {
  border: 0;
  background: transparent;
  color: #777770;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.new-tab-btn,
.panel-close {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  flex-shrink: 0;
}
.new-tab-btn:hover,
.panel-close:hover,
.head-btn:hover,
.nav-btn:hover { background: rgba(28,28,26,.06); color: #242421; }
.panel-close { margin-left: auto; }
.preview-head {
  height: 44px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  border-bottom: 1px solid rgba(28,28,26,.07);
  background: #fff;
}
.preview-head.flat-head {
  justify-content: flex-end;
  border-bottom-color: transparent;
}
.head-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.file-name { font-size: 13px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-type {
  flex-shrink: 0;
  padding: 1px 6px;
  border-radius: 6px;
  background: #f1f1ef;
  color: #777770;
  font-family: var(--m-font-mono);
  font-size: 10px;
  font-weight: 700;
}
.kind-dot { width: 8px; height: 8px; border-radius: 999px; background: #aaa9a2; flex-shrink: 0; }
.kind-image { background: #c96442; }
.kind-code, .kind-plain, .kind-md, .kind-html { background: #2f8a52; }
.kind-pdf { background: #b5392f; }
.head-right { display: flex; gap: 2px; }
.head-btn { width: 30px; height: 30px; border-radius: 9px; text-decoration: none; }
.preview-body { flex: 1; min-height: 0; overflow: auto; background: #fff; padding-top: 8px; }
.state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #777770;
  font-size: 13px;
  text-align: center;
  padding: 24px;
}
.state.subtle span,
.state > span { color: #aaa9a2; font-size: 12px; }
.state.error { color: var(--m-danger); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.renderer-frame { width: 100%; height: 100%; border: none; background: #fff; }
.browser-bar {
  height: 42px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  border-bottom: 1px solid rgba(28,28,26,.07);
  background: #fff;
}
.nav-btn { width: 26px; height: 26px; border-radius: 8px; font-size: 17px; }
.nav-btn:disabled { opacity: .35; cursor: default; }
.url-input {
  flex: 1;
  height: 28px;
  border: 0;
  border-radius: 9px;
  background: #f5f5f2;
  outline: none;
  text-align: center;
  color: #56554e;
}
.md-body {
  padding: 24px 32px;
  max-width: 920px;
  margin: 0 auto;
  background: #fff;
  min-height: 100%;
  font-size: 14px;
  line-height: 1.7;
}
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3) { color: #242421; letter-spacing: -.01em; }
.md-body :deep(p) { color: #3d3c38; }
.md-body :deep(pre),
.code-body {
  background: #f7f7f4;
  color: #242421;
  border: 1px solid rgba(28,28,26,.09);
  border-radius: 12px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.72);
}
.md-body :deep(pre) { padding: 14px; overflow: auto; }
.md-body :deep(:not(pre) > code) {
  padding: 2px 5px;
  border-radius: 6px;
  background: #f1f1ee;
  color: #2f5d48;
}
.code-body,
.plain-body {
  margin: 14px;
  padding: 18px 20px;
  min-height: calc(100% - 28px);
  font-family: var(--m-font-mono);
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.plain-body {
  max-width: 860px;
  min-height: auto;
  margin: 18px auto;
  background: #fff;
  color: #34332f;
  border: 1px solid rgba(28,28,26,.08);
  border-radius: 16px;
  box-shadow: 0 18px 42px -34px rgba(0,0,0,.25);
  font-family: var(--m-font-ui);
  font-size: 14px;
  line-height: 1.8;
}
.image-body {
  height: 100%;
  padding: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.image-body img {
  max-width: 100%;
  max-height: 100%;
  border-radius: 12px;
  box-shadow: 0 18px 52px -36px rgba(0,0,0,.35);
}
.svg-body {
  min-height: 100%;
  padding: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
}
.svg-body :deep(svg) { max-width: 100%; height: auto; }
.download-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  padding: 8px 13px;
  border-radius: 10px;
  background: #242421;
  color: #fff;
  text-decoration: none;
  font-size: 13px;
  font-weight: 650;
}
:global(.preview-new-menu.el-popper) {
  border-radius: 14px !important;
  overflow: hidden;
  box-shadow: 0 18px 46px -28px rgba(0,0,0,.34), 0 8px 18px -14px rgba(0,0,0,.20) !important;
}
:global(.preview-new-menu .el-dropdown-menu) { padding: 6px !important; }
:global(.preview-new-menu .el-dropdown-menu__item) {
  height: 32px !important;
  gap: 8px;
  border-radius: 9px !important;
}
:global(.preview-new-menu kbd) {
  margin-left: auto;
  color: #aaa9a2;
  font-size: 11px;
  font-family: var(--m-font-ui);
}
</style>
