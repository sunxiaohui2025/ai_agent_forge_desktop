<template>
  <div class="page">
    <div class="page-head">
      <div>
        <span class="page-title">连接应用</span>
        <span class="page-count">{{ filtered.length }}</span>
      </div>
      <el-button type="primary" @click="customVisible = true"><el-icon><Plus /></el-icon>自定义应用</el-button>
    </div>
    <div class="ca-toolbar">
      <el-input v-model="keyword" clearable placeholder="搜索应用..." />
      <el-radio-group v-model="filterMode" size="small">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="connected">已连接</el-radio-button>
        <el-radio-button value="installed">已安装</el-radio-button>
      </el-radio-group>
    </div>

    <div v-loading="loading" class="ca-grid">
      <article v-for="app in filtered" :key="app.app_key" class="ca-card">
        <div class="ca-card-head">
          <div class="ca-icon">{{ app.icon || '🧩' }}</div>
          <div class="ca-main">
            <div class="ca-name" :title="app.name">{{ app.name }}</div>
            <div class="ca-cats">
              <span v-for="c in app.categories" :key="c" class="ca-cat">{{ c }}</span>
              <span v-if="app.version" class="ca-ver">v{{ app.version }}</span>
            </div>
          </div>
          <el-tag :type="app.status === 'installed' ? 'success' : 'info'" size="small">
            {{ app.status === 'installed' ? '已安装' : '未安装' }}
          </el-tag>
        </div>
        <p class="ca-summary">{{ app.summary || '命令行应用' }}</p>
        <div v-if="app.example_prompts?.length" class="ca-examples">
          <span v-for="(p, i) in app.example_prompts.slice(0, 2)" :key="i" class="ca-example">"{{ p }}"</span>
        </div>
        <div class="ca-actions">
          <button v-if="!app.connected" @click="connect(app)">{{ busyKey === app.app_key ? '连接中…' : '连接' }}</button>
          <template v-else>
            <span class="ca-connected">✓ 已连接</span>
            <button v-if="app.status !== 'installed' && app.install_command"
                    @click="install(app)">{{ busyKey === app.app_key ? '安装中…' : '安装' }}</button>
            <button @click="detect(app)">检测</button>
            <button class="danger" @click="disconnect(app)">移除</button>
          </template>
          <a v-if="app.homepage" class="ca-link" :href="app.homepage" target="_blank" rel="noopener">主页</a>
        </div>
      </article>
      <div v-if="!loading && !filtered.length" class="ca-empty">没有匹配的应用</div>
    </div>

    <el-dialog v-model="customVisible" title="添加自定义应用" width="520px">
      <el-form :model="customForm" label-width="92px">
        <el-form-item label="名称"><el-input v-model="customForm.name" placeholder="例如 我的工具" /></el-form-item>
        <el-form-item label="命令名"><el-input v-model="customForm.bin_name" placeholder="终端里的可执行命令，如 mytool" /></el-form-item>
        <el-form-item label="图标"><el-input v-model="customForm.icon" placeholder="一个 Emoji，如 🧩" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="customForm.summary" type="textarea" :rows="2" placeholder="这个应用能做什么" /></el-form-item>
        <el-form-item label="安装命令"><el-input v-model="customForm.install_command" placeholder="可选，如 brew install mytool" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="customVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCustom">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { api } from '@/api'

interface AppItem {
  app_key: string; name: string; icon?: string; summary?: string
  bin_names?: string[]; install_command?: string; categories?: string[]
  homepage?: string; needs_auth?: boolean; example_prompts?: string[]
  status: string; version?: string | null; connected: boolean; cli_app_id?: number | null
}

const catalog = ref<AppItem[]>([])
const keyword = ref('')
const filterMode = ref<'all' | 'connected' | 'installed'>('all')
const loading = ref(false)
const busyKey = ref('')
const customVisible = ref(false)
const customForm = reactive({ name: '', bin_name: '', icon: '', summary: '', install_command: '' })

async function load() {
  loading.value = true
  try { catalog.value = await api.cliAppsCatalog() }
  finally { loading.value = false }
}
onMounted(load)

const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return catalog.value.filter((a) => {
    if (filterMode.value === 'connected' && !a.connected) return false
    if (filterMode.value === 'installed' && a.status !== 'installed') return false
    if (!q) return true
    return [a.name, a.summary, (a.categories || []).join(' '), a.app_key]
      .some((v) => String(v || '').toLowerCase().includes(q))
  })
})

