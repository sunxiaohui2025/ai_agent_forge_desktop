<template>
  <div class="page">
    <div class="page-head"><span class="page-title">执行引擎</span></div>

    <p class="lead">
      执行引擎决定「谁来驱动智能体的每一轮对话」。这里选择的是<b>默认执行引擎</b>——
      所有智能体默认跟随它；你也可以在下方为单个智能体单独指定其它引擎。
      <br />
      <b>执行时的引擎优先级：</b>单个智能体的单独指定 ＞ 默认执行引擎 ＞ 按模型 provider 自动推断。
      即：某智能体单独指定过引擎，就用它自己的；显示「跟随默认」的才用默认引擎。
      切换引擎不影响已配置的模型、插件与 MCP，它们会被所选引擎复用。
      内置引擎随应用打包、始终可用；命令行引擎需本机安装对应 CLI（可点「安装」自动装）。
    </p>

    <div class="section-title">默认执行引擎</div>
    <el-radio-group :model-value="selected" class="eng-grid" @change="onPick">
      <label
        v-for="e in engines"
        :key="e.name"
        :class="['eng-item', { active: selected === e.name, disabled: !e.available }]"
      >
        <el-radio :value="e.name" :disabled="!e.available" class="eng-radio">
          <span class="sr-only">{{ e.label }}</span>
        </el-radio>
        <div class="eng-body">
          <div class="eng-line1">
            <span class="eng-label">{{ e.label }}</span>
            <el-tag :type="e.available ? 'success' : 'info'" size="small" effect="light">
              {{ e.available ? '可用' : (e.out_of_process ? '未安装' : '不可用') }}
            </el-tag>
            <el-tag v-if="e.name === current" type="warning" size="small" effect="light">默认</el-tag>
          </div>
          <div class="eng-name mono">{{ e.name }}</div>
          <div v-if="e.capabilities?.notes" class="eng-notes">{{ e.capabilities.notes }}</div>
          <div class="eng-caps">
            <span v-for="c in capsOf(e)" :key="c.key" :class="['cap', c.on ? 'on' : 'off']">
              {{ c.on ? '✓' : '—' }} {{ c.label }}
            </span>
          </div>
          <div v-if="!e.available" class="eng-install">
            <div class="eng-install-hint">
              未检测到 <code>{{ e.required_binary }}</code>，安装后自动可用。
            </div>
            <div class="eng-install-actions">
              <el-button
                v-if="e.can_auto_install"
                type="primary" size="small" plain
                :loading="installing[e.name]"
                @click.prevent="install(e)"
              >
                {{ installing[e.name] ? '安装中…' : '一键安装' }}
              </el-button>
              <el-button v-if="e.install_url" link type="primary" size="small" @click.prevent="openUrl(e.install_url)">
                安装文档
              </el-button>
            </div>
            <code v-if="e.install_hint" class="cmd">{{ e.install_hint }}</code>
          </div>
        </div>
      </label>
    </el-radio-group>

    <div class="footer-bar">
      <span class="footer-hint">当前默认引擎：<b>{{ currentLabel }}</b></span>
      <el-button type="primary" :loading="saving" :disabled="selected === current" @click="applyDefault">
        设为默认引擎
      </el-button>
    </div>

    <!-- Per-agent overrides -->
    <div class="section-title agents-title">按智能体单独指定（可选）</div>
    <div class="default-banner">
      <el-icon :size="16"><SetUp /></el-icon>
      <span>当前默认执行引擎：<b>{{ currentLabel }}</b></span>
      <span class="banner-hint">未单独指定的智能体都跟随它</span>
    </div>
    <p class="sub-lead">如需让某个智能体使用不同引擎，在此单独设置；也可用下方下拉一键批量应用到全部智能体。</p>
    <div class="bulk-bar">
      <span class="bulk-label">一键批量设置：</span>
      <el-select
        v-model="bulkChoice"
        size="default" style="width: 240px"
        placeholder="选择要批量应用的引擎"
      >
        <el-option label="全部跟随默认引擎" value="" />
        <el-option
          v-for="e in engines" :key="e.name"
          :label="e.label" :value="e.name" :disabled="!e.available"
        />
      </el-select>
      <el-button type="primary" plain :loading="bulkSaving" @click="applyBulk">
        应用到全部智能体
      </el-button>
    </div>
    <div class="set-rows">
      <div v-for="a in agents" :key="a.id" class="set-row">
        <div class="set-row-body">
          <div class="set-row-title">{{ a.name }}</div>
          <div class="set-row-desc">
            <span class="mono">{{ a.code }}</span>
            <span class="dot">·</span>
            <span>实际生效：{{ effectiveLabel(a) }}</span>
          </div>
        </div>
        <el-select
          :model-value="a.engine_kind || ''"
          size="default" style="width: 240px"
          :loading="rowSaving[a.id]"
          @change="(v: string) => onRowChange(a, v)"
        >
          <el-option label="跟随默认引擎" value="" />
          <el-option
            v-for="e in engines" :key="e.name"
            :label="e.label" :value="e.name" :disabled="!e.available"
          />
        </el-select>
      </div>
      <div v-if="!agents.length" class="set-row"><span class="set-row-desc">还没有配置任何智能体。</span></div>
    </div>
  </div>
