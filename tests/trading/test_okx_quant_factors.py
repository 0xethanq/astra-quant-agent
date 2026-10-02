"""OKX 7 梯队量化因子引擎的**纯计算**回归（2026-10 数理系统退场、因子进场）。

本文件替代原来的 `tests/extraction/test_factors_scoring_extraction.py`
（那是一份 550 行的"微积分/定积分/概率论打分"逐字搬运回归 —— 该打分规则已被
**整体替换**，旧回归的存在前提消失了，故随实现一并退场）。

## 这里守什么

`scripts/factors/okx_quant_factors.py` 承担两件**必须正确**的事：

1. **数值算法**：24H VWAP ± σ 带与 VPVR POC、MACD(12,26,9) 柱与顶底背离、
   RSI 情境区间、CVD 方向与量价背离、OBI 失衡度、清算脉冲、基差年化。
   算错不会报错，只会让模型照着错的筹码位下单。
2. **缺失语义**：无期权链的山寨币必须 `available=False` + reason，
   接口失败必须保持占位符 —— **绝不用 0 冒充"信号中性"**。

## 特别钉住的三条

- **K 线 newest-first**：忘了 `reversed` 指标会整体反向，且不报错；
- **CVD 行索引 1=卖、2=买**：写反会把方向整体颠倒，同样不报错；
- **MACD 与执行层同源**：本模块的 `macd_series` 末值必须与
  `astra_backend.execution.calc_macd_histogram_acceleration` 逐位一致，
  否则"因子库的柱"与"执行层的柱"会变成两个数。
"""

from __future__ import annotations

import sys
import unittest
import urllib.error
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from astra_backend.execution import calc_macd_histogram_acceleration  # noqa: E402
from scripts.factors import okx_quant_factors as qf  # noqa: E402


def _candle(ts, o, h, l, c, v):
    """OKX 原始行形态：`[ts, o, h, l, c, vol, ...]`。"""
    return [str(ts), str(o), str(h), str(l), str(c), str(v)]


class MacdParityTest(unittest.TestCase):
    """MACD 两条实现必须**同源**（否则因子库与执行层报出两个柱值）。"""

    def _prices(self, n=60):
        out = []
        px = 100.0
        for i in range(n):
            px *= 1.0 + (0.004 if i % 3 else -0.003)
            out.append(round(px, 6))
        return out

    def test_series_tail_matches_the_execution_layer(self):
        prices = self._prices()
        dif_exec, dea_exec, hist_exec, accel_exec = calc_macd_histogram_acceleration(prices)
        dif_s, dea_s, hist_s = qf.macd_series(prices)
        self.assertAlmostEqual(dif_s[-1], dif_exec, places=9)
        self.assertAlmostEqual(dea_s[-1], dea_exec, places=9)
        self.assertAlmostEqual(hist_s[-1], hist_exec, places=9)
        self.assertAlmostEqual(hist_s[-1] - hist_s[-2], accel_exec, places=9)

    def test_short_series_is_not_extrapolated(self):
        """样本不足 `slow+signal=35` ⇒ 因子块**显式缺失**，不猜方向、也不假装中性。

        ⚠️ 2026-10 实测踩到的坑：原实现返回「柱=0、态=NEUTRAL」，而**实盘调用方
        只取 24 根 1H K 线** ⇒ 快照里 BTC 的 1H MACD 恒为 0，下游把它读成
        「真实的中性动量」。现在数值键是 `None`、状态是 `INSUFFICIENT_DATA`，
        「没数据」与「中性」再也不会混为一谈。
        """
        out = qf.compute_macd_factors([100.0, 101.0, 102.0])
        self.assertIsNone(out["macd_hist"])
        self.assertIsNone(out["macd_accel"])
        self.assertEqual(out["macd_momentum_state"], "INSUFFICIENT_DATA")
        # 背离同样不许用 "NONE" 冒充"已检测且无背离"
        self.assertEqual(out["macd_divergence"], "INSUFFICIENT_DATA")
        # 反向断言：34 根（差一根）仍算不足；35 根才出真值
        self.assertIsNone(qf.compute_macd_factors([100.0 + i for i in range(34)])["macd_hist"])
        self.assertIsNotNone(qf.compute_macd_factors([100.0 + i for i in range(36)])["macd_hist"])

    def test_normalised_pct_keeps_low_price_signals_visible(self):
        """★ 2026-10 展示事故回归：低价币的绝对 MACD 小到被两位小数抹成 0.00。

        实盘数字：BTC 柱=27.88（价 83,766）而 ARB 柱=−1.8e−05（价 0.203）。
        前端按两位小数渲染 ⇒ ARB/DOGE 显示成 `-0.00 / 0.00`，看着像"没有动能"。
        归一化口径（占现价 %）让两者可比：ARB = −0.0089%、BTC = +0.0333%。
        """
        prices = [0.2 + 1e-4 * i for i in range(40)]      # 低价币走势
        out = qf.compute_macd_factors(prices, price=prices[-1])
        self.assertIsNotNone(out["macd_hist_pct"])
        # 绝对值确实"看不见"（两位小数下 = 0.00），而归一化值是有量纲的
        self.assertLess(abs(float(out["macd_hist"])), 0.005)
        self.assertAlmostEqual(
            out["macd_hist_pct"], float(out["macd_hist"]) / prices[-1] * 100.0, places=3)
        self.assertNotEqual(out["macd_hist_pct"], 0.0)
        # 加速度同样有归一化口径，且与绝对口径同号
        self.assertEqual(out["macd_accel_pct"] > 0, float(out["macd_accel"]) > 0)

    def test_normalised_pct_is_none_when_price_missing(self):
        """价格缺失 ⇒ 归一化键 `None`（与全仓"缺失即缺失"同纪律，不用 0 冒充）。"""
        prices = [100.0 + i for i in range(40)]
        for bad in (0.0, -1.0, None):
            out = qf.compute_macd_factors(prices, price=bad)      # type: ignore[arg-type]
            self.assertIsNone(out["macd_hist_pct"], f"price={bad!r} 不该产出归一化值")
            self.assertIsNone(out["macd_accel_pct"], f"price={bad!r} 不该产出归一化值")
            self.assertIsNotNone(out["macd_hist"], "绝对口径不受影响")

    def test_normalised_keys_missing_when_insufficient(self):
        out = qf.compute_macd_factors([100.0, 101.0], price=100.0)
        self.assertIsNone(out["macd_hist_pct"])
        self.assertIsNone(out["macd_accel_pct"])
        self.assertEqual(out["macd_momentum_state"], "INSUFFICIENT_DATA")

    def test_momentum_state_is_the_hist_accel_cross(self):
        self.assertEqual(qf.classify_macd_momentum_state(1.0, 0.5), "BULL_EXPANDING")
        self.assertEqual(qf.classify_macd_momentum_state(1.0, -0.5), "BULL_EXHAUSTING")
        self.assertEqual(qf.classify_macd_momentum_state(-1.0, -0.5), "BEAR_EXPANDING")
        self.assertEqual(qf.classify_macd_momentum_state(-1.0, 0.5), "BEAR_EXHAUSTING")


