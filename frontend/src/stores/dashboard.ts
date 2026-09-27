import { defineStore } from 'pinia'
import { ref, shallowRef, computed } from 'vue'
import { useI18n } from '../composables/useI18n'
import type { DashboardResponse, InstrumentFactor, PositionItem, PendingOrderItem } from '../types/dashboard'

export const useDashboardStore = defineStore('dashboard', () => {
  // 批 76：回落文案改走 i18n（useI18n 只读模块级 locale ref，在 store 作用域调用是安全的）
  const { t } = useI18n()
  const activeTab = ref<'trading' | 'factors' | 'news' | 'lab' | 'history'>('trading')
  // 性能优化：大型 ~380KB 接口数据整包替换，改用 shallowRef 避免深层递归生成数千个 Proxy 实例，大幅削减 CPU 与 GC 压力
  const data = shallowRef<DashboardResponse | null>(null)
  const loading = ref<boolean>(false)
  const isRefreshing = ref<boolean>(false)
  const error = ref<string | null>(null)
  const lastUpdated = ref<Date | null>(null)
  const isConnected = ref<boolean>(true)
  const pollingTimer = ref<any>(null)
  const showAboutModal = ref<boolean>(false)

  // Getters
  const account = computed(() => data.value?.account || null)
  const positions = computed<PositionItem[]>(() => data.value?.positions_summary?.items || [])
  const pendingOrders = computed<PendingOrderItem[]>(() => data.value?.pending_orders || [])
  const factors = computed<InstrumentFactor[]>(() => {
    const rawFactors = data.value?.factors || []
    const libInstruments: any[] = (data.value as any)?.factor_library?.instruments || (data.value as any)?.factor_library_snapshot?.instruments || []
    const libMap = new Map<string, any>()
    for (const li of libInstruments) {
      if (li?.instId) libMap.set(li.instId, li)
    }
    return rawFactors.map((f: any) => {
      const lib = libMap.get(f.instId) || {}
      const calc = lib.calculus_dynamics || {}
      const vol = lib.volatility_channel || {}
      const sm = lib.smart_money_derivatives || f.smart_money || {}
      const trend = lib.trend_momentum || {}
      return {
        ...f,
        adx_1h: f.adx_1h ?? trend.adx_1h,
        // ATR 只存在于快照的 volatility_channel 中；此前未透出，导致图表头部显示 $0.0
        // 且风控面板 atrMultiple 恒为 0（永远判定"ATR 非最优"）。
        atr_1h: f.atr_1h ?? vol.atr_1h,
        atr_14: f.atr_14 ?? vol.atr_14,
        atr_pct: f.atr_pct ?? vol.atr_pct ?? vol.atr_1h_pct,
        volatility_regime: vol.volatility_regime,
        calculus: {
          velocity_1h: calc.velocity,
          accel_1h: calc.acceleration,
          jerk_1h: calc.jerk,
          impulse_1h: calc.impulse,
          energy_1h: (lib.definite_integrals || {}).energy_integral,
          action_area_1h: (lib.definite_integrals || {}).deviation_area_integral,
          state_1h: calc.regime,
        },
        smart_money: {
          weighted_long_pct: sm.weighted_long_pct ?? f.smart_money?.weighted_long_pct,
          net_flow_usdt: sm.smart_money_flow_usd ?? f.smart_money?.net_flow_usdt,
          top_win_rate: sm.top_win_rate,
        },
        decision: f.decision || {
          action: f.action,
          confidence: f.confidence,
          leverage: f.leverage,
          margin_usdt: f.margin_usdt,
          entry_price: f.entry_price,
          take_profit_price: f.take_profit_price,
          stop_loss_price: f.stop_loss_price,
          risk_reward_ratio: f.risk_reward_ratio || f.rr_ratio,
          summary_reason: f.decision?.summary_reason || f.reason,
        },
      }
    })
  })
  const macroAssessment = computed(() => data.value?.macro_assessment || t('common.dashboardScanning'))
  // 不再伪造默认模型名：数据缺失时返回空对象，由视图显式呈现「未配置」，避免界面谎报正在使用的模型。
  const llmRuntime = computed(() => data.value?.llm_runtime || {})
  // 巡检日志倒序展示：最新在前（后端按时间正序 tail，此处仅显示层反转）
  const logs = computed(() => [...(data.value?.logs || [])].reverse())
  const isStale = computed(() => data.value?.is_stale ?? false)

  // Actions
  // 批A(2026-09-13)·轮询竞态收口：/api/all 单次 ~387KB，移动弱网下 3s 一轮会堆积
  // （上发未回又发）且**慢响应迟到可把快响应的新数据覆盖回几秒前**（行情倒跳）。
  // 三重守卫：① in-flight 互斥——静默轮询遇忙直接跳过本轮；② 递增 seq——仅接受
  // 发起序号最新的响应落盘；③ 页面隐藏（切后台）暂停轮询，回前台立即补一次。
  let _inflight = false
  let _seq = 0
  let _lastAppliedSeq = 0
  async function fetchDashboard(silent = false) {
    if (_inflight && silent) return
    _inflight = true
    const mySeq = ++_seq
    if (!silent) {
      isRefreshing.value = true
    }
    try {
      const resp = await fetch(`/api/all?_t=${Date.now()}`, {
        headers: {
          'Accept-Encoding': 'gzip, deflate, br',
        },
      })
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}: ${resp.statusText}`)
      }
      const json: DashboardResponse = await resp.json()
      if (mySeq < _lastAppliedSeq) return   // 陈旧响应：已被更新的发起覆盖，禁落盘
      _lastAppliedSeq = mySeq
      data.value = json
      lastUpdated.value = new Date()
      isConnected.value = true
      error.value = null
    } catch (err: any) {
      if (mySeq < _lastAppliedSeq) return
      console.error('[DashboardStore] fetch failed:', err)
      error.value = err.message || t('common.dashboardLoadFailed')
      isConnected.value = false
    } finally {
      _inflight = false
      loading.value = false
      if (!silent) {
        setTimeout(() => {
          isRefreshing.value = false
        }, 300)
      }
    }
  }

  function startPolling(intervalMs = 3000) {
    stopPolling()
    fetchDashboard(false)
    pollingTimer.value = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return   // 后台页不烧流量，回前台见 _onVis
      fetchDashboard(true)
    }, intervalMs)
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', _onVis)
      document.addEventListener('visibilitychange', _onVis)
    }
  }
  function _onVis() {
    if (!document.hidden && pollingTimer.value) fetchDashboard(true)   // 回前台立即补一轮
  }

  function stopPolling() {
    if (pollingTimer.value) {
      clearInterval(pollingTimer.value)
      pollingTimer.value = null
    }
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', _onVis)
  }

  return {
    activeTab,
    data,
    loading,
    isRefreshing,
    error,
    lastUpdated,
    isConnected,
    account,
    positions,
    pendingOrders,
    factors,
    macroAssessment,
    llmRuntime,
    logs,
    isStale,
    showAboutModal,
    fetchDashboard,
    startPolling,
    stopPolling,
  }
})
