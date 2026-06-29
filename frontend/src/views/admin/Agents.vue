<template>
  <div class="page">
    <div class="page-head"><span class="page-title">专家管理</span>
      <el-button type="primary" @click="openCreate">新建专家</el-button>
    </div>
    <div class="agent-grid">
      <article v-for="row in rows" :key="row.id" class="agent-card">
        <div class="agent-head">
          <div class="agent-avatar">
            <img v-if="isImageIcon(row.icon)" :src="row.icon" alt="" />
            <span v-else>{{ iconText(row.icon || row.name || row.code) }}</span>
          </div>
          <div class="agent-main">
            <div class="agent-name">
              <span>{{ row.name }}</span>
              <el-tag v-if="row.is_default" type="primary" size="small" effect="light">默认</el-tag>
            </div>
            <div class="agent-code mono">{{ row.code }}</div>
          </div>
          <div class="agent-right">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '停用' }}</el-tag>
           
          </div>
        </div>
        <p class="agent-desc">{{ row.description || '暂无描述' }}</p>
        <div class="agent-meta">
          <span>模型 {{ row.default_model_id ? modelLabel(row.default_model_id) : '未配置' }}</span>
          <span>技能 {{ row.skill_ids?.length || 0 }}</span>
          <span>MCP {{ row.mcp_ids?.length || 0 }}</span>
          <div class="agent-actions">
              <button class="hover-only" @click="openCapabilities(row)"><el-icon :size="14"><InfoFilled /></el-icon> 技能能力</button>
              <button class="hover-only" @click="openEdit(row)">编辑</button>
              <button class="hover-only danger" @click="onDelete(row)">删除</button>
            </div>
        </div>
         
      </article>
      <button v-if="!rows.length" class="empty-agent" @click="openCreate">新建第一个专家</button>
    </div>

    <el-dialog v-model="visible" :title="editing ? '编辑专家' : '新建专家'" width="760px">
      <el-form :model="form" label-width="120px">
        <el-form-item label="专家图标">
          <div class="icon-uploader">
            <div class="icon-preview">
              <img v-if="isImageIcon(form.icon)" :src="form.icon" alt="" />
              <span v-else>{{ iconText(form.icon || form.name || form.code || '专') }}</span>
            </div>
            <div class="icon-tools">
              <el-upload
                :show-file-list="false"
                :auto-upload="false"
                accept="image/*"
                :on-change="onIconPick"
              >
                <el-button>上传图标</el-button>
              </el-upload>
              <el-input v-model="form.icon" placeholder="也可以粘贴图片 URL；留空则使用名称首字" />
              <button v-if="form.icon" type="button" class="icon-clear" @click="form.icon = ''">清除</button>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="专家编码"><el-input v-model="form.code" placeholder="例如 xhs_writer / data_analyst" /></el-form-item>
        <el-form-item label="专家名称"><el-input v-model="form.name" placeholder="例如 小红书运营专家" /></el-form-item>
        <el-form-item label="专家介绍">
          <div class="polish-wrap">
            <el-input v-model="form.description" type="textarea" :rows="3"
                      placeholder="一句话介绍这位专家擅长什么；可点击右下角的「✨ AI 润色」生成简介 + 示例问题" />
            <button type="button" class="polish-btn"
                    :disabled="polishing.description"
                    @click="onPolish('description')">
              <span v-if="polishing.description">润色中…</span>
              <span v-else>✨ AI 润色</span>
            </button>
          </div>
        </el-form-item>
        <el-form-item label="专家设定">
          <div class="polish-wrap">
            <el-input v-model="form.system_prompt" type="textarea" :rows="4"
                      placeholder="定义这位专家的角色、工作方式、输出风格和边界；可点击右下角的「✨ AI 润色」帮你结构化" />
            <button type="button" class="polish-btn"
                    :disabled="polishing.system_prompt"
                    @click="onPolish('system_prompt')">
              <span v-if="polishing.system_prompt">润色中…</span>
              <span v-else>✨ AI 润色</span>
            </button>
          </div>
        </el-form-item>
        <el-form-item label="首选模型">
          <el-select v-model="form.default_model_id" clearable>
            <el-option v-for="m in models" :key="m.id" :label="m.code" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="备用模型">
          <el-select v-model="form.fallback_model_id" clearable>
            <el-option v-for="m in models" :key="m.id" :label="m.code" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="任务轮次上限">
          <el-input-number v-model="form.max_turns" :min="1" :max="100" :step="1" controls-position="right" />
          <span style="margin-left:8px;font-size:12px;color:var(--m-text-secondary)">轮 · 专家一次任务中允许的工具调用循环上限,默认 15</span>
        </el-form-item>
        <el-form-item label="思考深度">
          <el-select v-model="form.effort" style="width:220px">
            <el-option label="low — 轻量推理,响应快" value="low" />
            <el-option label="medium — 平衡推理（默认）" value="medium" />
            <el-option label="high — 深入分析,适合重构/调试" value="high" />
            <el-option label="xhigh — 扩展推理深度（推荐 Opus 4.7）" value="xhigh" />
            <el-option label="max — 最大推理深度,多步骤问题" value="max" />
          </el-select>
        </el-form-item>
        <el-form-item label="工作目录">
          <div class="workdir-row">
            <el-input v-model="form.work_dir" clearable
                      placeholder="留空 = 不绑定本地目录；调用时优先级低于用户在对话框中选择的目录" />
            <el-button v-if="isDesktop" @click="pickWorkDir">选择目录</el-button>
          </div>
          <div style="margin-top:4px;font-size:12px;color:var(--m-text-secondary)">
            配置后,调用该专家时默认在此目录工作；若用户在首页对话框重新选择了工作目录,则以用户选择为准；都没有则不绑定本地目录。
          </div>
        </el-form-item>
        <el-divider style="margin:20px 0 12px"><span style="font-size:12px;color:var(--m-text-secondary)">专家能力</span></el-divider>
        <el-form-item label="可用技能">
          <el-select v-model="form.skill_ids" multiple style="width:100%">
            <el-option v-for="s in skills" :key="s.id" :label="`${s.code} (${s.type})`" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="连接器">
          <el-select v-model="form.mcp_ids" multiple style="width:100%">
            <el-option v-for="m in mcps" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="连接应用">
          <el-select v-model="form.cli_app_ids" multiple style="width:100%"
                     placeholder="选择该专家可调用的命令行应用">
            <el-option v-for="c in cliApps" :key="c.id"
                       :label="`${c.icon || '🧩'} ${c.name}${c.status === 'installed' ? '' : '（未安装）'}`"
                       :value="c.id" />
          </el-select>
          <div style="margin-top:4px;font-size:12px;color:var(--m-text-secondary)">
            在「插件 → 连接应用」里连接应用后可在此多选；用户问题触发时专家会自动调用对应 CLI
          </div>
        </el-form-item>
        <el-divider style="margin:20px 0 12px"><span style="font-size:12px;color:var(--m-text-secondary)">专家处理文件规则</span></el-divider>
        <el-form-item label="允许扩展名">
          <el-input v-model="extText" placeholder="逗号分隔,如: pdf,docx,png. 留空=不限" />
        </el-form-item>
        <el-form-item label="单文件大小">
          <el-input-number v-model="maxSizeMb" :min="0" :max="500" :step="5" controls-position="right" />
          <span style="margin-left:8px;font-size:12px;color:var(--m-text-secondary)">MB · 0 表示用全局默认</span>
        </el-form-item>
        <el-form-item label="单次文件上限">
          <el-input-number v-model="maxFilesPerSend" :min="0" :max="50" :step="1" controls-position="right" />
          <span style="margin-left:8px;font-size:12px;color:var(--m-text-secondary)">个 · 一次发送最多带几个文件,0 表示不限</span>
        </el-form-item>
        <el-form-item label="文件读取方式">
          <el-radio-group v-model="parseMode">
            <el-radio value="auto">自动解析(默认)</el-radio>
            <el-radio value="never">不解析,原始文件直传工具</el-radio>
          </el-radio-group>
          <div style="margin-top:4px;font-size:12px;color:var(--m-text-secondary)">
            选"不解析"时,上传的文件不做文本提取,后端会在 Prompt 里给出本地路径和短期签名 URL,供 skill / MCP 工具按需读取原始文件
          </div>
        </el-form-item>
        <el-form-item label="读取内容上限">
          <el-input-number
            v-model="form.parsed_content_limit"
            :min="0"
            :max="2000000"
            :step="5000"
            controls-position="right"
            placeholder="留空 = 全局默认"
            style="width:220px"
          />
          <span style="margin-left:8px;font-size:12px;color:var(--m-text-secondary)">
            字符 · 留空使用全局默认(20000),<b>0 表示不截断</b>(全文喂模型,谨慎)
          </span>
        </el-form-item>
        <el-form-item label="默认专家">
          <el-switch v-model="form.is_default" />
          <span style="margin-left:12px;font-size:12px;color:var(--m-text-secondary)">勾选后将取消其它专家的默认状态。新用户首次进入对话会自动使用默认专家。</span>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>

    <AgentCapabilityDrawer
      v-model="capVisible"
      :agent-id="capAgentId"
      :agent-name="capAgentName"
    />
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import { api } from '@/api'
import AgentCapabilityDrawer from '@/components/AgentCapabilityDrawer.vue'

