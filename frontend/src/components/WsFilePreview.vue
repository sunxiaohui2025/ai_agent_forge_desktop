<template>
  <div v-if="ws.preview" class="wsp-overlay" @click.self="ws.closePreview()">
    <div class="wsp-panel">
      <div class="wsp-head">
        <div class="wsp-title">
          <el-icon :size="15"><Document /></el-icon>
          <span>{{ ws.preview.name }}</span>
          <span class="wsp-path">{{ ws.preview.path }}</span>
        </div>
        <button class="wsp-close" @click="ws.closePreview()"><el-icon :size="16"><Close /></el-icon></button>
      </div>
      <div class="wsp-body">
        <div v-if="ws.preview.is_binary" class="wsp-hint">二进制文件，无法预览（{{ humanSize(ws.preview.size) }}）</div>
        <!-- HTML: render in sandboxed iframe via blob URL -->
        <iframe
          v-else-if="isHtml && htmlBlobUrl"
          class="wsp-frame"
          sandbox="allow-scripts allow-popups"
          :src="htmlBlobUrl"
        />
        <template v-else>
          <pre class="wsp-code"><code>{{ ws.preview.content }}</code></pre>
          <div v-if="ws.preview.truncated" class="wsp-trunc">⚠ 文件较大，仅显示前 512KB</div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch, ref, onBeforeUnmount } from 'vue'
import { useWorkspace } from '@/stores/workspace'
const ws = useWorkspace()

const isHtml = computed(() => {
  const name = ws.preview?.name || ''
  const ext = name.split('.').pop()?.toLowerCase() || ''
  return ext === 'html' || ext === 'htm'
})

const htmlBlobUrl = ref('')
watch(
  () => ws.preview?.content,
  (content) => {
    if (htmlBlobUrl.value) { URL.revokeObjectURL(htmlBlobUrl.value); htmlBlobUrl.value = '' }
    if (content && isHtml.value) {
      htmlBlobUrl.value = URL.createObjectURL(new Blob([content], { type: 'text/html' }))
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => { if (htmlBlobUrl.value) URL.revokeObjectURL(htmlBlobUrl.value) })

function humanSize(n: number) {
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}
</script>

<style scoped>
.wsp-overlay {
  position: fixed; inset: 0; z-index: 2000;
  background: rgba(0,0,0,.28);
  display: flex; align-items: stretch; justify-content: flex-end;
}
.wsp-panel {
  width: 64%; max-width: 920px; height: 100%;
  background: var(--m-surface, #fff); display: flex; flex-direction: column;
  box-shadow: -8px 0 32px rgba(0,0,0,.12);
  animation: slideIn .18s ease;
}
@keyframes slideIn { from { transform: translateX(20px); opacity: .6; } to { transform: translateX(0); opacity: 1; } }
.wsp-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--m-border, #e7e7e4);
}
.wsp-title { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 14px; min-width: 0; }
.wsp-path { font-size: 12px; color: var(--m-text-tertiary, #9a9a93); font-weight: 400; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wsp-close { border: none; background: transparent; cursor: pointer; color: var(--m-text-secondary, #6b6b66); width: 30px; height: 30px; border-radius: 7px; display: flex; align-items: center; justify-content: center; }
.wsp-close:hover { background: var(--m-surface-variant, #ececea); }
.wsp-body { flex: 1; overflow: auto; }
.wsp-code {
  margin: 0; padding: 18px;
  font-family: 'Roboto Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px; line-height: 1.6; color: var(--m-text, #1c1c1a);
  white-space: pre; tab-size: 2;
}
.wsp-frame { width: 100%; height: 100%; border: none; background: #fff; display: block; }
.wsp-hint, .wsp-trunc { padding: 24px; color: var(--m-text-tertiary, #9a9a93); font-size: 13px; }
.wsp-trunc { padding: 8px 18px 24px; color: var(--m-warning, #b5791f); }
</style>
