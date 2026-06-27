<template>
  <div class="login-bg">
    <div class="login-card">
      <div class="brand">
        <div class="brand-mark">
          <span class="dot dot-1" /><span class="dot dot-2" /><span class="dot dot-3" /><span class="dot dot-4" />
        </div>
        <div>
          <div class="brand-name">H3C Agent</div>
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
    radial-gradient(circle at 50% 0, rgba(255,255,255,.92), transparent 360px),
    linear-gradient(180deg, #fbfbf8 0%, #f1f1ed 100%);
}

.login-card {
  position: relative; z-index: 1;
  width: 410px; padding: 34px;
  background: rgba(255,255,255,.86);
  backdrop-filter: blur(22px) saturate(1.16);
  -webkit-backdrop-filter: blur(22px) saturate(1.16);
  border-radius: var(--m-radius-xl);
  border: 1px solid rgba(28,28,26,.08);
  box-shadow: var(--m-shadow-3);
}
.brand { display:flex; align-items:center; gap: 10px; margin-bottom: 28px; }
.brand-mark {
  display:grid; grid-template-columns: 1fr 1fr; gap: 3px;
  width: 28px; height: 28px; padding: 6px;
  border-radius: 9px;
  background: linear-gradient(145deg, #1f1f1d, #4c4b45);
}
.dot { border-radius: 3px; }
.dot-1 { background:#ffffff } .dot-2 { background:#d8d7cf }
.dot-3 { background:#aaa99f } .dot-4 { background:#77766e }
.brand-name { font-size: 17px; font-weight: 700; letter-spacing: 0; line-height: 1.1; }
.brand-sub { margin-top: 3px; font-size: 12px; color: var(--m-text-tertiary); }

.title { margin: 0 0 4px; font-size: 26px; font-weight: 680; letter-spacing: 0; }
.subtitle { margin: 0 0 24px; color: var(--m-text-secondary); font-size: 14px; }

.footer-hint { margin-top: 20px; text-align: center; color: var(--m-text-tertiary); font-size: 12px; }
.footer-hint code { background: var(--m-surface-variant); padding: 2px 6px; border-radius: 4px; }

.remember-row { margin: -4px 0 14px; }
.remember-label {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; color: var(--m-text-secondary);
  cursor: pointer; user-select: none;
}
.remember-check { width: 14px; height: 14px; accent-color: var(--m-primary); cursor: pointer; }
</style>
