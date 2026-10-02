export interface AccountSummary {
  // 第一百九十八刀删除：`margin_ratio` / `trend_direction` 全仓**无生产者**（后端从不发、
  // 前端也没人读）⇒ 类型不该承诺不存在的东西（要恢复请先在后端真的发出来）。

  total_eq: number
  avail_eq: number
  // 该快照取自哪一档（`dashboard_cache.py` 按 OKX 实际档位写入 "demo"/"live"）。
  // 消费点：`KpiRibbon` 的单所回落闸 —— 快照档位必须与用户所选档位一致，
  // 否则会把模拟盘余额当成实盘总权益显示。
  environment?: string
  cash_bal?: number
  upl?: number
  pos_upl_total?: number
  margin_usage_pct?: number
  risk_level?: string
  initial_capital?: number
  cum_net_pnl?: number
  cum_realized_pnl?: number
  cum_roi_pct?: number
  cum_total_fees?: number
}

export interface PositionItem {
  instId: string
  name: string
  side: 'long' | 'short'
  posSide?: string
  pos: string
  lever: string
  margin: string
  margin_usdt?: number
  // 第一百九十八刀删除 `margin_source`：后端发的键是 **`marginSource`**（驼峰，
  // 见 dashboard_payload/factors.py），蛇形这份全仓无人读 ⇒ 死声明。
  notional_usdt?: number
  avgPx: string
  last: string
  markPx?: number | string
  upl: string
  uplRatio: string
  roi_pct?: number
  liqPx?: string | number
  bePx?: string | number
  trailingSl?: number
  exchangeSl?: number
  exchangeTp?: number
  displayStop?: number
  displayTakeProfit?: number
  cloud_oco_verified?: boolean
  protectionStatus?: string
  protectionCoveragePct?: number
  //: 保护腿**触发价类型**（第一百六十七刀后端新增）：`mark`/`last`/`index`；
  //: `'unknown'` = 腿在但该所未上报；`null`/缺省 = 没有该类腿（≠ 未上报）
  protectionSlTriggerPxType?: string | null
  protectionTpTriggerPxType?: string | null
  slTriggerPx?: number | string
  tpTriggerPx?: number | string
  stageDesc?: string
  scaleOutPhase?: number
  scaleOutTp?: number | string
  strategyTag?: string
  venue?: string
  environment?: string
  account_mode?: string
}

export interface PendingOrderItem {
  ordId: string
  instId: string
  name: string
  inst?: string
  side: 'buy' | 'sell'
  side_raw?: string
  posSide: 'long' | 'short'
  px: string
  sz: string
  state: string
  cTime: string
  time?: string
  sl_px?: number
  tp_px?: number
  tpTriggerPx?: string
  slTriggerPx?: string
  lever?: string
  venue?: string
  environment?: string
  account_mode?: string
  margin_usdt?: number
  notional_usdt?: number
}

