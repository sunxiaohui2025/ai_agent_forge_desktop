<template>
  <div class="file-card" :class="[`kind-${fileKind}`, { previewable: canPreview }]" @click="onCardClick">
    <div class="file-icon">
      <el-icon :size="19"><component :is="iconComp" /></el-icon>
    </div>
    <div class="file-meta">
      <div class="file-name-row">
        <div class="file-name" :title="file.name">{{ file.name }}</div>
        <span class="file-badge">{{ typeLabel }}</span>
      </div>
      <div class="file-info">
        <span>{{ fileKindLabel }}</span>
        <span class="dot">·</span>
        <span>{{ formatSize(file.size) || shortMime }}</span>
      </div>
    </div>
    <div class="file-actions">
      <button class="action-btn primary" v-if="canPreview" @click.stop="onPreview">
        <el-icon :size="14"><View /></el-icon>
        <span>打开</span>
      </button>
      <a class="action-btn" :href="downloadUrl" :download="file.name" @click.stop="onDownloadClick">
        <el-icon :size="14"><Download /></el-icon>
      </a>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { api } from '@/api'

const props = defineProps<{ file: { name: string; size?: number; mime?: string; ext?: string; download_url: string; preview_url?: string; output_path?: string } }>()
const emit = defineEmits<{ (e: 'preview', file: any): void }>()

// Local override of download_url after we've refreshed an expired token.
const refreshedUrl = ref<string>('')

// Only formats the browser can render natively (or we have a light inline renderer for).
// Office formats (docx/xlsx/pptx) go download-only — preview quality would be poor.
const PREVIEWABLE = new Set([
  'html', 'htm',
  'pdf',
  'md', 'markdown',
  'txt', 'log',
  'json', 'csv', 'xml',
  'svg',
  'js', 'ts', 'css', 'py', 'sql', 'yml', 'yaml', 'sh',
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp',
])

const ext = computed(() => {
  const e = (props.file.ext || props.file.name.split('.').pop() || '').toLowerCase().replace(/^\./, '')
  return e
})

const canPreview = computed(() => PREVIEWABLE.has(ext.value))
const codeExts = new Set(['js', 'ts', 'tsx', 'jsx', 'vue', 'css', 'scss', 'less', 'py', 'sql', 'yml', 'yaml', 'sh', 'json', 'xml', 'html', 'htm'])
const fileKind = computed(() => {
  const e = ext.value
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp'].includes(e)) return 'image'
  if (codeExts.has(e)) return 'code'
  if (['md', 'markdown', 'txt', 'log', 'csv'].includes(e)) return 'text'
  if (['pdf'].includes(e)) return 'document'
  if (['doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx'].includes(e)) return 'office'
  if (['zip', 'tar', 'gz', '7z', 'rar'].includes(e)) return 'archive'
  return 'file'
})
const typeLabel = computed(() => ext.value ? ext.value.toUpperCase() : 'FILE')
const fileKindLabel = computed(() => {
  const k = fileKind.value
  if (k === 'image') return '图像预览'
  if (k === 'code') return '代码文件'
  if (k === 'text') return '文本内容'
  if (k === 'document') return '文档预览'
  if (k === 'office') return '复杂文档'
  if (k === 'archive') return '压缩包'
  return '输出文件'
})

// Append JWT as ?t= so <a download> (which can't set Authorization) still works.
const downloadUrl = computed(() => {
  const token = localStorage.getItem('access_token') || ''
  const url = refreshedUrl.value || props.file.download_url || ''
  if (!url) return ''
  const sep = url.includes('?') ? '&' : '?'
  return token ? `${url}${sep}t=${encodeURIComponent(token)}` : url
})

// Try a HEAD-ish ping to detect 410 from an expired download token.
// If we still have a stable output_path, mint a fresh token and patch the file in-place.
async function ensureFreshToken(): Promise<string> {
  const url = refreshedUrl.value || props.file.download_url || ''
  if (!url) return url
  if (!props.file.output_path) return url  // no way to refresh — give up
  try {
    const r = await fetch(url, { method: 'GET', headers: getAuthHeader() })
    if (r.ok) return url
    if (r.status === 410 || r.status === 404 || r.status === 403) {
      const fresh = await api.refreshDownload(props.file.output_path)
      if (fresh?.download_url) {
        refreshedUrl.value = fresh.download_url
        // Mutate the parent's file object so PreviewPanel (and history) sees the new URL.
        props.file.download_url = fresh.download_url
        return fresh.download_url
      }
    }
  } catch { /* network — let the actual click surface the error */ }
  return url
}

function getAuthHeader(): Record<string, string> {
  const t = localStorage.getItem('access_token')
  return t ? { Authorization: `Bearer ${t}` } : {}
}

async function onPreview() {
  await ensureFreshToken()
  emit('preview', props.file)
}