class MissingInputMarkerTest(unittest.TestCase):
    """★ 2026-10：K 线拿不到时，默认值不许冒充"真实的中性动量"。

    调用点原先是 `if closes_1h: apply_momentum_tier(...)`（**没有 else**）⇒ 默认块里的
    `柱=0.0 / RSI=50.0 / 态=NEUTRAL` 会被下游当成真因子读走（看板上就是"柱 0.00、RSI 50"）。
    """

    def test_momentum_missing_marks_every_t4_key(self):
        f = {"trend_momentum": {"macd_hist": 0.0, "macd_accel": 0.0, "rsi_1h": 50.0,
                               "rsi_zone": "NEUTRAL", "macd_momentum_state": "NEUTRAL"}}
        qf.mark_momentum_missing(f)
        tm = f["trend_momentum"]
        for key in ("macd_dif", "macd_dea", "macd_hist", "macd_accel",
                    "macd_hist_pct", "macd_accel_pct", "rsi_1h", "rsi_15m"):
            self.assertIsNone(tm[key], f"{key} 必须显式缺失，不能留默认值")
        self.assertEqual(tm["macd_momentum_state"], "INSUFFICIENT_DATA")
        self.assertEqual(tm["rsi_zone"], "INSUFFICIENT_DATA")

    def test_momentum_missing_is_not_a_neutral_signal(self):
        """标缺失后，打分器必须**跳过**动量项（不能按 0 当成中性加分/减分）。

        数值键 ⇒ `None` ⇒ `_pick` 视为 `_MISSING`（跳过该项）；
        枚举键 ⇒ 统一哨兵 `INSUFFICIENT_DATA` ⇒ **不匹配任何打分分支**（白名单式判定，
        所以不会因"未列入的词"而误加/误减分）。两者都不会产生假信号。
        """
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from scripts.factors import scoring
        f = {"trend_momentum": {"macd_hist": 0.0, "macd_accel": 0.0,
                               "macd_momentum_state": "NEUTRAL", "rsi_zone": "NEUTRAL"}}
        qf.mark_momentum_missing(f)
        tm = f["trend_momentum"]
        self.assertIs(scoring._pick(tm, "macd_hist"), scoring._MISSING)
        self.assertIs(scoring._pick(tm, "macd_accel"), scoring._MISSING)
        self.assertEqual(scoring._pick(tm, "macd_momentum_state"), "INSUFFICIENT_DATA")
        self.assertEqual(scoring._pick(tm, "rsi_zone"), "INSUFFICIENT_DATA")
        # 白名单式判定 ⇒ 哨兵不落入任何加减分分支
        for zone_tuple in (("BULL_PULLBACK_BUY", "RANGE_OVERSOLD"),
                           ("BEAR_RALLY_SELL", "RANGE_OVERBOUGHT"),
                           ("OVERBOUGHT_NO_CHASE",), ("OVERSOLD_NO_CHASE",)):
            self.assertNotIn(tm["rsi_zone"], zone_tuple)

    def test_volume_profile_missing_nulls_known_keys(self):
        f = {"volume_profile": {"vwap_24h": 100.0, "vwap_bias_pct": 0.0,
                               "poc_price": 100.0, "unknown_key": 1.0}}
        qf.mark_volume_profile_missing(f)
        self.assertIsNone(f["volume_profile"]["vwap_24h"])
        self.assertIsNone(f["volume_profile"]["vwap_bias_pct"])
        self.assertIsNone(f["volume_profile"]["poc_price"])
        self.assertEqual(f["volume_profile"]["unknown_key"], 1.0, "不认识的键不动")


class DivergenceTest(unittest.TestCase):
    def test_lower_low_with_higher_oscillator_is_bullish(self):
        closes = [10, 9, 8, 9, 10, 9, 7, 8, 9, 10]
        osc = [0, -1, -2, -1, 0, -1, -0.5, 0, 0.5, 1]
        self.assertEqual(qf.detect_divergence(closes, osc), "BULLISH")

    def test_higher_high_with_lower_oscillator_is_bearish(self):
        closes = [10, 11, 12, 11, 10, 11, 13, 12, 11, 10]
        osc = [0, 1, 2, 1, 0, 1, 0.5, 0, -0.5, -1]
        self.assertEqual(qf.detect_divergence(closes, osc), "BEARISH")

    def test_no_divergence_when_both_confirm(self):
        closes = list(range(10, 20))
        osc = list(range(10, 20))
        self.assertEqual(qf.detect_divergence(closes, osc), "NONE")

    def test_divergence_respects_lookback_window(self):
        # 历史远端有背离，但最近 10 根无背离；lookback=10 必须返回 NONE
        old_closes = [10, 9, 8, 9, 10, 9, 7, 8, 9, 10]
        old_osc = [0, -1, -2, -1, 0, -1, -0.5, 0, 0.5, 1]
        recent_closes = list(range(10, 20))
        recent_osc = list(range(10, 20))
        closes = old_closes + recent_closes
        osc = old_osc + recent_osc
        self.assertEqual(qf.detect_divergence(closes, osc, lookback=10), "NONE")

    def test_short_input_is_none_not_a_guess(self):
        self.assertEqual(qf.detect_divergence([1, 2, 3], [1, 2, 3]), "NONE")


