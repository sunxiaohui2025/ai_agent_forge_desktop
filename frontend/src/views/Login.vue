<template>
  <div class="login-bg">
    <div class="ambient ambient-terracotta" />
    <div class="ambient ambient-sage" />
    <div class="ambient ambient-sand" />
    <div class="login-card">
      <div class="brand">
        <div class="brand-mark">
          <span class="dot dot-1" /><span class="dot dot-2" /><span class="dot dot-3" /><span class="dot dot-4" />
        </div>
        <div>
          <div class="brand-name">Agent Forge</div>
          <div class="brand-sub">Desktop Workbench</div>
        </div>
      </div>
      <h2 class="title">欢迎回来</h2>
      <p class="subtitle">登录后开始与你的智能体协作</p>

      <el-form @submit.prevent="onSubmit" :model="form" :rules="rules" ref="formRef" label-position="top" size="large">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" autofocus placeholder="输入用户名" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="输入密码" />
        </el-form-item>
        <div class="remember-row">
          <label class="remember-label">
            <input type="checkbox" v-model="rememberMe" class="remember-check" />
            记住密码
          </label>
        </div>
        <el-button type="primary" :loading="loading" style="width:100%;height:44px;font-size:15px" @click="onSubmit">
          登录
        </el-button>
      </el-form>
      <p class="footer-hint">默认账号 <code>admin</code> · 密码 <code>admin123</code>，登录后请及时修改</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'

const STORAGE_KEY = 'remembered_login'

const auth = useAuth()
const router = useRouter()
const formRef = ref<any>(null)
const form = reactive({ username: 'admin', password: 'admin123' })
const loading = ref(false)
const rememberMe = ref(false)
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

onMounted(() => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const { username, password } = JSON.parse(saved)
      form.username = username || ''
      form.password = password || ''
      rememberMe.value = true
    }
  } catch { localStorage.removeItem(STORAGE_KEY) }
})

async function onSubmit() {
  const ok = await formRef.value?.validate().catch(() => false)
  if (!ok) return
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    if (rememberMe.value) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ username: form.username, password: form.password }))
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
    router.push('/chat')
  } finally { loading.value = false }
}
</script>

<style scoped>
.login-bg {
  position: relative;
  display: flex; align-items: center; justify-content: center;
  height: 100vh; overflow: hidden;
  background:
    linear-gradient(120deg, rgba(255,255,255,.78) 0 1px, transparent 1px 32px),
    linear-gradient(210deg, rgba(255,255,255,.64) 0 1px, transparent 1px 34px),
    radial-gradient(circle at 20% 18%, rgba(201,100,66,.18), transparent 320px),
    radial-gradient(circle at 82% 24%, rgba(91,141,126,.15), transparent 330px),
    linear-gradient(180deg, #fbf7f1 0%, #f4f4ee 48%, #eef2ef 100%);
}

.login-bg::before {
  content: "";
  position: absolute;
  inset: 8%;
  border-radius: 40px;
  background:
    radial-gradient(circle at 14% 84%, rgba(201,100,66,.12), transparent 230px),
    radial-gradient(circle at 90% 78%, rgba(219,180,108,.14), transparent 260px);
  filter: blur(2px);
  opacity: .92;
}

.login-bg::after {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(90deg, rgba(28,28,26,.035) 1px, transparent 1px),
    linear-gradient(180deg, rgba(28,28,26,.03) 1px, transparent 1px);
  background-size: 78px 78px;
  mask-image: radial-gradient(circle at 50% 48%, rgba(0,0,0,.72), transparent 68%);
  -webkit-mask-image: radial-gradient(circle at 50% 48%, rgba(0,0,0,.72), transparent 68%);
  pointer-events: none;
}

.ambient {
  position: absolute;
  border-radius: 999px;
  filter: blur(30px);
  opacity: .72;
  pointer-events: none;
}
.ambient-terracotta {
  width: 280px; height: 280px;
  left: calc(50% - 420px); top: calc(50% - 290px);
  background: rgba(201,100,66,.18);
}
.ambient-sage {
  width: 250px; height: 250px;
  right: calc(50% - 430px); top: calc(50% - 230px);
  background: rgba(107,151,137,.16);
}
.ambient-sand {
  width: 330px; height: 180px;
  left: calc(50% - 180px); bottom: calc(50% - 380px);
  background: rgba(219,180,108,.13);
}

.login-card {
  position: relative; z-index: 1;
  width: 414px; padding: 34px;
  background:
    linear-gradient(180deg, rgba(255,255,255,.92), rgba(255,255,255,.84));
  backdrop-filter: blur(24px) saturate(1.18);
  -webkit-backdrop-filter: blur(24px) saturate(1.18);
  border-radius: 22px;
  border: 1px solid rgba(255,255,255,.78);
  box-shadow:
    0 24px 70px -34px rgba(50,43,35,.34),
    0 0 0 1px rgba(28,28,26,.055);
}
.brand { display:flex; align-items:center; gap: 10px; margin-bottom: 28px; }
.brand-mark {
  display:grid; grid-template-columns: 1fr 1fr; gap: 3px;
  width: 28px; height: 28px; padding: 6px;
  border-radius: 9px;
  background:
    linear-gradient(145deg, rgba(201,100,66,.96), rgba(49,49,45,.96));
  box-shadow: 0 10px 22px -14px rgba(201,100,66,.75);
}
.dot { border-radius: 3px; }
.dot-1 { background:#ffffff } .dot-2 { background:#d8d7cf }
.dot-3 { background:#aaa99f } .dot-4 { background:#77766e }
.brand-name { font-size: 17px; font-weight: 700; letter-spacing: 0; line-height: 1.1; }
.brand-sub { margin-top: 3px; font-size: 12px; color: var(--m-text-tertiary); }

.title { margin: 0 0 4px; font-size: 26px; font-weight: 680; letter-spacing: 0; }
.subtitle { margin: 0 0 24px; color: var(--m-text-secondary); font-size: 14px; }

.footer-hint { margin-top: 20px; text-align: center; color: var(--m-text-tertiary); font-size: 12px; }
.footer-hint code { background: rgba(201,100,66,.08); color: #8f452e; padding: 2px 6px; border-radius: 5px; }

.remember-row { margin: -4px 0 14px; }
.remember-label {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; color: var(--m-text-secondary);
  cursor: pointer; user-select: none;
}
.remember-check { width: 14px; height: 14px; accent-color: var(--m-primary); cursor: pointer; }

:deep(.el-form-item__label) {
  color: var(--m-text-secondary);
  font-weight: 560;
}

:deep(.el-input__wrapper) {
  min-height: 42px;
  border-radius: 11px !important;
  background: rgba(255,255,255,.72) !important;
}

:deep(.el-button--primary) {
  border-radius: 12px !important;
  background: linear-gradient(135deg, #242421, #3a332e) !important;
  border-color: transparent !important;
}

@media (max-width: 520px) {
  .login-bg { padding: 20px; }
  .login-card { width: 100%; padding: 28px; }
}
</style>
