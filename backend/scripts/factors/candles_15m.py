"""15M K 线 → 技术指标（结构优化阶段 4·B3 第三十二刀）。

原样搬自 `scripts/factor_library.py::compute_instrument_factors` 的
「15M Candles → ATR, RSI, VWAP Bias, Vol Ratio, OBV」一段。

## 2026-10 变更：Pillar 6（微积分/定积分/概率）整段摘除

原实现紧随其后还有一段"Pillar 6: Calculus, Definite Integrals & Probability
Theory"，把 15M 的 `closes/highs/lows/vols` 喂给 `calculate_calculus` 并写回
`factors["calculus_dynamics"] / definite_integrals / probability_theory`。
该段已随**数理系统整体退场**删除（不再计算、不进提示词、不参与打分；
三个 Pillar 的键位在 `defaults.py` 里保留为 `retired: True` 的诊断占位）。

于是本模块的注入面**收缩为零**：不再需要 `calculate_calculus` 由调用方传入。

## ⚠️ 本模块**没有**取数依赖（这是刻意的）

`fetch_candles(...)` 留在门面，本模块只吃**已经取回的** `raw_candles`。
于是：

- **零新增注入面** —— 门面对 `fetch_candles` 的 `patch.object` 缝不受影响；
- 本模块可以纯函数式地测（喂构造 K 线即可），不需要任何 mock。

## 五处易错点（均原样保留）

1. **K 线是"倒序"的**：`reversed(raw_candles)` 转成时间正序之后再算。
   OKX 返回 newest-first，若忘了 reverse，ATR/RSI 全部反向计算 —— 而且
   **不会报错**，只会给出错误的数值。
2. **索引含义**：`c[2]=high, c[3]=low, c[4]=close, c[5]=volume`。
   把 2/3 写反（high/low 互换）在 `max(high-low, ...)` 里**看不出来**
   （绝对值对称），但会让 RSI 的 close 序列错位。
3. **ATR 是"简单移动平均"不是 Wilder 平滑**：`sum(tr_list[-14:]) / 14`。
4. **RSI 的 `avg_l == 0` 分支给 `rs = 100.0`**（不是除零）。
5. **`atr_pct` / `vwap_bias_pct` 都会再除以 `price`**：
   `price > 0` 与 `v_sum > 0` 是**两道独立的除零守卫**，不能合并。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

__all__ = ["derive_candle_series", "compute_15m_indicators"]

#: K 线列索引（OKX: [ts, open, high, low, close, vol, ...]）
_COL_HIGH = 2
_COL_LOW = 3
_COL_CLOSE = 4
_COL_VOL = 5


def derive_candle_series(raw_candles: List[Any], *, safe_float
                         ) -> Tuple[List[float], List[float], List[float], List[float]]:
    """`raw_candles` → `(closes, highs, lows, vols)`，**时间正序**。

    ⚠️ `reversed(...)` 是必须的：OKX 返回 newest-first。忘了 reverse 不会报错，
    只会让 ATR/RSI/OBV 全部按反向时间计算。
    """
    closes = [safe_float(c[_COL_CLOSE]) for c in reversed(raw_candles)]
    highs = [safe_float(c[_COL_HIGH]) for c in reversed(raw_candles)]
    lows = [safe_float(c[_COL_LOW]) for c in reversed(raw_candles)]
    vols = [safe_float(c[_COL_VOL]) for c in reversed(raw_candles)]
    return closes, highs, lows, vols


def compute_15m_indicators(raw_candles: List[Any], factors: Dict[str, Any], *,
                           safe_float) -> Tuple[
                               List[float], List[float], List[float], List[float]]:
    """按原顺序写入 15M 指标，返回派生序列。

    调用方保证 `raw_candles` 非空且 `len >= 15`（门面里的判断是 `>= 15`）。
    """
    closes, highs, lows, vols = derive_candle_series(raw_candles, safe_float=safe_float)

    # ATR 14
    tr_list = []
    for i in range(1, len(closes)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        tr_list.append(tr)
    if len(tr_list) >= 14:
        atr = sum(tr_list[-14:]) / 14
        factors["volatility_channel"]["atr_14"] = round(atr, 4)
        if factors["price"] > 0:
            factors["volatility_channel"]["atr_pct"] = round(atr / factors["price"] * 100, 2)

    # RSI 14
    diffs = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in diffs]
    losses = [-d if d < 0 else 0 for d in diffs]
    if len(gains) >= 14:
        avg_g = sum(gains[-14:]) / 14
        avg_l = sum(losses[-14:]) / 14
        rs = (avg_g / avg_l) if avg_l > 0 else 100.0
        factors["trend_momentum"]["rsi_14"] = round(100.0 - (100.0 / (1.0 + rs)), 1)
    else:
        # ★ 不足 14 根算不出 RSI ⇒ 显式缺失。默认块的 `rsi_14=50.0` 会被
        #   打分侧读成"中性偏多"（`rsi >= 50 ⇒ +15` 趋势分）—— 那 15 分是假的。
        factors["trend_momentum"]["rsi_14"] = None

    # VWAP Bias
    pv_sum = sum(closes[i] * vols[i] for i in range(len(closes)))
    v_sum = sum(vols)
    if v_sum > 0:
        vwap = pv_sum / v_sum
        factors["trend_momentum"]["vwap_bias_pct"] = round((factors["price"] - vwap) / vwap * 100, 2)
    else:
        # ★ 成交量合计为 0 ⇒ 算不出 VWAP：显式缺失，不用默认 0.0 冒充"正好贴在 VWAP 上"
        factors["trend_momentum"]["vwap_bias_pct"] = None

    # Vol Ratio（最后一根已收盘的量 vs 它前面 5 根均量；杜绝 vols[-1] 跳动未收盘 K 线把量比拉至 0.03）
    if len(vols) >= 7:
        avg_v5 = sum(vols[-7:-2]) / 5
        if avg_v5 > 0:
            factors["volume_money_flow"]["vol_ratio_15m"] = round(vols[-2] / avg_v5, 2)

    # OBV
    obv = 0
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]: obv += vols[i]
        elif closes[i] < closes[i-1]: obv -= vols[i]
    factors["volume_money_flow"]["obv_flow"] = "BULL_FLOW" if obv > 0 else ("BEAR_FLOW" if obv < 0 else "NEUTRAL")

    return closes, highs, lows, vols


def mark_15m_missing(factors: Dict[str, Any]) -> None:
    """15M K 线拿不到时，把 15M 派生的因子键**显式标缺失**。

    ⚠️ 2026-10「不许假数据」审计：门面的 15M 分支是
    `if d["data"] and len(...) >= 15: compute_15m_indicators(...)` **没有 else**
    ⇒ 取数失败时 `build_default_factors` 的默认值留在原地：
    `rsi_14=50.0`（打分侧 `rsi >= 50 ⇒ +15` **凭空加 15 分趋势分**）、
    `vwap_bias_pct=0.0`（"正好贴在 VWAP 上"）、`atr/atr_pct/vol_ratio/obv_flow`。
    这里与 `okx_quant_factors.mark_momentum_missing` 同纪律：数值 `None`、状态缺失。
    """
    tm = factors.setdefault("trend_momentum", {})
    for key in ("rsi_14", "vwap_bias_pct", "vol_ratio", "ema21_slope_pct"):
        tm[key] = None
    vc = factors.setdefault("volatility_channel", {})
    for key in ("atr_14", "atr_pct", "atr", "atr_15m"):
        vc[key] = None
    mf = factors.setdefault("volume_money_flow", {})
    mf["obv_flow"] = "INSUFFICIENT_DATA"


__all__ = ["derive_candle_series", "compute_15m_indicators", "mark_15m_missing"]
