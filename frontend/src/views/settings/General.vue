<template>
  <div class="page">
    <div class="page-head"><span class="page-title">通用</span></div>
    <div class="set-rows">
      <div class="set-row">
        <div class="set-row-main">
          <div class="set-row-title">数据目录(重要数据)</div>
          <div class="set-row-desc mono">{{ dataDir || '~/.h3c-agent' }}</div>
        </div>
        <el-button v-if="isDesktop" size="small" @click="openData">打开</el-button>
      </div>
      <div class="set-row">
        <div class="set-row-main">
          <div class="set-row-title">运行环境</div>
          <div class="set-row-desc">{{ isDesktop ? '桌面客户端 · ' + platform : '浏览器' }}</div>
        </div>
      </div>
    </div>

    <!-- MinerU 文档解析配置 -->
    <div class="section">
      <div class="section-head">
        <div class="section-title">文档解析 (MinerU)</div>
        <div class="section-desc">
          上传 PDF / Word / PPT / 图片等文件时，使用 MinerU 云服务进行高质量解析。
          请前往
          <a href="https://mineru.net" target="_blank" rel="noopener">mineru.net</a>
          注册并申请 API Token，填入下方。未配置时将退回本地基础解析（仅支持纯文本 / PDF / DOCX / XLSX / PPTX）。
        </div>
      </div>
      <div v-loading="mineruLoading" class="mineru-card">
        <el-form label-position="top" class="mineru-form">
          <el-form-item label="解析模式">
            <el-radio-group v-model="mineru.mode">
              <el-radio value="cloud">云端解析（推荐）</el-radio>
              <el-radio value="disabled">禁用（仅用本地解析）</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="API Base URL">
            <el-input v-model="mineru.base_url" placeholder="https://mineru.net" :disabled="mineru.mode === 'disabled'" />
          </el-form-item>
          <el-form-item label="API Token">
            <el-input
              v-model="mineru.api_key"
              type="password"
              show-password
              placeholder="粘贴你的 MinerU API Token"
              :disabled="mineru.mode === 'disabled'"
            />
          </el-form-item>
          <el-form-item label="解析超时（秒）">
            <el-input-number v-model="mineru.timeout_sec" :min="30" :max="300" :step="10" :disabled="mineru.mode === 'disabled'" />
          </el-form-item>
        </el-form>
        <div class="mineru-actions">
          <el-button type="primary" :loading="mineruSaving" @click="saveMineru">保存配置</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api'

const isDesktop = typeof window !== 'undefined' && (window as any).desktop?.isDesktop === true
const platform = isDesktop ? (window as any).desktop.platform : 'web'
const dataDir = ref('')
onMounted(async () => { if (isDesktop) dataDir.value = await (window as any).desktop.getDataDir().catch(() => '') })
function openData() { if (dataDir.value && (window as any).desktop) (window as any).desktop.openPath(dataDir.value) }

// ── MinerU settings ──
const mineru = reactive({ mode: 'cloud', base_url: 'https://mineru.net', api_key: '', timeout_sec: 60 })
const mineruLoading = ref(false)
const mineruSaving = ref(false)

onMounted(async () => {
  mineruLoading.value = true
  try {
    const s = await api.getMineruSettings()
    Object.assign(mineru, s)
  } catch { /* defaults are fine */ }
  finally { mineruLoading.value = false }
})

async function saveMineru() {
  mineruSaving.value = true
  try {
    const s = await api.saveMineruSettings({
      mode: mineru.mode,
      base_url: mineru.base_url,
      api_key: mineru.api_key,
      timeout_sec: mineru.timeout_sec,
    })
    Object.assign(mineru, s)
    ElMessage.success('MinerU 配置已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    mineruSaving.value = false
  }
}
</script>

<style scoped>
.set-rows { display: flex; flex-direction: column; border: 1px solid var(--m-border); border-radius: var(--m-radius-lg); overflow: hidden; }
.set-row { display: flex; align-items: center; gap: 16px; padding: 14px 16px; border-bottom: 1px solid var(--m-border); background: var(--m-surface); }
.set-row:last-child { border-bottom: none; }
.set-row-main { flex: 1; min-width: 0; }
.set-row-title { font-size: 13px; font-weight: 600; }
.set-row-desc { font-size: 12px; color: var(--m-text-secondary); margin-top: 3px; word-break: break-all; }

.section { margin-top: 32px; }
.section-head { margin-bottom: 16px; }
.section-title { font-size: 16px; font-weight: 700; color: var(--m-text); margin-bottom: 6px; }
.section-desc { font-size: 13px; color: var(--m-text-secondary); line-height: 1.6; }
.section-desc a { color: var(--m-primary); text-decoration: none; }
.section-desc a:hover { text-decoration: underline; }

.mineru-card {
  border: 1px solid var(--m-border);
  border-radius: var(--m-radius-lg);
  background: var(--m-surface);
  padding: 20px 24px;
}
.mineru-form { max-width: 520px; }
.mineru-form :deep(.el-form-item__label) { font-size: 13px; font-weight: 600; padding-bottom: 4px; }
.mineru-actions { margin-top: 8px; }
</style>
