<template>
  <div class="dlayout" :class="{ 'nav-collapsed': navCollapsed, 'file-collapsed': filePanelCollapsed }">
    <!-- ░░ Left nav ░░ -->
    <aside class="nav" :class="{ 'os-win': isWin }">
      <div class="nav-top">
        <div class="nav-product">
          <span class="nav-product-name">Agent Forge</span>
          <span class="nav-product-version">v1.0.2</span>
        </div>
      </div>

      <!-- Primary actions -->
      <nav class="nav-primary">
        <button class="nav-item accent" @click="onNewTask">
          <el-icon :size="18"><Plus /></el-icon><span>新任务</span>
        </button>
        <router-link to="/plugins" class="nav-item" active-class="active">
          <el-icon :size="18"><MagicStick /></el-icon><span>插件</span>
        </router-link>
        <router-link to="/experts" class="nav-item" active-class="active">
          <el-icon :size="18"><User /></el-icon><span>专家</span>
        </router-link>
        <router-link to="/tasks" class="nav-item" active-class="active">
          <el-icon :size="18"><AlarmClock /></el-icon><span>自动化</span>
        </router-link>
        <router-link to="/space" class="nav-item" active-class="active">
          <el-icon :size="18"><FolderChecked /></el-icon><span>产物</span>
        </router-link>
      </nav>

      <div class="nav-scroll">
        <!-- Task groups (projects with a working dir) -->
        <div class="grp-head">
          <span>任务</span>
          <el-tooltip content="打开/新建项目" placement="top">
            <button class="grp-add" @click="onAddProject"><el-icon :size="14"><Plus /></el-icon></button>
          </el-tooltip>
        </div>

        <div v-if="!ws.list.length" class="grp-empty">暂无项目<br/>点击 + 选择目录</div>

        <div v-for="p in ws.list" :key="p.id" class="project">
          <div
            class="project-head" :class="{ active: ws.currentId === p.id }"
            @click="toggleProject(p)"
          >
            <el-icon class="proj-caret" :class="{ open: ws.currentId === p.id }"><ArrowRight /></el-icon>
            <el-icon class="proj-ico"><Folder /></el-icon>
            <span class="proj-name" :title="p.path">{{ p.name }}</span>
          </div>
          <div v-if="ws.currentId === p.id" class="project-convs">
            <div
              v-for="c in tasksOf(p.id)" :key="c.id"
              class="conv" :class="{ active: c.id === chat.currentConvId }"
              @click="openConv(c)"
            >
              <el-icon v-if="chat.isStreaming(c.id)" class="conv-ico conv-running"><Loading /></el-icon>
              <el-icon v-else class="conv-ico"><ChatLineRound /></el-icon>
              <span class="conv-title">{{ c.title }}</span>
              <el-icon class="conv-del" @click.stop="onDeleteConv(c)"><Delete /></el-icon>
            </div>
            <button class="conv-new" @click="onNewTaskIn(p)">
              <el-icon :size="13"><Plus /></el-icon> 新会话
            </button>
          </div>
        </div>

        <!-- Chats (no working dir) -->
        <div class="grp-head"><span>对话</span></div>
        <div v-if="!plainChats.length" class="grp-empty">暂无对话</div>
        <div
          v-for="c in plainChats" :key="c.id"
          class="conv standalone" :class="{ active: c.id === chat.currentConvId }"
          @click="openConv(c)"
        >
          <el-icon v-if="chat.isStreaming(c.id)" class="conv-ico conv-running"><Loading /></el-icon>
          <el-icon v-else class="conv-ico"><ChatLineRound /></el-icon>
          <span class="conv-title">{{ c.title }}</span>
          <el-icon class="conv-del" @click.stop="onDeleteConv(c)"><Delete /></el-icon>
        </div>
      </div>

      <!-- Settings pinned bottom -->
      <div class="nav-foot">
        <el-dropdown trigger="click" placement="top-start" popper-class="nav-foot-menu">
          <button class="nav-item nav-foot-btn">
            <el-icon :size="18"><Setting /></el-icon><span>设置</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="goSettings">
                <el-icon><Setting /></el-icon>设置
              </el-dropdown-item>
              <el-dropdown-item divided @click="onLogout">
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </aside>

    <div class="work-area">
      <div class="work-main">
        <!-- ░░ Center ░░ -->
        <div class="center">
          <header class="topbar">
            <div class="corner-controls">
              <el-tooltip :content="navCollapsed ? '展开侧边栏' : '收起侧边栏'" placement="bottom">
                <button class="chrome-icon" @click="navCollapsed = !navCollapsed">
                  <span class="sidebar-glyph" />
                </button>
              </el-tooltip>
              <el-tooltip content="新任务" placement="bottom">
                <button class="chrome-icon" @click="onNewTask">
                  <el-icon :size="17"><Plus /></el-icon>
                </button>
              </el-tooltip>
            </div>
            <div class="topbar-title">
              <div class="crumb">{{ currentSection }}</div>
              <div class="headline">{{ currentHeadline }}</div>
            </div>
            <div class="topbar-actions">
              <span class="status-pill">
                <span class="status-dot" />
                {{ ws.current ? ws.current.name : '本地工作台' }}
              </span>
              <NotificationBell />
              <router-link to="/settings" class="top-icon" title="设置">
                <el-icon :size="16"><Setting /></el-icon>
              </router-link>
              <el-tooltip
                v-if="showFilePanel"
                :content="filePanelCollapsed ? '展开文件工具栏' : '收起文件工具栏'"
                placement="bottom"
              >
                <button class="top-icon file-toggle" @click="filePanelCollapsed = !filePanelCollapsed">
                  <span class="file-glyph" />
                </button>
              </el-tooltip>
            </div>
          </header>
          <main class="view-shell">
            <router-view />
          </main>
        </div>

        <!-- ░░ Right file panel (only for tasks with a workspace) ░░ -->
        <FilePanel
          v-if="showFilePanel"
          :collapsed="filePanelCollapsed"
          :terminal-dock="terminalDock"
          @toggle="filePanelCollapsed = !filePanelCollapsed"
          @preview="onPreview"
          @dock-terminal-bottom="openBottomTerminal"
        />
      </div>

      <section
        v-if="showBottomTerminal"
        class="bottom-terminal-shell"
        :style="{ height: `${bottomTerminalHeight}px` }"
      >
        <div class="bottom-terminal-resize" title="拖拽调整终端高度" @pointerdown="startResizeBottomTerminal" />
        <TerminalTabs
          class="bottom-terminal"
          :cwd="ws.current?.path || null"
          :session-key="ws.currentId || 0"
          dock="bottom"
          @dock-side="dockTerminalSide"
          @close="bottomTerminalOpen = false"
        />
      </section>
    </div>
    <WsFilePreview />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useChat } from '@/stores/chat'
