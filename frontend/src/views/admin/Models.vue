<template>
  <div class="page">
    <div class="page-head"><span class="page-title">模型管理</span>
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建模型</el-button>
    </div>
    <div class="model-grid">
      <article v-for="row in rows" :key="row.id" class="model-card">
        <div class="model-card-head">
          <div class="model-icon">{{ (row.code || row.model_id || '?').slice(0, 1).toUpperCase() }}</div>
          <div class="model-main">
            <div class="model-code">{{ row.code || row.model_id }}</div>
            <div class="model-id mono">{{ row.model_id }}</div>
          </div>
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '停用' }}</el-tag>
        </div>
        <div class="model-meta">
          <span>{{ providerLabel(row.provider) }}</span>
          <span>{{ row.has_api_key ? 'API Key 已配置' : '未配置 API Key' }}</span>
          <span>Max {{ row.max_tokens || 8192 }}</span>
        </div>
        <div class="model-actions">
          <button @click="onTest(row)" :disabled="testing[row.id]">{{ testing[row.id] ? '测试中…' : '测试' }}</button>
          <button @click="openEdit(row)">编辑</button>
          <button class="danger" @click="onDelete(row)">删除</button>
        </div>
      </article>
      <button v-if="!rows.length" class="empty-card" @click="openCreate">添加第一个模型</button>
    </div>

    <el-dialog v-model="testVisible" title="模型测试" width="640px">
      <div v-if="testResult">
        <div class="qa-block">
          <div class="qa-label">问题</div>
          <div class="qa-content">{{ testResult.question }}</div>
        </div>
        <div class="qa-block answer">
          <div class="qa-label">回答</div>
          <div class="qa-content">{{ testResult.answer }}</div>
        </div>
        <div class="qa-stats">
          <span>输入 {{ testResult.tokens_in }} tokens</span>
          <span>输出 {{ testResult.tokens_out }} tokens</span>
        </div>
      </div>
      <template #footer><el-button @click="testVisible = false">关闭</el-button></template>
    </el-dialog>

    <!-- Step 1: pick a vendor preset -->
    <el-dialog v-model="presetVisible" title="选择模型厂商" width="720px">
      <div v-for="g in presetGroups" :key="g" class="preset-group">
        <div class="preset-group-title">{{ g }}</div>
        <div class="preset-grid">
          <div
            v-for="p in presetsByGroup[g]" :key="p.key"
            class="preset-card" @click="choosePreset(p)"
          >
            <div class="preset-name">{{ p.name }}</div>
            <div class="preset-proto">{{ p.protocol === 'anthropic' ? 'Anthropic 协议' : 'OpenAI 兼容' }}</div>
          </div>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="visible" :title="editing ? '编辑模型' : `配置 ${form._presetName || '模型'}`" width="640px">
      <el-form :model="form" label-width="100px">
        <el-form-item v-if="form._note" label=" ">
          <el-alert :title="form._note" type="info" :closable="false" />
        </el-form-item>
        <el-form-item label="协议">
          <el-radio-group v-model="form.provider">
            <el-radio-button label="anthropic">Anthropic</el-radio-button>
            <el-radio-button label="openai-compatible">OpenAI 兼容</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="编码"><el-input v-model="form.code" placeholder="自定义,如 glm-prod" /></el-form-item>
        <el-form-item label="模型ID">
          <el-input v-model="form.model_id" :placeholder="modelIdSuggestions[0] || '模型 ID'">
            <template v-if="modelIdSuggestions.length" #append>
              <el-dropdown trigger="click" @command="form.model_id = $event">
                <el-button text>常用 ▾</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-for="m in modelIdSuggestions" :key="m" :command="m">{{ m }}</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="留空使用默认" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" :placeholder="editing ? '留空则不改' : '从供应商控制台获取'" show-password />
          <a v-if="form._apiKeyUrl" :href="form._apiKeyUrl" target="_blank"
             style="font-size:12px;color:var(--m-primary);margin-top:4px">获取 API Key →</a>
        </el-form-item>
        <el-form-item label="Max Tokens"><el-input-number v-model="form.max_tokens" :min="1024" :max="200000" :step="1024" /></el-form-item>

        <el-form-item label="高级参数">
          <div style="display:flex;gap:6px;margin-bottom:6px;flex-wrap:wrap">
            <el-button size="small" @click="applyPreset('disable_thinking')">关闭思考</el-button>
            <el-button size="small" @click="applyPreset('enable_thinking')">开启思考</el-button>
            <el-button size="small" @click="extraText = '{}'">清空</el-button>
          </div>
          <el-input v-model="extraText" type="textarea" :rows="4"
                    placeholder='额外参数 JSON,作为 extra_body 透传给模型 API。例如关闭思考: {"enable_thinking": false}' />
        </el-form-item>

        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted, reactive, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'

