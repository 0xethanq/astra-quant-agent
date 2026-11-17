"""因子库的默认结构（结构优化阶段 4·B3 第二十五刀）。

## 2026-10 重大变更：数理噱头退场，OKX 7 梯队量化因子进场

旧结构里的 `calculus_dynamics` / `definite_integrals` / `probability_theory`
三个 Pillar 是"把离散 K 线当连续质点做微积分与概率论"的产物（速度 v、加速度 a、
冲量 I、做功 E、偏离面积 A、条件延续概率、高阶矩）。实盘复盘认定其
**噪音大、滞后、无可交易含义**，已从**策略决策链路彻底退场**：

- 不再计算（`candles_15m.py` 已摘除 `calculate_calculus` 调用段）；
- 不再进提示词（`scripts/brain/prompt.py` 已删除全部数理文本行）；
- 不再参与打分（`scoring.py` 已换成 7 梯队真实量化因子）；
- 不再进前端载荷（`astra_backend/dashboard_payload/factors.py` 已删除 `calculus` 块）。

**但键位保留**（`retired: True` 标记 + `retired_reason`），因为它们是
`calculus_snapshot.json`（诊断档案）、`ledger_view.py` 的兜底读取链
与三个 Pillar 的历史回归测试的形状契约 —— 直接删键会波及一批与策略无关的
诊断/台账路径。保留即"平滑下线"：值恒为中性默认，且**没有任何策略路径读它**。

新进的 7 梯队因子（默认值在下方对应 Pillar 里）：
T0 衍生品杠杆与费率、T0.5 订单流 CVD、T1 盘口 OBI、T1.5 期权结构、
T2 期限结构基差、T3 筹码分布 VWAP/VPVR、T4 动量 MACD/RSI/布林。

原样搬自 `scripts/factor_library.py::compute_instrument_factors` 开头的
95 行 `factors = {...}` 字面量（后续各刀按需增补）。

## 为什么这段值得抽

`compute_instrument_factors` 是 438 行的单函数，而其中 **95 行是一个纯默认值
字面量** —— 六个 Pillar 的完整结构、每个字段的初值与占位符。它不读任何外部
状态（除了 `time.time()`），却占了整个函数近四分之一，把真正的计算逻辑挤到了
后半段。

抽出来之后，`compute_instrument_factors` 一开头就是"建默认结构 → 逐段填充"，
读者能立刻看到**数据形状**与**计算过程**的分界。

## ⚠️ `timestamp` 用函数调用而不是模块级常量

结构里唯一的"活值"是 `"timestamp": int(time.time())`。**必须每次调用求值** ——
若写成模块级常量（`_DEFAULTS = {... "timestamp": int(time.time())}`），
那么所有标的、所有周期都会拿到**模块首次导入那一刻**的时间戳，
且因子库缓存的时间判定会全线偏早。这是一个很容易在抽取时犯的错，故写在这里。

## 字段语义（原样保留，不得"顺手归一"）

- **Pillar 5 `smart_money_derivatives` 的 `available=False` 是刻意的**：
  OKX CLI 已移除且 smartmoney 无公开 V5 等价接口。数据源缺失时显式
  `available=False` + `"--"` 占位符，**禁止以 50/NEUTRAL/0 中性值冒充真实信号**
  —— 那会让前端把"没有数据"渲染成"信号中性"。注释也原样搬。
- **各 Pillar 的初值口径不同且都有含义**：比率类用 `1.0`（中性比值）、
  百分比类用 `50.0`（中性百分位）、幅度类用 `0.0`。不要统一成 `0.0` —
  那会把"中性"变成"极度看空"。
- `"taker_net_usd": "0 U"` 是**带单位的字符串**，不是数字。
"""
from __future__ import annotations

import time
from typing import Any, Dict

__all__ = ["build_default_factors"]


