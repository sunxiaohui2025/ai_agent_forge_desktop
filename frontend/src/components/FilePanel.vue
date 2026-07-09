<template>
  <aside class="file-panel" :class="{ collapsed, 'workspace-compact': isWorkspaceCompact, fullscreen }">
    <div v-show="!collapsed" class="fp-content">
      <div class="fp-tabs">
        <button :class="['fp-tab', { active: ws.sideMode === 'files' }]" @click="openFilesTab">
          <el-icon :size="12"><Files /></el-icon> 工作区
        </button>
         <button :class="['fp-tab', { active: ws.sideMode === 'artifacts' }]" @click="openArtifactsTab">
          <el-icon :size="12"><Box /></el-icon> 产物
        </button>
        <button :class="['fp-tab', { active: ws.sideMode === 'browser' }]" @click="openBrowserTab">
          <el-icon :size="12"><Compass /></el-icon> 浏览器
        </button>
        <button :class="['fp-tab', { active: ws.sideMode === 'term' }]" @click="openTerm">
          <el-icon :size="12"><Monitor /></el-icon> 终端
        </button>
        <el-tooltip :content="fullscreen ? '恢复面板宽度' : '全屏展开侧边栏'" placement="bottom">
          <button class="fp-tab fp-tab-icon" @click="emit('toggleFullscreen')">
            <el-icon :size="13"><component :is="fullscreen ? 'CopyDocument' : 'FullScreen'" /></el-icon>
          </button>
        </el-tooltip>
       
      </div>

      <div class="fp-body">
        <template v-if="ws.sideMode === 'files'">
          <div class="fp-split" :class="{ 'with-preview': !!ws.activeWorkspaceFile }">
            <div v-if="ws.activeWorkspaceFile" class="fp-preview">
              <PreviewPanel
                :file="ws.activeWorkspaceFile"
                :show-tabs="false"
                @close="ws.activeWorkspaceFile = null"
              />
            </div>

            <div class="fp-tree">
              <div class="fp-head">
                <div class="fp-title" :title="ws.current?.path">
                  <el-icon :size="15"><Folder /></el-icon>
                  <span class="fp-name">{{ ws.current?.name || '工作目录' }}</span>
                </div>
                <div class="fp-actions">
                  <el-tooltip content="新建文件" placement="bottom">
                    <button class="fp-btn" @click="onNewFile"><el-icon :size="15"><DocumentAdd /></el-icon></button>
                  </el-tooltip>
                  <el-tooltip content="新建文件夹" placement="bottom">
                    <button class="fp-btn" @click="onNewDir"><el-icon :size="15"><FolderAdd /></el-icon></button>
                  </el-tooltip>
                  <el-tooltip content="刷新" placement="bottom">
                    <button class="fp-btn" @click="ws.loadTree()"><el-icon :size="15"><Refresh /></el-icon></button>
                  </el-tooltip>
                  <el-tooltip content="在访达中打开" placement="bottom" v-if="ws.isDesktop">
                    <button class="fp-btn" @click="openInFinder"><el-icon :size="15"><Position /></el-icon></button>
                  </el-tooltip>
                </div>
              </div>

              <div class="fp-search">
                <el-input v-model="query" size="small" placeholder="筛选文件…" clearable @input="onSearch">
                  <template #prefix><el-icon><Search /></el-icon></template>
                </el-input>
              </div>

              <div class="fp-tree-body">
                <div v-if="ws.treeLoading" class="fp-hint">加载中…</div>
                <template v-else-if="query.trim()">
                  <div v-if="ws.searching" class="fp-hint">搜索中…</div>
                  <div v-else-if="!ws.searchResults.length" class="fp-hint">无匹配文件</div>
                  <div
                    v-for="f in ws.searchResults" :key="f.path"
                    class="fp-row file" @click="openFile(f)"
                  >
                    <el-icon class="fp-ico"><Document /></el-icon>
                    <span class="fp-row-name">{{ f.name }}</span>
                    <span class="fp-row-path">{{ f.path }}</span>
                  </div>
                </template>
                <template v-else>
                  <div v-if="!ws.tree.length" class="fp-hint">空目录</div>
                  <FileTreeNode
                    v-for="entry in ws.tree" :key="entry.path"
                    :entry="entry" :depth="0"
                    @open="openFile"
                  />
                </template>
              </div>
            </div>
          </div>
        </template>

        <template v-else-if="ws.sideMode === 'browser'">
          <div class="fp-browser">
            <div class="browser-bar">
              <button class="nav-btn" disabled>‹</button>
              <button class="nav-btn" disabled>›</button>
              <button class="nav-btn" @click="commitBrowserUrl"><el-icon :size="14"><Refresh /></el-icon></button>
              <input v-model="browserInput" class="url-input" placeholder="输入 URL" @keydown.enter="commitBrowserUrl" />
            </div>
            <iframe v-if="browserUrl" class="browser-frame" :src="browserUrl" />
            <div v-else class="fp-empty-preview">
              <el-icon :size="24"><Compass /></el-icon>
              <div>浏览器标签</div>
              <span>输入 URL 后按 Enter 打开</span>
            </div>
          </div>
        </template>

        <template v-else>
          <div v-if="ws.sideMode === 'artifacts'" class="fp-artifacts">
            <div v-if="artifactTabs.length" class="artifact-tabs">
              <button
                v-for="tab in artifactTabs"
                :key="tab.id"
                :class="['artifact-tab', { active: tab.id === activeArtifactId }]"
                @click="selectArtifact(tab.id)"
              >
                <el-icon :size="13"><component :is="artifactIcon(tab)" /></el-icon>
                <span>{{ tab.name || '生成文件' }}</span>
                <button class="artifact-tab-close" title="关闭" @click.stop="closeArtifact(tab.id)">
                  <el-icon :size="11"><Close /></el-icon>
                </button>
              </button>
            </div>
            <PreviewPanel
              v-if="activeArtifact"
              :file="activeArtifact"
              :show-tabs="false"
              :show-header-title="false"
              :flat-header="true"
              :show-header-close="false"
              @close="closeActiveArtifact"
            />
            <div v-else class="fp-empty-preview artifact-empty">
              <el-icon :size="26"><Box /></el-icon>
              <div>还没有可预览产物</div>
              <span>大模型生成的代码、图片、文本会集中在这里</span>
            </div>
          </div>

          <div v-else class="fp-term">
            <TerminalTabs
              v-if="termMounted"
              :cwd="ws.current?.path || null"
              :session-key="ws.currentId || 0"
              dock="side"
              @dock-bottom="emit('dockTerminalBottom')"
            />
          </div>
        </template>

      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useWorkspace, type TreeEntry } from '@/stores/workspace'