const rows = ref<any[]>([])
const presets = ref<any[]>([])
const visible = ref(false)
const presetVisible = ref(false)
const editing = ref<any | null>(null)
const form = reactive<any>(emptyForm())
const extraText = ref('{}')

function emptyForm() {
  return {
    code: '', provider: 'openai-compatible', model_id: '', base_url: '',
    api_key: '', max_tokens: 50000, enabled: true, extra_params: { enable_thinking: false },
    _presetName: '', _note: '', _apiKeyUrl: '', _models: [] as string[],
  }
}

// Presets grouped by their `group` field (国内 / 国际 / 自部署).
const presetGroups = computed(() => {
  const seen: string[] = []
  for (const p of presets.value) if (!seen.includes(p.group)) seen.push(p.group)
  return seen
})
const presetsByGroup = computed(() => {
  const m: Record<string, any[]> = {}
  for (const p of presets.value) (m[p.group] ||= []).push(p)
  return m
})
const modelIdSuggestions = computed<string[]>(() => form._models || [])

const DISABLE_THINKING_PRESETS: Record<string, any> = {
  anthropic: { thinking: { type: 'disabled' } },
  'openai-compatible': { enable_thinking: false },
}
const ENABLE_THINKING_PRESETS: Record<string, any> = {
  anthropic: { thinking: { type: 'enabled' } },
  'openai-compatible': { enable_thinking: true },
}
function applyPreset(kind: 'disable_thinking' | 'enable_thinking') {
  const map = kind === 'disable_thinking' ? DISABLE_THINKING_PRESETS : ENABLE_THINKING_PRESETS
  extraText.value = JSON.stringify(map[form.provider] || {}, null, 2)
}

function providerLabel(v: string) {
  return v === 'anthropic' ? 'Anthropic' : 'OpenAI 兼容'
}
function providerTagType(v: string) {
  return v === 'anthropic' ? 'warning' : 'primary'
}

async function load() { rows.value = await api.models() }
onMounted(async () => {
  await load()
  try { presets.value = await api.modelPresets() } catch { presets.value = [] }
})

// Step 1 → open the vendor picker.
function openCreate() {
  if (!presets.value.length) { editing.value = null; Object.assign(form, emptyForm()); extraText.value = '{\n  "enable_thinking": false\n}'; visible.value = true; return }
  presetVisible.value = true
}
// Step 2 → vendor chosen, pre-fill the form.
function choosePreset(p: any) {
  editing.value = null
  Object.assign(form, emptyForm(), {
    provider: p.protocol,
    base_url: p.base_url || '',
    model_id: (p.models && p.models[0]) || '',
    code: p.key,
    _presetName: p.name,
    _note: p.note || '',
    _apiKeyUrl: p.api_key_url || '',
    _models: p.models || [],
  })
  extraText.value = p.protocol === 'anthropic'
    ? '{\n  "thinking": { "type": "disabled" }\n}'
    : '{\n  "enable_thinking": false\n}'
  presetVisible.value = false
  visible.value = true
}
function openEdit(row: any) {
  editing.value = row
  Object.assign(form, emptyForm(), { ...row, api_key: '' })
  extraText.value = JSON.stringify(row.extra_params || {}, null, 2)
  visible.value = true
}

