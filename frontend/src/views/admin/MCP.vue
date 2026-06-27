<template>
  <div class="page">
    <div class="page-head">
      <div>
        <span class="page-title">MCP</span>
        <span class="page-count">{{ filteredRows.length }}</span>
      </div>
      <el-button type="primary" @click="openCreate"><el-icon><Plus /></el-icon>新建连接</el-button>
    </div>
    <div class="mcp-toolbar">
      <el-input v-model="keyword" clearable placeholder="搜索 MCP..." />
    </div>
    <div class="mcp-grid">
      <article v-for="row in filteredRows" :key="row.id" class="mcp-card" @click="openTools(row)">
        <div class="mcp-card-head">
          <div class="mcp-icon">{{ fallbackInitial(row.name) }}</div>
          <div class="mcp-main">
            <div class="mcp-name" :title="row.name">{{ row.name }}</div>
            <div class="mcp-url" :title="summarize(row)">{{ summarize(row) || '未配置连接信息' }}</div>
          </div>
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '停用' }}</el-tag>
        </div>
        <p class="mcp-summary">{{ row.user_summary || '暂无使用说明。点击查看工具或编辑连接配置。' }}</p>
        <div class="mcp-meta-row">
          <div class="meta-tags">
            <span class="meta-tag">{{ row.transport }}</span>
            <span class="meta-tag">{{ statusLabel(row) }}</span>
            <span v-if="statuses[row.id + '_count']" class="meta-tag">{{ statuses[row.id + '_count'] }} 个工具</span>
          </div>
          <div class="mcp-actions" @click.stop>
            <button @click="openTools(row)">查看工具</button>
            <button @click="testConnect(row)">{{ statuses[row.id] === 'loading' ? '连接中…' : '测试连接' }}</button>
            <button @click="openEdit(row)">编辑</button>
            <button @click="onResummarize(row)">重新说明</button>
            <button class="danger" @click="onDelete(row)">删除</button>
          </div>
        </div>
      </article>
      <button v-if="!filteredRows.length" class="empty-mcp" @click="openCreate">
        <span class="empty-icon">{{ keyword ? 'M' : '+' }}</span>
        <span class="empty-title">{{ keyword ? '没有找到匹配连接' : '还没有 MCP 连接' }}</span>
        <span class="empty-desc">{{ keyword ? '换个关键词试试，或创建一个新的 MCP 服务。' : '连接外部工具服务，让专家可以读取、检索或调用更多能力。' }}</span>
        <span class="empty-action">{{ keyword ? '新建连接' : '新建第一个连接' }}</span>
      </button>
    </div>

    <!-- Create / edit dialog -->
    <el-dialog v-model="visible" :title="editing ? '编辑 MCP 连接' : '新建 MCP 连接'" width="640px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="例如 filesystem" />
        </el-form-item>
        <el-form-item label="协议">
          <el-radio-group v-model="form.transport" @change="onTransportChange">
            <el-radio-button value="stdio">stdio</el-radio-button>
            <el-radio-button value="sse">sse</el-radio-button>
            <el-radio-button value="http">http</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <!-- stdio fields -->
        <template v-if="form.transport === 'stdio'">
          <el-form-item label="命令">
            <el-input v-model="form.config_json.command" placeholder="如 npx" />
          </el-form-item>
          <el-form-item label="参数">
            <el-input v-model="argsText" placeholder='JSON 数组,如 ["@modelcontextprotocol/server-filesystem","/tmp"]' />
          </el-form-item>
          <el-form-item label="环境变量">
            <el-input v-model="envText" type="textarea" :rows="3" placeholder='JSON 对象,如 {"API_KEY":"xxx"}' />
          </el-form-item>
        </template>

        <!-- sse / http fields -->
        <template v-else>
          <el-form-item label="URL">
            <el-input v-model="form.config_json.url" :placeholder="form.transport === 'sse' ? 'https://server.com/sse' : 'https://server.com/mcp'" />
          </el-form-item>
          <el-form-item label="请求头">
            <el-input v-model="headersText" type="textarea" :rows="3" placeholder='JSON 对象,如 {"Authorization":"Bearer xxx"}' />
          </el-form-item>
        </template>

        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>

    <!-- Tools drawer -->
    <el-drawer v-model="toolsVisible" :size="640" direction="rtl" :title="drawerTitle" :with-header="true">
      <div v-if="toolsLoading" style="text-align:center;padding:40px;color:var(--m-text-secondary)">
        <el-icon class="is-loading" :size="28"><Loading /></el-icon>
        <div style="margin-top:8px">连接中...</div>
      </div>
      <div v-else-if="toolsError" style="padding:20px">
        <el-alert :title="toolsError" type="error" :closable="false" show-icon />
      </div>
      <div v-else-if="toolsData">
        <div class="server-card">
          <div class="server-name">{{ toolsData.server.name }}</div>
          <div v-if="toolsData.server.version" class="muted" style="font-size:12px">v{{ toolsData.server.version }}</div>
          <div class="muted" style="margin-top:8px">共 {{ toolsData.tools.length }} 个工具</div>
        </div>
        <div v-for="(t, i) in toolsData.tools" :key="i" class="tool-card">
          <div class="tool-head">
            <el-icon style="color:var(--m-primary)"><Tools /></el-icon>
            <div class="tool-name mono">{{ t.name }}</div>
          </div>
          <div v-if="t.description" class="tool-desc">{{ t.description }}</div>
          <details v-if="t.input_schema && Object.keys(t.input_schema).length" class="tool-schema">
            <summary>输入参数</summary>
            <pre>{{ JSON.stringify(t.input_schema, null, 2) }}</pre>
          </details>
        </div>
        <div v-if="!toolsData.tools.length" style="padding:20px;color:var(--m-text-secondary)">该服务器没有暴露任何工具</div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api'

