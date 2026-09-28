/**
 * 安全页（`SecurityPage.vue`）的显示派生逻辑（结构优化阶段 4·B3 第三十四刀）。
 *
 * 原样搬自 `frontend/src/views/admin/SecurityPage.vue` 的 script setup：
 * `okxLinked` / `mxHealthChips` / `okxEnvText` / `envBadge` —— 四段**纯派生**
 * （给定输入与 i18n 函数就有确定输出），与 Vue 响应式、网络请求、组件状态
 * 都无关，因此可以脱离组件单测。
 *
 * ⚠️ 2026-10：本系统已收口为 **OKX 单所**。原先随"三所平权"搬过来的五段派生
 * （两段执行闸脏标记、一段 OKX 执行闸脏标记、按所状态徽章、按所档位文字）已
 * **整体删除** —— 它们没有消费者，且其入参类型（已下架场所的档位字面量）
 * 与多所路由语义都不再存在。删除清单见 git 历史与
 * `tests/ui/test_frontend_security_logic.py` 的反向守卫常量。
 *
 * ⚠️ 同步须知：`tests/ui/test_frontend_security_logic.py` 曾以 node oracle
 * 逐条断言这五个**已删除**的导出。该 Python 门的持有者需把它收窄到
 * `deriveOkxLinked` / `deriveMxHealthChips` / `okxEnvText` / `envBadge`
 * 四个存活导出（前端侧不得改 .py）。
 *
 * ## 与组件内的版本是**同一逻辑**，只是把 `*.value` 换成入参
 *
 * ## 易错点（均原样保留）
 *
 * 1. **"未知"一律 `warn`/`unknown`，不升级为已就绪。** 这是本模块所有
 *    状态派生的共同红线：读不到 ≠ 就绪。
 * 2. **`mxHealthChips` 的 `total` 是"ok + failed 的键数"，不是"ok 的条数"。**
 *    且缺 `health.venues` 时返回 **`null`**（而不是空数组）—— 前端用
 *    `v-if="mxHealthChips"` 区分"没有数据"与"没有失败"，两者渲染不同。
 * 3. **`okxEnvText` 是三态**（live / demo / 其它一律 unknown），
 *    不把认不出的档位乐观地当成实盘或模拟盘。
 * 4. **`envBadge` 对空值兜底成 `DEMO`**（`(env || 'demo').toUpperCase()`），
 *    不是空串。
 *
 * ## 为什么这些值得单独测
 *
 * 状态派生直接决定运维看到的是"绿/黄/红"。它们错的方向如果是**乐观**
 * （把未知当成就绪），会让人以为 OKX 已连通 —— 这类"UI 说谎"是本仓
 * 反复强调的红线。
 */

/** i18n 取值函数（与 `useI18n().t` 同形；测试里传替身即可）。 */
export type TFn = (path: string, fallback?: string, params?: Record<string, string | number>) => string

export interface VenueLike {
  has_api_key?: boolean
  execution_open?: boolean
  testnet?: boolean
}

export interface MxLike {
  venues?: Record<string, VenueLike | undefined>
  health?: { venues?: Record<string, { ok?: unknown[]; failed?: Record<string, unknown>; avg_ms?: number; testnet?: boolean }> }
}

/** OKX 是否已连通：**两个条件都要**（READY 且 mode_configured 为真）。 */
export function deriveOkxLinked(runtime: any): boolean {
  return runtime?.status === 'READY' && runtime?.mode_configured === true
}

/**
 * 交易所健康度 chip。
 *
 * - 缺 `health.venues` → **`null`**（不是 `[]`）；
 * - `total` = `ok` 条数 + `failed` 的**键数**；
 * - `avg_ms` 缺省 0；`testnet` 强转布尔。
 */
export function deriveMxHealthChips(mx: MxLike | null | undefined) {
  const venues = mx?.health?.venues
  if (!venues) return null
  return Object.entries(venues).map(([name, v]: [string, any]) => ({
    name,
    ok: (v.ok || []).length,
    total: (v.ok || []).length + Object.keys(v.failed || {}).length,
    avg_ms: v.avg_ms || 0,
    testnet: !!v.testnet,
  }))
}

/** OKX 资金档位文字（三态：live / demo / 其它一律 unknown）。 */
export function okxEnvText(okxEnvironment: unknown, t: TFn): string {
  const env = String(okxEnvironment || '')
  return env === 'live' ? t('admin.security.envLive') : env === 'demo' ? t('admin.security.envDemoOkx') : t('admin.security.envUnknown')
}

/** 环境徽章文字：空值兜底 `DEMO`（不是空串）。 */
export function envBadge(env: string | null | undefined): string {
  return (env || 'demo').toUpperCase()
}