import { useWorkspace } from '@/stores/workspace'
import { useAuth } from '@/stores/auth'
import FilePanel from '@/components/FilePanel.vue'
import WsFilePreview from '@/components/WsFilePreview.vue'
import NotificationBell from '@/components/NotificationBell.vue'
import TerminalTabs from '@/components/TerminalTabs.vue'
import { Delete } from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()
const auth = useAuth()
const chat = useChat()
const ws = useWorkspace()
const navCollapsed = ref(false)
const filePanelCollapsed = ref(false)
const terminalDock = ref<'side' | 'bottom'>('side')
const bottomTerminalOpen = ref(false)
const bottomTerminalHeight = ref(248)
const _plat = typeof window !== 'undefined' && (window as any).desktop?.platform
const isWin = ref(_plat === 'win32')

function onOpenTerminalPanel() {
  if (terminalDock.value === 'bottom') {
    bottomTerminalOpen.value = true
  } else {
    filePanelCollapsed.value = false
  }
}

onMounted(async () => {
  if (!chat.loaded) await chat.loadInit()
  if (!ws.loaded) await ws.load()
  window.addEventListener('workbuddy:open-terminal', onOpenTerminalPanel)
})
onBeforeUnmount(() => window.removeEventListener('workbuddy:open-terminal', onOpenTerminalPanel))

const plainChats = computed(() => chat.convs.filter((c: any) => !c.workspace_id))
function tasksOf(wid: number) {
  return chat.convs.filter((c: any) => c.workspace_id === wid)
}

const showFilePanel = computed(() =>
  route.path === '/chat' && ws.currentId != null && ws.isDesktop)
const showBottomTerminal = computed(() =>
  showFilePanel.value && terminalDock.value === 'bottom' && bottomTerminalOpen.value)

