<template>
  <aside class="preview-panel">
    <div v-if="showTabs" class="preview-tabs">
      <div
        v-for="tab in tabs"
        :key="tab.id"
        role="button"
        tabindex="0"
        :class="['preview-tab', { active: tab.id === activeId }]"
        @click="$emit('select', tab.id)"
        @keydown.enter.prevent="$emit('select', tab.id)"
        @keydown.space.prevent="$emit('select', tab.id)"
      >
        <el-icon :size="14"><component :is="tabIcon(tab)" /></el-icon>
        <span class="tab-name" :title="tab.name">{{ tab.name || tabLabel(tab) }}</span>
        <button class="tab-close" @click.stop="$emit('closeTab', tab.id)">
          <el-icon :size="12"><Close /></el-icon>
        </button>
      </div>
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
          <el-dropdown v-if="canOpenFileActions" trigger="click" placement="bottom-end" popper-class="file-open-menu" @command="onOpenCommand">
            <button class="open-menu-btn" title="打开方式">
              <el-icon :size="15"><Promotion /></el-icon>
              <span>打开方式</span>
              <el-icon :size="12"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="default">
                  <el-icon><Promotion /></el-icon>
                  <span>默认应用打开</span>
                </el-dropdown-item>
                <el-dropdown-item v-if="localFilePath" command="finder">
                  <el-icon><FolderOpened /></el-icon>
                  <span>在 Finder 中显示</span>
                </el-dropdown-item>
                <template v-if="availableApps.length">
                  <div class="open-menu-section">选择应用</div>
                  <el-dropdown-item
                    v-for="app in availableApps"
                    :key="app.path"
                    :command="`app:${app.path}`"
                  >
                    <el-icon><Collection /></el-icon>
                    <span>{{ app.name }}</span>
                  </el-dropdown-item>
                </template>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
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
        <div v-else-if="officePreview?.kind === 'unsupported'" class="state">
          <el-icon :size="30"><Document /></el-icon>
          <div>该 Office 格式建议用本地软件打开</div>
          <span>{{ officePreview.message || '当前轻量预览暂不支持该格式' }}</span>
          <button class="download-link as-button" @click="openDefaultApp">
            <el-icon :size="14"><Promotion /></el-icon> 默认应用打开
          </button>
        </div>
        <div v-else-if="kind === 'word' && officePreview" class="office-word">
          <div class="word-paper">
            <template v-for="(block, i) in officePreview.document?.blocks || []" :key="i">
              <table v-if="block.type === 'table'" class="office-table">
                <tbody>
                  <tr v-for="(row, ri) in block.rows" :key="ri">
                    <td v-for="(cell, ci) in row" :key="ci">{{ cell }}</td>
                  </tr>
                </tbody>
              </table>
              <p v-else :class="{ 'word-heading': isWordHeading(block) }">{{ block.text }}</p>
            </template>
            <div v-if="officePreview.document?.truncated" class="office-note">内容较长，已展示前 260 个段落/表格。</div>
          </div>
        </div>
        <div v-else-if="kind === 'ppt' && officePreview" class="office-ppt">
          <div class="slide-list">
            <button
              v-for="(slide, i) in officePreview.slides || []"
              :key="slide.index || i"
              :class="['slide-thumb', { active: i === activeSlideIndex }]"
              @click="activeSlideIndex = i"
            >
              <span class="slide-no">{{ i + 1 }}</span>
              <span class="slide-title">{{ slide.title || `第 ${i + 1} 页` }}</span>
            </button>
          </div>
          <div class="slide-stage">
            <div v-if="activeSlide" class="slide-page">
              <div class="slide-page-no">Slide {{ activeSlide.index || activeSlideIndex + 1 }}</div>
              <h3>{{ activeSlide.title || `第 ${activeSlideIndex + 1} 页` }}</h3>
              <div class="slide-lines">
                <p v-for="(line, i) in activeSlide.lines || []" :key="i">{{ line }}</p>
              </div>
              <div v-if="activeSlide.truncated" class="office-note">该页内容较长，已截取展示。</div>
            </div>
          </div>
        </div>
        <div v-else-if="kind === 'sheet' && officePreview" class="office-sheet">
          <div class="sheet-tabs">
            <button
              v-for="(sheet, i) in officePreview.sheets || []"
              :key="sheet.name || i"
              :class="['sheet-tab', { active: i === activeSheetIndex }]"
              @click="activeSheetIndex = i"
            >
              {{ sheet.name || `Sheet ${i + 1}` }}
            </button>
          </div>
          <div class="sheet-grid-wrap">
            <table v-if="activeSheet" class="sheet-grid">
              <tbody>
                <tr v-for="(row, ri) in activeSheet.rows || []" :key="ri">
                  <th>{{ ri + 1 }}</th>
                  <td v-for="(cell, ci) in row" :key="ci">{{ cell }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="activeSheet?.truncated" class="office-note">表格较大，已展示前 120 行、30 列。</div>
          </div>
        </div>
        <div v-else-if="file?.is_binary && !isOfficeKind" class="state">
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
          <div>该文件类型建议用本机应用查看</div>
          <span>压缩包、音视频等复杂格式暂不在线解析</span>
          <button class="download-link as-button" @click="openDefaultApp">
            <el-icon :size="14"><Promotion /></el-icon> 默认应用打开
          </button>
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
const officePreview = ref<any | null>(null)
const activeSlideIndex = ref(0)
const activeSheetIndex = ref(0)
const browserUrl = ref('')
const activeBrowserUrl = ref('')
const availableApps = ref<Array<{ name: string; path: string; score?: number }>>([])
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

const kind = computed<'html' | 'pdf' | 'md' | 'code' | 'plain' | 'image' | 'svg' | 'word' | 'ppt' | 'sheet' | 'other'>(() => {
  const e = ext.value
  if (['html', 'htm'].includes(e)) return 'html'
  if (e === 'pdf') return 'pdf'
  if (['docx', 'doc'].includes(e)) return 'word'
  if (['pptx', 'ppt'].includes(e)) return 'ppt'
  if (['xlsx', 'xls'].includes(e)) return 'sheet'
  if (['md', 'markdown'].includes(e)) return 'md'
  if (e === 'svg') return 'svg'
  if (CODE_EXTS.has(e)) return 'code'
  if (['txt', 'text', 'log', 'csv'].includes(e)) return 'plain'
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(e)) return 'image'
  return 'other'
})
const isOfficeKind = computed(() => kind.value === 'word' || kind.value === 'ppt' || kind.value === 'sheet')
const activeSlide = computed(() => officePreview.value?.slides?.[activeSlideIndex.value] || null)
const activeSheet = computed(() => officePreview.value?.sheets?.[activeSheetIndex.value] || null)
const localFilePath = computed(() => officePreview.value?.local_path || file.value?.local_path || '')
const canOpenFileActions = computed(() => !!file.value && (!!localFilePath.value || !!tokenizedUrl.value))

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
  officePreview.value = null
  activeSlideIndex.value = 0
  activeSheetIndex.value = 0
  if (!file.value) { activeUrl.value = ''; return }
  const k = kind.value
  if (binary && !isOfficeKind.value) { activeUrl.value = ''; return }
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
    if (isOfficeKind.value) {
      let previewUrl = officePreviewUrl(activeUrl.value)
      if (!previewUrl) throw new Error('暂不支持该文件来源的 Office 预览')
      let pr = await fetch(previewUrl, { headers: getAuthHeader() })
      if ((pr.status === 410 || pr.status === 404 || pr.status === 403) && file.value?.output_path) {
        try {
          const refreshed = await api.refreshDownload(file.value.output_path)
          if (refreshed?.download_url) {
            activeUrl.value = refreshed.download_url
            file.value.download_url = refreshed.download_url
            if (refreshed.local_path) file.value.local_path = refreshed.local_path
            previewUrl = officePreviewUrl(activeUrl.value)
            pr = await fetch(previewUrl, { headers: getAuthHeader() })
          }
        } catch {}
      }
      if (!pr.ok) {
        if (pr.status === 400) {
          throw new Error('文件无法解析，可能不是有效的 Office 文件或文件内容已损坏。请重新生成文件，或用原始本地文件路径创建卡片。')
        }
        throw new Error(`HTTP ${pr.status}`)
      }
      officePreview.value = await pr.json()
      return
    }
    let r = await fetch(activeUrl.value, { headers: getAuthHeader() })
    if ((r.status === 410 || r.status === 404 || r.status === 403) && file.value?.output_path) {
      try {
        const refreshed = await api.refreshDownload(file.value.output_path)
        if (refreshed?.download_url) {
          activeUrl.value = refreshed.download_url
          file.value.download_url = refreshed.download_url
          if (refreshed.local_path) file.value.local_path = refreshed.local_path
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

watch(() => localFilePath.value, async (p) => {
  availableApps.value = []
  const desktop = (window as any).desktop
  if (!p || !desktop?.listAppsForFile) return
  try {
    const apps = await desktop.listAppsForFile(p)
    availableApps.value = Array.isArray(apps) ? apps : []
  } catch {
    availableApps.value = []
  }
}, { immediate: true })

watch(() => file.value?.output_path || '', async (outputPath) => {
  if (!outputPath || file.value?.local_path) return
  try {
    const refreshed = await api.refreshDownload(outputPath)
    if (refreshed?.download_url) {
      activeUrl.value = refreshed.download_url
      file.value.download_url = refreshed.download_url
    }
    if (refreshed?.local_path) file.value.local_path = refreshed.local_path
  } catch {}
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

function openDefaultApp() {
  const localPath = localFilePath.value
  const desktop = (window as any).desktop
  if (localPath && desktop?.openPath) {
    desktop.openPath(localPath)
    return
  }
  openInNewTab()
}

function revealInFinder() {
  const localPath = localFilePath.value
  const desktop = (window as any).desktop
  if (localPath && desktop?.showItemInFolder) desktop.showItemInFolder(localPath)
}

function openWithApp(appPath: string) {
  const localPath = localFilePath.value
  const desktop = (window as any).desktop
  if (localPath && appPath && desktop?.openWithApp) desktop.openWithApp(localPath, appPath)
}

function onOpenCommand(command: string) {
  if (command === 'default') return openDefaultApp()
  if (command === 'finder') return revealInFinder()
  if (command.startsWith('app:')) return openWithApp(command.slice(4))
}

function officePreviewUrl(url: string) {
  if (!url) return ''
  const clean = url.split('#')[0].split('?')[0]
  const downloadMatch = clean.match(/^(.*\/api\/downloads\/[^/]+)$/)
  if (downloadMatch) return `${downloadMatch[1]}/preview`
  const fileMatch = clean.match(/^(.*\/api\/files\/\\d+)\/raw$/)
  if (fileMatch) return `${fileMatch[1]}/preview`
  return ''
}

function isWordHeading(block: any) {
  return String(block?.style || '').toLowerCase().includes('heading')
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
.kind-word { background: #2f67c8; }
.kind-ppt { background: #c97342; }
.kind-sheet { background: #2f8a52; }
.kind-pdf { background: #b5392f; }
.head-right { display: flex; gap: 6px; align-items: center; }
.head-btn { width: 30px; height: 30px; border-radius: 9px; text-decoration: none; }
.open-menu-btn {
  height: 30px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid rgba(28,28,26,.08);
  border-radius: 10px;
  background: #fff;
  color: #3f3f39;
  cursor: pointer;
  font-size: 12px;
  font-weight: 650;
  box-shadow: 0 8px 20px -18px rgba(28,28,26,.35);
  transition: background .15s ease, border-color .15s ease, box-shadow .15s ease;
}
.open-menu-btn:hover {
  background: #f7f7f4;
  border-color: rgba(28,28,26,.14);
  box-shadow: 0 12px 26px -20px rgba(28,28,26,.42);
}
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
.office-word {
  min-height: 100%;
  /* padding: 22px; */
  background:
    radial-gradient(circle at top left, rgba(47,103,200,.08), transparent 30%),
    #f7f7f4;
}
.word-paper {
  max-width: 820px;
  min-height: calc(100% - 44px);
  margin: 0 auto;
  padding: 34px 42px;
  border: 1px solid rgba(28,28,26,.08);
  /* border-radius: 18px; */
  background: #fff;
  box-shadow: 0 24px 60px -42px rgba(0,0,0,.35);
  color: #2f2e2a;
  font-size: 14px;
  line-height: 1.85;
}
.word-paper p { margin: 0 0 12px; }
.word-paper .word-heading {
  margin-top: 18px;
  font-size: 20px;
  font-weight: 760;
  letter-spacing: -.02em;
  color: #1f1f1c;
}
.office-table {
  width: 100%;
  margin: 16px 0;
  border-collapse: collapse;
  font-size: 12px;
}
.office-table td {
  border: 1px solid rgba(28,28,26,.10);
  padding: 7px 8px;
  vertical-align: top;
}
.office-ppt {
  height: 100%;
  display: grid;
  grid-template-columns: 168px minmax(0, 1fr);
  background: #f6f3ef;
}
.slide-list {
  min-height: 0;
  overflow: auto;
  padding: 12px;
  border-right: 1px solid rgba(28,28,26,.09);
  background: #fff;
}
.slide-thumb {
  width: 100%;
  min-height: 74px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 7px;
  margin-bottom: 9px;
  padding: 10px;
  border: 1px solid rgba(28,28,26,.09);
  border-radius: 13px;
  background: #fbfbf8;
  color: #55544d;
  text-align: left;
  cursor: pointer;
}
.slide-thumb.active {
  border-color: rgba(201,100,66,.45);
  background: #fff7f2;
  box-shadow: 0 12px 26px -22px rgba(201,100,66,.8);
}
.slide-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: #ede9e3;
  font-size: 11px;
  font-weight: 750;
}
.slide-title {
  max-width: 100%;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  font-size: 12px;
  line-height: 1.35;
}
.slide-stage {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  display: flex;
  justify-content: center;
  /* padding: 26px; */
}
.slide-page {
  width: min(920px, 100%);
  min-height: 520px;
  align-self: flex-start;
  padding: 44px 52px;
  /* border-radius: 22px; */
  background: linear-gradient(135deg, #fffaf6 0%, #ffffff 58%, #f5f0eb 100%);
  /* border: 1px solid rgba(28,28,26,.08); */
  box-shadow: 0 30px 70px -48px rgba(0,0,0,.45);
}
.slide-page-no {
  color: #b27b5d;
  font-size: 12px;
  font-weight: 780;
  text-transform: uppercase;
  letter-spacing: .08em;
}
.slide-page h3 {
  margin: 12px 0 24px;
  color: #242421;
  font-size: 28px;
  line-height: 1.2;
  letter-spacing: -.03em;
}
.slide-lines p {
  margin: 0 0 11px;
  color: #3d3c38;
  font-size: 15px;
  line-height: 1.65;
}
.office-sheet {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
}
.sheet-tabs {
  height: 42px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-bottom: 1px solid rgba(28,28,26,.08);
  overflow-x: auto;
}
.sheet-tab {
  height: 28px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: #f3f3ef;
  color: #66655e;
  white-space: nowrap;
  cursor: pointer;
}
.sheet-tab.active {
  background: #eef8f0;
  border-color: rgba(47,138,82,.22);
  color: #23683c;
  font-weight: 720;
}
.sheet-grid-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 14px;
  background: #fbfbf8;
}
.sheet-grid {
  border-collapse: collapse;
  min-width: 100%;
  background: #fff;
  box-shadow: 0 18px 42px -36px rgba(0,0,0,.3);
}
.sheet-grid th,
.sheet-grid td {
  border: 1px solid rgba(28,28,26,.09);
  padding: 7px 9px;
  min-width: 88px;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.sheet-grid th {
  position: sticky;
  left: 0;
  z-index: 1;
  min-width: 42px;
  background: #f2f2ee;
  color: #8a897f;
  font-weight: 650;
  text-align: center;
}
.office-note {
  margin-top: 14px;
  color: #aaa9a2;
  font-size: 12px;
}
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
.download-link.as-button {
  border: 0;
  cursor: pointer;
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
:global(.file-open-menu.el-popper) {
  border-radius: 16px !important;
  overflow: hidden;
  border: 1px solid rgba(28,28,26,.08) !important;
  box-shadow: 0 18px 48px -30px rgba(0,0,0,.36), 0 8px 18px -16px rgba(0,0,0,.20) !important;
}
:global(.file-open-menu .el-dropdown-menu) {
  min-width: 210px;
  max-height: min(420px, 58vh);
  overflow: auto;
  padding: 7px !important;
}
:global(.file-open-menu .el-dropdown-menu__item) {
  height: 34px !important;
  gap: 9px;
  border-radius: 10px !important;
  color: #33332e !important;
  font-size: 13px;
}
:global(.file-open-menu .el-dropdown-menu__item:hover) {
  background: #f2f2ef !important;
  color: #1f1f1b !important;
}
:global(.file-open-menu .open-menu-section) {
  padding: 8px 9px 5px;
  color: #aaa9a2;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .04em;
}
</style>
