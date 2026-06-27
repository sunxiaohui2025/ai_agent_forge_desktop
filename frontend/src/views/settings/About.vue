<template>
  <div class="page">
    <div class="page-head"><span class="page-title">关于</span></div>

    <div class="about-hero">
      <img class="about-logo" src="/icon.svg" alt="logo" />
      <div>
        <div class="about-name">个人桌面智能体</div>
        <div class="about-tag">Agent command center · 本地工作台 / 编排 / 评审控制台</div>
      </div>
    </div>

    <!-- Update check -->
    <div class="about-card">
      <div class="about-row">
        <div>
          <div class="row-title">当前版本</div>
          <div class="row-val mono">v{{ info.version }}</div>
        </div>
        <el-button size="small" :loading="checking" @click="check">检查更新</el-button>
      </div>

      <!-- Update result -->
      <div v-if="update" class="update-result">
        <template v-if="update.error">
          <span class="status-warning"><span class="status-dot"></span> 检查失败：{{ update.error }}</span>
        </template>
        <template v-else-if="update.hasUpdate">
          <div class="update-available">
            <span class="status-running"><span class="status-dot"></span> 发现新版本 v{{ update.latest }}</span>
            <div v-if="update.releaseNotes" class="release-notes">{{ update.releaseNotes }}</div>
            <div class="update-actions">
              <a v-if="update.url" :href="update.url" target="_blank" class="update-link">查看详情 →</a>
              <el-button
                v-if="update.downloadUrl"
                type="primary"
                size="small"
                :loading="downloading"
                :disabled="downloaded"
                @click="startDownload"
              >
                {{ downloading ? '下载中...' : downloaded ? '已下载' : '下载更新' }}
              </el-button>
              <el-button
                v-if="downloading"
                size="small"
                @click="cancelDownload"
              >取消</el-button>
              <el-button
                v-if="downloaded"
                type="success"
                size="small"
                @click="installUpdate"
              >安装更新</el-button>
            </div>
            <!-- Download progress bar -->
            <div v-if="downloading" class="download-progress">
              <div class="progress-bar">
                <div class="progress-fill" :style="{ width: downloadPercent + '%' }"></div>
              </div>
              <span class="progress-text">{{ downloadPercent }}% · {{ formatSize(downloadedBytes) }} / {{ formatSize(downloadTotal) }}</span>
            </div>
            <div v-if="downloadError" class="status-warning" style="margin-top:8px">{{ downloadError }}</div>
          </div>
        </template>
        <template v-else>
          <span class="status-success"><span class="status-dot"></span> 已是最新版本</span>
        </template>
      </div>
    </div>

    <!-- Platform info -->
    <div class="about-card">
      <div class="card-title">平台信息</div>
      <div class="info-grid">
        <div class="info-item"><span class="k">系统平台</span><span class="v mono">{{ info.platform }} · {{ info.arch }}</span></div>
        <div class="info-item"><span class="k">Electron</span><span class="v mono">{{ info.electron || '—' }}</span></div>
        <div class="info-item"><span class="k">Node</span><span class="v mono">{{ info.node || '—' }}</span></div>
        <div class="info-item"><span class="k">Chromium</span><span class="v mono">{{ info.chrome || '—' }}</span></div>
        <div class="info-item"><span class="k">后端端口</span><span class="v mono">{{ info.backendPort || '—' }}</span></div>
        <div class="info-item"><span class="k">运行模式</span><span class="v">{{ isDesktop ? '桌面客户端' : '浏览器' }}</span></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'

const isDesktop = typeof window !== 'undefined' && (window as any).desktop?.isDesktop === true
const desktop = (window as any).desktop || {}
const info = reactive<any>({ version: '0.1.0', platform: isDesktop ? desktop.platform : 'web', arch: '', electron: '', node: '', chrome: '', backendPort: '' })
const update = ref<any>(null)
const checking = ref(false)

// Download state
const downloading = ref(false)
const downloaded = ref(false)
const downloadPercent = ref(0)
const downloadedBytes = ref(0)
const downloadTotal = ref(0)
const downloadError = ref('')
const downloadPath = ref('')
let unsubProgress: (() => void) | null = null