class RsiZoneTest(unittest.TestCase):
    def test_bull_regime_zones(self):
        self.assertEqual(qf.classify_rsi_zone(45.0, "1H_SWING_BULL"), "BULL_PULLBACK_BUY")
        self.assertEqual(qf.classify_rsi_zone(60.0, "BULL"), "BULL_HEALTHY")
        self.assertEqual(qf.classify_rsi_zone(80.0, "BULL"), "OVERBOUGHT_NO_CHASE")

    def test_bear_regime_zones(self):
        self.assertEqual(qf.classify_rsi_zone(55.0, "BEAR"), "BEAR_RALLY_SELL")
        self.assertEqual(qf.classify_rsi_zone(35.0, "BEAR"), "BEAR_HEALTHY")
        self.assertEqual(qf.classify_rsi_zone(20.0, "BEAR"), "OVERSOLD_NO_CHASE")

    def test_range_regime_stays_classic(self):
        self.assertEqual(qf.classify_rsi_zone(30.0, "CHOP"), "RANGE_OVERSOLD")
        self.assertEqual(qf.classify_rsi_zone(70.0, "CHOP"), "RANGE_OVERBOUGHT")
        self.assertEqual(qf.classify_rsi_zone(50.0, "CHOP"), "NEUTRAL")


class NewestFirstOrderingTest(unittest.TestCase):
    """⚠️ OKX 原始 K 线是 newest-first：忘了 reverse 会**静默算反**。"""

    def test_series_are_reversed_into_chronological_order(self):
        raw = [_candle(3, 1, 1, 1, 30, 3), _candle(2, 1, 1, 1, 20, 2),
               _candle(1, 1, 1, 1, 10, 1)]
        closes, _highs, _lows, vols = qf.derive_series(raw)
        self.assertEqual(closes, [10.0, 20.0, 30.0])
        self.assertEqual(vols, [1.0, 2.0, 3.0])

    def test_vwap_uses_the_chronological_window(self):
        raw = [_candle(i, 100, 100, 100, 100, 1) for i in range(12, 0, -1)]
        out = qf.compute_vwap_volume_profile(raw, 100)
        self.assertAlmostEqual(out["vwap_24h"], 100.0, places=6)

    def test_too_few_candles_refuse_to_publish_a_vwap(self):
        """样本不足 ⇒ 不发布 VWAP（宁可缺失，也不给一个假的筹码中枢）。"""
        raw = [_candle(2, 1, 1, 1, 100, 1), _candle(1, 1, 1, 1, 100, 1)]
        out = qf.compute_vwap_volume_profile(raw, 100)
        self.assertIsNone(out["vwap_24h"])      # 不许发布 0.0 这种"假中枢"
        self.assertIsNone(out["vah"])


class VolumeProfileTest(unittest.TestCase):
    def _flat(self, n=96, px=100.0, vol=1.0):
        return [_candle(i, px, px, px, px, vol) for i in range(n)]

    def test_insufficient_sample_is_explicitly_missing_not_neutral(self):
        """★ 2026-10「不许假数据」：样本不足 ⇒ `None`/`INSUFFICIENT_DATA`。

        原实现返回 `vwap_24h=0.0` / `vwap_extreme_band="NONE"` —— 提示词会把它
        渲染成"24H VWAP=0.0、不在极值带"，那是**两个假结论**（真实原因是没数据）。
        """
        out = qf.compute_vwap_volume_profile(self._flat(5), 100.0)
        self.assertIsNone(out["vwap_24h"])
        self.assertIsNone(out["vpvr_poc"])
        self.assertEqual(out["vwap_extreme_band"], "INSUFFICIENT_DATA")
        self.assertEqual(out["value_area_position"], "INSUFFICIENT_DATA")

    def test_vwap_and_value_area_bands(self):
        raw = []
        for i in range(96):
            px = 100.0 + (2.0 if i % 2 else -2.0)
            raw.append(_candle(i, px, px + 0.5, px - 0.5, px, 10.0))
        out = qf.compute_vwap_volume_profile(raw, 105.0)
        self.assertAlmostEqual(out["vwap_24h"], 100.0, places=4)
        self.assertGreater(out["vah"], out["vwap_24h"])
        self.assertLess(out["val"], out["vwap_24h"])
        # σ ≈ 2.0 ⇒ 现价 105 落在 +2σ 外侧 ⇒ 极值带标记
        self.assertEqual(out["vwap_extreme_band"], "UPPER_EXTREME")
        self.assertEqual(out["value_area_position"], "ABOVE_VWAP")

    def test_price_inside_the_value_area_is_marked_as_such(self):
        raw = []
        for i in range(96):
            px = 100.0 + (2.0 if i % 2 else -2.0)
            raw.append(_candle(i, px, px + 0.5, px - 0.5, px, 10.0))
        out = qf.compute_vwap_volume_profile(raw, 100.5)
        self.assertEqual(out["vwap_extreme_band"], "INSIDE_VALUE_AREA")

    def test_poc_sits_inside_the_range(self):
        raw = []
        for i in range(96):
            px = 100.0 + (i - 48) * 0.1
            raw.append(_candle(i, px, px, px, px, 100.0 if i > 80 else 1.0))
        out = qf.compute_vwap_volume_profile(raw, 100.0)
        self.assertGreater(out["vpvr_poc"], 100.0)   # 成交量集中在窗口后段（高价区）
        self.assertLessEqual(out["vpvr_poc"], 105.0)


