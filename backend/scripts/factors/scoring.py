"""复合 alpha 打分与信号建议 —— OKX 7 梯队量化因子版（2026-10 重构）。

## 这一版换掉了什么（以及为什么）

旧版是 8 项加权（`ADX / 主力资金 / RSI+KDJ / OBV+CMF / 盘口 / 微积分 / 定积分 / 概率论`），
其中后三项把"离散 K 线当连续质点"的导数与积分当方向证据。实盘复盘认定：
**它们噪音大、滞后、无可交易含义**，且会让模型对着 v/a/E/P 这些数字编故事。

本版把方向证据换成 `okx_factor_library.md` 的 7 梯队真实量化因子，
每项都有明确的经济学含义与可复现的触发门槛：

| # | 项 | 来源梯队 | 区间 | 触发（简） |
|---|---|---|---|---|
| 1 | 趋势结构 | 盘面 | ±15 | `adx>=22` 且 `rsi>=50` → `+15`（反向 `-15`）；低 ADX 写 `CHOP_RANGE` |
| 2 | 动量与背离 | T4 | ±25 | 柱+加速度同向 `±15`；MACD/RSI 顶底背离 `±10/±5`；RSI 区间修正 `±6` |
| 3 | 衍生品杠杆 | T0 | ±20 | OI 四象限 `±12/±6`；费率拥挤反向 `±10`；清算偏向 `±4` |
| 4 | 订单流意图 | T0.5 | ±15 | 1H CVD 方向 `±6`；Taker 买卖比 `±5`；CVD 量价背离 `±6` |
| 5 | 筹码中枢 | T3 | ±12 | VWAP 极值带 `±12`、价值区 `±6` |
| 6 | 盘口失衡 | T1 | ±10 | OBI `>=20%` → `±10`、`>=8%` → `±5` |

**注意**：`macd_hist` 只出现在第 2 项 —— 第 1 项刻意**只**看 ADX/RSI 结构，
避免同一个 MACD 柱在两处重复计分（会把动量项人为放大一倍）。

**阻尼（乘，不是减）**：1H ATR% ≥ 4.0（波动冲击）或点差 > 15bps（流动性恶化）
⇒ `*= 0.8`；两者同时命中连乘。

**方向性闸门（不是阻尼）**：`funding_crowding` 为极端时，
**只封禁拥挤方向的新单**（`EXTREME_LONG_CROWDED` → 封 `BUY_LONG`；
`EXTREME_SHORT_CROWDED` → 封 `SELL_SHORT`），
**反方向的"反拥挤"单照常放行** —— 把两个方向一起封死，恰好会封掉最该做的
那笔轧空/踩踏反转交易。

## 三条必须守住的语义

1. **缺失 ≠ 中性**：任何一项的输入字段缺失时，该项**跳过计分**（`continue`），
   绝不当 0 分计入 —— 给"没有数据"投中性票会稀释其他项的真实强度。
   `smart_money_derivatives.available=False` 时的资金流字段同理跳过。
2. **对称**：每个门槛都有严格对称的多空分支，不做"偏袒多头"的隐性倾斜。
3. **零注入面**：本模块只读入参 `factors`，不 import 任何取数模块
   （由 `tests/audit/test_directory_docs_current.py::test_factors_scoring_is_dependency_free` 钉住）。
"""

from __future__ import annotations

from typing import Any, Dict

__all__ = [
    "score_composite_alpha", "ADX_TREND_THRESHOLD", "ADX_SIGNAL_THRESHOLD",
    "SCORE_SIGNAL_THRESHOLD", "TREND_ITEM_CAP", "MOMENTUM_ITEM_CAP",
    "DERIVATIVES_ITEM_CAP", "ORDERFLOW_ITEM_CAP", "VALUE_AREA_ITEM_CAP",
    "DEPTH_ITEM_CAP", "TAKER_RATIO_HIGH", "TAKER_RATIO_LOW", "OBI_STRONG_PCT",
    "OBI_MILD_PCT", "ATR_SHOCK_PCT", "SPREAD_WIDE_BPS", "SHOCK_DAMPEN",
    "CROWDED_DIRECTION_BLOCK",
]