async function check() {
  if (!isDesktop) { update.value = { error: '仅桌面客户端支持' }; return }
  checking.value = true
  downloaded.value = false
  downloadError.value = ''
  try { update.value = await desktop.checkUpdate() }
  finally { checking.value = false }
}

async function startDownload() {
  if (!update.value?.downloadUrl) {
    downloadError.value = '未找到可下载的安装包'
    return
  }
  downloading.value = true
  downloadError.value = ''
  downloadPercent.value = 0
  downloadedBytes.value = 0
  downloadTotal.value = update.value.downloadSize || 0

  // Listen for progress
  unsubProgress = desktop.onDownloadProgress((p: any) => {
    downloadPercent.value = p.percent
    downloadedBytes.value = p.downloaded
    if (p.total) downloadTotal.value = p.total
  })

  try {
    const result = await desktop.downloadUpdate(update.value.downloadUrl)
    if (result.ok) {
      downloadPath.value = result.path
      downloaded.value = true
      downloading.value = false
      ElMessage.success('下载完成，点击"安装更新"开始升级')
    } else {
      downloadError.value = result.error || '下载失败'
      downloading.value = false
    }
  } catch (e: any) {
    downloadError.value = e.message || '下载失败'
    downloading.value = false
  } finally {
    if (unsubProgress) { unsubProgress(); unsubProgress = null }
  }
}

function cancelDownload() {
  desktop.cancelDownload?.()
  downloading.value = false
  downloadPercent.value = 0
  if (unsubProgress) { unsubProgress(); unsubProgress = null }
}

async function installUpdate() {
  if (!downloadPath.value) {
    ElMessage.warning('请先下载更新')
    return
  }
  const result = await desktop.installUpdate(downloadPath.value)
  if (!result.ok) {
    ElMessage.warning('打开安装文件失败：' + (result.error || '未知错误'))
  }
}

function formatSize(bytes: number): string {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

onUnmounted(() => {
  if (unsubProgress) unsubProgress()
})

onMounted(async () => {
  if (isDesktop) {
    try { Object.assign(info, await desktop.getInfo()) } catch {}
  }
})
</script>

<style scoped>
.about-hero { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
.about-logo { width: 44px; height: 44px; border-radius: 10px; flex-shrink: 0; object-fit: contain; }
.about-name { font-size: 17px; font-weight: 650; }
.about-tag { font-size: 12px; color: var(--m-text-secondary); margin-top: 3px; }

.about-card { border: 1px solid var(--m-border); border-radius: var(--m-radius-lg); padding: 16px; background: var(--m-surface); margin-bottom: 12px; }
.about-row { display: flex; align-items: center; justify-content: space-between; }
.row-title { font-size: 12px; color: var(--m-text-tertiary); }
.row-val { font-size: 16px; font-weight: 600; margin-top: 2px; }
.update-result { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--m-border); font-size: 13px; }
.update-available { display: flex; flex-direction: column; gap: 10px; }
.update-actions { display: flex; align-items: center; gap: 8px; }
.release-notes {
  max-height: 120px; overflow-y: auto;
  background: var(--m-surface-variant);
  border-radius: 6px; padding: 10px 12px;
  font-size: 12px; white-space: pre-wrap; word-break: break-all;
  color: var(--m-text-secondary); line-height: 1.5;
  border: 1px solid var(--m-border);
}
.update-link { color: var(--m-running); font-size: 13px; }
.download-progress { margin-top: 4px; }
.progress-bar {
  height: 6px; background: var(--m-border);
  border-radius: 3px; overflow: hidden;
}
.progress-fill {
  height: 100%; background: var(--m-primary);
  border-radius: 3px; transition: width .2s;
}
.progress-text { font-size: 11px; color: var(--m-text-tertiary); margin-top: 4px; display: block; }

.card-title { font-size: 12px; font-weight: 650; color: var(--m-text-secondary); margin-bottom: 12px; }
.info-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px 24px; }
.info-item { display: flex; justify-content: space-between; align-items: center; font-size: 13px; padding-bottom: 8px; border-bottom: 1px solid var(--m-border); }
.info-item .k { color: var(--m-text-secondary); }
.info-item .v { font-weight: 500; }
</style>