// View an expert's skills / MCP / model via the shared capability drawer
// (same component the chat header uses).
const capVisible = ref(false)
const capAgentId = ref<number | null>(null)
const capAgentName = ref<string>('')
function openCapabilities(row: any) {
  capAgentId.value = row.id
  capAgentName.value = row.name
  capVisible.value = true
}

const rows = ref<any[]>([])
const models = ref<any[]>([])
const skills = ref<any[]>([])
const mcps = ref<any[]>([])
const packs = ref<any[]>([])
const roles = ref<any[]>([])
const cliApps = ref<any[]>([])
const visible = ref(false)
const editing = ref<any | null>(null)
const form = reactive<any>(emptyForm())
const extText = ref('')
const maxSizeMb = ref<number>(0)
const maxFilesPerSend = ref<number>(0)
const parseMode = ref<'auto' | 'never'>('auto')
const polishing = reactive({ description: false, system_prompt: false })

const isDesktop = typeof window !== 'undefined' && (window as any).desktop?.isDesktop === true
async function pickWorkDir() {
  const dir = await (window as any).desktop?.openFolder?.({ title: '选择专家工作目录' })
  if (dir) form.work_dir = dir
}

async function onPolish(kind: 'description' | 'system_prompt') {
  if (polishing[kind]) return
  polishing[kind] = true
  try {
    const r = await api.polishAgentText({
      kind,
      text: (form as any)[kind] || '',
      agent_name: form.name || undefined,
      model_id: form.default_model_id || undefined,
    })
    if (r?.text) {
      ;(form as any)[kind] = r.text
      ElMessage.success('已润色')
    } else {
      ElMessage.warning('润色返回为空')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '润色失败')
  } finally {
    polishing[kind] = false
  }
}

