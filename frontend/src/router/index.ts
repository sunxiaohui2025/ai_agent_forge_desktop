import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/stores/auth'

const routes = [
  { path: '/login', component: () => import('@/views/Login.vue') },
  {
    path: '/',
    component: () => import('@/views/DesktopLayout.vue'),
    redirect: '/chat',
    children: [
      { path: 'chat', component: () => import('@/views/chat/Chat.vue') },
      { path: 'plugins', component: () => import('@/views/Plugins.vue') },
      { path: 'experts', component: () => import('@/views/admin/Agents.vue') },
      { path: 'tasks', component: () => import('@/views/tasks/Tasks.vue') },
      { path: 'tasks/:id/runs', component: () => import('@/views/tasks/TaskRuns.vue') },
      { path: 'space', component: () => import('@/views/space/Space.vue') },
    ],
  },
  // Settings is a SEPARATE full-screen shell (left menu + right content + back button).
  {
    path: '/settings',
    component: () => import('@/views/SettingsLayout.vue'),
    redirect: '/settings/general',
    children: [
      { path: 'general', component: () => import('@/views/settings/General.vue') },
      { path: 'pets', component: () => import('@/views/settings/Pets.vue') },
      { path: 'models', component: () => import('@/views/admin/Models.vue') },
      { path: 'skills', redirect: '/plugins' },
      { path: 'mcp', redirect: '/plugins' },
      { path: 'usage', component: () => import('@/views/settings/Usage.vue') },
      { path: 'logs', component: () => import('@/views/admin/Logs.vue') },
      { path: 'bridge', component: () => import('@/views/settings/Bridge.vue') },
      { path: 'about', component: () => import('@/views/settings/About.vue') },
    ],
  },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  if (to.path === '/login') return true
  const auth = useAuth()
  const token = localStorage.getItem('access_token')
  if (!token) return '/login'
  if (!auth.user) {
    try { await auth.fetchMe() } catch { return '/login' }
  }
  if (to.meta.manage && !auth.canManage) return '/chat'
  return true
})

export default router
