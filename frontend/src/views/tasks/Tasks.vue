<template>
  <div class="page">
    <div class="page-head">
      <span class="page-title">自动化</span>
      <el-button type="primary" :icon="Plus" @click="openCreateChoice">新建任务</el-button>
    </div>

    <div v-loading="loading" class="task-grid">
      <article v-for="row in rows" :key="row.id" class="task-card">
        <div class="task-head">
          <div class="task-icon">
            <el-icon :size="18"><Clock /></el-icon>
          </div>
          <div class="task-main">
            <div class="task-name">
              <span>{{ row.name }}</span>
              <el-tag v-if="!row.enabled" size="small" type="info">已停用</el-tag>
            </div>
            <div class="task-agent">{{ row.agent_name || `#${row.agent_id}` }}</div>
          </div>
          <div class="task-right">
            <el-switch :model-value="row.enabled" @change="onToggle(row)" />
            <el-dropdown trigger="click" placement="bottom-end" :teleported="false" popper-class="task-action-popper">
              <button class="task-menu" type="button" aria-label="更多操作">
                <el-icon :size="16"><MoreFilled /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu class="task-dropdown-menu">
                  <el-dropdown-item :disabled="runningId === row.id" @click="onRun(row)">
                    <span class="dropdown-item-inner">
                      <el-icon :size="15"><VideoPlay /></el-icon>
                      <span>{{ runningId === row.id ? '运行中...' : '运行' }}</span>
                    </span>
                  </el-dropdown-item>
                  <el-dropdown-item @click="$router.push(`/tasks/${row.id}/runs`)">
                    <span class="dropdown-item-inner">
                      <el-icon :size="15"><Clock /></el-icon>
                      <span>历史</span>
                    </span>
                  </el-dropdown-item>
                  <el-dropdown-item @click="openEdit(row)">
                    <span class="dropdown-item-inner">
                      <el-icon :size="15"><EditPen /></el-icon>
                      <span>编辑</span>
                    </span>
                  </el-dropdown-item>
                  <el-dropdown-item divided @click="onDelete(row)">
                    <span class="dropdown-item-inner danger">
                      <el-icon :size="15"><Delete /></el-icon>
                      <span>删除</span>
                    </span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
        <p class="task-desc">{{ row.description || '暂无描述' }}</p>
        <div class="task-meta">
          <span class="schedule-tag" :data-type="row.schedule_type">{{ scheduleLabel(row) }}</span>
          <span v-if="row.last_run_at" class="last-run">
            <span :class="['status-dot', row.last_run_status]"></span>
            {{ statusLabel(row.last_run_status) }} · {{ relTime(row.last_run_at) }}
          </span>
          <span v-else>未执行</span>
        </div>
      </article>
      <button v-if="!loading && !rows.length" class="empty-task" @click="openCreateChoice">
        <span class="empty-icon">+</span>
        <span class="empty-title">还没有自动化任务</span>
        <span class="empty-desc">把重复提醒、定时查询或固定工作流交给专家按时执行。</span>
        <span class="empty-action">新建第一个任务</span>
      </button>
    </div>

    <!-- New-task path chooser: 对话生成 vs 高级配置 -->
    <el-dialog v-model="choiceVisible" title="新建任务" width="640px">
      <div class="create-choices">
        <button class="create-choice" @click="chooseCustom">
          <div class="create-choice-icon">💬</div>
          <div class="create-choice-body">
            <div class="create-choice-title">对话创建（推荐）</div>
            <div class="create-choice-desc">
              用一句话描述你想自动化的事情、由哪个专家执行、多久跑一次，AI 会理解需求并自动创建任务。最简单、最快的方式。
            </div>
          </div>
          <el-tag size="small" type="primary" effect="light">推荐</el-tag>
        </button>
        <button class="create-choice" @click="chooseAdvanced">
          <div class="create-choice-icon">🛠️</div>
          <div class="create-choice-body">
            <div class="create-choice-title">高级配置（专业配置）</div>
            <div class="create-choice-desc">
              通过完整表单手动配置执行专家、提示词、调度（cron / 单次）、通知渠道、超时与并发等全部参数。适合需要精细控制的场景。
            </div>
          </div>
        </button>
      </div>
    </el-dialog>

    <el-dialog v-model="visible" :title="editing ? '编辑任务' : '新建任务'" width="720px" :close-on-click-modal="false">
      <el-form :model="form" label-width="120px">
        <el-form-item label="名称">
          <el-input v-model="form.name" maxlength="128" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
         <el-divider><span class="section-title">执行</span></el-divider>
        <el-form-item label="执行专家">
          <el-select v-model="form.agent_id" filterable style="width:100%">
            <el-option v-for="a in agents" :key="a.id" :label="a.name" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="提示词">
          <el-input v-model="form.prompt_text" type="textarea" :rows="6"
                    placeholder="任务执行时发送给专家的内容" />
        </el-form-item>

        <el-divider><span class="section-title">调度</span></el-divider>
        <el-form-item label="调度类型">
          <el-radio-group v-model="form.schedule_type">
            <el-radio-button value="manual">仅手动</el-radio-button>
            <el-radio-button value="once">单次定时</el-radio-button>
            <el-radio-button value="cron">周期 (cron)</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.schedule_type === 'cron'" label="cron 表达式">
          <el-input v-model="form.schedule_value" placeholder="如 0 9 * * 1-5（工作日 9:00）" />
          <div class="cron-hints">
            <a v-for="p in cronPresets" :key="p.expr" @click.prevent="form.schedule_value = p.expr">{{ p.label }}</a>
          </div>
        </el-form-item>
        <el-form-item v-else-if="form.schedule_type === 'once'" label="执行时间">
          <el-date-picker
            v-model="form.schedule_value" type="datetime"
            format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DDTHH:mm:ss"
            style="width:100%" placeholder="选择执行时间" />
        </el-form-item>
        <el-form-item label="时区">
          <el-input v-model="form.timezone" placeholder="Asia/Shanghai" />
        </el-form-item>

        <el-divider><span class="section-title">通知</span></el-divider>
        <el-form-item label="通知渠道">
          <el-checkbox-group v-model="form.notify_channels">
            <el-checkbox value="inapp">站内通知</el-checkbox>
            <el-checkbox value="feishu">飞书</el-checkbox>
            <!-- 邮件渠道暂时隐藏：<el-checkbox value="email">邮件</el-checkbox> -->
          </el-checkbox-group>
          <div v-if="form.notify_channels.includes('feishu')" class="muted small channel-hint">
            通过「设置 → 远程桥接」已配置的飞书机器人推送，会发送到机器人所在的会话。
          </div>
        </el-form-item>
        <el-form-item v-if="form.notify_channels.includes('email')" label="收件邮箱">
          <el-input v-model="form.notify_email_to" :placeholder="auth.user?.email || '默认使用账号绑定邮箱'" />
        </el-form-item>
        <el-form-item label="通知时机">
          <el-radio-group v-model="form.notify_on">
            <el-radio-button value="always">总是</el-radio-button>
            <el-radio-button value="success">仅成功</el-radio-button>
            <el-radio-button value="failure">仅失败</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-divider><span class="section-title">高级</span></el-divider>
        <el-form-item label="单次超时">
          <el-input-number v-model="form.max_runtime_seconds" :min="60" :max="86400" :step="60"
                            controls-position="right" />
          <span class="muted small" style="margin-left:8px">秒 · 默认 1800（30 分钟）</span>
        </el-form-item>
        <el-form-item label="并发策略">
          <el-radio-group v-model="form.concurrency_policy">
            <el-radio-button value="skip">上次未完成则跳过</el-radio-button>
            <el-radio-button value="queue" disabled>排队（暂未实现）</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, VideoPlay, Clock, EditPen, Delete, MoreFilled } from '@element-plus/icons-vue'