function emptyForm() {
  return {
    code: '', name: '', description: '', icon: '', system_prompt: '',
    default_model_id: null, fallback_model_id: null,
    upload_policy_json: {}, max_turns: 50, effort: 'medium',
    parsed_content_limit: null, work_dir: '',
    enabled: true, is_default: false,
    skill_ids: [], mcp_ids: [], pack_ids: [], role_ids: [], cli_app_ids: [],
  }
}

async function load() {
  ;[rows.value, models.value, skills.value, mcps.value, packs.value, roles.value, cliApps.value] = await Promise.all([
    api.agents(), api.models(), api.skills(), api.mcps(), api.packs(), api.roles(), api.cliApps(),
  ])
}
onMounted(load)

function modelLabel(id: number) {
  const m = models.value.find((x: any) => x.id === id)
  return m ? (m.code || m.model_id || `#${id}`) : `#${id}`
}

function iconText(value: string) {
  const s = String(value || '').trim()
  return (Array.from(s)[0] || '专').toUpperCase()
}
function isImageIcon(icon: string | null | undefined) {
  const s = String(icon || '').trim()
  return /^data:image\//i.test(s) || /^https?:\/\//i.test(s) || s.startsWith('/')
}
async function onIconPick(uploadFile: any) {
  const file: File | undefined = uploadFile?.raw
  if (!file) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请选择图片文件')
    return
  }
  if (file.size > 512 * 1024) {
    ElMessage.warning('图标建议小于 512KB')
    return
  }
  form.icon = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function openCreate() {
  editing.value = null
  Object.assign(form, emptyForm())
  extText.value = ''
  maxSizeMb.value = 5
  maxFilesPerSend.value = 5
  parseMode.value = 'auto'
  visible.value = true
}
function openEdit(row: any) {
  editing.value = row
  Object.assign(form, emptyForm(), JSON.parse(JSON.stringify(row)))
  if (form.max_turns == null) form.max_turns = 100
  if (!form.effort) form.effort = 'medium'
  const policy = row.upload_policy_json || {}
  extText.value = (policy.allowed_ext || []).join(',')
  maxSizeMb.value = Number(policy.max_size_mb || 0)
  // Backwards-compat: read legacy max_files_per_conv if present
  maxFilesPerSend.value = Number(policy.max_files_per_send || policy.max_files_per_conv || 0)
  parseMode.value = (policy.parse_mode === 'never') ? 'never' : 'auto'
  visible.value = true
}
async function onSubmit() {
  const ext = extText.value.split(',').map(s => s.trim()).filter(Boolean)
  const policy: any = {}
  if (ext.length) policy.allowed_ext = ext
  if (maxSizeMb.value > 0) policy.max_size_mb = maxSizeMb.value
  if (maxFilesPerSend.value > 0) policy.max_files_per_send = maxFilesPerSend.value
  if (parseMode.value === 'never') policy.parse_mode = 'never'
  form.upload_policy_json = policy
  if (editing.value) await api.updateAgent(editing.value.id, form)
  else await api.createAgent(form)
  visible.value = false
  ElMessage.success('保存成功')
  await load()
}
async function onDelete(row: any) {
  try { await ElMessageBox.confirm(`删除 ${row.code}?`, '确认', { type: 'warning' }); await api.deleteAgent(row.id); await load() } catch {}
}
</script>