class OrderflowTest(unittest.TestCase):
    def test_cvd_row_index_1_is_sell_and_2_is_buy(self):
        """⚠️ 索引写反会把主动买当主动卖 —— 方向整体颠倒且不报错。"""
        rows_5m = [["t", "100", "250"]]     # sell=100, buy=250
        rows_1h = [["t", "1000", "4000"]]   # sell=1000, buy=4000
        out = qf.compute_cvd_factors(rows_5m, rows_1h, [100.0, 101.0])
        self.assertAlmostEqual(out["cvd_5m_usd"], 150.0)
        self.assertAlmostEqual(out["cvd_1h_usd"], 3000.0)
        self.assertAlmostEqual(out["taker_buy_sell_ratio"], 4.0)

    def test_missing_rows_are_explicitly_missing_not_neutral(self):
        """★ 不许用 0.0/1.0 冒充"零净流/买卖均衡"，也不许用 NONE 冒充"无背离"。"""
        out = qf.compute_cvd_factors(None, None, [])
        self.assertIsNone(out["cvd_1h_usd"])
        self.assertIsNone(out["cvd_5m_usd"])
        self.assertIsNone(out["taker_buy_sell_ratio"])
        self.assertEqual(out["cvd_divergence"], "INSUFFICIENT_DATA")

    def test_a_real_sample_can_still_conclude_no_divergence(self):
        """有数据时"无背离"仍须是 `NONE`（缺失与结论不能混为一谈）。"""
        rows = [["t5", "10", "10"], ["t4", "10", "10"], ["t3", "10", "10"],
                ["t2", "10", "10"], ["t1", "10", "10"]]
        out = qf.compute_cvd_factors(rows, rows, [100.0, 100.0, 100.0, 100.0, 100.0])
        self.assertEqual(out["cvd_divergence"], "NONE")

    def test_price_up_with_net_selling_is_a_bearish_divergence(self):
        # newest-first：最新一根在最前
        rows = [["t5", "50", "10"], ["t4", "50", "10"], ["t3", "50", "10"],
                ["t2", "50", "10"], ["t1", "50", "10"]]
        closes = [100.0, 101.0, 102.0, 103.0, 104.0]
        out = qf.compute_cvd_factors(None, rows, closes)
        self.assertEqual(out["cvd_divergence"], "BEARISH")

    def test_price_down_with_net_buying_is_a_bullish_divergence(self):
        rows = [["t5", "10", "50"], ["t4", "10", "50"], ["t3", "10", "50"],
                ["t2", "10", "50"], ["t1", "10", "50"]]
        closes = [104.0, 103.0, 102.0, 101.0, 100.0]
        out = qf.compute_cvd_factors(None, rows, closes)
        self.assertEqual(out["cvd_divergence"], "BULLISH")

    def test_cvd_divergence_includes_first_bar_in_delta_calculation(self):
        # 验证全窗口累加：首根（t1）大额净买入+100，后续 4 根（t2~t5）各小卖-10
        # 全窗口净差 = 100 - 40 = +60（净流入）；价格下跌 104 -> 100 ⇒ 应为 BULLISH
        # 若有丢弃首根的 bug，后续 4 根累积为 -40（净流出），会被错判为 NONE
        rows = [
            ["t5", "20", "10"],  # -10
            ["t4", "20", "10"],  # -10
            ["t3", "20", "10"],  # -10
            ["t2", "20", "10"],  # -10
            ["t1", "10", "110"], # +100
        ]
        closes = [104.0, 103.0, 102.0, 101.0, 100.0]
        out = qf.compute_cvd_factors(None, rows, closes)
        self.assertEqual(out["cvd_divergence"], "BULLISH")


class DerivativesTest(unittest.TestCase):
    def test_funding_crowding_thresholds_are_symmetric(self):
        self.assertEqual(qf.classify_funding_crowding(0.001), "NEUTRAL")
        self.assertEqual(qf.classify_funding_crowding(0.04), "LONG_CROWDED")
        self.assertEqual(qf.classify_funding_crowding(-0.04), "SHORT_CROWDED")
        self.assertEqual(qf.classify_funding_crowding(0.06), "EXTREME_LONG_CROWDED")
        self.assertEqual(qf.classify_funding_crowding(-0.06), "EXTREME_SHORT_CROWDED")

    def test_oi_price_quadrant_maps_the_four_states(self):
        self.assertEqual(qf.classify_derivatives_quadrant(1.2, 3.0), "LONG_BUILDUP")
        self.assertEqual(qf.classify_derivatives_quadrant(1.2, -3.0), "SHORT_COVERING")
        self.assertEqual(qf.classify_derivatives_quadrant(-1.2, 3.0), "SHORT_BUILDUP")
        self.assertEqual(qf.classify_derivatives_quadrant(-1.2, -3.0), "LONG_LIQUIDATION")
        self.assertEqual(qf.classify_derivatives_quadrant(1.2, 0.2), "NEUTRAL")

    def test_liquidation_sides_are_not_swapped(self):
        """`posSide=long` 是**多头被清算**（强制卖出），不能读成轧空。"""
        details = [
            {"posSide": "long", "sz": "10", "bkPx": "100"},
            {"posSide": "short", "sz": "1", "bkPx": "100"},
        ]
        long_usd, short_usd, bias = qf.summarize_liquidations(details, 1.0)
        self.assertAlmostEqual(long_usd, 1000.0)
        self.assertAlmostEqual(short_usd, 100.0)
        self.assertEqual(bias, "LONG_CASCADE")

    def test_annualized_basis_scales_by_days_to_expiry(self):
        now = 1_700_000_000_000
        ninety_days = now + 90 * 86400000
        got = qf.annualized_basis_pct(103.0, 100.0, ninety_days, now)
        self.assertAlmostEqual(got, 12.1667, places=3)

    def test_basis_is_zero_when_expiry_is_illegal(self):
        now = 1_700_000_000_000
        self.assertEqual(qf.annualized_basis_pct(103.0, 100.0, now - 1000, now), 0.0)
        self.assertEqual(qf.annualized_basis_pct(0.0, 100.0, now + 86400000, now), 0.0)


