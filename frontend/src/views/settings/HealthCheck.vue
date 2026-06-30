<template>
  <div class="page">
    <div class="page-head">
      <span class="page-title">健康检查</span>
      <el-button :loading="loading" round @click="run">
        <el-icon style="margin-right:6px"><Refresh /></el-icon>重新检查
      </el-button>
    </div>

    <p class="hc-lead">自动体检模型连通性与专家智能体配置，帮助你快速发现并修复异常。</p>

    <!-- 1. 模型服务 -->
    <div class="hc-item" :class="modelTone">
      <div class="hc-body">
        <div class="hc-title-row">
          <span class="hc-name">模型服务</span>
          <el-tag v-if="!loading && report" :type="modelTagType" size="small" effect="light" round>
            {{ modelTagText }}
          </el-tag>
        </div>
        <div class="hc-sub">
          <template v-if="loading">正在检测各模型连通性…</template>
          <template v-else-if="report">
            已配置 {{ report.models.providers }} 个 provider，共 {{ report.models.total }} 个模型 ·
            <span class="ok-text">正常 {{ report.models.ok }}</span> ·
            <span :class="report.models.abnormal ? 'err-text' : 'muted-text'">异常 {{ report.models.abnormal }}</span>
          </template>
        </div>
        <!-- per-model breakdown -->
        <div v-if="!loading && report && report.models.items.length" class="hc-detail">
          <div v-for="m in report.models.items" :key="m.id" class="hc-line">
            <span class="dot" :class="m.ok ? 'dot-ok' : 'dot-err'"></span>
            <span class="hc-line-name">{{ m.code }}</span>
            <span class="hc-line-meta">{{ m.provider }} · {{ m.model_id }}</span>
            <span class="hc-line-status" :class="m.ok ? 'ok-text' : 'err-text'">
              {{ m.ok ? '连通正常' : (m.error || '异常') }}
            </span>
          </div>
        </div>
      </div>
      <div class="hc-action">
        <el-button class="hc-link-btn" round @click="goModels">
          模型管理<el-icon style="margin-left:2px"><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- 2. 专家智能体检查 -->
    <div class="hc-item" :class="agentTone">
      <div class="hc-body">
        <div class="hc-title-row">
          <span class="hc-name">专家智能体</span>
          <el-tag v-if="!loading && report" :type="agentTagType" size="small" effect="light" round>
            {{ agentTagText }}
          </el-tag>
        </div>
        <div class="hc-sub">
          <template v-if="loading">正在检测专家模型配置…</template>
          <template v-else-if="report">
            共 {{ report.agents.total }} 个专家 ·
            <span class="ok-text">正常 {{ report.agents.ok }}</span> ·
            <span :class="report.agents.abnormal ? 'err-text' : 'muted-text'">异常 {{ report.agents.abnormal }}</span>
            <span v-if="report.agents.abnormal && !report.agents.has_healthy_model" class="err-text">
              （暂无可用模型，无法自动修复）</span>
          </template>
        </div>
        <div v-if="!loading && report && report.agents.items.length" class="hc-detail">
          <div v-for="a in report.agents.items" :key="a.id" class="hc-line">
            <span class="dot" :class="a.status === 'ok' ? 'dot-ok' : 'dot-err'"></span>
            <span class="hc-line-name">{{ a.name }}<span v-if="a.is_default" class="badge-default">默认</span></span>
            <span class="hc-line-meta">{{ a.model_code || '未绑定模型' }}</span>
            <span class="hc-line-status" :class="a.status === 'ok' ? 'ok-text' : 'err-text'">
              {{ a.status === 'ok' ? '配置正常' : a.reason }}
            </span>
          </div>
        </div>
      </div>
      <div class="hc-action">
        <el-button
          v-if="!loading && report && report.agents.abnormal"
          class="hc-fix-btn"
          round
          :disabled="!report.agents.has_healthy_model"
          :loading="fixing"
          @click="fix"
        >
          一键修复
        </el-button>
        <el-button v-else class="hc-link-btn" round @click="goExperts">
          专家管理<el-icon style="margin-left:2px"><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/api'

