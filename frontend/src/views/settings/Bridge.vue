<template>
  <div class="page">
    <div class="page-head"><span class="page-title">远程桥接</span></div>
    <p class="bridge-lead">将外部即时通讯渠道接入本地智能体，从飞书 / 企业微信 / QQ / 微信直接与你的专家对话。</p>

    <div class="bridge-body">
      <!-- Channel sub-nav -->
      <div class="ch-nav">
        <button v-for="c in channels" :key="c.channel"
                :class="['ch-tab', { active: active === c.channel }]"
                @click="active = c.channel">
          <span class="ch-name">{{ c.name }}</span>
          <span :class="['ch-state', stateClass(c)]">
            <span class="status-dot"></span>{{ c.enabled ? stateLabel(c) : '未启用' }}
          </span>
        </button>
      </div>

      <!-- Channel config -->
      <div v-if="cur" class="ch-config">
        <div class="ch-head">
          <div>
            <div class="ch-title">{{ cur.name }}</div>
            <div class="ch-desc">{{ cur.desc }}</div>
          </div>
          <el-switch v-model="cur.enabled" />
        </div>

        <div class="ch-form">
          <div v-for="f in cur.fields" :key="f.key" class="ch-field">
            <label>{{ f.label }}<span v-if="optional(f)" class="opt">（可选）</span></label>
            <el-input
              v-model="cur.values[f.key]"
              :type="f.secret ? 'password' : 'text'"
              :show-password="f.secret"
              :placeholder="f.placeholder"
              size="default"
            />
          </div>

          <div class="ch-field">
            <label>回复专家</label>
            <el-select v-model="cur.agent_id" clearable placeholder="默认专家" style="width:100%">
              <el-option v-for="a in agents" :key="a.id" :label="a.name" :value="a.id" />
            </el-select>
          </div>

          <div v-if="cur.mode === 'ws'" class="callback-box ws-hint">
            <div class="callback-label">长连接模式（推荐）</div>
            <div class="ws-text">
              本渠道走长连接（WebSocket），<b>无需公网地址、无需配置回调 URL、无需消息加解密</b>。
              只要填好上方凭证，开启开关并保存，就能直接在 {{ cur.name }} 里
              给机器人发消息和你的专家对话。
            </div>
            <a v-if="cur.console_url" class="console-link" :href="cur.console_url" target="_blank" rel="noopener">
              {{ cur.console_label || '前往开发者后台配置' }} ↗
            </a>
          </div>
          <div v-else-if="cur.callback_path" class="callback-box">
            <div class="callback-label">事件回调地址（在渠道开发者后台配置）</div>
            <code class="callback-url">{{ backendBase }}{{ cur.callback_path }}</code>
            <div class="callback-tip">
              该地址需<b>公网可达</b>。桌面 / 内网环境可用内网穿透（如 cpolar、frp）
              把本机 47900 端口映射到公网，再把映射后的完整 URL 填到渠道后台的接收消息配置里。
            </div>
            <a v-if="cur.console_url" class="console-link" :href="cur.console_url" target="_blank" rel="noopener">
              {{ cur.console_label || '前往开发者后台配置' }} ↗
            </a>
          </div>

          <div v-if="cur.enabled && cur.status_detail" class="status-detail">
            {{ cur.status_detail }}
          </div>
        </div>

        <div class="ch-actions">
          <el-button @click="onTest(cur.channel)" :loading="testing">检查配置</el-button>
          <el-button type="primary" @click="onSave(cur.channel)" :loading="saving">保存</el-button>
        </div>

        <el-alert v-if="testResult" :type="testResult.ok ? 'success' : 'warning'"
                  :closable="true" @close="testResult = null" style="margin-top:12px">
          {{ testResult.message }}
          <span v-if="testResult.missing">：{{ testResult.missing.join('、') }}</span>
        </el-alert>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api'

const channels = ref<any[]>([])
const active = ref<string>('feishu')
const agents = ref<any[]>([])
const saving = ref(false)
const testing = ref(false)
const testResult = ref<any>(null)

const cur = computed(() => channels.value.find((c) => c.channel === active.value))
const backendBase = computed(() => 'http://127.0.0.1:47900')

function optional(f: any) { return (f.placeholder || '').includes('可选') }
function stateClass(c: any) {
  if (!c.enabled) return 'status-waiting'
  return { connected: 'status-success', error: 'status-danger', connecting: 'status-running' }[c.status as string] || 'status-waiting'
}
function stateLabel(c: any) {
  return ({ connected: '已连接', error: '错误', connecting: '连接中', disconnected: '待连接' } as any)[c.status] || '待连接'
}

async function load() {
  channels.value = await api.bridgeChannels()
  if (!channels.value.find((c) => c.channel === active.value)) active.value = channels.value[0]?.channel
}

// Patch only the live status fields of a channel so we never clobber the
// user's in-progress form edits (values / enabled / agent_id).
function patchStatus(ch: string, fresh: any) {
  const c = channels.value.find((x) => x.channel === ch)
  if (!c || !fresh) return
  c.status = fresh.status
  c.status_detail = fresh.status_detail
}

