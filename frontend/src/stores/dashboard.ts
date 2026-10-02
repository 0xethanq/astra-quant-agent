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
      // ★ 2026-10：原 `lib.calculus_dynamics` 随数理系统退场，改读 7 梯队因子块。
      const tm = lib.trend_momentum || {}
      const flow = lib.volume_money_flow || {}
      const micro = lib.microstructure || {}
      const vp = lib.volume_profile || {}
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
        momentum: {
          macd_hist_1h: tm.macd_hist ?? null,
          macd_accel_1h: tm.macd_accel ?? null,
          // 归一化（占现价 %）：跨标的可比，见 types/dashboard.ts 注释
          macd_hist_pct_1h: tm.macd_hist_pct ?? null,
          macd_accel_pct_1h: tm.macd_accel_pct ?? null,
          macd_momentum_state: tm.macd_momentum_state ?? '--',
          macd_divergence: tm.macd_divergence ?? '--',
          rsi_1h: tm.rsi_1h ?? f.rsi_1h,
          rsi_15m: tm.rsi_15m ?? f.rsi_15m,
          rsi_zone: tm.rsi_zone ?? '--',
        },
        orderflow: {
          cvd_5m_usd: flow.cvd_5m_usd ?? null,
          cvd_1h_usd: flow.cvd_1h_usd ?? null,
          taker_buy_sell_ratio: flow.taker_buy_sell_ratio ?? null,
          cvd_divergence: flow.cvd_divergence ?? '--',
        },
        microstructure: {
          obi_pct: micro.obi_pct ?? null,
          depth_bias: micro.depth_bias ?? f.depth_bias ?? '--',
          bid_ask_depth_ratio: micro.bid_ask_depth_ratio ?? null,
          spread_bps: micro.spread_bps ?? null,
        },
        value_area: {
          vwap_24h: vp.vwap_24h ?? null,
          vwap_bias_pct: vp.vwap_bias_pct ?? tm.vwap_bias_pct ?? null,
          vah: vp.vah ?? null,
          val: vp.val ?? null,
          vpvr_poc: vp.vpvr_poc ?? null,
          value_area_position: vp.value_area_position ?? '--',
          vwap_extreme_band: vp.vwap_extreme_band ?? '--',
        },
        derivatives: {
          funding_rate_pct: sm.funding_rate_pct ?? null,
          next_funding_rate_pct: sm.next_funding_rate_pct ?? null,
          funding_crowding: sm.funding_crowding ?? '--',
          oi_chg_1h_pct: sm.oi_chg_1h_pct ?? null,
          oi_price_quadrant: sm.oi_price_quadrant ?? '--',
          elite_divergence: sm.elite_divergence ?? '--',
          liquidation_bias: sm.liquidation_bias ?? '--',
          basis_annualized_pct: sm.basis_annualized_pct ?? null,
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
          // 三态可观测性（2026-10）：旧载荷没有这几个键 ⇒ 按 model/false 兜底，
          // 保证老缓存不会把"未知"渲染成"被风控拦了"。
          decision_source: f.decision?.decision_source ?? f.decision_source ?? 'model',
          gate_blocked: f.decision?.gate_blocked ?? f.gate_blocked ?? false,
          gate_reason: f.decision?.gate_reason ?? f.gate_reason ?? '',
          model_reason: f.decision?.model_reason ?? f.model_reason ?? '',
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
