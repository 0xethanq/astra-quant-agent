import { ref } from 'vue'

export type ThemeMode = 'light' | 'dark'

const currentTheme = ref<ThemeMode>('dark')
const cvdMode = ref(false)
let initialized = false

function applyCvd(on: boolean) {
  cvdMode.value = on
  if (typeof document !== 'undefined') {
    const el = document.documentElement
    if (on) el.setAttribute('data-cvd', 'true')
    else el.removeAttribute('data-cvd')
    try {
      localStorage.setItem('astra_cvd', on ? '1' : '0')
    } catch {
      // ignore
    }
  }
}

export function useTheme() {
  function applyTheme(theme: ThemeMode = 'dark') {
    currentTheme.value = theme
    if (typeof document !== 'undefined') {
      const el = document.documentElement
      el.setAttribute('data-theme', theme)
      if (theme === 'light') {
        el.classList.add('light')
        el.classList.remove('dark')
      } else {
        el.classList.add('dark')
        el.classList.remove('light')
      }
      try {
        localStorage.setItem('astra_theme', theme)
        localStorage.setItem('astra_theme_v2', theme)
      } catch {
        // ignore
      }
    }
  }

  function toggleTheme() {
    applyTheme(currentTheme.value === 'dark' ? 'light' : 'dark')
  }

  function initTheme() {
    if (initialized) return
    initialized = true
    let savedTheme: ThemeMode = 'dark'
    if (typeof document !== 'undefined') {
      try {
        if (localStorage.getItem('astra_cvd') === '1') applyCvd(true)
        const storedV2 = localStorage.getItem('astra_theme_v2')
        if (storedV2 === 'dark' || storedV2 === 'light') {
          savedTheme = storedV2
        } else {
          // 清理历史残留的主题设置，确保全站升级为默认深色黑曜石主题
          localStorage.removeItem('astra_theme')
          localStorage.setItem('astra_theme_v2', 'dark')
          savedTheme = 'dark'
        }
      } catch {
        // fallback
      }
    }
    applyTheme(savedTheme)
  }

  return {
    theme: currentTheme,
    toggleTheme,
    setTheme: applyTheme,
    initTheme,
    cvd: cvdMode,
    setCvd: applyCvd,
    toggleCvd: () => applyCvd(!cvdMode.value),
  }
}