// Some channels (e.g. 企业微信长连接) flip to "connected" asynchronously a
// moment after save, once the WebSocket subscribe is acked. Poll the status a
// few times so the UI reflects the real state without a manual page reload.
async function pollUntilSettled(ch: string, tries = 8, interval = 1500) {
  for (let i = 0; i < tries; i++) {
    await new Promise((r) => setTimeout(r, interval))
    try {
      const fresh = await api.bridgeChannel(ch)
      patchStatus(ch, fresh)
      if (fresh.status !== 'connecting') return
    } catch { /* keep trying */ }
  }
}

async function onSave(ch: string) {
  saving.value = true
  try {
    const c = channels.value.find((x) => x.channel === ch)
    const updated = await api.saveBridgeChannel(ch, { enabled: c.enabled, agent_id: c.agent_id, values: c.values })
    const idx = channels.value.findIndex((x) => x.channel === ch)
    channels.value[idx] = updated
    ElMessage.success('已保存')
    if (updated.enabled && updated.status === 'connecting') pollUntilSettled(ch)
  } finally { saving.value = false }
}

async function onTest(ch: string) {
  testing.value = true
  testResult.value = null
  try {
    // Persist the current form first so the backend has something to validate
    // (otherwise a never-saved channel returns "尚未配置").
    const c = channels.value.find((x) => x.channel === ch)
    const updated = await api.saveBridgeChannel(ch, { enabled: c.enabled, agent_id: c.agent_id, values: c.values })
    const idx = channels.value.findIndex((x) => x.channel === ch)
    channels.value[idx] = updated
    if (updated.enabled && updated.status === 'connecting') await pollUntilSettled(ch)
    testResult.value = await api.testBridgeChannel(ch)
  }
  finally { testing.value = false }
}

// Light periodic refresh while the page is open so live status (connect /
// reconnect / error) stays current without clobbering form edits.
let statusTimer: number | undefined
async function refreshAllStatus() {
  try {
    const fresh = await api.bridgeChannels()
    for (const f of fresh) patchStatus(f.channel, f)
  } catch { /* ignore transient errors */ }
}

onMounted(async () => {
  agents.value = await api.agents().catch(() => [])
  await load()
  statusTimer = window.setInterval(refreshAllStatus, 4000)
})

onUnmounted(() => {
  if (statusTimer) window.clearInterval(statusTimer)
})
</script>

<style scoped>
.bridge-lead { font-size: 13px; color: var(--m-text-secondary); margin: 0 0 16px; }
.bridge-body { display: flex; gap: 16px; align-items: flex-start; }

.ch-nav { width: 170px; flex-shrink: 0; display: flex; flex-direction: column; gap: 4px; }
.ch-tab {
  display: flex; flex-direction: column; gap: 4px; align-items: flex-start;
  padding: 10px 12px; border: 1px solid var(--m-border); border-radius: var(--m-radius-lg);
  background: var(--m-surface); cursor: pointer; text-align: left;
  transition: border-color .12s, background .12s;
}
.ch-tab:hover { background: var(--m-surface-variant); }
.ch-tab.active { border-color: var(--m-primary); box-shadow: inset 0 0 0 1px var(--m-primary); }
.ch-name { font-size: 13px; font-weight: 600; }
.ch-state { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; }

.ch-config { flex: 1; min-width: 0; border: 1px solid var(--m-border); border-radius: var(--m-radius-lg); padding: 18px; background: var(--m-surface); }
.ch-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.ch-title { font-size: 15px; font-weight: 650; }
.ch-desc { font-size: 12px; color: var(--m-text-secondary); margin-top: 4px; line-height: 1.6; max-width: 560px; }

.ch-form { display: flex; flex-direction: column; gap: 12px; }
.ch-field label { display: block; font-size: 12px; font-weight: 600; color: var(--m-text-secondary); margin-bottom: 5px; }
.ch-field .opt { font-weight: 400; color: var(--m-text-tertiary); }

.callback-box { padding: 10px 12px; background: var(--m-surface-sunken); border: 1px solid var(--m-border); border-radius: var(--m-radius); }
.callback-label { font-size: 11px; color: var(--m-text-tertiary); margin-bottom: 4px; }
.callback-url { font-size: 12px; word-break: break-all; color: var(--m-text); }
.callback-tip { margin-top: 8px; font-size: 12px; line-height: 1.6; color: var(--m-text-secondary); }
.callback-box .console-link { display: inline-block; margin-top: 8px; font-size: 12px; color: var(--m-primary); text-decoration: none; }
.callback-box .console-link:hover { text-decoration: underline; }

.ws-hint .ws-text { font-size: 12px; line-height: 1.7; color: var(--m-text-secondary); }
.ws-hint .console-link { display: inline-block; margin-top: 8px; font-size: 12px; color: var(--m-primary); text-decoration: none; }
.ws-hint .console-link:hover { text-decoration: underline; }
.status-detail { margin-top: 10px; font-size: 12px; color: var(--m-text-tertiary); }

.ch-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
</style>