</template>


<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'

interface EngineCaps {
  native_skills?: boolean; native_mcp?: boolean; permission_gating?: boolean
  thinking_budget?: boolean; workspace_fs?: boolean; out_of_process?: boolean
  notes?: string
}
interface EngineItem {
  name: string; label: string; available: boolean; out_of_process?: boolean
  required_binary?: string; install_hint?: string; install_url?: string
  install_manager?: string; can_auto_install?: boolean
  capabilities: EngineCaps
}
interface AgentRow {
  id: number; code: string; name: string
  engine_kind: string | null; default_model_id: number | null
}

const engines = ref<EngineItem[]>([])
const agents = ref<AgentRow[]>([])
const models = ref<any[]>([])
const current = ref('')        // app-wide default engine (from backend)
const selected = ref('')       // user's current radio pick
const saving = ref(false)
const installing = ref<Record<string, boolean>>({})
const rowSaving = ref<Record<number, boolean>>({})
const bulkChoice = ref('')     // engine to bulk-apply to all agents ('' = follow default)
const bulkSaving = ref(false)

const CAP_DEFS: { key: keyof EngineCaps; label: string }[] = [
  { key: 'native_skills', label: '原生 Skills' },
  { key: 'native_mcp', label: '原生 MCP' },
  { key: 'permission_gating', label: '权限门控' },
  { key: 'thinking_budget', label: '思考预算' },
  { key: 'workspace_fs', label: '工作区文件' },
  { key: 'out_of_process', label: '独立进程' },
]
function capsOf(e: EngineItem) {
  const c = e.capabilities || {}
  return CAP_DEFS.map((d) => ({ key: d.key, label: d.label, on: !!c[d.key] }))
}

function labelOf(name: string): string {
  return engines.value.find((e) => e.name === name)?.label || (name || '自动')
}
const currentLabel = computed(() => (current.value ? labelOf(current.value) : '自动（按模型 provider 推断）'))

// Mirror the backend's provider → engine inference so the "auto" hint matches
// what will actually run when neither a per-agent override nor a default is set.
const PROVIDER_DEFAULT: Record<string, string> = { anthropic: 'claude-agent-sdk' }
const FALLBACK = 'openai-compat'
function effectiveLabel(a: AgentRow): string {
  // Priority mirrors registry.resolve_name: per-agent → default → provider → fallback
  if (a.engine_kind) return labelOf(a.engine_kind)
  if (current.value) return `跟随默认 → ${labelOf(current.value)}`
  const m = models.value.find((x) => x.id === a.default_model_id)
  const provider = (m?.provider || '').toLowerCase()
  return `自动 → ${labelOf(PROVIDER_DEFAULT[provider] || FALLBACK)}`
}