async function onSubmit() {
  if (!form.code || !form.model_id) { ElMessage.error('请填写编码和模型 ID'); return }
  let parsedExtra: any = {}
  try { parsedExtra = JSON.parse(extraText.value || '{}') }
  catch { ElMessage.error('高级参数 JSON 格式错误'); return }
  const payload: any = {
    code: form.code, provider: form.provider, model_id: form.model_id,
    base_url: form.base_url, max_tokens: form.max_tokens, enabled: form.enabled,
    api_key: form.api_key, extra_params: parsedExtra,
  }
  if (editing.value && !payload.api_key) delete payload.api_key
  if (editing.value) await api.updateModel(editing.value.id, payload)
  else await api.createModel(payload)
  visible.value = false
  ElMessage.success('保存成功')
  await load()
}
async function onDelete(row: any) {
  try { await ElMessageBox.confirm(`删除 ${row.code}?`, '确认', { type: 'warning' }); await api.deleteModel(row.id); await load() } catch {}
}

const testing = reactive<Record<number, boolean>>({})
const testVisible = ref(false)
const testResult = ref<any>(null)
async function onTest(row: any) {
  testing[row.id] = true
  try {
    testResult.value = await api.testModel(row.id)
    testVisible.value = true
  } finally { testing[row.id] = false }
}
</script>

<style scoped>
.model-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.model-card {
  min-height: 154px;
  padding: 18px;
  border: 1px solid #eeeeeb;
  border-radius: 18px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.model-card-head { display: flex; align-items: center; gap: 12px; min-width: 0; }
.model-icon {
  width: 42px; height: 42px; border-radius: 12px;
  background: #f1f1ef; color: #292926;
  display: flex; align-items: center; justify-content: center;
  font-weight: 760; font-size: 22px;
  flex-shrink: 0;
}
.model-main { flex: 1; min-width: 0; }
.model-code { font-size: 15px; font-weight: 760; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-id { margin-top: 3px; color: #8a8a84; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-meta { display: flex; flex-wrap: wrap; gap: 8px; color: #777770; font-size: 12px; }
.model-meta span { padding: 4px 8px; border-radius: 999px; background: #f6f6f3; }
.model-actions { display: flex; gap: 8px; margin-top: auto; }
.model-actions button {
  border: 0; background: #f1f1ef; color: #30302d;
  border-radius: 999px; height: 30px; padding: 0 12px;
  cursor: pointer; font-size: 12px; font-weight: 650;
}
.model-actions button:hover { background: #e5e5e2; }
.model-actions .danger { color: #b5392f; background: #f8ebe9; }
.empty-card {
  min-height: 154px;
  border-radius: 18px;
  width: 100%;
  border: 2px dashed #d0d0cc;
  background: #fff;
  color: #8a8a84;
  cursor: pointer;
  font-size: 14px; font-weight: 580;
  display: flex; align-items: center; justify-content: center;
  transition: all .2s;
}
.empty-card:hover { border-color: #30302d; color: #30302d; background: #fafaf8; }
.preset-group { margin-bottom: 16px; }
.preset-group-title {
  font-size: 12px; font-weight: 650; color: var(--m-text-secondary, #6b6b66);
  letter-spacing: .05em; margin-bottom: 8px;
}
.preset-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.preset-card {
  padding: 12px 14px; border: 1px solid var(--m-border, #e7e7e4); border-radius: 10px;
  cursor: pointer; transition: all .15s; background: var(--m-surface, #fff);
}
.preset-card:hover { border-color: #1c1c1a; background: var(--m-surface-variant, #f1f1ef); }
.preset-name { font-size: 13.5px; font-weight: 600; color: var(--m-text, #1c1c1a); }
.preset-proto { font-size: 11px; color: var(--m-text-tertiary, #9a9a93); margin-top: 3px; }

.qa-block { padding: 14px 16px; border-radius: var(--m-radius); background: var(--m-surface-variant); margin-bottom: 12px; }
.qa-block.answer { background: var(--m-primary-soft); }
.qa-label { font-size: 11px; font-weight: 600; color: var(--m-text-secondary); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }
.qa-content { font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; color: var(--m-text); }
.qa-stats { display: flex; gap: 16px; font-size: 12px; color: var(--m-text-secondary); margin-top: 8px; }
@media (max-width: 900px) { .model-grid { grid-template-columns: 1fr; } }
</style>
