/**
 * K 线工位的纯计算（结构优化阶段 3·F4 抽离）。
 *
 * 这两块原先内嵌在 `ChartWorkstation.vue`（1285 行）里，但都不需要组件上下文：
 * 只吃入参、只返回结果；`symbolPrecision` 甚至**零自由变量**。抽到模块里之后
 * 可被 `vue-tsc` 独立检查，也不再占着组件的体量。
 *
 * `computeRiskReward` 把原先在 computed 内部读的 `store.account` 提到调用点传入；
 * 值完全一样，响应式追踪也仍在 computed 求值期间发生。
 */

export function computeRiskReward(input: {
  entry: number
  sl: number
  tp: number
  side: 'long' | 'short'
  atr: number
  activePosition: any
  /** 可用权益：未持仓时按「可用余额 × 20%」估算单笔保证金（与执行层同口径） */
  availEq: number
}) {
  const { entry, sl, tp, side, atr, activePosition, availEq } = input


  let riskDist = 0
  let rewardDist = 0
  let isLockProfit = false
  let slDiffPct = 0

  if (side === 'long') {
    if (entry > 0 && sl >= entry) {
      isLockProfit = true
      slDiffPct = ((sl - entry) / entry) * 100
      riskDist = 0
    } else {
      riskDist = Math.max(0, entry - sl)
      slDiffPct = entry > 0 ? -((entry - sl) / entry) * 100 : 0
    }
    rewardDist = Math.max(0, tp - entry)
  } else {
    if (entry > 0 && sl <= entry && sl > 0) {
      isLockProfit = true
      slDiffPct = ((entry - sl) / entry) * 100
      riskDist = 0
    } else {
      riskDist = Math.max(0, sl - entry)
      slDiffPct = entry > 0 ? -((sl - entry) / entry) * 100 : 0
    }
    rewardDist = Math.max(0, entry - tp)
  }

  const riskPct = entry > 0 ? (riskDist / entry) * 100 : 0
  const rewardPct = entry > 0 ? (rewardDist / entry) * 100 : 0
  const rrRatio = riskDist > 0 ? rewardDist / riskDist : (isLockProfit ? 99.9 : 0)
  const atrMultiple = atr > 0 ? riskDist / atr : 0

  const isRrCompliant = rrRatio >= 2.0
  const isAtrOptimal = atrMultiple >= 1.8 && atrMultiple <= 2.2

  const hasRealPosition = !!activePosition
  // 未持仓时按「可用余额 × 20%」估算单笔保证金（与执行层 ASTRA_MAX_MARGIN_EQUITY_RATIO 同口径），
  // 不再写死 100U —— 那会让小资金账户看到与真实风险完全不符的预估盈亏。
  let activeMargin = availEq > 0 ? Math.round(availEq * 0.20 * 100) / 100 : 0
  let activeLeverage = 3.0

  if (hasRealPosition && activePosition) {
    const rawMargin = Number(activePosition.margin_usdt ?? activePosition.margin ?? 0)
    if (rawMargin > 0) activeMargin = rawMargin
    const rawLever = Number(activePosition.lever ?? 3)
    if (rawLever > 0) activeLeverage = rawLever
  }

  const estProfitUsd = activeMargin * activeLeverage * (rewardPct / 100)
  const estRiskUsd = activeMargin * activeLeverage * (riskPct / 100)

  return {
    riskDist,
    rewardDist,
    riskPct,
    rewardPct,
    rrRatio,
    atrMultiple,
    isRrCompliant,
    isAtrOptimal,
    hasRealPosition,
    estProfitUsd,
    estRiskUsd,
    isLockProfit,
    slDiffPct,
  }
}

/** 价格精度自适应（零自由变量，纯函数） */
export function symbolPrecision(price: number): number {
  if (price >= 10000) return 1
  if (price >= 100) return 2
  if (price >= 10) return 3
  if (price >= 1) return 3
  return 4
}
