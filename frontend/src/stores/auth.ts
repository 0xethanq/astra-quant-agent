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
      if (!resp.ok) {
        logout()
        return false
      }
      const data = await resp.json()
      if (data.user) {
        user.value = { username: data.user.username, role: data.user.role }
        localStorage.setItem(SESSION_USER_KEY, JSON.stringify(user.value))
      }
      return true
    } catch {
      return false
    }
  }

  function restoreSession() {
    const savedToken = localStorage.getItem(SESSION_TOKEN_KEY)
    const savedUser = localStorage.getItem(SESSION_USER_KEY)
    if (savedToken && savedUser) {
      token.value = savedToken
      try {
        user.value = JSON.parse(savedUser)
      } catch {
        user.value = null
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