function onCardClick() {
  if (canPreview.value) onPreview()
}

async function onDownloadClick(ev: MouseEvent) {
  // If we already know the token is fresh, let the browser handle it natively.
  if (refreshedUrl.value) return
  // We can't await a real download in-anchor; intercept once, refresh, then
  // re-trigger the click programmatically with the new URL.
  if (!props.file.output_path) return
  ev.preventDefault()
  const fresh = await ensureFreshToken()
  if (!fresh) return
  const a = document.createElement('a')
  a.href = downloadUrl.value
  a.download = props.file.name || ''
  document.body.appendChild(a)
  a.click()
  a.remove()
}

const iconComp = computed(() => {
  const e = ext.value
  if (['html', 'htm'].includes(e)) return 'Monitor'
  if (e === 'pdf') return 'Document'
  if (['doc', 'docx'].includes(e)) return 'DocumentCopy'
  if (['ppt', 'pptx'].includes(e)) return 'PictureRounded'
  if (['md', 'markdown', 'txt'].includes(e)) return 'Notebook'
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(e)) return 'Picture'
  if (['zip', 'tar', 'gz', '7z'].includes(e)) return 'FolderOpened'
  return 'Files'
})

const iconBg = computed(() => {
  const e = ext.value
  if (['html', 'htm'].includes(e)) return 'linear-gradient(135deg,#fb923c,#f97316)'
  if (e === 'pdf') return 'linear-gradient(135deg,#ef4444,#dc2626)'
  if (['doc', 'docx'].includes(e)) return 'linear-gradient(135deg,#3b82f6,#1d4ed8)'
  if (['ppt', 'pptx'].includes(e)) return 'linear-gradient(135deg,#f59e0b,#d97706)'
  if (['md', 'markdown'].includes(e)) return 'linear-gradient(135deg,#6366f1,#4f46e5)'
  return 'linear-gradient(135deg,#64748b,#475569)'
})

const shortMime = computed(() => {
  const m = props.file.mime || ''
  if (!m) return ext.value.toUpperCase() || 'FILE'
  return m.split('/').pop() || m
})

function formatSize(b?: number): string {
  if (!b && b !== 0) return ''
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1024 / 1024).toFixed(2)} MB`
}
</script>

<style scoped>
.file-card {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px;
  background:
    linear-gradient(180deg, rgba(255,255,255,.96), rgba(250,250,247,.9));
  border: 1px solid rgba(28,28,26,.08);
  border-radius: 14px;
  margin: 0;
  box-shadow: 0 12px 34px -30px rgba(28,28,26,.34);
  transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease, background .15s ease;
}
.file-card.previewable { cursor: pointer; }
.file-card:hover {
  transform: translateY(-1px);
  border-color: rgba(28,28,26,.15);
  box-shadow: 0 18px 42px -34px rgba(28,28,26,.42);
}

.file-icon {
  width: 38px; height: 38px; border-radius: 11px;
  display: flex; align-items: center; justify-content: center;
  color: #56554e; flex-shrink: 0;
  background: #f2f2ef;
  border: 1px solid rgba(28,28,26,.06);
}
.kind-code .file-icon { color: #2f6f59; background: #edf6f1; }
.kind-image .file-icon { color: #9a5a34; background: #fbf0e9; }
.kind-document .file-icon { color: #3a6fb0; background: #eef3f9; }
.kind-office .file-icon { color: #a8741a; background: #f8f1e3; }
.kind-archive .file-icon { color: #6d625b; background: #f1efec; }

.file-meta { flex: 1; min-width: 0; }
.file-name-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.file-name {
  font-size: 13px; font-weight: 650; color: #282824;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.file-badge {
  flex-shrink: 0;
  height: 19px;
  padding: 0 6px;
  border-radius: 6px;
  background: rgba(28,28,26,.055);
  color: #777770;
  font-family: var(--m-font-mono);
  font-size: 10px;
  line-height: 19px;
  font-weight: 650;
}
.file-info {
  font-size: 12px; color: #8a897f;
  margin-top: 3px;
  display: flex; align-items: center; gap: 6px;
}
.file-info .dot { color: var(--m-text-tertiary); }

.file-actions { display: flex; align-items: center; gap: 5px; flex-shrink: 0; }
.action-btn {
  display: inline-flex; align-items: center; gap: 4px;
  min-height: 29px;
  padding: 0 9px;
  border-radius: 9px;
  font-size: 12px; font-weight: 500;
  color: #56554e;
  background: rgba(255,255,255,.72);
  border: 1px solid rgba(28,28,26,.08);
  cursor: pointer;
  text-decoration: none;
  transition: background .15s, color .15s, border-color .15s;
}
.action-btn.primary { color: #282824; }
.action-btn:hover { background: #fff; color: var(--m-primary); border-color: rgba(28,28,26,.15); }
</style>