const rows = ref<any[]>([])
const keyword = ref('')
const visible = ref(false)
const editing = ref<any | null>(null)
const form = reactive<any>({ name: '', transport: 'stdio', config_json: {}, enabled: true })
const argsText = ref('[]')
const envText = ref('{}')
const headersText = ref('{}')

const statuses = reactive<Record<string | number, any>>({})

// tools drawer
const toolsVisible = ref(false)
const toolsLoading = ref(false)
const toolsError = ref('')
const toolsData = ref<any>(null)
const currentRow = ref<any>(null)
const drawerTitle = computed(() => currentRow.value ? `${currentRow.value.name} · 工具列表` : '工具列表')

watch(visible, (v) => {
  if (!v) return
  argsText.value = JSON.stringify(form.config_json.args || [], null, 0)
  envText.value = JSON.stringify(form.config_json.env || {}, null, 2)
  headersText.value = JSON.stringify(form.config_json.headers || {}, null, 2)
})

async function load() { rows.value = await api.mcps() }
onMounted(load)

const filteredRows = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((row) => [
    row.name, row.transport, row.user_summary, summarize(row), statusLabel(row),
  ].some((v) => String(v || '').toLowerCase().includes(q)))
})

function summarize(row: any) {
  const c = row.config_json || {}
  if (row.transport === 'stdio') return `${c.command || '?'} ${(c.args || []).join(' ')}`.trim()
  return c.url || ''
}
function statusLabel(row: any) {
  const s = statuses[row.id]
  if (s === 'ok') return '已连接'
  if (s === 'fail') return '连接失败'
  if (s === 'loading') return '连接中'
  return '未测试'
}

function fallbackInitial(value: string) {
  const s = String(value || '').trim()
  return (Array.from(s)[0] || 'M').toUpperCase()
}

function openCreate() {
  editing.value = null
  Object.assign(form, { name: '', transport: 'stdio', config_json: {}, enabled: true })
  argsText.value = '[]'; envText.value = '{}'; headersText.value = '{}'
  visible.value = true
}
function openEdit(row: any) {
  editing.value = row
  Object.assign(form, JSON.parse(JSON.stringify(row)))
  visible.value = true
}
function onTransportChange() {
  form.config_json = {}
  argsText.value = '[]'; envText.value = '{}'; headersText.value = '{}'
}

async function onSubmit() {
  try {
    if (form.transport === 'stdio') {
      form.config_json.args = JSON.parse(argsText.value || '[]')
      form.config_json.env = JSON.parse(envText.value || '{}')
    } else {
      form.config_json.headers = JSON.parse(headersText.value || '{}')
    }
  } catch {
    ElMessage.error('JSON 格式错误'); return
  }
  if (editing.value) await api.updateMcp(editing.value.id, form)
  else await api.createMcp(form)
  visible.value = false
  ElMessage.success('保存成功')
  await load()
}

async function onDelete(row: any) {
  try { await ElMessageBox.confirm(`删除 ${row.name}?`, '确认', { type: 'warning' }); await api.deleteMcp(row.id); await load() } catch {}
}

async function onResummarize(row: any) {
  try {
    await api.resummarizeMcp(row.id)
    ElMessage.success('已触发重新生成,稍后刷新列表查看')
    setTimeout(() => { load() }, 6000)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '触发失败')
  }
}

async function testConnect(row: any) {
  statuses[row.id] = 'loading'
  try {
    const r = await api.pingMcp(row.id)
    statuses[row.id] = 'ok'
    statuses[row.id + '_count'] = r.tools_count
    ElMessage.success(`连接成功: ${r.server?.name} · ${r.tools_count} 个工具`)
  } catch {
    statuses[row.id] = 'fail'
  }
}

async function openTools(row: any) {
  currentRow.value = row
  toolsVisible.value = true
  toolsLoading.value = true
  toolsError.value = ''
  toolsData.value = null
  try {
    toolsData.value = await api.mcpTools(row.id)
    statuses[row.id] = 'ok'
    statuses[row.id + '_count'] = toolsData.value.tools.length
  } catch (e: any) {
    toolsError.value = e.response?.data?.detail || e.message || '连接失败'
    statuses[row.id] = 'fail'
  } finally {
    toolsLoading.value = false
  }
}
</script>