import { api } from '@/api'
import { useAuth } from '@/stores/auth'

const auth = useAuth()
const router = useRouter()
const rows = ref<any[]>([])
const agents = ref<any[]>([])
const loading = ref(false)
const visible = ref(false)
const choiceVisible = ref(false)
const saving = ref(false)
const editing = ref<any | null>(null)
const runningId = ref<number | null>(null)
const form = reactive<any>(emptyForm())

const cronPresets = [
  { label: '每分钟', expr: '* * * * *' },
  { label: '每小时', expr: '0 * * * *' },
  { label: '每天 9:00', expr: '0 9 * * *' },
  { label: '每天 18:00', expr: '0 18 * * *' },
  { label: '工作日 9:00', expr: '0 9 * * 1-5' },
  { label: '每周一 9:00', expr: '0 9 * * 1' },
  { label: '每月 1 号 9:00', expr: '0 9 1 * *' },
]

function emptyForm() {
  return {
    name: '', description: '', agent_id: null, prompt_text: '',
    schedule_type: 'manual', schedule_value: '', timezone: 'Asia/Shanghai',
    max_runtime_seconds: 1800, concurrency_policy: 'skip',
    notify_channels: ['inapp'], notify_email_to: '', notify_on: 'always',
    enabled: true,
  }
}