import FileTreeNode from './FileTreeNode.vue'
import TerminalTabs from './TerminalTabs.vue'
import PreviewPanel from './PreviewPanel.vue'

const ws = useWorkspace()
const props = withDefaults(defineProps<{ collapsed?: boolean; terminalDock?: 'side' | 'bottom'; fullscreen?: boolean }>(), {
  terminalDock: 'side',
  fullscreen: false,
})
const emit = defineEmits<{
  (e: 'toggle'): void
  (e: 'dockTerminalBottom'): void
  (e: 'toggleFullscreen'): void
}>()

const query = ref('')
const browserInput = ref('')
const termMounted = ref(false)
const htmlPreviewUrls = ref<string[]>([])

const artifactTabs = computed(() => ws.sideTabs.filter((t: any) => t.kind === 'file'))
const activeArtifactId = computed(() => artifactTabs.value.some((t: any) => t.id === ws.activeSideTabId) ? ws.activeSideTabId : (artifactTabs.value[0]?.id || ''))
const activeArtifact = computed(() => artifactTabs.value.find((t: any) => t.id === activeArtifactId.value) || artifactTabs.value[0] || null)
const browserUrl = computed(() => ws.browserUrl)
const isWorkspaceCompact = computed(() => ws.sideMode === 'files' && !ws.activeWorkspaceFile)

function openFilesTab() {
  ws.sideMode = 'files'
  if (!ws.tree.length) ws.loadTree()
}

function openBrowserTab() {
  ws.openBrowserTab(ws.browserUrl || '')
  browserInput.value = ws.browserUrl || ''
}

function openTerm() {
  ws.sideMode = 'term'
  ws.openTerminalTab()
  termMounted.value = true
  if (props.terminalDock === 'bottom') emit('dockTerminalBottom')
}

function openArtifactsTab() {
  ws.sideMode = 'artifacts'
  if (!ws.activeSideTabId && artifactTabs.value.length) ws.activeSideTabId = artifactTabs.value[0].id
}

function onOpenTerminal() {
  openTerm()
}