#: 第 1 项趋势过滤门槛（写 `trend_regime`）
ADX_TREND_THRESHOLD = 22.0
#: 信号建议的 ADX 门槛 —— **与上者不同**（20 vs 22），不要合并
ADX_SIGNAL_THRESHOLD = 20.0
#: 信号建议的 |score| 门槛
SCORE_SIGNAL_THRESHOLD = 45.0

#: 各分项区间上限（注释里的区间必须与实际累加对得上）
TREND_ITEM_CAP = 15.0
MOMENTUM_ITEM_CAP = 25.0
DERIVATIVES_ITEM_CAP = 20.0
ORDERFLOW_ITEM_CAP = 15.0
VALUE_AREA_ITEM_CAP = 12.0
DEPTH_ITEM_CAP = 10.0

#: Taker 买卖比强/弱门槛
TAKER_RATIO_HIGH = 1.15
TAKER_RATIO_LOW = 0.87
#: OBI 强/中门槛（%）
OBI_STRONG_PCT = 20.0
OBI_MILD_PCT = 8.0
#: 1H ATR% 达到该值视为波动冲击（阻尼）
ATR_SHOCK_PCT = 4.0
#: 点差超过该 bps 视为流动性恶化（阻尼）
SPREAD_WIDE_BPS = 15.0
#: 波动冲击 / 流动性恶化时的阻尼系数
SHOCK_DAMPEN = 0.8
#: 费率极端拥挤 ⇒ **只封禁拥挤方向**的新单（反拥挤单照常放行）
CROWDED_DIRECTION_BLOCK = {
    "EXTREME_LONG_CROWDED": "BUY_LONG",
    "EXTREME_SHORT_CROWDED": "SELL_SHORT",
}

_MISSING = object()


def _pick(block: Any, key: str, default: Any = _MISSING) -> Any:
    """从因子块里取数；块不存在或键不存在 ⇒ `_MISSING`（调用方跳过该项）。"""
    if not isinstance(block, dict) or key not in block:
        return default
    value = block.get(key)
    if value is None or value == "" or value == "--":
        return default
    return value


def _num(value: Any, default: float = 0.0) -> float:
    """宽松数值化：不可转 / 非有限 / 占位符 ⇒ `default`。"""
    if value is _MISSING or value is None:
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if f == f and abs(f) != float("inf") else default