async function load() {
  loading.value = true
  try {
    const [t, a] = await Promise.all([api.tasks(), api.myAgents()])
    rows.value = t
    agents.value = a
  } finally { loading.value = false }
}
onMounted(load)

function openCreateChoice() {
  choiceVisible.value = true
}
function chooseAdvanced() {
  choiceVisible.value = false
  openCreate()
}
// 对话创建：跳转到首页对话框，预置「自动化任务生成器」技能 + 一句话模板，
// 用户补全描述后发送即可由 create_task skill 理解并创建任务。
function chooseCustom() {
  choiceVisible.value = false
  const template =
    '帮我创建一个自动化任务，任务是要[在这里描述要做什么]，调用[填写专家名称]专家智能体，执行时间是[多久执行一次，例如每天早上9点 / 每隔1小时]。'
  router.push({
    path: '/chat',
    query: { skill: 'create_task', draft: template },
  })
}

function openCreate() {
  editing.value = null
  Object.assign(form, emptyForm())
  if (agents.value.length && !form.agent_id) form.agent_id = agents.value[0].id
  visible.value = true
}

function openEdit(row: any) {
  editing.value = row
  Object.assign(form, emptyForm(), JSON.parse(JSON.stringify(row)))
  form.notify_channels = Array.isArray(row.notify_channels) ? [...row.notify_channels] : ['inapp']
  visible.value = true
}

async function onSubmit() {
  if (!form.name?.trim()) return ElMessage.warning('请输入任务名称')
  if (!form.agent_id) return ElMessage.warning('请选择执行专家')
  if (!form.prompt_text?.trim()) return ElMessage.warning('请输入提示词')
  if (form.schedule_type === 'cron' && !form.schedule_value?.trim())
    return ElMessage.warning('请填写 cron 表达式')
  if (form.schedule_type === 'once' && !form.schedule_value)
    return ElMessage.warning('请选择执行时间')
  saving.value = true
  try {
    const payload = { ...form }
    if (payload.schedule_type === 'manual') payload.schedule_value = null
    if (editing.value) await api.updateTask(editing.value.id, payload)
    else await api.createTask(payload)
    ElMessage.success('保存成功')
    visible.value = false
    await load()
  } finally { saving.value = false }
}

async function onDelete(row: any) {
  try {
    await ElMessageBox.confirm(`删除任务「${row.name}」？此操作不可恢复。`, '确认', { type: 'warning' })
    await api.deleteTask(row.id)
    ElMessage.success('已删除')
    await load()
  } catch {}
}

async function onToggle(row: any) {
  await api.toggleTask(row.id)
  await load()
}