class DepthTest(unittest.TestCase):
    def test_obi_and_depth_ratio_are_symmetric(self):
        depth = {
            "bids": [[str(100 - i), "10"] for i in range(20)],
            "asks": [[str(101 + i), "5"] for i in range(20)],
        }
        out = qf.compute_depth_factors(depth, 100.5)
        self.assertAlmostEqual(out["bid_ask_depth_ratio"], 2.0)
        self.assertAlmostEqual(out["depth_ratio_20"], 2.0)
        self.assertAlmostEqual(out["obi_pct"], 33.33, places=2)
        self.assertEqual(out["depth_bias"], "STRONG_BID")

    def test_missing_depth_is_explicitly_missing_not_neutral(self):
        """★ 缺盘口 ⇒ `None`/`INSUFFICIENT_DATA`；`0.0` 与 `NEUTRAL` 都是**结论**。"""
        out = qf.compute_depth_factors(None, 100.0)
        self.assertIsNone(out["obi_pct"])
        self.assertIsNone(out["bid_ask_depth_ratio"])
        self.assertIsNone(out["spread_bps"])
        self.assertEqual(out["depth_bias"], "INSUFFICIENT_DATA")
        self.assertFalse(out["depth_reliable"])

    def test_a_single_repostable_quote_does_not_count_as_depth(self):
        """⭐ 2026-10 实测复现：当全簿**只有单笔挂单**时，OBI 不可信。

        真实采样（BTC-USDT-SWAP，间隔 2s）里买一档在 3~574 张之间跳变，
        而买 2~5 档加起来不到 5 张 ⇒ 原始 OBI 能从 +14% 翻到 −94%。
        故：只累计 `numOrders >= 3` 的多笔档；两侧多笔档不足 3 个 ⇒
        `depth_reliable=False`，下游按缺失处理。
        """
        # 逐字抄自 2026-10 的**真实采样 #1**（买一档 3.44 张、卖一档 791.85 张，
        # 2~5 档全是个位数/零点几张，且每档 numOrders 都 < 3）
        depth = {
            "bids": [["83347.6", "3.44", "0", "1"], ["83347.5", "0.01", "0", "1"],
                     ["83347.4", "0.01", "0", "1"], ["83346.7", "0.46", "0", "1"],
                     ["83346.6", "3.88", "0", "1"]],
            "asks": [["83347.7", "791.85", "0", "1"], ["83347.8", "2.6", "0", "2"],
                     ["83347.9", "14.83", "0", "1"], ["83348", "5", "0", "1"],
                     ["83348.1", "3.19", "0", "1"]],
        }
        out = qf.compute_depth_factors(depth, 83347.65)
        self.assertIs(out["depth_reliable"], False)
        self.assertIn("单笔", out["depth_note"])
        # 原始口径仍给出（诊断用）：卖盘厚度压倒性
        self.assertLess(out["obi_pct"], -20.0)

    def test_multi_order_levels_make_the_reading_reliable(self):
        """两侧各有 ≥3 个多笔档 ⇒ 可信，且稳健口径**只算多笔档**。"""
        depth = {
            "bids": [["100", "1", "0", "1"]] + [[f"{100 - i}", "10", "0", "7"]
                                                for i in range(1, 6)],
            "asks": [["101", "50", "0", "1"]] + [[f"{101 + i}", "10", "0", "5"]
                                                 for i in range(1, 6)],
        }
        out = qf.compute_depth_factors(depth, 100.5)
        self.assertIs(out["depth_reliable"], True)
        self.assertEqual(out["depth_note"], "")
        # 稳健口径完全忽略买一那 1 张与卖一那 50 张：50/50 ⇒ OBI 0
        self.assertAlmostEqual(out["obi_robust_pct"], 0.0, places=2)
        # 原始口径则被卖一压到负值（这正说明两者必须分开看）
        self.assertLess(out["obi_pct"], 0.0)

    def test_a_missing_book_is_marked_unreliable_not_neutral(self):
        """盘口没取回 ⇒ `depth_reliable=False` + 明确 note（**不许**当"中性盘口"）。"""
        out = qf.compute_depth_factors(None, 100.0)
        self.assertIs(out["depth_reliable"], False)
        self.assertIn("未取回", out["depth_note"])

    def test_spread_bps_uses_the_quote_midpoint(self):
        depth = {"bids": [["99.9", "1"]], "asks": [["100.1", "1"]]}
        out = qf.compute_depth_factors(depth, 0.0)
        self.assertAlmostEqual(out["spread_bps"], 20.0, places=4)


class OptionsTest(unittest.TestCase):
    def test_altcoin_without_a_chain_is_explicitly_unavailable(self):
        """**不得**用 0 冒充"波动率为零"。"""
        out = qf.compute_options_factors(None, 0.0)
        self.assertIs(out["available"], False)
        self.assertEqual(out["atm_iv_pct"], "--")
        self.assertIn("期权", out["reason"])

    def test_atm_iv_and_skew_come_from_the_near_expiry(self):
        rows = [
            {"instId": "BTC-USD-261030-100000-C", "delta": "0.50", "markVol": "0.40",
             "fwdPx": "100000"},
            {"instId": "BTC-USD-261030-100000-P", "delta": "-0.50", "markVol": "0.42",
             "fwdPx": "100000"},
            {"instId": "BTC-USD-261030-120000-C", "delta": "0.25", "markVol": "0.45",
             "fwdPx": "100000"},
            {"instId": "BTC-USD-261030-80000-P", "delta": "-0.25", "markVol": "0.38",
             "fwdPx": "100000"},
        ]
        out = qf.compute_options_factors(rows, 100000.0, official_put_call_ratio=0.733)
        self.assertIs(out["available"], True)
        self.assertEqual(out["expiry"], "261030")
        self.assertAlmostEqual(out["atm_iv_pct"], 40.0, places=4)
        self.assertAlmostEqual(out["risk_reversal_25d_pct"], 7.0, places=4)
        self.assertAlmostEqual(out["put_call_oi_ratio"], 0.733, places=4)

    def test_put_call_ratio_is_official_not_locally_fabricated(self):
        """官方接口没给 ⇒ 保持 `--`；给了 ⇒ 用官方的数。"""
        self.assertEqual(qf.compute_options_factors(None, 100.0)["put_call_oi_ratio"], "--")
        got = qf.compute_options_factors([], 100.0, official_put_call_ratio=1.25)
        self.assertAlmostEqual(got["put_call_oi_ratio"], 1.25, places=4)
        self.assertEqual(got["max_pain_price"], "--",
                         "Max Pain 无公开行权价分布接口 ⇒ 显式缺失")


if __name__ == "__main__":
    unittest.main()