function onPick(v: string) { selected.value = v }
function openUrl(url: string) { window.open(url, '_blank') }

async function load() {
  const [engRes, agentRes, modelRes] = await Promise.all([
    api.agentEngines(),
    api.agents(),
    api.models().catch(() => []),
  ])
  engines.value = engRes?.engines || []
  current.value = engRes?.current || ''
  selected.value = current.value
  agents.value = agentRes || []
  models.value = modelRes || []
}

async function applyDefault() {
  const target = engines.value.find((e) => e.name === selected.value)
  if (target && !target.available) {
    ElMessage.warning(`「${target.label}」在本机不可用，请先安装其命令行`)
    return
  }
  const label = selected.value ? labelOf(selected.value) : '自动（按模型 provider 推断）'
  try {
    await ElMessageBox.confirm(
      `确定切换默认执行引擎为「${label}」吗？\n\n确认后将同时把全部智能体一键切换为该默认引擎（清除各智能体的单独指定）。之后你仍可为单个智能体单独指定其它引擎。`,
      '切换默认执行引擎',
      { confirmButtonText: '确认切换并应用到全部', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  saving.value = true
  try {
    // 1) set app-wide default
    const r = await api.setGlobalEngine(selected.value || null)
    current.value = r?.engine || ''
    selected.value = current.value
    // 2) one-click apply to ALL agents (clear per-agent overrides → follow default)
    await api.bulkSetAgentEngine(null)
    agents.value.forEach((a) => { a.engine_kind = null })
    ElMessage.success(`默认执行引擎已设为「${currentLabel.value}」，全部智能体已切换为跟随默认`)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '设置失败')
  } finally {
    saving.value = false
  }
}

async function onRowChange(a: AgentRow, value: string) {
  rowSaving.value = { ...rowSaving.value, [a.id]: true }
  try {
    const updated = await api.setAgentEngine(a.id, value || null)
    a.engine_kind = updated?.engine_kind ?? (value || null)
    ElMessage.success(value
      ? `「${a.name}」已单独设为「${labelOf(value)}」`
      : `「${a.name}」已恢复为跟随默认引擎`)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '设置失败')
  } finally {
    rowSaving.value = { ...rowSaving.value, [a.id]: false }
  }
}

async function applyBulk() {
  const target = engines.value.find((e) => e.name === bulkChoice.value)
  if (target && !target.available) {
    ElMessage.warning(`「${target.label}」在本机不可用，请先安装其命令行`)
    return
  }
  const label = bulkChoice.value ? labelOf(bulkChoice.value) : '跟随默认引擎'
  try {
    await ElMessageBox.confirm(
      `确定把全部智能体设为「${label}」吗？此操作会覆盖每个智能体当前的单独设置。`,
      '批量设置执行引擎',
      { confirmButtonText: '确定应用', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  bulkSaving.value = true
  try {
    const r = await api.bulkSetAgentEngine(bulkChoice.value || null)
    const applied = bulkChoice.value || null
    agents.value.forEach((a) => { a.engine_kind = applied })
    ElMessage.success(`已将 ${r?.agents_updated ?? agents.value.length} 个智能体设为「${label}」`)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '批量设置失败')
  } finally {
    bulkSaving.value = false
  }
}

async function install(e: EngineItem) {
  try {
    await ElMessageBox.confirm(
      `将通过 npm 全局安装「${e.label}」（${e.install_hint || e.name}）。安装可能需要 1–3 分钟，确定继续吗？`,
      '安装执行引擎',
      { confirmButtonText: '开始安装', cancelButtonText: '取消', type: 'info' },
    )
  } catch { return }
  installing.value = { ...installing.value, [e.name]: true }
  try {
    const r = await api.installEngine(e.name)
    ElMessage.success(r?.message || `「${e.label}」安装成功`)
    await load()  // refresh availability
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '安装失败，请查看安装文档手动安装')
  } finally {
    installing.value = { ...installing.value, [e.name]: false }
  }
}

onMounted(load)
</script>

<style scoped>
.lead { color: #8a8a84; font-size: 13px; line-height: 1.7; margin: 0 0 24px; max-width: 820px; }
.lead b { color: #272724; font-weight: 650; }
.sub-lead { color: #8a8a84; font-size: 12px; line-height: 1.6; margin: 0 0 12px; }

.section-title { font-size: 13px; font-weight: 700; color: #272724; margin: 0 0 12px; }
.agents-title { margin-top: 40px; }

/* Two engine cards per row */
.eng-grid {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px; width: 100%;
}
.eng-item {
  display: flex; align-items: flex-start; gap: 12px; margin: 0;
  border: 1px solid #eeeeeb; border-radius: 16px; background: #fff;
  padding: 16px 18px; cursor: pointer; transition: border-color .12s, box-shadow .12s;
}
.eng-item:hover { border-color: #ddddd8; }
.eng-item.active { border-color: var(--m-primary); box-shadow: 0 0 0 1px var(--m-primary) inset; }
.eng-item.disabled { cursor: not-allowed; background: #fafaf8; }
.eng-radio { margin-top: 1px; height: 20px; }
.eng-radio :deep(.el-radio__label) { display: none; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

.eng-body { flex: 1; min-width: 0; }
.eng-line1 { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.eng-label { font-size: 14px; font-weight: 650; color: #20201e; }
.eng-name { font-size: 12px; color: #989891; margin-top: 2px; }
.eng-notes { color: #8a8a84; font-size: 12px; line-height: 1.55; margin: 8px 0 0; }
.eng-caps { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.cap { font-size: 11px; padding: 3px 8px; border-radius: 999px; }
.cap.on { background: #eaf5ee; color: #2c8a52; }
.cap.off { background: #f4f4f2; color: #a9a9a2; }

.eng-install {
  margin-top: 12px; padding: 10px 12px; border-radius: 12px;
  background: #f7f6f3; font-size: 12px; color: #8a8a84;
}
.eng-install-hint { line-height: 1.5; }
.eng-install-hint code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: #6a6a63; }
.eng-install-actions { display: flex; align-items: center; gap: 8px; margin: 8px 0; }
.eng-install .cmd {
  display: inline-block; background: #ecebe7; padding: 3px 8px;
  border-radius: 8px; color: #4a4a45;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.footer-bar {
  position: sticky; bottom: 0; margin-top: 24px;
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 0 4px; background: linear-gradient(to top, #fff 60%, transparent);
}
.footer-hint { font-size: 13px; color: #8a8a84; }
.footer-hint b { color: #272724; }

/* Per-agent override list */
.default-banner {
  display: flex; align-items: center; gap: 8px;
  margin: 0 0 10px; padding: 10px 14px;
  border: 1px solid #e6efe9; border-radius: 12px;
  background: #f2f9f5; color: #2c6a48; font-size: 13px;
}
.default-banner b { color: #1f5637; font-weight: 700; }
.banner-hint { color: #8a9d92; font-size: 12px; margin-left: 2px; }
.bulk-bar {
  display: flex; align-items: center; gap: 10px;
  margin: 0 0 12px; padding: 12px 14px;
  border: 1px solid #eeeeeb; border-radius: 14px; background: #fbfaf9;
}
.bulk-label { font-size: 13px; color: #676761; font-weight: 600; }
.set-rows { border: 1px solid #eeeeeb; border-radius: 16px; background: #fff; overflow: hidden; }
.set-row {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 16px 18px; border-bottom: 1px solid #f1f1ee;
}
.set-row:last-child { border-bottom: 0; }
.set-row-body { min-width: 0; }
.set-row-title { font-size: 14px; font-weight: 650; color: #272724; }
.set-row-desc { font-size: 12px; color: #8a8a84; margin-top: 3px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.dot { color: #ccc; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

@media (max-width: 900px) {
  .eng-grid { grid-template-columns: 1fr; }
}
</style>