async function onRun(row: any) {
  runningId.value = row.id
  try {
    await api.runTask(row.id)
    ElMessage.success('已启动，结束后会通过通知告知')
    await load()
  } finally { runningId.value = null }
}

function scheduleLabel(row: any) {
  if (row.schedule_type === 'manual') return '仅手动'
  if (row.schedule_type === 'once') return `单次 · ${(row.schedule_value || '').replace('T', ' ').slice(0, 16)}`
  return `cron · ${row.schedule_value}`
}

function statusLabel(s: string | null | undefined) {
  return ({
    succeeded: '成功', failed: '失败', running: '运行中', timeout: '超时',
    cancelled: '已取消', skipped: '已跳过', pending: '等待中',
  } as any)[s || ''] || s || '—'
}

function relTime(iso: string | null | undefined) {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  const diff = Date.now() - t
  if (diff < 60_000) return '刚刚'
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} 小时前`
  return new Date(iso).toLocaleString()
}
</script>

<style scoped>
/* Fill the flex-column view-shell and scroll our own overflow. .center sets
   overflow:hidden, so without an explicit scroll container the task grid grows
   past the viewport and the extra cards get clipped with no scrollbar. */
.page {
  padding: 24px 28px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  box-sizing: border-box;
}
.page-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 18px;
}
.page-title { font-size: 18px; font-weight: 600; letter-spacing: -.01em; }

.small { font-size: 13px; }

.task-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; min-height: 140px; align-items: start; }
.task-card {
  min-height: 156px;
  padding: 14px;
  border: 1px solid #ebe9e2;
  border-radius: 16px;
  background:
    linear-gradient(180deg, rgba(252, 251, 247, .96), rgba(255, 255, 255, 1)),
    #fff;
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: box-shadow .16s ease, transform .16s ease, border-color .16s ease;
}
.task-card:hover { box-shadow: 0 18px 40px -34px rgba(34, 34, 30, .28); border-color: #ddd9cf; transform: translateY(-1px); }
.task-head { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
.task-icon {
  width: 40px; height: 40px; border-radius: 12px;
  background: linear-gradient(135deg, #f5f1e8, #ece8de);
  color: #56554e;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.task-main { flex: 1; min-width: 0; }
.task-name { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 760; min-width: 0; line-height: 1.25; }
.task-name span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-agent { margin-top: 4px; color: #8a8a84; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.task-menu {
  width: 28px;
  height: 28px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #777770;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background .14s ease, color .14s ease, border-color .14s ease;
}
.task-menu:hover {
  background: #f6f6f3;
  color: #2f2e28;
  border-color: #e6e6e2;
}
.task-desc {
  margin: 0;
  color: #6f6d64;
  font-size: 13px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: calc(1.6em * 2);
}
.task-meta { display: flex; flex-wrap: wrap; gap: 8px; color: #777770; font-size: 12px; }
.task-meta > span {
  padding: 5px 9px;
  border-radius: 999px;
  background: #f6f4ee;
  color: #666257;
  border: 1px solid #ede7db;
}
.last-run { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.empty-task {
  border: 0; background: #f1f1ef; color: #30302d;
  border-radius: 999px; min-height: 30px; padding: 0 12px;
  cursor: pointer; font-size: 12px; font-weight: 650;
  display: inline-flex; align-items: center; gap: 5px;
}
.empty-task:hover { background: #e5e5e2; }
.dropdown-item-inner {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #2f2e28;
}
.dropdown-item-inner.danger { color: #9d3a31; }
:deep(.task-action-popper.el-popper) {
  border: 1px solid #e8e8e3;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 14px 34px -24px rgba(24, 24, 22, .38);
  padding: 4px;
}
:deep(.task-action-popper.el-popper .el-popper__arrow) { display: none; }
:deep(.task-action-popper .el-dropdown-menu) {
  padding: 0;
  background: transparent;
  box-shadow: none;
}
:deep(.task-action-popper .el-dropdown-menu__item) {
  min-width: 132px;
  border-radius: 7px;
  padding: 8px 10px;
  margin: 1px 0;
  color: #2f2e28;
  line-height: 1.2;
  font-size: 13px;
  transition: background .12s ease, color .12s ease;
}
:deep(.task-action-popper .el-dropdown-menu__item:hover) { background: #f6f6f3; }
:deep(.task-action-popper .el-dropdown-menu__item.is-disabled) {
  color: #a8a8a2;
  cursor: wait;
}
:deep(.task-action-popper .el-dropdown-menu__item.is-divided) {
  margin-top: 4px;
  border-top-color: #eeeeeb;
  padding-top: 9px;
}
.empty-task {
  min-height: 132px;
  width: min(380px, 100%);
  border: 1px dashed #e6e6e2;
  border-radius: 16px;
  background: #fafaf8;
  color: #56554e;
  padding: 18px;
  justify-content: center;
  align-items: flex-start;
  flex-direction: column;
  text-align: left;
  gap: 5px;
}
.empty-task:hover {
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
  font-size: 17px;
  font-weight: 760;
  margin-bottom: 3px;
}
.empty-title { font-size: 13px; font-weight: 760; color: #3f3f3b; }
.empty-desc { font-size: 12px; color: #8a8a84; line-height: 1.45; max-width: 300px; }
.empty-action { margin-top: 4px; font-size: 12px; font-weight: 700; color: #56554e; }

.muted { color: var(--m-text-secondary); }

.section-title { font-size: 12px; color: var(--m-text-secondary); }

.channel-hint { margin-top: 4px; line-height: 1.5; }

.cron-hints {
  display: flex; flex-wrap: wrap; gap: 4px 10px;
  margin-top: 6px; font-size: 12px;
}
.cron-hints a {
  color: var(--m-primary); cursor: pointer; user-select: none;
}
.cron-hints a:hover { text-decoration: underline; }

.schedule-tag {
  display: inline-flex; align-items: center;
  font-size: 12px;
  color: var(--m-text-secondary);
}
.schedule-tag[data-type="cron"] { background: rgba(66,133,244,.08); color: var(--m-primary); }
.schedule-tag[data-type="once"] { background: rgba(251,188,4,.12); color: #b06000; }

.status-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--m-text-tertiary); flex-shrink: 0;
}
.status-dot.succeeded { background: var(--m-success); }
.status-dot.failed, .status-dot.timeout { background: var(--m-danger); }
.status-dot.running, .status-dot.pending { background: var(--m-primary); animation: pulse 1.4s ease-in-out infinite; }
.status-dot.cancelled, .status-dot.skipped { background: #9aa0a6; }
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: .5; transform: scale(.8); }
}
@media (max-width: 1180px) { .task-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 900px) { .task-grid { grid-template-columns: 1fr; } }

/* New-task path chooser (对话生成 vs 高级配置) — mirrors 专家管理 visual. */
.create-choices { display: flex; flex-direction: column; gap: 12px; }
.create-choice {
  display: flex; align-items: center; gap: 14px;
  text-align: left; width: 100%;
  padding: 16px 18px;
  border: 1px solid #eeeeeb; border-radius: 16px;
  background: #fff; cursor: pointer;
  transition: border-color .14s ease, box-shadow .14s ease, background .14s ease;
}
.create-choice:hover {
  border-color: #c9d6f5; background: #fafbff;
  box-shadow: 0 14px 30px -28px rgba(0,0,0,.35);
}
.create-choice-icon {
  width: 44px; height: 44px; border-radius: 12px;
  background: #f2f2ef; display: flex; align-items: center; justify-content: center;
  font-size: 22px; flex-shrink: 0;
}
.create-choice-body { flex: 1; min-width: 0; }
.create-choice-title { font-size: 15px; font-weight: 760; margin-bottom: 4px; }
.create-choice-desc { font-size: 12.5px; color: #777770; line-height: 1.55; }
</style>