<style scoped>
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-head > div:first-child { display: flex; align-items: baseline; gap: 10px; }
.page-count { color: #8a8a84; font-size: 13px; font-weight: 650; }
.mcp-toolbar {
  max-width: 420px;
  margin: -10px 0 18px;
}
.mcp-toolbar :deep(.el-input__wrapper) {
  border-radius: 999px;
  box-shadow: none;
  background: #f5f5f2;
  padding: 0 14px;
}
.mcp-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.mcp-card {
  min-height: 190px;
  padding: 18px;
  border: 1px solid #eeeeeb;
  border-radius: 18px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 12px;
  cursor: pointer;
}
.mcp-card:hover { background: #fff; border-color: #d8d8d4; }
.mcp-card-head { display: flex; align-items: center; gap: 12px; min-width: 0; }
.mcp-main { flex: 1; min-width: 0; }
.mcp-name { font-size: 15px; font-weight: 760; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mcp-url { margin-top: 3px; color: #8a8a84; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mcp-summary {
  margin: 0;
  color: #777770;
  font-size: 13px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.mcp-meta-row {
  display: flex; align-items: center;
  justify-content: space-between;
  margin-top: auto;
}
.meta-tags { display: flex; align-items: center; gap: 6px; }
.meta-tag {
  padding: 4px 8px; border-radius: 999px;
  background: #f6f6f3; color: #777770;
  font-size: 12px;
}
.mcp-actions {
  display: flex; gap: 4px;
  opacity: 0; transition: opacity .15s;
}
.mcp-card:hover .mcp-actions { opacity: 1; }
.mcp-actions button {
  border: 0; background: #f1f1ef; color: #30302d;
  border-radius: 999px; min-height: 30px; padding: 0 12px;
  cursor: pointer; font-size: 12px; font-weight: 650;
}
.mcp-actions button:hover { background: #e5e5e2; }
.mcp-actions .danger { color: #b5392f; background: #f8ebe9; }
.mcp-actions .danger:hover { background: #f2dcd9; }
.empty-mcp {
  border: 1px dashed #e6e6e2;
  background: #fafaf8; color: #56554e;
  border-radius: 16px; padding: 16px;
  cursor: pointer; font-size: 12px; font-weight: 650;
  min-height: 126px;
  width: min(360px, 100%);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  text-align: left;
  gap: 5px;
}
.empty-mcp:hover {
  background: #f6f6f3;
  border-color: #ddddda;
}
.empty-icon {
  width: 30px;
  height: 30px;
  border-radius: 10px;
  background: #eeeeeb;
  color: #777770;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 760;
  margin-bottom: 3px;
}
.empty-title { font-size: 13px; font-weight: 760; color: #3f3f3b; }
.empty-desc { font-size: 12px; color: #8a8a84; line-height: 1.45; max-width: 290px; }
.empty-action { margin-top: 4px; font-size: 12px; font-weight: 700; color: #56554e; }
.row-sub {
  font-size: 12px;
  color: var(--m-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row-actions {
  display: flex; align-items: center; gap: 2px;
  flex-wrap: nowrap;
}
.row-actions :deep(.el-button + .el-button) { margin-left: 0; }
.row-actions :deep(.el-button) { padding: 4px 6px; }
.row-actions :deep(.el-button.is-circle) { padding: 5px; }
.muted { color: var(--m-text-tertiary); font-size: 12px; }
.mcp-icon {
  width: 36px; height: 36px; border-radius: 10px;
  background: #f2f2ef; color: #56554e;
  display: flex; align-items: center; justify-content: center;
  font-size: 15px;
  font-weight: 760;
  flex-shrink: 0;
}

.server-card {
  padding: 16px 20px;
  border-bottom: 1px solid var(--m-border);
  margin-bottom: 8px;
}
.server-name { font-size: 16px; font-weight: 600; }

.tool-card {
  margin: 12px 16px;
  padding: 14px 16px;
  background: var(--m-surface);
  border: 1px solid var(--m-border);
  border-radius: var(--m-radius);
  transition: box-shadow .15s, border-color .15s;
}
.tool-card:hover { box-shadow: var(--m-shadow-1); border-color: var(--m-border-strong); }
.tool-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.tool-name { font-size: 14px; font-weight: 600; color: var(--m-text); }
.tool-desc { font-size: 13px; color: var(--m-text-secondary); line-height: 1.6; }
.tool-schema { margin-top: 10px; font-size: 12px; }
.tool-schema summary {
  cursor: pointer; color: var(--m-primary); font-weight: 500;
  padding: 4px 0;
}
.tool-schema pre {
  background: #f8f9fa; padding: 12px; border-radius: 8px;
  font-family: 'Roboto Mono', monospace; font-size: 12px;
  overflow: auto; max-height: 320px; margin: 8px 0 0;
}

.is-loading { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .mcp-grid { grid-template-columns: 1fr; } }
</style>
