<template>
  <section class="terminal-tabs" :class="`dock-${dock}`">
    <div class="terminal-head">
      <div class="terminal-tabstrip">
        <button
          v-for="t in tabs"
          :key="t.id"
          :class="['terminal-tab', { active: t.id === activeId }]"
          @click="activeId = t.id"
        >
          <span>{{ t.title }}</span>
          <span v-if="tabs.length > 1" class="tab-close" @click.stop="closeTab(t.id)">×</span>
        </button>
        <button class="terminal-add" title="新增终端" @click="addTab">+</button>
      </div>
      <div class="terminal-actions">
        <button v-if="dock === 'side'" class="terminal-action" @click="$emit('dockBottom')">切换底部面板</button>
        <button v-else class="terminal-action" @click="$emit('dockSide')">切回右侧栏</button>
        <button v-if="dock === 'bottom'" class="terminal-close" title="关闭底部面板" @click="$emit('close')">×</button>
      </div>
    </div>

    <div class="terminal-body">
      <TerminalView
        v-for="t in tabs"
        :key="t.id"
        v-show="t.id === activeId"
        :cwd="cwd"
        :session-key="`${sessionKey}-${dock}-${t.id}`"
        :active="t.id === activeId"
        :receive-external="t.id === activeId"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import TerminalView from './TerminalView.vue'

defineProps<{
  cwd: string | null
  sessionKey: string | number
  dock: 'side' | 'bottom'
}>()

defineEmits<{
  (e: 'dockBottom'): void
  (e: 'dockSide'): void
  (e: 'close'): void
}>()

const nextId = ref(2)
const tabs = ref([{ id: 1, title: '终端 1' }])
const activeId = ref(1)

function addTab() {
  const id = nextId.value++
  tabs.value.push({ id, title: `终端 ${id}` })
  activeId.value = id
}

function closeTab(id: number) {
  if (tabs.value.length <= 1) return
  const index = tabs.value.findIndex((t) => t.id === id)
  tabs.value = tabs.value.filter((t) => t.id !== id)
  if (activeId.value === id) {
    activeId.value = tabs.value[Math.max(0, index - 1)]?.id || tabs.value[0]?.id || 1
  }
}
</script>

<style scoped>
.terminal-tabs {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  color: var(--m-text, #1c1c1a);
  overflow: hidden;
}
.terminal-head {
  height: 36px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 5px 10px;
  background: #ffffff;
  border-bottom: 0;
}
.terminal-tabstrip {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  overflow: hidden;
}
.terminal-tab,
.terminal-add,
.terminal-action,
.terminal-close {
  border: 0;
  background: transparent;
  color: var(--m-text-secondary, #56554e);
  cursor: pointer;
  font-size: 12px;
  height: 26px;
  border-radius: 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.terminal-tab {
  gap: 6px;
  max-width: 120px;
  padding: 0 10px;
  background: #f3f3f0;
  font-weight: 560;
}
.terminal-tab span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.terminal-tab.active {
  background: #e9e9e6;
  color: var(--m-text, #1c1c1a);
  box-shadow: none;
}
.terminal-tab:hover,
.terminal-add:hover,
.terminal-action:hover,
.terminal-close:hover {
  background: rgba(28,28,26,.055);
  color: var(--m-text, #1c1c1a);
}
.tab-close {
  color: #aaa9a2;
  font-size: 15px;
  line-height: 1;
}
.terminal-add {
  width: 26px;
  flex-shrink: 0;
  font-size: 16px;
  background: #f3f3f0;
}
.terminal-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.terminal-action {
  padding: 0 9px;
  background: #f3f3f0;
  color: #3f3f3b;
  font-weight: 650;
}
.terminal-close {
  width: 26px;
  font-size: 17px;
  background: #f3f3f0;
}
.terminal-body {
  flex: 1;
  min-height: 0;
  background: #ffffff;
}
.dock-side .terminal-head {
  padding-left: 8px;
}
.dock-bottom .terminal-head {
  padding: 5px 14px 4px;
}
</style>