const router = useRouter()
const loading = ref(false)
const fixing = ref(false)
const report = ref<any>(null)

async function run() {
  loading.value = true
  try {
    report.value = await api.healthCheck()
  } catch {
    ElMessage.error('检查失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

async function fix() {
  fixing.value = true
  try {
    const r = await api.fixAgentModels()
    if (r.ok) {
      ElMessage.success(`已为 ${r.fixed} 个专家替换为可用模型「${r.model_code}」`)
      await run()
    } else {
      ElMessage.warning(r.reason || '无法修复')
    }
  } catch {
    ElMessage.error('修复失败，请稍后重试')
  } finally {
    fixing.value = false
  }
}

function goModels() { router.push('/settings/models') }
function goExperts() { router.push('/experts') }

const modelTone = computed(() => {
  if (loading.value || !report.value) return ''
  return report.value.models.abnormal ? 'tone-err' : 'tone-ok'
})
const agentTone = computed(() => {
  if (loading.value || !report.value) return ''
  return report.value.agents.abnormal ? 'tone-err' : 'tone-ok'
})
const modelTagType = computed(() => (report.value?.models.abnormal ? 'danger' : 'success'))
const modelTagText = computed(() => (report.value?.models.abnormal ? '存在异常' : '全部正常'))
const agentTagType = computed(() => (report.value?.agents.abnormal ? 'danger' : 'success'))
const agentTagText = computed(() => (report.value?.agents.abnormal ? '存在异常' : '全部正常'))

onMounted(run)
</script>

<style scoped>
.hc-lead { color: #8a8a84; font-size: 13px; margin: -8px 0 22px; }

.hc-item {
  display: flex; gap: 16px; align-items: flex-start;
  padding: 20px; margin-bottom: 16px;
  border: 1px solid #eeeeeb; border-radius: 16px; background: #fff;
}
.hc-item.tone-ok { border-color: #d6ecd8; }
.hc-item.tone-err { border-color: #f3d6d6; }

.hc-ico {
  width: 40px; height: 40px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  border-radius: 12px; background: #f4f4f1; color: #5a5a54;
}
.tone-ok .hc-ico { background: #ecf7ed; color: #2e9e44; }
.tone-err .hc-ico { background: #fcecec; color: #d05050; }

.hc-body { flex: 1; min-width: 0; }
.hc-title-row { display: flex; align-items: center; gap: 10px; }
.hc-name { font-size: 15px; font-weight: 700; color: #272724; }
.hc-sub { margin-top: 5px; font-size: 13px; color: #8a8a84; }

.ok-text { color: #2e9e44; }
.err-text { color: #d05050; }
.muted-text { color: #a8a8a2; }

.hc-detail {
  margin-top: 14px; padding-top: 12px;
  border-top: 1px dashed #eee; display: flex; flex-direction: column; gap: 9px;
}
.hc-line { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot-ok { background: #2e9e44; }
.dot-err { background: #d05050; }
.hc-line-name { font-weight: 600; color: #3a3a36; min-width: 130px; }
.badge-default {
  margin-left: 6px; font-size: 11px; font-weight: 500; color: #8a8a84;
  background: #f0f0ec; border-radius: 6px; padding: 1px 6px;
}
.hc-line-meta { color: #a8a8a2; flex: 1; min-width: 0; }
.hc-line-status { flex-shrink: 0; }

.hc-action { flex-shrink: 0; align-self: flex-start; }

/* White, clean action buttons (no solid black/primary fill). */
.hc-link-btn,
.hc-fix-btn {
  height: 32px;
  background: #fff;
  border: 1px solid #e2e2dd;
  color: #3a3a36;
}
.hc-link-btn:hover,
.hc-fix-btn:hover {
  background: #fafaf8;
  border-color: #d0d0c9;
  color: #20201e;
}
.hc-link-btn :deep(.el-icon) { color: #9a9a93; }
.hc-fix-btn:not(.is-disabled) { border-color: #f0cccc; color: #c24a4a; }
.hc-fix-btn:not(.is-disabled):hover { background: #fcf4f4; border-color: #e6b8b8; color: #b03e3e; }
</style>