onMounted(() => {
  window.addEventListener('workbuddy:open-terminal', onOpenTerminal)
  if (ws.sideMode === 'term') termMounted.value = true
  browserInput.value = ws.browserUrl || ''
})
onBeforeUnmount(() => {
  window.removeEventListener('workbuddy:open-terminal', onOpenTerminal)
  htmlPreviewUrls.value.forEach((url) => URL.revokeObjectURL(url))
})

watch(() => ws.sideMode, (mode) => {
  if (mode === 'term') termMounted.value = true
  if (mode === 'browser') browserInput.value = ws.browserUrl || ''
})

function selectArtifact(id: string) {
  ws.activeSideTabId = id
  ws.sideMode = 'artifacts'
}

function closeArtifact(id: string) {
  ws.closeSideTab(id)
  if (!artifactTabs.value.length) ws.sideMode = 'artifacts'
}

function closeActiveArtifact() {
  if (activeArtifactId.value) closeArtifact(activeArtifactId.value)
}

let searchTimer: any = null
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => ws.search(query.value), 250)
}

async function openFile(entry: TreeEntry) {
  const data = await ws.readFile(entry.path)
  if (!data) return
  if (isHtmlFile(data) && typeof data.content === 'string' && !data.is_binary) {
    const url = URL.createObjectURL(new Blob([data.content], { type: 'text/html;charset=utf-8' }))
    htmlPreviewUrls.value.push(url)
    ws.activeWorkspaceFile = null
    ws.openBrowserTab(url)
    browserInput.value = url
    return
  }
  ws.openWorkspaceFile(data)
  ws.sideMode = 'files'
}

function isHtmlFile(file: any) {
  const e = String(file?.ext || String(file?.name || '').split('.').pop() || '').toLowerCase().replace(/^\./, '')
  return e === 'html' || e === 'htm'
}

function artifactIcon(tab: any) {
  const e = (tab.ext || (tab.name || '').split('.').pop() || '').toLowerCase()
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp'].includes(e)) return 'Picture'
  if (['js', 'ts', 'tsx', 'jsx', 'vue', 'css', 'py', 'json', 'html', 'md', 'txt'].includes(e)) return 'DocumentCopy'
  return 'Document'
}

async function onNewFile() {
  try {
    const { value } = await ElMessageBox.prompt('文件名（可含子路径，如 src/new.py）', '新建文件', {
      inputPattern: /.+/, inputErrorMessage: '请输入文件名',
    })
    await ws.newFile(value.trim())
    ElMessage.success('已创建')
  } catch {}
}

async function onNewDir() {
  try {
    const { value } = await ElMessageBox.prompt('文件夹名（可含子路径）', '新建文件夹', {
      inputPattern: /.+/, inputErrorMessage: '请输入名称',
    })
    await ws.newDir(value.trim())
    ElMessage.success('已创建')
  } catch {}
}

function openInFinder() {
  const p = ws.current?.path
  if (p && (window as any).desktop) (window as any).desktop.openPath(p)
}

function commitBrowserUrl() {
  let url = browserInput.value.trim()
  if (!url) return
  if (!/^(https?:|blob:|data:|file:|\/)/i.test(url)) url = `https://${url}`
  ws.openBrowserTab(url)
}
</script>

