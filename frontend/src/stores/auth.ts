import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useI18n } from '../composables/useI18n'

const SESSION_TOKEN_KEY = 'astra.admin.session.id'
const SESSION_USER_KEY = 'astra.admin.session.user'

export interface AdminUser {
  username: string
  role: string
}

export const useAuthStore = defineStore('auth', () => {
  // 批 76：错误文案改走 i18n
  const { t } = useI18n()
  const token = ref<string>('')
  const user = ref<AdminUser | null>(null)
  const error = ref<string>('')

  const isAuthenticated = computed(() => !!token.value)
  const isSuperadmin = computed(() => user.value?.role === 'superadmin')

  async function login(username: string, password: string): Promise<boolean> {
    error.value = ''
    try {
      const resp = await fetch('/api/v1/admin/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const data = await resp.json()
      if (!resp.ok) {
        error.value = data.detail || `${t('common.loginFailed')} (HTTP ${resp.status})`
        return false
      }
      token.value = data.session_token
      user.value = { username: data.user?.username || username, role: data.user?.role || 'admin' }
      localStorage.setItem(SESSION_TOKEN_KEY, token.value)
      localStorage.setItem(SESSION_USER_KEY, JSON.stringify(user.value))
      return true
    } catch (e: any) {
      error.value = e.message || t('common.networkError')
      return false
    }
  }

  async function validateSession(): Promise<boolean> {
    if (!token.value) return false
    try {
      const resp = await fetch('/api/v1/admin/auth/me', {
        headers: { 'X-Astra-Session': token.value },
      })
      if (resp.status === 401) {
        logout()
        return false
      }
      if (!resp.ok) {
        // 服务端升级重启中（502/503/504 等网关瞬态错误），保留本地会话不误踢
        return true
      }
      const data = await resp.json()
      if (data.user) {
        user.value = { username: data.user.username, role: data.user.role }
        localStorage.setItem(SESSION_USER_KEY, JSON.stringify(user.value))
      }
      return true
    } catch {
      // 网络波动或离线，保留本地会话
      return true
    }
  }

  function restoreSession() {
    let savedToken = localStorage.getItem(SESSION_TOKEN_KEY)
    let savedUser = localStorage.getItem(SESSION_USER_KEY)

    // 平滑兼容历史内部代号 r20 存储键（升级后无感迁移）
    if (!savedToken) {
      const legacyToken = localStorage.getItem('r20.admin.session.id')
      if (legacyToken) {
        savedToken = legacyToken
        localStorage.setItem(SESSION_TOKEN_KEY, legacyToken)
        localStorage.removeItem('r20.admin.session.id')
      }
    }
    if (!savedUser) {
      const legacyUser = localStorage.getItem('r20.admin.session.user')
      if (legacyUser) {
        savedUser = legacyUser
        localStorage.setItem(SESSION_USER_KEY, legacyUser)
        localStorage.removeItem('r20.admin.session.user')
      }
    }

    if (savedToken) {
      token.value = savedToken
      if (savedUser) {
        try {
          user.value = JSON.parse(savedUser)
        } catch {
          user.value = { username: 'admin', role: 'admin' }
        }
      } else {
        user.value = { username: 'admin', role: 'admin' }
      }
      validateSession()
    }
  }

  function logout() {
    // Best-effort server-side logout (don't block)
    if (token.value) {
      fetch('/api/v1/admin/logout', {
        method: 'POST',
        headers: { 'X-Astra-Session': token.value },
      }).catch(() => {})
    }
    token.value = ''
    user.value = null
    localStorage.removeItem(SESSION_TOKEN_KEY)
    localStorage.removeItem(SESSION_USER_KEY)
  }

  return {
    token,
    user,
    error,
    isAuthenticated,
    isSuperadmin,
    login,
    logout,
    restoreSession,
  }
})
