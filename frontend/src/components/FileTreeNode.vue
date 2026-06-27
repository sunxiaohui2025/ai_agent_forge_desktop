<template>
  <div class="ftn">
    <div
      class="ftn-row" :style="{ paddingLeft: depth * 14 + 8 + 'px' }"
      @click="onClick"
    >
      <el-icon v-if="entry.type === 'directory'" class="ftn-caret" :class="{ open: isOpen }">
        <ArrowRight />
      </el-icon>
      <span v-else class="ftn-caret-spacer" />
      <el-icon class="ftn-ico">
        <FolderOpened v-if="entry.type === 'directory' && isOpen" />
        <Folder v-else-if="entry.type === 'directory'" />
        <Document v-else />
      </el-icon>
      <span class="ftn-name">{{ entry.name }}</span>
    </div>

    <template v-if="entry.type === 'directory' && isOpen">
      <FileTreeNode
        v-for="child in children" :key="child.path"
        :entry="child" :depth="depth + 1"
        @open="(e) => $emit('open', e)"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useWorkspace, type TreeEntry } from '@/stores/workspace'

const props = defineProps<{ entry: TreeEntry; depth: number }>()
const emit = defineEmits<{ (e: 'open', entry: TreeEntry): void }>()
const ws = useWorkspace()

const isOpen = computed(() => !!ws.expanded[props.entry.path])
const children = computed(() => ws.expanded[props.entry.path] || [])

function onClick() {
  if (props.entry.type === 'directory') ws.expandDir(props.entry.path)
  else emit('open', props.entry)
}
</script>

<style scoped>
.ftn-row {
  display: flex; align-items: center; gap: 5px;
  padding: 4px 8px; border-radius: 6px; cursor: pointer; font-size: 13px;
  user-select: none;
}
.ftn-row:hover { background: var(--m-surface-variant, #f1f1ef); }
.ftn-caret { color: var(--m-text-tertiary, #9a9a93); transition: transform .12s; flex-shrink: 0; font-size: 12px; }
.ftn-caret.open { transform: rotate(90deg); }
.ftn-caret-spacer { width: 12px; flex-shrink: 0; }
.ftn-ico { color: var(--m-text-secondary, #6b6b66); flex-shrink: 0; }
.ftn-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