function openBottomTerminal() {
  terminalDock.value = 'bottom'
  bottomTerminalOpen.value = true
}

function dockTerminalSide() {
  terminalDock.value = 'side'
  bottomTerminalOpen.value = false
  filePanelCollapsed.value = false
}

function startResizeBottomTerminal(e: PointerEvent) {
  e.preventDefault()
  const startY = e.clientY
  const startHeight = bottomTerminalHeight.value
  const maxHeight = Math.max(280, Math.floor(window.innerHeight * 0.72))
  const minHeight = 170
  const onMove = (ev: PointerEvent) => {
    const next = startHeight - (ev.clientY - startY)
    bottomTerminalHeight.value = Math.min(maxHeight, Math.max(minHeight, next))
  }
  const onUp = () => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}

const currentSection = computed(() => {
  if (route.path.startsWith('/plugins')) return 'Extensions'
  if (route.path.startsWith('/experts')) return 'Experts'
  if (route.path.startsWith('/tasks')) return 'Automations'
  if (route.path.startsWith('/space')) return 'Artifacts'
  return 'Agent Session'
})

const currentHeadline = computed(() => {
  if (route.path.startsWith('/plugins')) return '插件与工具'
  if (route.path.startsWith('/experts')) return '专家配置'
  if (route.path.startsWith('/tasks')) return '自动化任务'
  if (route.path.startsWith('/space')) return '产物'
  return ws.current ? `正在协作：${ws.current.name}` : '和你的专家开始一次任务'
})

async function onNewTask() {
  // New plain chat by default (no workspace selected).
  await ws.select(null)
  await chat.newConv()
  if (route.path !== '/chat') router.push('/chat')
}

async function onAddProject() {
  if (!ws.isDesktop) {
    ElMessage.info('请在桌面客户端中使用项目目录功能')
    return
  }
  const p = await ws.addViaPicker()
  if (p) {
    await chat.newConv()
    if (route.path !== '/chat') router.push('/chat')
  }
}

async function toggleProject(p: any) {
  if (ws.currentId === p.id) { await ws.select(null); return }
  await ws.select(p.id)
}

async function onNewTaskIn(p: any) {
  await ws.select(p.id)
  await chat.newConv()
  // The conversation row is created lazily on first send (ensureConv with wid).
  ;(chat as any)._pendingWorkspaceId = p.id
  if (route.path !== '/chat') router.push('/chat')
}

async function openConv(c: any) {
  // Restore the bound workspace FIRST so the right-hand file panel + composer
  // chip reflect this task's working directory. selectConv may overwrite the
  // active agent but never the workspace, so order is safe.
  if (c.workspace_id) {
    await ws.select(c.workspace_id)
  } else {
    await ws.select(null)
  }
  await chat.selectConv(c)
  if (route.path !== '/chat') router.push('/chat')
}

function onPreview(_file: any) {
  // PreviewPanel wiring lands with the chat-area refactor (next step).
}

function goSettings() { router.push('/settings') }