<style scoped>
.muted { color: var(--m-text-tertiary); }

.workdir-row { display: flex; gap: 8px; width: 100%; }
.workdir-row .el-input { flex: 1; }

.agent-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.agent-card {
  min-height: 156px;
  padding: 16px;
  border: 1px solid #eeeeeb;
  border-radius: 18px;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.agent-card:hover { box-shadow: 0 16px 36px -34px rgba(0,0,0,.35); border-color: #e6e6e2; }
.agent-head { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
.agent-avatar {
  width: 42px; height: 42px; border-radius: 12px;
  background: #f2f2ef; color: #56554e;
  display: flex; align-items: center; justify-content: center;
  font-weight: 760;
  font-size: 17px;
  flex-shrink: 0;
  overflow: hidden;
}
.agent-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.agent-main { flex: 1; min-width: 0; }
.agent-name { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 760; min-width: 0; }
.agent-name span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-code { margin-top: 3px; color: #8a8a84; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.agent-desc {
  margin: 0;
  color: #777770;
  font-size: 13px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.agent-meta { display: flex; flex-wrap: wrap; gap: 8px; color: #777770; font-size: 12px; }
.agent-meta span { padding: 4px 8px; border-radius: 999px; background: #f6f6f3; }
.agent-actions {
  display: flex;
  flex-wrap:right;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.agent-actions button,
.empty-agent {
  display: inline-flex; align-items: center; justify-content: center; gap: 4px;
  border: 0; background: #f1f1ef; color: #30302d;
  border-radius: 999px; min-height: 30px; padding: 0 12px;
  cursor: pointer; font-size: 12px; font-weight: 650;
}
.agent-actions button:hover,
.empty-agent:hover { background: #e5e5e2; }
.agent-actions .always {
  background: #f6f6f3;
  color: #56554e;
}
.agent-actions .hover-only {
  opacity: 0;
  transform: translateX(4px);
  pointer-events: none;
  transition: opacity .14s ease, transform .14s ease, background .14s ease;
}
.agent-card:hover .agent-actions .hover-only {
  opacity: 1;
  transform: translateX(0);
  pointer-events: auto;
}
.agent-actions .danger { color: #b5392f; background: #f8ebe9; }
.empty-agent { min-height: 182px; border-radius: 18px; width: 100%; }

.icon-uploader {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 14px;
}
.icon-preview {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: #f2f2ef;
  color: #56554e;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 760;
  overflow: hidden;
  flex-shrink: 0;
}
.icon-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.icon-tools {
  flex: 1;
  display: grid;
  grid-template-columns: auto minmax(220px, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.icon-clear {
  height: 32px;
  border: 0;
  border-radius: 9px;
  background: #f1f1ef;
  color: #777770;
  padding: 0 10px;
  cursor: pointer;
}
.icon-clear:hover { background: #e5e5e2; color: #30302d; }

/* AI polish — button sits in the bottom-right corner of the textarea */
.polish-wrap { position: relative; width: 100%; }
.polish-btn {
  position: absolute;
  right: 8px; bottom: 8px;
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid #dadce0;
  background: rgba(255, 255, 255, 0.95);
  color: #1a73e8;
  cursor: pointer;
  font-weight: 500;
  letter-spacing: 0.01em;
  transition: background .15s, border-color .15s, box-shadow .15s;
  z-index: 2;
  user-select: none;
}
.polish-btn:hover:not(:disabled) {
  background: #e8f0fe;
  border-color: #aecbfa;
  box-shadow: 0 1px 2px rgba(60,64,67,.1);
}
.polish-btn:disabled { color: #80868b; cursor: progress; }
.polish-wrap :deep(.el-textarea__inner) { padding-bottom: 36px; }
@media (max-width: 900px) { .agent-grid { grid-template-columns: 1fr; } }
</style>