<style scoped>
.file-panel {
  width: var(--file-panel-width, clamp(320px, 38vw, 800px));
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-left: 1px solid rgba(28,28,26,.10);
  height: 100%;
  position: relative;
  transition: width .18s ease, opacity .14s ease;
  overflow: hidden;
}
.file-panel.workspace-compact {
  width: var(--file-panel-compact-width, 266px);
}
.file-panel.fullscreen {
  width: var(--file-panel-fullscreen-width, 100%);
}
.file-panel.collapsed {
  width: 0;
  opacity: 0;
  pointer-events: none;
  background: transparent;
}
.fp-content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.fp-tabs {
  height: 43px;
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 6px 2px 6px 8px;
  border-bottom: 1px solid rgba(28,28,26,.08);
  background: #fff;
  overflow-x: auto;
}
.fp-tab {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 5px;
  border: 0;
  background: transparent;
  cursor: pointer;
  border-radius: 12px;
  font-size: 12px;
  color: var(--m-text-secondary, #6b6b66);
  white-space: nowrap;
}
.fp-tab:hover { color: var(--m-text, #1c1c1a); background: rgba(28,28,26,.04); }
.fp-tab.active { color: var(--m-text, #1c1c1a); font-weight: 650; background: #f2f2ef; }
.fp-tab-icon {
  margin-left: auto;
  width: 30px;
  height: 30px;
  justify-content: center;
  padding: 0;
}
.fp-body {
  flex: 1;
  min-height: 0;
  display: flex;
  background: #fff;
  padding-top: 8px;
  box-sizing: border-box;
}
.fp-split {
  flex: 1;
  min-width: 0;
  display: flex;
  min-height: 0;
  background: #fff;
}
.fp-split:not(.with-preview) .fp-tree {
  width: 100%;
  border-left: 0;
}
.fp-preview {
  flex: 1 1 auto;
  min-width: 0;
  background: #fff;
  border-right: 1px solid rgba(28,28,26,.08);
  min-height: 0;
}
.fp-tree {
  width: 300px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  /* border-left: 1px solid rgba(28,28,26,.08); */
  min-height: 0;
}
.fp-empty-preview {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #777770;
  text-align: center;
  padding: 24px;
}
.fp-empty-preview span { font-size: 12px; color: #aaa9a2; }
.fp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px 8px;
  gap: 8px;
}
.fp-title { display: flex; align-items: center; gap: 7px; min-width: 0; font-weight: 600; font-size: 14px; }
.fp-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fp-actions { display: flex; gap: 2px; flex-shrink: 0; }
.fp-btn {
  width: 28px; height: 28px; border: none; background: transparent;
  border-radius: 7px; cursor: pointer; color: var(--m-text-secondary, #6b6b66);
  display: flex; align-items: center; justify-content: center;
  transition: background .15s, color .15s;
}
.fp-btn:hover { background: rgba(28,28,26,.06); color: var(--m-text, #1c1c1a); }
.fp-search { padding: 0 12px 8px; }
.fp-tree-body { flex: 1; overflow: auto; padding: 4px 6px 16px; }
.fp-hint { padding: 20px; text-align: center; color: var(--m-text-tertiary, #9a9a93); font-size: 14px; }
.fp-row {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 8px; border-radius: 7px; cursor: pointer; font-size: 13px;
}
.fp-row:hover { background: rgba(28,28,26,.055); }
.fp-ico { color: var(--m-text-secondary, #6b6b66); flex-shrink: 0; }
.fp-row-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fp-row-path { margin-left: auto; font-size: 12px; color: var(--m-text-tertiary, #9a9a93); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px; }
.fp-browser,
.fp-term,
.fp-artifacts { flex: 1; min-width: 0; display: flex; flex-direction: column; background: #fff; min-height: 0; }
.fp-browser { flex: 1; min-width: 0; display: flex; flex-direction: column; background: #fff; min-height: 0; }
.artifact-tabs {
  height: 42px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-bottom: 1px solid rgba(28,28,26,.08);
  background: #fff;
  overflow-x: auto;
}
.artifact-tab {
  height: 30px;
  max-width: 180px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: #777770;
  cursor: pointer;
  font-size: 12px;
  white-space: nowrap;
}
.artifact-tab span { overflow: hidden; text-overflow: ellipsis; }
.artifact-tab:hover { background: rgba(28,28,26,.05); color: #242421; }
.artifact-tab.active {
  background: #f4f4f1;
  border-color: rgba(28,28,26,.08);
  color: #242421;
  font-weight: 650;
}
.artifact-tab-close {
  width: 17px;
  height: 17px;
  margin-right: -3px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #aaa9a2;
  cursor: pointer;
}
.artifact-tab-close:hover {
  background: rgba(28,28,26,.09);
  color: #3d3c38;
}
.artifact-empty { flex: 1; }
.browser-bar {
  height: 42px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 12px;
  border-bottom: 1px solid rgba(28,28,26,.08);
  background: #fff;
}
.nav-btn {
  width: 26px; height: 26px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #777770;
  cursor: pointer;
}
.nav-btn:hover { background: rgba(28,28,26,.06); color: #242421; }
.url-input {
  flex: 1;
  height: 28px;
  border: 1px solid rgba(28,28,26,.08);
  border-radius: 9px;
  background: #f8f8f5;
  outline: none;
  padding: 0 10px;
  text-align: center;
  color: #56554e;
}
.browser-frame {
  width: 100%;
  height: 100%;
  border: none;
  background: #fff;
}
</style>
