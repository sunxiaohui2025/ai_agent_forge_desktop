<template>
  <aside class="file-panel" :class="{ collapsed }">

    <div v-show="!collapsed" class="fp-content">
    <!-- Tab switch: files / terminal -->
    <div class="fp-tabs">
      <button :class="['fp-tab', { active: tab === 'files' }]" @click="tab = 'files'">
        <el-icon :size="12"><Files /></el-icon> 文件
      </button>
      <button :class="['fp-tab', { active: tab === 'term' }]" @click="openTerm">
        <el-icon :size="12"><Monitor /></el-icon> 终端
      </button>
    </div>

    <!-- ░ Files tab ░ -->
    <template v-if="tab === 'files'">
    <!-- Header -->
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

    <!-- Search -->
    <div class="fp-search">
      <el-input v-model="query" size="small" placeholder="搜索文件…" clearable @input="onSearch">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
    </div>

    <!-- Body -->
    <div class="fp-body">
      <div v-if="ws.treeLoading" class="fp-hint">加载中…</div>

      <!-- Search results mode -->
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

      <!-- Tree mode -->
      <template v-else>
        <div v-if="!ws.tree.length" class="fp-hint">空目录</div>
        <FileTreeNode
          v-for="entry in ws.tree" :key="entry.path"
          :entry="entry" :depth="0"
          @open="openFile"
        />
      </template>
    </div>
    </template>

    <!-- ░ Terminal tab ░ -->
    <div v-show="tab === 'term'" class="fp-term">
      <TerminalTabs
        v-if="termMounted && terminalDock === 'side'"
        :cwd="ws.current?.path || null"
        :session-key="ws.currentId || 0"
        dock="side"
        @dock-bottom="emit('dockTerminalBottom')"
      />
      <div v-else-if="terminalDock === 'bottom'" class="fp-term-docked">
        <div class="fp-term-docked-title">终端已切换到底部面板</div>
        <button class="fp-term-docked-btn" @click="emit('dockTerminalBottom')">打开底部面板</button>
      </div>
    </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useWorkspace, type TreeEntry } from '@/stores/workspace'
import FileTreeNode from './FileTreeNode.vue'
import TerminalTabs from './TerminalTabs.vue'

const ws = useWorkspace()
const props = withDefaults(defineProps<{ collapsed?: boolean; terminalDock?: 'side' | 'bottom' }>(), {
  terminalDock: 'side',
})
const query = ref('')
const tab = ref<'files' | 'term'>('files')
const termMounted = ref(false)

function openTerm() {
  tab.value = 'term'
  termMounted.value = true   // lazy-mount the terminal on first open
  if (props.terminalDock === 'bottom') emit('dockTerminalBottom')
}
function onOpenTerminal() {
  openTerm()
}
onMounted(() => window.addEventListener('workbuddy:open-terminal', onOpenTerminal))
onBeforeUnmount(() => window.removeEventListener('workbuddy:open-terminal', onOpenTerminal))
const emit = defineEmits<{
  (e: 'preview', file: any): void
  (e: 'toggle'): void
  (e: 'dockTerminalBottom'): void
}>()

let searchTimer: any = null
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => ws.search(query.value), 250)
}

async function openFile(entry: TreeEntry) {
  const data = await ws.readFile(entry.path)
  if (data) emit('preview', data)
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
</script>

<style scoped>
.file-panel {
  width: 320px; flex-shrink: 0;
  display: flex; flex-direction: column;
  background: var(--m-surface-glass, rgba(250,250,247,.78));
  backdrop-filter: blur(20px) saturate(1.14);
  -webkit-backdrop-filter: blur(20px) saturate(1.14);
  border-left: 0;
  height: 100%;
  position: relative;
  transition: width .18s ease, opacity .14s ease;
  font-size: 15px;
  overflow: hidden;
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
  opacity: 1;
  transition: opacity .14s ease;
}
.file-panel.collapsed .fp-content {
  opacity: 0;
  pointer-events: none;
}
.fp-collapse {
  position: absolute;
  top: 10px;
  left: 6px;
  z-index: 5;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--m-text-secondary, #6b6b66);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background .12s, color .12s;
}
.fp-collapse:hover { background: rgba(28,28,26,.065); color: var(--m-text, #1c1c1a); }
.fp-collapse :deep(.el-icon) { transform: rotate(0); transition: transform .18s ease; }
.file-panel:not(.collapsed) .fp-tabs {
  padding-left: 8px;
}
.fp-tabs {
  display: flex; gap: 2px; padding: 6px 6px 8px;
  border-bottom: 0;
}
.fp-tab {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 7px 11px; border: 0; background: transparent; cursor: pointer;
  border-radius: var(--m-radius);
  font-size: 15px; color: var(--m-text-secondary, #6b6b66);
}
.fp-tab:hover { color: var(--m-text, #1c1c1a); }
.fp-tab.active { color: var(--m-text, #1c1c1a); font-weight: 600; background: rgba(255,255,255,.68); }
.fp-term { flex: 1; min-height: 0; }
.fp-term-docked {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 20px;
  color: var(--m-text-secondary, #56554e);
  text-align: center;
}
.fp-term-docked-title { font-size: 13px; color: #777770; }
.fp-term-docked-btn {
  border: 0;
  border-radius: 9px;
  background: #f1f1ef;
  color: #242421;
  min-height: 30px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}
.fp-term-docked-btn:hover { background: #e5e5e2; }
.fp-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 14px 8px; gap: 8px;
}
.fp-title { display: flex; align-items: center; gap: 7px; min-width: 0; font-weight: 600; font-size: 15px; }
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
.fp-body { flex: 1; overflow: auto; padding: 4px 6px 16px; }
.fp-hint { padding: 20px; text-align: center; color: var(--m-text-tertiary, #9a9a93); font-size: 14px; }
.fp-row {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 8px; border-radius: 7px; cursor: pointer; font-size: 15px;
}
.fp-row:hover { background: rgba(28,28,26,.055); }
.fp-ico { color: var(--m-text-secondary, #6b6b66); flex-shrink: 0; }
.fp-row-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fp-row-path { margin-left: auto; font-size: 13px; color: var(--m-text-tertiary, #9a9a93); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px; }
</style>