async function connect(app: AppItem) {
  busyKey.value = app.app_key
  try {
    await api.connectCliApp(app.app_key)
    ElMessage.success('已连接 ' + app.name)
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '连接失败')
  } finally { busyKey.value = '' }
}

async function install(app: AppItem) {
  if (!app.cli_app_id) return
  busyKey.value = app.app_key
  try {
    const r = await api.installCliApp(app.cli_app_id)
    if (r.status === 'installed') ElMessage.success(app.name + ' 安装成功')
    else ElMessage.warning('安装命令已执行，但未检测到可执行文件，请检查输出')
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '安装失败')
  } finally { busyKey.value = '' }
}

async function detect(app: AppItem) {
  if (!app.cli_app_id) return
  try {
    const r = await api.detectCliApp(app.cli_app_id)
    ElMessage[r.status === 'installed' ? 'success' : 'info'](
      r.status === 'installed' ? ('已安装' + (r.version ? ' v' + r.version : '')) : '未检测到该应用')
    await load()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '检测失败') }
}

async function disconnect(app: AppItem) {
  if (!app.cli_app_id) return
  try {
    await ElMessageBox.confirm('移除 ' + app.name + '?', '确认', { type: 'warning' })
    await api.deleteCliApp(app.cli_app_id)
    await load()
  } catch {}
}

async function submitCustom() {
  if (!customForm.name.trim() || !customForm.bin_name.trim()) {
    ElMessage.warning('请填写名称和命令名'); return
  }
  try {
    await api.addCustomCliApp({ ...customForm })
    ElMessage.success('已添加')
    customVisible.value = false
    Object.assign(customForm, { name: '', bin_name: '', icon: '', summary: '', install_command: '' })
    await load()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  }
}
</script>

<style scoped>
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-head > div:first-child { display: flex; align-items: baseline; gap: 10px; }
.page-count { color: #8a8a84; font-size: 13px; font-weight: 650; }
.ca-toolbar { display: flex; align-items: center; gap: 14px; margin: -6px 0 18px; }
.ca-toolbar :deep(.el-input) { max-width: 360px; }
.ca-toolbar :deep(.el-input__wrapper) { border-radius: 999px; box-shadow: none; background: #f5f5f2; padding: 0 14px; }
.ca-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.ca-card {
  min-height: 180px; padding: 18px; border: 1px solid #eeeeeb; border-radius: 18px;
  background: #fff; display: flex; flex-direction: column; gap: 10px;
}
.ca-card:hover { box-shadow: 0 16px 36px -34px rgba(0,0,0,.35); }
.ca-card-head { display: flex; align-items: center; gap: 12px; min-width: 0; }
.ca-icon {
  width: 40px; height: 40px; border-radius: 11px; background: #f1f1ef;
  display: flex; align-items: center; justify-content: center; font-size: 20px; flex-shrink: 0;
}
.ca-main { flex: 1; min-width: 0; }
.ca-name { font-size: 15px; font-weight: 760; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ca-cats { margin-top: 3px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.ca-cat { font-size: 11px; color: #8a8a84; background: #f6f6f3; padding: 2px 7px; border-radius: 999px; }
.ca-ver { font-size: 11px; color: #2f8f4e; }
.ca-summary {
  margin: 0; color: #777770; font-size: 13px; line-height: 1.55;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.ca-examples { display: flex; flex-direction: column; gap: 2px; }
.ca-example { font-size: 12px; color: #9a9a93; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ca-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: auto; }
.ca-actions button {
  border: 0; background: #f1f1ef; color: #30302d; border-radius: 999px;
  min-height: 30px; padding: 0 14px; cursor: pointer; font-size: 12px; font-weight: 650;
}
.ca-actions button:hover { background: #e5e5e2; }
.ca-actions .danger { color: #b5392f; background: #f8ebe9; }
.ca-connected { font-size: 12px; color: #2f8f4e; font-weight: 650; }
.ca-link { font-size: 12px; color: #1a73e8; text-decoration: none; margin-left: auto; }
.ca-link:hover { text-decoration: underline; }
.ca-empty { grid-column: 1 / -1; text-align: center; color: #9a9a93; padding: 48px 0; }
@media (max-width: 900px) { .ca-grid { grid-template-columns: 1fr; } }
</style>