class QuadrantVocabularyTest(unittest.TestCase):
    """⭐ 跨模块**词表契约**：下游引用的象限名必须真的存在。

    背景（2026-10 实测抓到）：`classify_derivatives_quadrant()` 返回的是
    `LONG_BUILDUP / SHORT_COVERING / SHORT_BUILDUP / LONG_LIQUIDATION / NEUTRAL`，
    而 `signals.py` 与 `pyramiding.py` 里写的是**不存在的** `LONG_UNWIND` /
    `SHORT_SQUEEZE` —— 字符串比较不匹配**不会报错**，只会让那几条门禁
    **永远不触发**（静默失效）。本类把"下游用到的名字 ⊆ 分类器词表"钉死。
    """

    VOCAB = {"LONG_BUILDUP", "SHORT_COVERING", "SHORT_BUILDUP",
             "LONG_LIQUIDATION", "NEUTRAL"}

    def test_the_classifier_only_emits_the_documented_vocabulary(self):
        cases = [(+1.0, +3.0), (+1.0, -3.0), (-1.0, +3.0), (-1.0, -3.0),
                 (+1.0, 0.1), (-1.0, -0.1), (0.0, 0.0)]
        got = {qf.classify_derivatives_quadrant(p, o) for p, o in cases}
        self.assertTrue(got <= self.VOCAB, f"出现未登记取值: {got - self.VOCAB}")
        self.assertIn("LONG_LIQUIDATION", got, "跌+OI减 必须归为多头踩踏")

    def test_downstream_gates_use_real_names(self):
        """扫描 signals.py / pyramiding.py 里 `oi_quadrant` 的比较字面量。"""
        import re
        from pathlib import Path
        root = Path(qf.__file__).resolve().parents[2]
        used = set()
        for rel in ("scripts/trader/signals.py", "scripts/trader/pyramiding.py"):
            src = (root / rel).read_text(encoding="utf-8")
            for m in re.finditer(r'oi_quadrant\s*[!=]=\s*"([A-Z_]+)"', src):
                used.add(m.group(1))
            for m in re.finditer(r'c_quadrant\s*==\s*"([A-Z_]+)"', src):
                used.add(m.group(1))
        self.assertTrue(used, "没扫到任何象限比较 —— 判据在空转（组件可能被改名）")
        self.assertTrue(used <= self.VOCAB,
                        f"下游引用了分类器**不可能返回**的象限名（该门禁永远不触发）: "
                        f"{used - self.VOCAB}")


class MaxPainTest(unittest.TestCase):
    """⭐ 2026-10：Max Pain 从"拿不到（--）"变成**自算**。

    官方 `rubik/stat/option/open-interest-volume-strike` 报 `Parameter expTime error`，
    但 `GET /public/open-interest?instType=OPTION&instFamily=BTC-USD` **直接给每档 OI**
    （实测 1838 行）—— 数据一直在，只是要自己按到期日聚合。
    """

    @staticmethod
    def _oi(inst_id, oi):
        return {"instId": inst_id, "instType": "OPTION", "oi": str(oi)}

    def test_argmin_matches_a_hand_computed_chain(self):
        """手算校验：赔付曲线取最小值的行权价才是 Max Pain。

        链：C100×10、C110×5、P90×4、P100×8（同一到期）
          payout(90)  = P100 实值 8×(100−90)                    = 80
          payout(100) = 无（100 处 call/put 都是平值）           = 0
          payout(110) = C100 实值 10×(110−100)                  = 100
        ⇒ argmin = 100。**严格不等号**是关键：行权价等于 K 的那一档是平值，不计赔付。
        """
        rows = [self._oi("BTC-USD-260930-100-C", 10), self._oi("BTC-USD-260930-110-C", 5),
                self._oi("BTC-USD-260930-90-P", 4), self._oi("BTC-USD-260930-100-P", 8)]
        out = qf.compute_max_pain(rows, forward_px=100.0)
        self.assertEqual(out["max_pain_price"], 100.0)
        self.assertEqual(out["max_pain_expiry"], "260930")
        self.assertEqual(out["max_pain_total_oi"], 27.0)
        self.assertEqual(out["max_pain_reason"], "")

    def test_it_picks_one_expiry_never_mixes_them(self):
        """Max Pain 是**到期日**概念：跨到期混算会把不同结算时间的仓位加在一起。

        近月 OI 很小但仍在阈值内 ⇒ 用近月；低于阈值则退到 OI 最大的到期。
        """
        rows = [
            self._oi("BTC-USD-260930-100-C", 10), self._oi("BTC-USD-260930-110-C", 5),
            self._oi("BTC-USD-260930-90-P", 4), self._oi("BTC-USD-260930-100-P", 8),
            # 远月 OI=100 ⇒ 阈值 20；近月 27 达标，故仍用近月
            self._oi("BTC-USD-261225-200-C", 100),
        ]
        near = qf.compute_max_pain(rows, forward_px=100.0)
        self.assertEqual(near["max_pain_expiry"], "260930")
        # 把近月 OI 压到远月的 20% 以下 ⇒ 改用 OI 最大的到期
        rows[0] = self._oi("BTC-USD-260930-100-C", 0.1)
        rows[1] = self._oi("BTC-USD-260930-110-C", 0.1)
        rows[2] = self._oi("BTC-USD-260930-90-P", 0.1)
        rows[3] = self._oi("BTC-USD-260930-100-P", 0.1)
        far = qf.compute_max_pain(rows, forward_px=100.0)
        self.assertEqual(far["max_pain_expiry"], "261225")

    def test_missing_or_zero_oi_is_a_dash_with_a_reason(self):
        """拿不到就 `--` + 原因，**绝不用 0 冒充**（0 会被读成"痛点在某价"）。"""
        for rows in (None, [], [self._oi("BTC-USD-260930-100-C", 0)]):
            out = qf.compute_max_pain(rows, forward_px=100.0)
            self.assertEqual(out["max_pain_price"], "--")
            self.assertTrue(out["max_pain_reason"], "必须给出原因")
        self.assertIn("未取回", qf.compute_max_pain(None)["max_pain_reason"])
        self.assertIn("0", qf.compute_max_pain([self._oi("BTC-USD-260930-100-C", 0)])["max_pain_reason"])

    def test_malformed_ids_are_skipped_not_crashed(self):
        out = qf.compute_max_pain([{"instId": "garbage"}, {"instId": ""}], forward_px=1.0)
        self.assertEqual(out["max_pain_price"], "--")