def _cap(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def score_composite_alpha(factors: Dict[str, Any]) -> float:
    """就地写入 `trend_regime` / `composite_alpha_score` / `signal_recommendation`。

    返回最终分数（**阻尼之后**的值，即写入的那个数）。
    """
    score = 0.0

    tm = factors.get("trend_momentum") if isinstance(factors.get("trend_momentum"), dict) else {}
    vc = factors.get("volatility_channel") if isinstance(factors.get("volatility_channel"), dict) else {}
    mf = factors.get("volume_money_flow") if isinstance(factors.get("volume_money_flow"), dict) else {}
    ms = factors.get("microstructure") if isinstance(factors.get("microstructure"), dict) else {}
    sm = factors.get("smart_money_derivatives") if isinstance(factors.get("smart_money_derivatives"), dict) else {}
    vp = factors.get("volume_profile") if isinstance(factors.get("volume_profile"), dict) else {}

    adx = _num(_pick(tm, "adx_1h"))
    # ★ 2026-10「不许假数据」：RSI 缺失时**不许**用 50.0 兜底 ——
    #   50.0 会让下面 `rsi >= 50 ⇒ +15` 凭空加分（趋势分本来就是在判方向，
    #   拿"中性=50"当方向证据是编造）。缺失 ⇒ 本项不计分。
    rsi = _pick(tm, "rsi_14")

    # ---------------------------------------------------------------------
    # 1. 趋势结构 (盘面) —— ±15
    # ⚠️ 这里刻意**不读** `macd_hist`：动量项（第 2 项）已经用它，
    #    两处都读会把同一个 MACD 柱人为放大一倍。
    # ---------------------------------------------------------------------
    score_trend = 0.0
    if adx >= ADX_TREND_THRESHOLD:
        # ⚠️ 必须同时判 `_MISSING` 与 `None`：`_pick` 对**值为 None** 的键也返回
        # `_MISSING` 哨兵，而哨兵不是 None —— 只判 `is not None` 会漏过去，
        # 再经 `_num(哨兵)→0.0` 变成"RSI<50"⇒ **−15 分**（2026-10 自查抓到）。
        if rsi is not _MISSING and rsi is not None:
            score_trend += 15.0 if _num(rsi) >= 50.0 else -15.0
        tm["trend_regime"] = "STRONG_TREND"
    else:
        tm["trend_regime"] = "CHOP_RANGE"
    score += _cap(score_trend, TREND_ITEM_CAP)

    # ---------------------------------------------------------------------
    # 2. 动量与背离 (T4) —— ±25
    # ---------------------------------------------------------------------
    score_mom = 0.0
    hist_v = _pick(tm, "macd_hist")
    accel_v = _pick(tm, "macd_accel")
    if hist_v is not _MISSING and accel_v is not _MISSING:
        h = _num(hist_v)
        a = _num(accel_v)
        if h > 0 and a > 0:
            score_mom += 15.0
        elif h < 0 and a < 0:
            score_mom -= 15.0
    mdiv = _pick(tm, "macd_divergence")
    if mdiv is not _MISSING:
        if str(mdiv) == "BULLISH":
            score_mom += 10.0
        elif str(mdiv) == "BEARISH":
            score_mom -= 10.0
    rdiv = _pick(tm, "rsi_divergence")
    if rdiv is not _MISSING:
        if str(rdiv) == "BULLISH":
            score_mom += 5.0
        elif str(rdiv) == "BEARISH":
            score_mom -= 5.0
    zone = _pick(tm, "rsi_zone")
    if zone is not _MISSING:
        zone_s = str(zone)
        if zone_s in ("BULL_PULLBACK_BUY", "RANGE_OVERSOLD"):
            score_mom += 6.0
        elif zone_s in ("BEAR_RALLY_SELL", "RANGE_OVERBOUGHT"):
            score_mom -= 6.0
        elif zone_s == "OVERBOUGHT_NO_CHASE":
            score_mom -= 6.0          # 超买禁追：不允许再往多头加码
        elif zone_s == "OVERSOLD_NO_CHASE":
            score_mom += 6.0          # 超卖禁追空：不允许再往空头加码
    score += _cap(score_mom, MOMENTUM_ITEM_CAP)

    # ---------------------------------------------------------------------
    # 3. 衍生品杠杆与持仓异动 (T0) —— ±20
    # ---------------------------------------------------------------------
    score_deriv = 0.0
    quadrant = _pick(sm, "oi_price_quadrant")
    if quadrant is not _MISSING:
        q = str(quadrant)
        if q == "LONG_BUILDUP":            # 价涨 + OI 增：主力真开多
            score_deriv += 12.0
        elif q == "SHORT_BUILDUP":         # 价跌 + OI 增：主力真压盘
            score_deriv -= 12.0
        elif q == "SHORT_COVERING":        # 价涨 + OI 减：空头回补的虚涨
            score_deriv -= 6.0
        elif q == "LONG_LIQUIDATION":      # 价跌 + OI 减：多头踩踏出清
            score_deriv += 6.0
    crowding = _pick(sm, "funding_crowding")
    if crowding is not _MISSING:
        c = str(crowding)
        if c == "LONG_CROWDED":
            score_deriv -= 6.0
        elif c == "EXTREME_LONG_CROWDED":
            score_deriv -= 10.0
        elif c == "SHORT_CROWDED":
            score_deriv += 6.0
        elif c == "EXTREME_SHORT_CROWDED":
            score_deriv += 10.0
    liq_bias = _pick(sm, "liquidation_bias")
    if liq_bias is not _MISSING:
        lb = str(liq_bias)
        if lb == "SHORT_SQUEEZE":          # 空头被轧空 ⇒ 短线上行动能
            score_deriv += 4.0
        elif lb == "LONG_CASCADE":         # 多头连环爆仓 ⇒ 短线下行压力
            score_deriv -= 4.0
    score += _cap(score_deriv, DERIVATIVES_ITEM_CAP)

    # ---------------------------------------------------------------------
    # 4. 订单流与 CVD 意图 (T0.5) —— ±15
    # ---------------------------------------------------------------------
    score_flow = 0.0
    cvd_1h = _pick(mf, "cvd_1h_usd")
    if cvd_1h is not _MISSING:
        v = _num(cvd_1h)
        if v > 0:
            score_flow += 6.0
        elif v < 0:
            score_flow -= 6.0
    taker = _pick(mf, "taker_buy_sell_ratio")
    if taker is not _MISSING:
        t = _num(taker, 1.0)
        if t >= TAKER_RATIO_HIGH:
            score_flow += 5.0
        elif t <= TAKER_RATIO_LOW:
            score_flow -= 5.0
    cvd_div = _pick(mf, "cvd_divergence")
    if cvd_div is not _MISSING:
        cd = str(cvd_div)
        if cd == "BULLISH":
            score_flow += 6.0
        elif cd == "BEARISH":
            score_flow -= 6.0
    score += _cap(score_flow, ORDERFLOW_ITEM_CAP)

    # ---------------------------------------------------------------------
    # 5. 筹码中枢与均值回归 (T3) —— ±12
    # ---------------------------------------------------------------------
    score_vp = 0.0
    band = _pick(vp, "vwap_extreme_band")
    if band is not _MISSING:
        b = str(band)
        if b == "LOWER_EXTREME":
            score_vp += 12.0
        elif b == "UPPER_EXTREME":
            score_vp -= 12.0
        elif b == "LOWER_VALUE_AREA":
            score_vp += 6.0
        elif b == "UPPER_VALUE_AREA":
            score_vp -= 6.0
    score += _cap(score_vp, VALUE_AREA_ITEM_CAP)

    # ---------------------------------------------------------------------
    # 6. 盘口微观失衡 (T1) —— ±10
    # ---------------------------------------------------------------------
    score_depth = 0.0
    # ⚠️ 只有 `depth_reliable` 为真才认 OBI 这份证据。2026-10 实测：OKX 永续的
    # **触价档**会被单笔可撤挂单支配（买一在 3~574 张间跳变），但**极端失衡本身
    # 可能是真的**（实测全簿 买17.7 vs 卖1786 张 ⇒ −98% 属实）。
    # 故这里不是"砍掉极端值"，而是"不可信就整项按缺失"（不加也不扣）——
    # 与"缺失≠中性"纪律一致：不给方向分，也不谎称盘口是平衡的。
    reliable = _pick(ms, "depth_reliable")
    if reliable is not _MISSING and str(reliable).lower() in ("true", "1"):
        obi = _pick(ms, "obi_robust_pct")
        if obi is _MISSING:
            obi = _pick(ms, "obi_pct")
        if obi is not _MISSING:
            o = _num(obi)
            if o >= OBI_STRONG_PCT:
                score_depth += 10.0
            elif o >= OBI_MILD_PCT:
                score_depth += 5.0
            elif o <= -OBI_STRONG_PCT:
                score_depth -= 10.0
            elif o <= -OBI_MILD_PCT:
                score_depth -= 5.0
    score += _cap(score_depth, DEPTH_ITEM_CAP)

    # ---------------------------------------------------------------------
    # 阻尼：波动冲击（1H ATR% ≥ 4.0）或流动性恶化（点差 > 15bps）⇒ ×0.8。
    # 两者同时命中连乘。**费率拥挤不参与阻尼** —— 它走下面的方向性闸门，
    # 否则"反拥挤"那笔最该做的交易会被连分一起缩掉。
    # ---------------------------------------------------------------------
    atr_pct_1h = _num(_pick(vc, "atr_1h_pct"))
    spread_bps = _num(_pick(ms, "spread_bps"))
    if atr_pct_1h >= ATR_SHOCK_PCT or spread_bps > SPREAD_WIDE_BPS:
        score *= SHOCK_DAMPEN

    factors["composite_alpha_score"] = round(score, 1)

    # ---------------------------------------------------------------------
    # 决策建议：三道门（分数 / ADX / **只封拥挤方向**）
    # ---------------------------------------------------------------------
    crowded_block = CROWDED_DIRECTION_BLOCK.get(str(_pick(sm, "funding_crowding", "")))
    long_ok = (score >= SCORE_SIGNAL_THRESHOLD and adx >= ADX_SIGNAL_THRESHOLD
               and crowded_block != "BUY_LONG")
    short_ok = (score <= -SCORE_SIGNAL_THRESHOLD and adx >= ADX_SIGNAL_THRESHOLD
                and crowded_block != "SELL_SHORT")
    if long_ok:
        factors["signal_recommendation"] = "BUY_LONG"
    elif short_ok:
        factors["signal_recommendation"] = "SELL_SHORT"
    else:
        factors["signal_recommendation"] = "WAIT"

    return score