export interface InstrumentFactor {
  instId: string
  name: string
  type: string
  price: number
  chg24h: number
  high24h: number
  low24h: number
  vol24h: number
  rsi: number
  macd_hist: number
  action?: string
  confidence?: number
  leverage?: number
  margin_usdt?: number
  entry_price?: number
  take_profit_price?: number
  stop_loss_price?: number
  risk_reward_ratio?: string
  reason?: string
  /**
   * ★ 2026-10 三态可观测性：把「模型主动观望 / 物理层拦单 / 模型漏答」分开。
   * `decision_source === 'omitted'` = 该标的压根没出现在模型响应里（契约允许省略），
   * 后端按 fail-closed 兜底为 WAIT —— 它**不是**模型的裁决，展示上必须区分。
   * 缺字段（旧缓存）按 `model` / `false` 处理，向后兼容。
   */
  decision_source?: 'model' | 'omitted'
  gate_blocked?: boolean
  gate_reason?: string
  model_reason?: string
  fundingRate?: number
  oiUsd?: number
  lsRatio?: number
  market_regime?: string
  atr_pct?: number
  adx_1h?: number
  /**
   * ★ 2026-10：原 `calculus`（velocity/accel/jerk/impulse）随数理系统退场，
   * 换成 7 梯队里前端真正会看的五块。数值字段缺失为 `null`/`undefined`，
   * 枚举字段缺失为 `"--"` —— 展示层一律按「未知」渲染，**不得填假 0**。
   */
  momentum?: {
    macd_hist_1h?: number | null
    macd_accel_1h?: number | null
    /** ★ 2026-10：归一化口径（占现价 %）。绝对 MACD 是价格单位，两位小数下
     *  低价币会显示成 -0.00/0.00（看着像"没有动能"）⇒ 展示与排序都用这两个键。 */
    macd_hist_pct_1h?: number | null
    macd_accel_pct_1h?: number | null
    macd_momentum_state?: string
    macd_divergence?: string
    rsi_1h?: number
    rsi_15m?: number
    rsi_zone?: string
  }
  orderflow?: {
    cvd_5m_usd?: number | null
    cvd_1h_usd?: number | null
    taker_buy_sell_ratio?: number | null
    cvd_divergence?: string
  }
  microstructure?: {
    obi_pct?: number | null
    /** 多笔档（numOrders≥3）口径的 OBI；抵消触价档被单笔可撤挂单支配的抖动 */
    obi_robust_pct?: number | null
    /** 两侧多笔档是否足够；false ⇒ 后端打分/信号均**不采信** OBI */
    depth_reliable?: boolean | null
    depth_bias?: string
    bid_ask_depth_ratio?: number | null
    spread_bps?: number | null
  }
  value_area?: {
    vwap_24h?: number | null
    vwap_bias_pct?: number | null
    vah?: number | null
    val?: number | null
    vpvr_poc?: number | null
    value_area_position?: string
    vwap_extreme_band?: string
  }
  derivatives?: {
    funding_rate_pct?: number | null
    next_funding_rate_pct?: number | null
    funding_crowding?: string
    oi_chg_1h_pct?: number | null
    oi_price_quadrant?: string
    elite_divergence?: string
    liquidation_bias?: string
    basis_annualized_pct?: number | null
  }
  smart_money?: {
    weighted_long_pct?: number
    net_flow_usdt?: string
    top_win_rate?: string
  }
  decision?: {
    action: 'BUY_LONG' | 'SELL_SHORT' | 'WAIT'
    confidence: number
    leverage: number
    margin_usdt: number
    entry_price: number
    take_profit_price: number
    stop_loss_price: number
    risk_reward_ratio: string
    summary_reason: string
    /** 2026-10 三态：`model` 模型给出裁决 / `omitted` 该标的未出现在模型响应里 */
    decision_source?: 'model' | 'omitted'
    /** 物理层是否拦下了模型的开仓意图（拦单时 `gate_reason` 有原文） */
    gate_blocked?: boolean
    gate_reason?: string
    /** 模型自己的原话（与展示用 `summary_reason` 区分开） */
    model_reason?: string
  }
  thought_process?: {
    market_structure?: string
    factor_evidence?: string
    volume_and_oi?: string
    risk_reward_evaluation?: string
  }
  position?: any
}

/**
 * US-004 · 账户区组合风险行（/api/all 顶层 portfolio_risk；US-001 预留层口径）。
 * 任一字段 null/缺失 = 未知，前端显「--」，严禁填假 0。
 */
export interface PortfolioRiskRow {
  /** 该数据所属资金环境（如 demo-trading / live）；缺省不展示比对 */
  environment?: string
  /** configured = 引擎按该总预算硬封顶；uncapped = 未配置（0）→ 引擎不封顶，预算相关字段一律 null */
  budget_mode?: 'configured' | 'uncapped' | null
  total_budget_usdt?: number | null
  /** 仅 uncapped 时给出的**展示参考**（最高持仓数×单标的封顶），绝不当作预算/占用率分母 */
  reference_cap_usdt?: number | null
  reserved_usdt?: number | null
  available_usdt?: number | null
  updated_utc?: string
}

export interface LLMRuntime {
  model: string
  provider_name: string
  reasoning_effort: string
  api_format: string
}

// ★ 2026-10 已退役：`MarketRegimeData`（全市场宏观体制）随退役数理引擎一并移除。
//   该块的数据源是已退役的 `calculus_engine`→`calculus/regime.py`，且缺数据时凭空编结论
//   （写死 `atr_pct=1.5`/`adx=20.0` 兜底；实盘 `calculus` 块已不存在）。提示词与看板
//   两处都已停用 ⇒ 后端不再签发该字段，前端也不再声明它（跨层契约门会强制两边一致）。

export interface DashboardResponse {
  timestamp: string
  is_stale: boolean
  account: AccountSummary
  positions_summary: {
    total_count: number
    long_count: number
    short_count: number
    items: PositionItem[]
  }
  pending_orders: PendingOrderItem[]
  factors: InstrumentFactor[]
  macro_assessment?: string
  llm_runtime?: LLMRuntime
  logs: string[]
  trades: any[]
  ai_last_prompt?: string
  today_stats?: any
  performance?: any
  news_intelligence?: any[]
  review?: any
  ai_trading_memory_md?: string
  factor_library?: any
  ai_brain_history?: any[]
  data_health?: any
  state_snapshot?: any
  environment?: 'demo' | 'live'
  /** US-004 · 组合风险占用（预算/已预留/可用余量；未接入时为缺省） */
  portfolio_risk?: PortfolioRiskRow | null
  [key: string]: any
}