def build_default_factors(inst_id: str, name: str) -> Dict[str, Any]:
    """按标的名建出因子字典的完整默认结构。

    `timestamp` 在**调用时**取当前时间（见模块文档串）。
    """
    return {
        "instId": inst_id,
        "name": name,
        "timestamp": int(time.time()),
        "price": 0.0,
        "chg24h": 0.0,

        # Pillar 1: Trend & Momentum
        # T4 动量确认：MACD(12,26,9) 柱 + 加速度 + 顶底背离；RSI(14) 情境区间。
        "trend_momentum": {
            "adx_1h": 0.0,
            "rsi_14": 50.0,
            "rsi_1h": 50.0,
            "rsi_15m": 50.0,
            "rsi_zone": "NEUTRAL",
            "rsi_divergence": "NONE",
            "kdj_j": 50.0,
            "vwap_bias_pct": 0.0,
            "trend_regime": "NEUTRAL",
            "macd_dif": 0.0,
            "macd_dea": 0.0,
            "macd_hist": 0.0,
            "macd_accel": 0.0,
            # 2026-10 新增：归一化 MACD（占现价 %）。价格量级差异极大（BTC 柱 27.88
            # vs ARB 柱 −1.8e−05），绝对值在两位小数下会显示成 -0.00/0.00（看着像无动能）。
            "macd_hist_pct": 0.0,
            "macd_accel_pct": 0.0,
            "macd_momentum_state": "NEUTRAL",
            "macd_divergence": "NONE",
        },

        # Pillar 2: Volatility & Channel
        "volatility_channel": {
            "atr_14": 0.0,
            "atr_pct": 0.0,
            "atr_1h": 0.0,
            "atr_1h_pct": 0.0,
            "bb_width_1h": 0.0,
            "bb_squeeze": False,
            "volatility_regime": "NORMAL"
        },

        # Pillar 3: Volume & Money Flow
        # T0.5 订单流：CVD（主动买-主动卖）与 Taker 买卖比、量价背离。
        "volume_money_flow": {
            "vol_ratio_15m": 1.0,
            "obv_flow": "NEUTRAL",
            "cmf_1h": 0.0,
            "taker_net_usd": "0 U",
            "taker_buy_sell_ratio": 1.0,
            "cvd_5m_usd": 0.0,
            "cvd_1h_usd": 0.0,
            "cvd_divergence": "NONE",
            "flow_sentiment": "BALANCED"
        },

        # Pillar 4: Microstructure & Orderbook
        # T1 盘口：OBI 失衡度、Top5/Top20 深度比、有效点差 bps。
        "microstructure": {
            "bid_px": 0.0,
            "ask_px": 0.0,
            "spread_pct": 0.0,
            "spread_bps": 0.0,
            "bid_ask_depth_ratio": 1.0,
            "obi_robust_pct": 0.0,
            "depth_reliable": False,
            "depth_note": "盘口未取回",
            "depth_ratio_20": 1.0,
            "obi_pct": 0.0,
            "depth_bias": "NEUTRAL"
        },

        # Pillar 5: Smart Money & Derivatives
        # T0 衍生品：费率（当期/预测/拥挤度）、OI 与 1H ΔOI 四象限、清算脉冲、基差年化。
        # 缺失语义：无公开等价接口的字段显式 available=False + 占位符，
        # 禁止以 50/NEUTRAL/0 中性值冒充真实信号。
        "smart_money_derivatives": {
            "available": False,
            "reason": "OKX CLI 已移除，smartmoney 无公开 V5 等价接口（待接新数据源）",
            "weighted_long_pct": "--",
            "smart_money_flow_usd": "--",
            "funding_rate_pct": 0.0,
            "next_funding_rate_pct": 0.0,
            "funding_crowding": "NEUTRAL",
            "oi_usd": "--",
            "oi_chg_1h_pct": 0.0,
            "oi_price_quadrant": "NEUTRAL",
            "long_short_ratio": "--",
            # ⚠️ 缺省 `None` 而不是 0.0：比值 0 是"不可能值"，用 0 会读成
            # "精英多空比为零"。缺失一律 `None` ⇒ 提示词渲染成 `--`。
            "elite_account_ratio": None,
            "elite_position_ratio": None,
            "elite_divergence": "NEUTRAL",
            "liquidation_long_usd": 0.0,
            "liquidation_short_usd": 0.0,
            "liquidation_net_usd": 0.0,
            "liquidation_bias": "NEUTRAL",
            # ★ 2026-10：自建"强平价位堆积图"（真实强平成交按价位分桶）
            "liquidation_clusters": [],
            "liquidation_window_min": None,
            "liquidation_cluster_top": "--",
            "basis_annualized_pct": 0.0,
            "loan_rate_usdt": 0.0,
            "avg_long_entry": "--",
            "avg_short_entry": "--",
            "top_win_rate": "--",
            "signal": "UNAVAILABLE"
        },

        # Pillar 7: Volume Profile & Value Area (T3 筹码分布与统计中枢)
        # 24H 滚动 VWAP ± 1σ（价值区）/ ± 2σ（统计极值带）与 VPVR 筹码密集峰 POC。
        "volume_profile": {
            "vwap_24h": 0.0,
            "vwap_sigma_pct": 0.0,
            "vah": 0.0,
            "val": 0.0,
            "vpvr_poc": 0.0,
            "value_area_position": "NEUTRAL",
            "vwap_extreme_band": "NONE"
        },

        # Pillar 8: Options Microstructure (T1.5，仅 BTC/ETH 有完备期权链)
        # 缺失语义：山寨币没有期权市场 ⇒ 显式 available=False，绝不用 0 冒充。
        "options_structure": {
            "available": False,
            "reason": "无期权链数据（仅 BTC/ETH 具备完备期权市场）",
            "atm_iv_pct": "--",
            "risk_reversal_25d_pct": "--",
            "put_call_oi_ratio": "--",
            "max_pain_price": "--",
            "max_pain_expiry": "--",
            "max_pain_total_oi": None,
            "max_pain_reason": "期权持仓量未取回",
            "expiry": "--"
        },

        # ------------------------------------------------------------------
        # 已下线（retired）的三个数理 Pillar 已于 2026-10 **整体删除**：
        # `calculus_dynamics` / `definite_integrals` / `probability_theory`。
        # 原实现保留「零值键位」供诊断/台账读取，但用户明确要求「不存在的因子全部剥离」——
        # 恒零键位会被下游误读成「只是这次没取到」，故连键位一起去掉。
        # 历史台账/快照里的旧键仍可读（`observability.RETIRED_DYNAMICS_FIELDS` 容忍名单）。
        # ------------------------------------------------------------------

        # Composite Factor Score (-100 to +100)
        "composite_alpha_score": 0.0,
        "signal_recommendation": "WAIT"
    }
