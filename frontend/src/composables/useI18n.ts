import { ref, computed } from 'vue'
// 批 76：写成显式 `/index` —— 目录导入只有 Vite 能解析，
// 而 `frontend/tests/*.test.mjs` 的自定义 loader 只试 `.ts`/`.js` 文件，
// 于是任何（直接或间接）依赖本模块的 node 测试都会在解析阶段就挂掉。
import { zhCN } from '../locales/zh/index'
import { enUS } from '../locales/en/index'

export type LocaleType = 'zh-CN' | 'en-US'

const LOCALE_KEY = 'astra_locale'

/**
 * 界面语言选项 —— **全站唯一来源**。
 *
 * `label` 用该语言**自己的名字**（中文 / English），不随当前语言翻译：
 * 语言开关的作用是让看不懂当前语言的人找到自己的语言，
 * 译成「Chinese」对只看中文的人反而是障碍。
 *
 * 批 75：此前两个开关各写各的 —— 设置面板写 `中文` / `English`，
 * 登录页模板里**硬编码**成 `中文` / `EN`，同一个语言两个写法。
 */
export const LOCALE_OPTIONS: { value: LocaleType; label: string }[] = [
  { value: 'zh-CN', label: '中文' },
  { value: 'en-US', label: 'English' },
]

type Dict = Record<string, any>

// 结构优化阶段 0（2026-09-14）：移除 locales/legacy 迁移期兼容层。
// 移除依据（实测，非估计）：新树 zh/en 各 1639 键；代码中静态 t() 键位 1356 个；
// 「仅 legacy 提供且仍被使用」的键位 = 0；legacy 292 键中 288 个无人使用。
// 原注释自定的移除条件「旧页面清零后移除」已达成，故连同 deepMerge 一并删除。
const messages: Record<LocaleType, Dict> = {
  'zh-CN': zhCN as Dict,
  'en-US': enUS as Dict,
}

let currentLocaleRaw = ref<LocaleType>('zh-CN')
let initialized = false

export function useI18n() {
  const currentLocale = currentLocaleRaw

  function applyLocale(locale: LocaleType) {
    currentLocale.value = locale
    if (typeof document !== 'undefined') {
      document.documentElement.setAttribute('lang', locale)
      try {
        localStorage.setItem(LOCALE_KEY, locale)
      } catch {
        // ignore storage error in private browsing
      }
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new Event('astra:locale-changed'))
      }
    }
  }

  function toggleLocale() {
    applyLocale(currentLocale.value === 'zh-CN' ? 'en-US' : 'zh-CN')
  }

  function initLocale() {
    if (initialized) return
    initialized = true

    let preferred: LocaleType = 'zh-CN'
    try {
      const saved = localStorage.getItem(LOCALE_KEY)
      if (saved === 'zh-CN' || saved === 'en-US') {
        preferred = saved
      } else if (typeof navigator !== 'undefined') {
        const navLang = (navigator.language || '').toLowerCase()
        if (navLang.startsWith('en')) {
          preferred = 'en-US'
        }
      }
    } catch {
      // fallback
    }

    applyLocale(preferred)
  }

  /**
   * Safe nested key getter with {placeholder} interpolation:
   *   t('common.confirmPhraseHint', undefined, { phrase: 'DELETE' })
   * 缺失键回退链：当前语言 → zh-CN → fallback → 键路径
   */
  function t(path: string, fallback?: string, params?: Record<string, string | number>): string {
    const lookup = (dict: Dict): string | null => {
      let curr: any = dict
      for (const p of path.split('.')) {
        if (curr && typeof curr === 'object' && p in curr) curr = curr[p]
        else return null
      }
      return typeof curr === 'string' ? curr : null
    }
    let out = lookup(messages[currentLocale.value]) ?? lookup(messages['zh-CN']) ?? fallback ?? path
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        out = out.replaceAll(`{${k}}`, String(v))
      }
    }
    return out
  }

  /** 取原始值（数组/对象），用于列表型文案 */
  function tm(path: string): any {
    const lookup = (dict: Dict): any => {
      let curr: any = dict
      for (const p of path.split('.')) {
        if (curr && typeof curr === 'object' && p in curr) curr = curr[p]
        else return undefined
      }
      return curr
    }
    return lookup(messages[currentLocale.value]) ?? lookup(messages['zh-CN'])
  }

  const isEn = computed(() => currentLocale.value === 'en-US')
  const locale = computed(() => currentLocale.value)

  return {
    locale,
    currentLocale,
    LOCALE_OPTIONS,
    isEn,
    t,
    tm,
    setLocale: applyLocale,
    toggleLocale,
    initLocale,
  }
}