async function onDeleteConv(c: any) {
  try {
    await ElMessageBox.confirm(
      `确定要删除对话「${c.title}」吗？删除后不可恢复。`,
      '删除对话',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return  // cancelled
  }
  await chat.deleteConv(c)
}

async function onLogout() {
  try {
    await ElMessageBox.confirm(
      '你需要重新登录才能继续使用 Agent Forge。',
      '退出登录？',
      { confirmButtonText: '退出登录', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return  // cancelled
  }
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.dlayout {
  display: flex;
  height: 100vh;
  background: #ffffff;
  color: var(--m-text);
  padding: 0;
  gap: 0;
  font-size: 13px;
}

/* ── Left nav (IDE activity rail + explorer) ── */
.nav {
  width: 256px; flex-shrink: 0;
  display: flex; flex-direction: column;
  background: rgba(251,250,251);
  border-right: 0;
  border-radius: 0;
  box-shadow: none;
  overflow: hidden;
  transition: width .18s ease, opacity .14s ease;
}

.nav-top {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  padding: 48px 18px 4px 22px; /* macOS: room for traffic-light buttons */
  min-height: 58px;
  -webkit-app-region: drag;
}
.os-win .nav-top {
  padding: 12px 18px 10px 22px;
  min-height: unset;
}
.nav-product {
  display: flex;
  align-items: baseline;
  min-width: 0;
  gap: 5px;
  color: #aaa9a4;
  white-space: nowrap;
}
.nav-product-name {
  font-size: 13px;
  font-weight: 680;
  color: #a4a39d;
}
.nav-product-version {
  font-size: 10px;
  font-weight: 600;
  color: #c3c2bc;
}
.nav-primary { display: flex; flex-direction: column; gap: 4px; padding: 4px 10px 10px; border-bottom: 0; }
.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px; border-radius: 8px;
  font-size: 13px; font-weight: 500; color: var(--m-text);
  background: transparent; border: none; cursor: pointer; text-decoration: none;
  text-align: left; width: 100%;
  transition: background .12s, box-shadow .12s, color .12s;
}
.nav-item:hover { background: #e9e9e7; }
.nav-item.active { background: #eaeae9; box-shadow: none; font-weight: 650; }
.nav-item.active :deep(.el-icon) { color: var(--m-primary); }
.nav-item.accent { background: #eaeae9; color: #1f1f1d; box-shadow: none; font-weight: 700; }
.nav-item.accent:hover { background: #ddddda; }
.nav-item.accent :deep(.el-icon) { color: #1f1f1d; }

.nav-scroll { flex: 1; overflow: auto; padding: 8px 12px; }
.grp-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 10px 7px; font-size: 12px; font-weight: 650;
  letter-spacing: 0; color: #9f9f98;
}
.grp-add {
  width: 22px; height: 20px; border: none; background: transparent; cursor: pointer;
  border-radius: var(--m-radius-sm); color: var(--m-text-tertiary);
  display: flex; align-items: center; justify-content: center;
}
.grp-add:hover { background: rgba(28,28,26,.06); color: var(--m-text); }
.grp-empty { padding: 8px 10px; font-size: 12px; color: #aaa9a2; line-height: 1.6; }

.project { margin-bottom: 1px; }
.project-head {
  display: flex; align-items: center; gap: 5px;
  padding: 6px 10px; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 550;
}
.project-head:hover { background: #e9e9e7; }
.project-head.active { background: #e4e4e2; box-shadow: none; }
.proj-caret { font-size: 11px; color: var(--m-text-tertiary); transition: transform .12s; }
.proj-caret.open { transform: rotate(90deg); }
.proj-ico { color: var(--m-text-secondary); }
.proj-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.project-convs { padding-left: 16px; }

.conv {
  display: flex; align-items: center; gap: 7px;
  padding: 4px 10px; border-radius: 8px; cursor: pointer; font-size: 13px;
  color: var(--m-text-secondary);
      margin-top: 3px;
}
.conv:hover { background: #e9e9e7; }
.conv.active { background: #e4e4e2; color: var(--m-text); box-shadow: none; }
.conv.standalone { margin: 0; }
.conv-ico { flex-shrink: 0; color: var(--m-text-tertiary); }
/* Running indicator: this conversation has an in-flight turn streaming in the
   background (kept alive in the chat store even when the chat view is unmounted).
   A spinning loader replaces the static chat icon so the user can spot it. */
.conv-running { color: var(--m-primary, #2f6df6); animation: conv-spin 1s linear infinite; }
@keyframes conv-spin { to { transform: rotate(360deg); } }
.conv-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin:2px}
.conv-del {
  margin-left: auto; flex-shrink: 0;
  opacity: 0; transition: opacity .12s;
  color: var(--m-text-tertiary); font-size: 14px;
}
.conv:hover .conv-del { opacity: 1; }
.conv-del:hover { color: #e5534b; }
.conv-new {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 8px; margin: 1px 0; border: none; background: transparent; cursor: pointer;
  font-size: 12px; color: var(--m-text-tertiary); border-radius: var(--m-radius);
}
.conv-new:hover { background: #e9e9e7; color: var(--m-text); }

.nav-foot { padding: 10px 12px 16px; border-top: 0; }
.nav-foot :deep(.el-dropdown) { width: 100%; display: block; }
.nav-foot-btn { width: 100%; }
.nav-foot-caret { margin-left: auto; color: var(--m-text-tertiary); }

/* ── Center ── */
.work-area {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
}
.work-main {
  flex: 1;
  min-height: 0;
  min-width: 0;
  display: flex;
}
.center {
  flex: 1; min-width: 0;
  display: flex; flex-direction: column;
  background: #ffffff;
  border: 0;
  border-radius: 0;
  box-shadow: none;
  overflow: hidden;
  position: relative;
}
.bottom-terminal-shell {
  position: relative;
  flex-shrink: 0;
  min-height: 170px;
  max-height: 72vh;
  border-top: 1px solid #eeeeeb;
  background: #ffffff;
  box-shadow: none;
}
.bottom-terminal-resize {
  position: absolute;
  z-index: 5;
  top: -3px;
  left: 0;
  right: 0;
  height: 7px;
  cursor: ns-resize;
  background: transparent;
}
.bottom-terminal-resize::after {
  content: "";
  position: absolute;
  left: 50%;
  top: 2px;
  width: 42px;
  height: 3px;
  border-radius: 999px;
  background: transparent;
  transform: translateX(-50%);
  transition: background .12s;
}
.bottom-terminal-resize:hover::after {
  background: #d8d8d4;
}
.bottom-terminal {
  height: 100%;
  min-height: 0;
}
.corner-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  -webkit-app-region: no-drag;
}
.chrome-icon {
  width: 30px; height: 30px;
  display: inline-flex; align-items: center; justify-content: center;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--m-text-secondary);
  cursor: pointer;
  transition: background .12s, color .12s;
}
.chrome-icon:hover { background: rgba(28,28,26,.06); color: var(--m-text); }
.sidebar-glyph {
  width: 16px;
  height: 14px;
  border: 1.7px solid currentColor;
  border-radius: 4px;
  position: relative;
  display: inline-block;
}
.sidebar-glyph::before {
  content: "";
  position: absolute;
  left: 4px;
  top: 0;
  bottom: 0;
  width: 1.5px;
  background: currentColor;
  opacity: .75;
}
.topbar {
  height: 56px;
  flex-shrink: 0;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 16px 0 14px;
  background: transparent;
  border-bottom: 0;
  /* The whole top bar is a draggable window region on macOS. Interactive
     children (.corner-controls, .topbar-actions and their buttons/links)
     opt out via -webkit-app-region: no-drag below so they stay clickable. */
  -webkit-app-region: drag;
}
.nav-collapsed .topbar {
  padding-left: 72px;
}
.topbar-title {
  min-width: 0;
  line-height: 1.18;
  visibility: hidden;
  flex: 1;
  align-self: stretch;
  display: flex;
  flex-direction: column;
  justify-content: center;
  -webkit-app-region: drag;
}
.crumb {
  font-size: 11px;
  font-weight: 650;
  letter-spacing: .04em;
  color: var(--m-text-tertiary);
  text-transform: uppercase;
}
.headline {
  margin-top: 4px;
  font-size: 15px;
  font-weight: 680;
  color: var(--m-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topbar-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.topbar-actions,
.nav button,
.nav a,
.chrome-icon {
  -webkit-app-region: no-drag;
}
.status-pill {
  display: inline-flex; align-items: center; gap: 7px;
  height: 30px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(255,255,255,.72);
  border: 1px solid #ececea;
  color: var(--m-text-secondary);
  font-size: 12px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-pill .status-dot {
  width: 7px; height: 7px;
  border-radius: 999px;
  background: #2f8a52;
  box-shadow: 0 0 0 3px rgba(47,138,82,.12);
}
.top-icon {
  width: 30px; height: 30px;
  display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--m-text-secondary);
  cursor: pointer;
  text-decoration: none;
}
.top-icon:hover {
  background: rgba(28,28,26,.055);
  border-color: transparent;
  color: var(--m-text);
}
.file-toggle {
  border: 0;
}
.file-glyph {
  width: 16px;
  height: 14px;
  border: 1.7px solid currentColor;
  border-radius: 4px;
  position: relative;
  display: inline-block;
}
.file-glyph::before {
  content: "";
  position: absolute;
  right: 4px;
  top: 0;
  bottom: 0;
  width: 1.5px;
  background: currentColor;
  opacity: .75;
}
.view-shell {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  -webkit-app-region: no-drag;
}

.nav-collapsed .nav {
  width: 0;
  opacity: 0;
  pointer-events: none;
}
</style>