class LiquidationClusterTest(unittest.TestCase):
    """⭐ 2026-10：自建"强平价位堆积图"（替代第三方清算热力图）。

    原料是 OKX 公开的**已发生强平成交明细**（`bkPx`/`sz`/`posSide`），
    实测 limit=100 覆盖约 416 分钟。输出必须带 `liquidation_window_min`，
    免得被下游当成"24h 热力图"。
    """

    def test_clusters_are_usd_ranked_and_carry_the_window(self):
        det = [
            {"bkPx": "83000", "sz": "10", "posSide": "long", "time": 1_000_000},
            {"bkPx": "83010", "sz": "10", "posSide": "long", "time": 1_600_000},
            {"bkPx": "83050", "sz": "2", "posSide": "long", "time": 1_600_000},
            {"bkPx": "84000", "sz": "5", "posSide": "short", "time": 1_600_000},
        ]
        out = qf.summarize_liquidation_clusters(det, ct_val=0.01, price=83500.0)
        self.assertEqual(len(out["liquidation_clusters"]), 3)
        top = out["liquidation_clusters"][0]
        # 0.1% 带宽 = 83.5 ⇒ 83000/83010 落同一桶（长头强平 20 张）
        self.assertEqual(top["side"], "long")
        self.assertEqual(top["count"], 2)
        # 美元额按**实际强平价**加权（83000 与 83010 两笔），不是桶价
        self.assertAlmostEqual(top["usd"], (10 * 83000 + 10 * 83010) * 0.01, places=2)
        # 报告价位是**量加权平均强平价**（83000 与 83010 各 10 张 ⇒ 83005）
        self.assertEqual(top["price"], 83005.0)
        self.assertAlmostEqual(top["distance_pct"], (83005.0 - 83500.0) / 83500.0 * 100, places=2)
        # 窗口 = 时间跨度（600s = 10 分钟），诚实告知不是 24h
        self.assertAlmostEqual(out["liquidation_window_min"], 10.0, places=1)
        self.assertIn("多头", out["liquidation_cluster_top"])
        self.assertIn("万 U", out["liquidation_cluster_top"])

    def test_short_liquidations_are_labelled_short(self):
        det = [{"bkPx": "84000", "sz": "5", "posSide": "short", "time": 1}]
        out = qf.summarize_liquidation_clusters(det, ct_val=0.01, price=84000.0)
        self.assertEqual(out["liquidation_clusters"][0]["side"], "short")
        self.assertIn("空头", out["liquidation_cluster_top"])

    def test_empty_details_yield_an_empty_list_not_a_fake_level(self):
        out = qf.summarize_liquidation_clusters(None, 0.01, 100.0)
        self.assertEqual(out["liquidation_clusters"], [])
        self.assertIsNone(out["liquidation_window_min"])
        self.assertEqual(out["liquidation_cluster_top"], "--")


class TransportResilienceTest(unittest.TestCase):
    """取数层的**限频韧性**（2026-10 实测：静默 429 会把因子打成 0）。

    实盘症状：`cvd_1h_usd` 长期为 0、`taker_buy_sell_ratio` 恒为 1.0 ——
    根因是 Rubik 系列限频 5 次/2 秒，而引擎每标的要打 5 个 Rubik 接口，
    6 标的池一轮 30 次，突发把其中一两次打成 429 后被静默吞掉。
    故本类钉住两条防线：**进程内节流**与**429 指数退避重试**。
    """

    #: 生产间隔常量（`_reset_cache_for_tests` 会把模块全局置 0 以便其他用例快跑，
    #: 故这里必须用**显式常量**验证节流，而不是模块全局）
    PROD_INTERVAL = 0.42

    def setUp(self):
        qf._reset_cache_for_tests()
        qf._RUBIK_LAST_AT[0] = 0.0
        self.addCleanup(qf._reset_cache_for_tests)

    def test_rubik_paths_are_throttled_but_others_are_not(self):
        """Rubik 路径要等足间隔；非 Rubik 路径**零等待**（否则整轮被拖慢）。"""
        sleeps = []
        with mock.patch.object(qf, "_RUBIK_MIN_INTERVAL", self.PROD_INTERVAL), \
             mock.patch.object(qf.time, "sleep", lambda s: sleeps.append(s)), \
             mock.patch.object(qf.time, "time", lambda: 1000.0):
            qf._RUBIK_LAST_AT[0] = 1000.0          # 刚请求过 ⇒ 下一次要等满间隔
            qf._throttle_rubik("/api/v5/rubik/stat/taker-volume")
            self.assertEqual(len(sleeps), 1)
            self.assertAlmostEqual(sleeps[0], self.PROD_INTERVAL, places=6)
            sleeps.clear()
            qf._throttle_rubik("/api/v5/public/funding-rate")
            self.assertEqual(sleeps, [], "非 Rubik 路径不得被节流")

    def test_local_failures_do_not_consume_the_rate_limit_slot(self):
        """⭐ 关键口径：**只有真正到达服务器**的 Rubik 请求才记账。

        本地失败（DNS 解析不了 / 连接被拒 / 测试打桩抛 OSError）根本没占用
        交易所配额，不该让后续请求为它排队 —— 否则打桩测试会白睡几十分钟。
        """
        def _boom(req, timeout=None):
            raise OSError("DNS 解析失败")

        with mock.patch.object(qf.urllib.request, "urlopen", _boom):
            self.assertIsNone(qf.fetch_taker_volume("BTC", "5m"))
        self.assertEqual(qf._RUBIK_LAST_AT[0], 0.0, "本地失败不得记账")

        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"code":"0","data":[["t","1","2"]]}'

        with mock.patch.object(qf.urllib.request, "urlopen",
                               lambda req, timeout=None: _Resp()):
            qf.fetch_taker_volume("BTC", "1H")
        self.assertGreater(qf._RUBIK_LAST_AT[0], 0.0, "到达服务器才记账")

    def test_a_429_is_retried_before_giving_up(self):
        """第一次 429 ⇒ 退避后重试；第二次成功 ⇒ **必须返回数据**（不能返回 None）。"""
        calls = {"n": 0}

        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"code":"0","data":[["t","1","2"]]}'

        def _fake_urlopen(req, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "rate limited", {}, None)
            return _Resp()

        with mock.patch.object(qf.urllib.request, "urlopen", _fake_urlopen), \
             mock.patch.object(qf.time, "sleep", lambda s: None):
            rows = qf.fetch_taker_volume("BTC", "1H")
        self.assertEqual(calls["n"], 2, "429 后应重试一次")
        self.assertEqual(rows, [["t", "1", "2"]])

    def test_a_persistent_429_yields_none_not_a_fake_value(self):
        """连续 429（超过重试次数）⇒ 返回 `None`（调用方显式降级，**不填 0**）。"""
        def _always_429(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 429, "rate limited", {}, None)

        with mock.patch.object(qf.urllib.request, "urlopen", _always_429), \
             mock.patch.object(qf.time, "sleep", lambda s: None):
            self.assertIsNone(qf.fetch_taker_volume("BTC", "5m"))

    def test_a_successful_fetch_is_cached_for_thirty_seconds(self):
        """TTL 缓存：同一 (ccy, period) 在 30s 内只打一次外呼。"""
        calls = {"n": 0}

        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"code":"0","data":[["t","5","9"]]}'

        def _urlopen(req, timeout=None):
            calls["n"] += 1
            return _Resp()

        with mock.patch.object(qf.urllib.request, "urlopen", _urlopen), \
             mock.patch.object(qf.time, "sleep", lambda s: None):
            first = qf.fetch_taker_volume("BTC", "5m")
            second = qf.fetch_taker_volume("BTC", "5m")
        self.assertEqual(first, second)
        self.assertEqual(calls["n"], 1, "第二次应命中缓存")


class NoFakeDataWhenSourcesFailTest(unittest.TestCase):
    """★ 2026-10「不许假数据」总门：**所有数据源都失败**时，因子块里不许留下
    "看起来合理"的常量（它们是**结论**，不是缺失）。

    历史坑（逐条实测过）：`rsi_1h=50.0`（读作"中性 RSI"）、`taker_buy_sell_ratio=1.0`
    （"买卖均衡"）、`bid_ask_depth_ratio=1.0`（"深度均衡"）、`obi_pct=0.0`（"零失衡"）、
    `cvd_5m_usd=0.0`（"零净流"）、`vwap_24h=0.0`（"价位在 0"）、`depth_bias="NEUTRAL"`、
    `rsi_zone="NEUTRAL"`、`funding_crowding="NEUTRAL"`、`oi_price_quadrant="NEUTRAL"`、
    `liquidation_*_usd=0.0`（"零清算"）、`adx_1h=0.0`（"无趋势"）、`rsi_14=50.0`。

    本门把它们全部钉成"缺失"：数值 `None`、状态 `INSUFFICIENT_DATA`、
    字符串型 `--`。
    """

    NUMERIC = {
        "trend_momentum": ("rsi_1h", "rsi_15m", "rsi_14", "macd_hist", "macd_accel",
                           "macd_hist_pct", "macd_accel_pct", "adx_1h", "vwap_bias_pct"),
        "volume_money_flow": ("cvd_5m_usd", "cvd_1h_usd", "taker_buy_sell_ratio"),
        "microstructure": ("obi_pct", "obi_robust_pct", "bid_ask_depth_ratio",
                           "depth_ratio_20", "spread_bps"),
        "volume_profile": ("vwap_24h", "vah", "val", "vpvr_poc", "vwap_sigma_pct"),
        "smart_money_derivatives": ("funding_rate_pct", "oi_chg_1h_pct",
                                    "liquidation_long_usd", "liquidation_short_usd",
                                    "basis_annualized_pct"),
    }
    STATES = {
        "trend_momentum": ("rsi_zone", "macd_momentum_state", "rsi_divergence",
                           "macd_divergence"),
        "volume_money_flow": ("cvd_divergence",),
        "microstructure": ("depth_bias",),
        "volume_profile": ("value_area_position", "vwap_extreme_band"),
        "smart_money_derivatives": ("funding_crowding", "oi_price_quadrant",
                                    "elite_divergence", "liquidation_bias"),
    }
    STRINGS = {"smart_money_derivatives": ("oi_usd", "long_short_ratio")}

    def _all_sources_failed(self):
        from scripts.factors.defaults import build_default_factors
        f = build_default_factors("BTC-USDT-SWAP", "BTC")
        qf.apply_momentum_tier(f, closes_1h=[], closes_15m=[], trend="", price=0.0)
        qf.apply_volume_profile_tier(f, raw_candles_15m=[], price=0.0)
        qf.apply_microstructure_tier(f, depth=None, price=0.0)
        qf.apply_orderflow_tier(f, taker_5m=None, taker_1h=None, closes_1h=[])
        qf.apply_derivatives_tier(f, snapshot={}, ct_val=None, price_chg_1h_pct=None)
        # 另外两条**门面**失败路径（不在梯队函数内）也要标缺失：
        #   15M K 线取不到 ⇒ `mark_15m_missing`（rsi_14/vwap_bias_pct…）
        #   指标批取不到 ⇒ 门面预置 `adx_1h=None`
        from scripts.factors.candles_15m import mark_15m_missing
        mark_15m_missing(f)
        f["trend_momentum"]["adx_1h"] = None
        return f

    def test_numeric_keys_are_none_not_plausible_constants(self):
        f = self._all_sources_failed()
        bad = [(blk, k, f[blk][k]) for blk, keys in self.NUMERIC.items()
               for k in keys if f[blk].get(k) is not None]
        self.assertEqual(bad, [], f"这些键仍是'看似合理'的常量（会被读成结论）：{bad}")

    def test_state_keys_say_insufficient_data(self):
        f = self._all_sources_failed()
        bad = [(blk, k, f[blk][k]) for blk, keys in self.STATES.items()
               for k in keys if f[blk].get(k) != "INSUFFICIENT_DATA"]
        self.assertEqual(bad, [], f"这些状态键仍在下'结论'：{bad}")

    def test_string_keys_use_the_documented_missing_marker(self):
        f = self._all_sources_failed()
        for blk, keys in self.STRINGS.items():
            for k in keys:
                self.assertEqual(f[blk].get(k), "--", f"{blk}.{k} 应为 '--'")

    def test_a_real_source_still_produces_real_values(self):
        """反向：真数据进来时必须照常算出真值（新语义不能把真值也抹成缺失）。"""
        raw = [_candle(i, 100.0 + (i % 3), 101.0, 99.0, 100.0 + (i % 3), 10.0)
               for i in range(96)]
        f = self._all_sources_failed()
        qf.apply_volume_profile_tier(f, raw_candles_15m=raw, price=100.0)
        qf.apply_microstructure_tier(
            f, depth={"bids": [["100", "10", "0", "5"]] * 5,
                      "asks": [["100", "10", "0", "5"]] * 5}, price=100.0)
        self.assertIsNotNone(f["volume_profile"]["vwap_24h"])
        self.assertIsNotNone(f["microstructure"]["obi_pct"])
        self.assertTrue(f["microstructure"]["depth_reliable"])
        self.assertEqual(f["microstructure"]["depth_bias"], "NEUTRAL")
