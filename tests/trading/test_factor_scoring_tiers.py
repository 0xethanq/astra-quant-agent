"""`scripts/factors/scoring.py` 的 **7 梯队量化因子版**回归（2026-10 重构）。

## 这一版替换掉了什么

旧版是 8 项打分，其中第 6/7/8 项读 `calculus_dynamics` / `definite_integrals` /
`probability_theory`（把离散 K 线当连续质点的导数、积分与高阶矩）。
那三项已随数理系统**整体退场**，本文件与实现一同替换了旧的
`tests/extraction/test_factors_scoring_extraction.py`（旧回归的前提已消失）。

## 判据

| 分项 | 区间 | 隔离触发 |
|---|---|---|
| 趋势结构 | ±20 | `adx>=22` 且 `rsi>=50` → +15；MACD 柱方向 ±5 |
| 动量与背离 | ±25 | 柱+加速度同向 ±15；MACD 背离 ±10；RSI 背离 ±5；RSI 区间 ±6 |
| 衍生品杠杆 | ±20 | OI 四象限 ±12/±6；费率拥挤反向 ±10；清算偏向 ±4 |
| 订单流意图 | ±15 | 1H CVD ±6；Taker 比 ±5；CVD 背离 ±6 |
| 筹码中枢 | ±12 | VWAP 极值带 ±12、价值区 ±6 |
| 盘口失衡 | ±10 | OBI `>=20%` → ±10、`>=8%` → ±5 |

外加两处**乘法阻尼**（费率极端 ×0.7、波动冲击/点差过宽 ×0.8）与
"信号建议"的三道门（|score| / ADX / 无极端拥挤）。
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.factors.defaults import build_default_factors  # noqa: E402
from scripts.factors.scoring import (  # noqa: E402
    ADX_SIGNAL_THRESHOLD,
    ADX_TREND_THRESHOLD,
    DEPTH_ITEM_CAP,
    DERIVATIVES_ITEM_CAP,
    MOMENTUM_ITEM_CAP,
    ORDERFLOW_ITEM_CAP,
    SCORE_SIGNAL_THRESHOLD,
    TREND_ITEM_CAP,
    VALUE_AREA_ITEM_CAP,
    score_composite_alpha,
)


def _factors(**over):
    """中性基线：所有分项为 0 且**不触发任何门槛**。"""
    f = build_default_factors("BTC-USDT-SWAP", "BTC")
    f.update(over.pop("_top", {}))
    for pillar, values in over.items():
        f[pillar].update(values)
    return f


def _score(**over):
    return score_composite_alpha(_factors(**over))


class NeutralBaselineTest(unittest.TestCase):
    def test_neutral_factors_score_zero_and_wait(self):
        f = _factors()
        self.assertEqual(score_composite_alpha(f), 0.0)
        self.assertEqual(f["composite_alpha_score"], 0.0)
        self.assertEqual(f["signal_recommendation"], "WAIT")
        self.assertEqual(f["trend_momentum"]["trend_regime"], "CHOP_RANGE")

    def test_caps_add_up_close_to_the_legacy_scale(self):
        self.assertEqual(ADX_TREND_THRESHOLD, 22.0)
        self.assertNotEqual(ADX_TREND_THRESHOLD, ADX_SIGNAL_THRESHOLD)
        self.assertEqual(SCORE_SIGNAL_THRESHOLD, 45.0)
        total = (TREND_ITEM_CAP + MOMENTUM_ITEM_CAP + DERIVATIVES_ITEM_CAP
                 + ORDERFLOW_ITEM_CAP + VALUE_AREA_ITEM_CAP + DEPTH_ITEM_CAP)
        self.assertLessEqual(total, 110.0, "分项上限之和应贴近原有 ±100 量级")
        self.assertGreaterEqual(total, 90.0)


class TrendItemTest(unittest.TestCase):
    def test_adx_trend_with_rsi_direction(self):
        self.assertEqual(_score(trend_momentum={"adx_1h": 25.0, "rsi_14": 60.0}), 15.0)
        self.assertEqual(_score(trend_momentum={"adx_1h": 25.0, "rsi_14": 40.0}), -15.0)

    def test_macd_hist_is_not_double_counted_in_the_trend_item(self):
        """⚠️ 第 1 项只认 ADX/RSI 结构；MACD 柱只在第 2 项计分一次。"""
        self.assertEqual(
            _score(trend_momentum={"adx_1h": 25.0, "rsi_14": 60.0, "macd_hist": 1.0}),
            15.0)

    def test_item_is_capped(self):
        got = _score(trend_momentum={"adx_1h": 30.0, "rsi_14": 70.0})
        self.assertEqual(got, TREND_ITEM_CAP)

    def test_chop_regime_is_written_when_adx_is_low(self):
        f = _factors(trend_momentum={"adx_1h": 15.0})
        score_composite_alpha(f)
        self.assertEqual(f["trend_momentum"]["trend_regime"], "CHOP_RANGE")


class MomentumItemTest(unittest.TestCase):
    def test_hist_and_accel_must_agree_in_direction(self):
        self.assertEqual(_score(trend_momentum={"macd_hist": 1.0, "macd_accel": 1.0}), 15.0)
        self.assertEqual(_score(trend_momentum={"macd_hist": -1.0, "macd_accel": -1.0}), -15.0)
        self.assertEqual(_score(trend_momentum={"macd_hist": 1.0, "macd_accel": -1.0}), 0.0)

    def test_divergences_add_directional_conviction(self):
        self.assertEqual(_score(trend_momentum={"macd_divergence": "BULLISH"}), 10.0)
        self.assertEqual(_score(trend_momentum={"macd_divergence": "BEARISH"}), -10.0)
        self.assertEqual(_score(trend_momentum={"rsi_divergence": "BULLISH"}), 5.0)
        self.assertEqual(_score(trend_momentum={"rsi_divergence": "BEARISH"}), -5.0)

    def test_rsi_zone_shifts_conviction(self):
        self.assertEqual(_score(trend_momentum={"rsi_zone": "BULL_PULLBACK_BUY"}), 6.0)
        self.assertEqual(_score(trend_momentum={"rsi_zone": "BEAR_RALLY_SELL"}), -6.0)
        # 超买禁追 ⇒ 抑制做多；超卖禁追 ⇒ 抑制做空
        self.assertEqual(_score(trend_momentum={"rsi_zone": "OVERBOUGHT_NO_CHASE"}), -6.0)
        self.assertEqual(_score(trend_momentum={"rsi_zone": "OVERSOLD_NO_CHASE"}), 6.0)

    def test_item_is_capped(self):
        got = _score(trend_momentum={
            "macd_hist": 1.0, "macd_accel": 1.0, "macd_divergence": "BULLISH",
            "rsi_divergence": "BULLISH", "rsi_zone": "BULL_PULLBACK_BUY"})
        self.assertEqual(got, MOMENTUM_ITEM_CAP)


class DerivativesItemTest(unittest.TestCase):
    def test_oi_quadrant_drives_the_tier(self):
        self.assertEqual(_score(smart_money_derivatives={"oi_price_quadrant": "LONG_BUILDUP"}), 12.0)
        self.assertEqual(_score(smart_money_derivatives={"oi_price_quadrant": "SHORT_BUILDUP"}), -12.0)
        self.assertEqual(_score(smart_money_derivatives={"oi_price_quadrant": "SHORT_COVERING"}), -6.0)
        self.assertEqual(_score(smart_money_derivatives={"oi_price_quadrant": "LONG_LIQUIDATION"}), 6.0)

    def test_funding_crowding_is_faded_not_followed(self):
        self.assertEqual(_score(smart_money_derivatives={"funding_crowding": "LONG_CROWDED"}), -6.0)
        self.assertEqual(_score(smart_money_derivatives={"funding_crowding": "EXTREME_LONG_CROWDED"}), -10.0)
        self.assertEqual(_score(smart_money_derivatives={"funding_crowding": "SHORT_CROWDED"}), 6.0)

    def test_liquidation_bias(self):
        self.assertEqual(_score(smart_money_derivatives={"liquidation_bias": "SHORT_SQUEEZE"}), 4.0)
        self.assertEqual(_score(smart_money_derivatives={"liquidation_bias": "LONG_CASCADE"}), -4.0)

    def test_item_is_capped(self):
        got = _score(smart_money_derivatives={
            "oi_price_quadrant": "LONG_BUILDUP", "funding_crowding": "SHORT_CROWDED",
            "liquidation_bias": "SHORT_SQUEEZE"})
        self.assertEqual(got, DERIVATIVES_ITEM_CAP)


class OrderflowItemTest(unittest.TestCase):
    def test_cvd_and_taker_ratio(self):
        self.assertEqual(_score(volume_money_flow={"cvd_1h_usd": 5e6}), 6.0)
        self.assertEqual(_score(volume_money_flow={"cvd_1h_usd": -5e6}), -6.0)
        self.assertEqual(_score(volume_money_flow={"taker_buy_sell_ratio": 1.3}), 5.0)
        self.assertEqual(_score(volume_money_flow={"taker_buy_sell_ratio": 0.7}), -5.0)
        self.assertEqual(_score(volume_money_flow={"taker_buy_sell_ratio": 1.0}), 0.0)

    def test_cvd_divergence(self):
        self.assertEqual(_score(volume_money_flow={"cvd_divergence": "BEARISH"}), -6.0)
        self.assertEqual(_score(volume_money_flow={"cvd_divergence": "BULLISH"}), 6.0)

    def test_item_is_capped(self):
        got = _score(volume_money_flow={
            "cvd_1h_usd": 5e6, "taker_buy_sell_ratio": 1.3, "cvd_divergence": "BULLISH"})
        self.assertEqual(got, ORDERFLOW_ITEM_CAP)


class ValueAreaItemTest(unittest.TestCase):
    def test_vwap_bands(self):
        self.assertEqual(_score(volume_profile={"vwap_extreme_band": "LOWER_EXTREME"}), 12.0)
        self.assertEqual(_score(volume_profile={"vwap_extreme_band": "UPPER_EXTREME"}), -12.0)
        self.assertEqual(_score(volume_profile={"vwap_extreme_band": "LOWER_VALUE_AREA"}), 6.0)
        self.assertEqual(_score(volume_profile={"vwap_extreme_band": "INSIDE_VALUE_AREA"}), 0.0)


class DepthItemTest(unittest.TestCase):
    def test_obi_thresholds(self):
        """只在 `depth_reliable=True` 时采信 OBI，且优先用**多笔档口径**。

        ⚠️ 生产里 `depth_reliable` 与 `obi_robust_pct` 由引擎**同时写入**
        （见 `apply_microstructure_tier`），故这里两者一起给。
        """
        for obi, want in ((25.0, 10.0), (12.0, 5.0), (0.0, 0.0),
                          (-12.0, -5.0), (-25.0, -10.0)):
            self.assertEqual(
                _score(microstructure={"obi_pct": 0.0, "obi_robust_pct": obi,
                                       "depth_reliable": True}),
                want, f"稳健 OBI={obi}")

    def test_unreliable_depth_is_not_scored_at_all(self):
        """⚠️ 盘口不可信 ⇒ 该项**按缺失处理**（0 分），既不加也不扣。

        实测背景：OKX 永续 Params 盘口常被单笔可撤挂单支配，原始 OBI 能在
        几十秒内从 +14% 翻到 −94% —— 若照它打分，等于把做市商刷新当方向证据。
        """
        for obi in (60.0, 25.0, 0.0, -25.0, -60.0):
            self.assertEqual(
                _score(microstructure={"obi_pct": obi, "depth_reliable": False}), 0.0,
                f"不可信盘口 OBI={obi} 不应计分")
        # 缺 `depth_reliable` 字段（老快照）同样不计分 —— 缺省即不采信
        self.assertEqual(_score(microstructure={"obi_pct": 30.0}), 0.0)

    def test_robust_obi_is_preferred_over_raw(self):
        """可信盘口下优先用**多笔档**口径的 `obi_robust_pct`。"""
        self.assertEqual(
            _score(microstructure={"obi_pct": 0.0, "obi_robust_pct": 30.0,
                                   "depth_reliable": True}), 10.0)

    def test_volatility_shock_dampens_by_eight_tenths(self):
        got = _score(trend_momentum={"adx_1h": 25.0, "rsi_14": 60.0},
                     volatility_channel={"atr_1h_pct": 5.0})
        self.assertAlmostEqual(got, 15.0 * 0.8, places=6)

    def test_wide_spread_dampens_the_same_way(self):
        got = _score(trend_momentum={"adx_1h": 25.0, "rsi_14": 60.0},
                     microstructure={"spread_bps": 40.0})
        self.assertAlmostEqual(got, 15.0 * 0.8, places=6)

    def test_both_shock_triggers_do_not_stack_with_each_other(self):
        """两条触发是**同一个**阻尼（或关系），不是两个乘子。"""
        got = _score(trend_momentum={"adx_1h": 25.0, "rsi_14": 60.0},
                     volatility_channel={"atr_1h_pct": 5.0},
                     microstructure={"spread_bps": 40.0})
        self.assertAlmostEqual(got, 15.0 * 0.8, places=6)

    def test_funding_crowding_does_not_shrink_the_score(self):
        """费率拥挤走**方向性闸门**，不参与阻尼 —— 否则反拥挤的分数被一起缩掉。"""
        got = _score(smart_money_derivatives={"funding_crowding": "EXTREME_LONG_CROWDED"})
        self.assertAlmostEqual(got, -10.0, places=6)


class SignalRecommendationTest(unittest.TestCase):
    def _bullish_stack(self):
        return dict(
            trend_momentum={"adx_1h": 30.0, "rsi_14": 60.0, "macd_hist": 1.0,
                            "macd_accel": 1.0, "macd_divergence": "BULLISH"},
            smart_money_derivatives={"oi_price_quadrant": "LONG_BUILDUP"},
            volume_money_flow={"cvd_1h_usd": 5e6, "taker_buy_sell_ratio": 1.3},
        )

    def test_strong_aligned_stack_recommends_long(self):
        f = _factors(**self._bullish_stack())
        score_composite_alpha(f)
        self.assertGreaterEqual(f["composite_alpha_score"], SCORE_SIGNAL_THRESHOLD)
        self.assertEqual(f["signal_recommendation"], "BUY_LONG")

    def test_mirrored_stack_recommends_short(self):
        f = _factors(
            trend_momentum={"adx_1h": 30.0, "rsi_14": 40.0, "macd_hist": -1.0,
                            "macd_accel": -1.0, "macd_divergence": "BEARISH"},
            smart_money_derivatives={"oi_price_quadrant": "SHORT_BUILDUP"},
            volume_money_flow={"cvd_1h_usd": -5e6, "taker_buy_sell_ratio": 0.7},
        )
        score_composite_alpha(f)
        self.assertLessEqual(f["composite_alpha_score"], -SCORE_SIGNAL_THRESHOLD)
        self.assertEqual(f["signal_recommendation"], "SELL_SHORT")

    def test_chop_blocks_the_signal_even_with_a_high_score(self):
        stack = self._bullish_stack()
        stack["trend_momentum"] = dict(stack["trend_momentum"], adx_1h=10.0)
        f = _factors(**stack)
        score_composite_alpha(f)
        self.assertGreaterEqual(f["composite_alpha_score"], SCORE_SIGNAL_THRESHOLD)
        self.assertEqual(f["signal_recommendation"], "WAIT",
                         "ADX 低于信号门槛时不得推单（这正是震荡绞肉市的入口）")

    def test_extreme_long_crowding_blocks_only_the_long_side(self):
        """费率极端多头拥挤 ⇒ 封 `BUY_LONG`（不许顺势加码），但反拥挤的空单放行。"""
        stack = self._bullish_stack()
        stack["smart_money_derivatives"] = {
            "oi_price_quadrant": "LONG_BUILDUP",
            "funding_crowding": "EXTREME_LONG_CROWDED",
        }
        f = _factors(**stack)
        score_composite_alpha(f)
        self.assertGreaterEqual(f["composite_alpha_score"], SCORE_SIGNAL_THRESHOLD)
        self.assertEqual(f["signal_recommendation"], "WAIT",
                         "极端多头拥挤时不得顺势加多")

    def test_extreme_short_crowding_blocks_only_the_short_side(self):
        stack = dict(
            trend_momentum={"adx_1h": 30.0, "rsi_14": 40.0, "macd_hist": -1.0,
                            "macd_accel": -1.0, "macd_divergence": "BEARISH"},
            smart_money_derivatives={"oi_price_quadrant": "SHORT_BUILDUP",
                                     "funding_crowding": "EXTREME_SHORT_CROWDED"},
            volume_money_flow={"cvd_1h_usd": -5e6, "taker_buy_sell_ratio": 0.7},
        )
        f = _factors(**stack)
        score_composite_alpha(f)
        self.assertLessEqual(f["composite_alpha_score"], -SCORE_SIGNAL_THRESHOLD)
        self.assertEqual(f["signal_recommendation"], "WAIT",
                         "极端空头拥挤时不得顺势追空")


class MissingInputTest(unittest.TestCase):
    """缺失不崩、不伪造方向；整块缺席时分数保持干净。"""

    def test_absent_blocks_do_not_fabricate_direction(self):
        f = _factors()
        for pillar in ("volume_profile", "options_structure", "smart_money_derivatives",
                       "volume_money_flow", "microstructure"):
            del f[pillar]
        self.assertEqual(score_composite_alpha(f), 0.0)
        self.assertEqual(f["signal_recommendation"], "WAIT")

    def test_placeholder_values_are_treated_as_missing_not_as_numbers(self):
        """`--` 占位符不得被当成数字（否则会算出荒谬的方向分）。"""
        got = _score(volume_money_flow={"taker_buy_sell_ratio": 1.0},
                     smart_money_derivatives={"oi_price_quadrant": "NEUTRAL",
                                              "funding_crowding": "NEUTRAL"})
        self.assertEqual(got, 0.0)

    def test_scoring_does_not_mutate_other_pillars(self):
        f = _factors(trend_momentum={"adx_1h": 25.0, "rsi_14": 60.0})
        before = copy.deepcopy(f["smart_money_derivatives"])
        score_composite_alpha(f)
        self.assertEqual(f["smart_money_derivatives"], before)


if __name__ == "__main__":
    unittest.main()


# =====================================================================
# 决策不变性门（2026-10）
# =====================================================================

class MissingDataMustNotChangeDecisionsTest(unittest.TestCase):
    """**显式缺失不许改变任何交易判定** —— 它只改"怎么显示"。

    背景：T4/T3 的输入缺失时，原先留着默认块的伪中性值（柱 0.0 / RSI 50.0 / 态 NEUTRAL），
    现改为显式缺失（`None` + `INSUFFICIENT_DATA`）。这一改动**只应**影响展示与归因可观测性，
    绝不允许悄悄改变评分或信号方向。

    本门用"旧默认值 vs 新显式缺失"跑同一套评分与信号，要求**逐字节相同**。
    若将来有人在缺失分支里塞进"补救逻辑"（例如把 None 当真 0 参与加减分、
    或把哨兵写进某个白名单），这里会当场变红。
    """

    def setUp(self):
        self.inst, self.name = "BTC-USDT-SWAP", "BTC"

    def _variants(self):
        from scripts.factors.defaults import build_default_factors
        from scripts.factors import okx_quant_factors as qf
        base = build_default_factors(self.inst, self.name)
        base["price"] = 83000.0
        base["chg24h"] = -1.2
        old = copy.deepcopy(base)                 # 旧行为：缺 K 线 ⇒ 保留伪中性默认值
        new = copy.deepcopy(base)                 # 新行为：显式标缺失
        qf.mark_momentum_missing(new)
        qf.mark_volume_profile_missing(new)
        return old, new

    def test_composite_score_is_unchanged(self):
        from scripts.factors import scoring
        old, new = self._variants()
        self.assertEqual(scoring.score_composite_alpha(copy.deepcopy(old)),
                         scoring.score_composite_alpha(copy.deepcopy(new)),
                         "显式缺失改变了 composite_alpha —— 缺失分支里混进了打分逻辑")

    def test_asset_signal_is_unchanged(self):
        from scripts.trader import signals as sig
        old, new = self._variants()

        def decide(f):
            return sig.evaluate_asset_signal(
                f, asset_class_profiles={"crypto": {}},
                is_in_stop_cooldown=lambda *a, **k: False,
                load_adaptive_config=lambda: {})

        self.assertEqual(decide(copy.deepcopy(old)), decide(copy.deepcopy(new)),
                         "显式缺失改变了信号决策")

    def test_only_display_keys_change(self):
        old, new = self._variants()
        changed = set()
        for pillar in set(old) | set(new):
            a, b = old.get(pillar), new.get(pillar)
            if isinstance(a, dict) and isinstance(b, dict):
                changed |= {f"{pillar}.{k}" for k in set(a) | set(b) if a.get(k) != b.get(k)}
            elif a != b:
                changed.add(pillar)
        allowed = {
            "trend_momentum.macd_dif", "trend_momentum.macd_dea",
            "trend_momentum.macd_hist", "trend_momentum.macd_accel",
            "trend_momentum.macd_hist_pct", "trend_momentum.macd_accel_pct",
            "trend_momentum.macd_momentum_state", "trend_momentum.rsi_1h",
            "trend_momentum.rsi_15m", "trend_momentum.rsi_zone",
            # ★ 背离状态：`NONE`（"已检测且无背离"）⇒ `INSUFFICIENT_DATA`（缺失）。
            #   打分侧只认 "BULLISH"/"BEARISH"，两者都不匹配 ⇒ 贡献同为 0（下一行就地证明）。
            "trend_momentum.macd_divergence", "trend_momentum.rsi_divergence",
            "volume_profile.vwap_24h",
        }
        self.assertTrue(changed <= allowed,
                        f"改动溢出到未预期的键（可能影响决策）：{sorted(changed - allowed)}")

    def test_divergence_missing_is_score_equivalent_to_none(self):
        """就地证明：`macd_divergence`/`rsi_divergence` 从 `NONE` 变 `INSUFFICIENT_DATA`
        对打分**零影响**（打分只认 BULLISH/BEARISH，两个值都不匹配 ⇒ 贡献 0）。"""
        from scripts.factors import scoring
        from scripts.factors.defaults import build_default_factors
        scores = []
        for value in ("NONE", "INSUFFICIENT_DATA"):
            f = build_default_factors("BTC-USDT-SWAP", "BTC")
            f["trend_momentum"]["adx_1h"] = 30.0
            f["trend_momentum"]["rsi_14"] = 60.0
            f["trend_momentum"]["macd_divergence"] = value
            f["trend_momentum"]["rsi_divergence"] = value
            scores.append(scoring.score_composite_alpha(f))
        self.assertEqual(scores[0], scores[1])
class MissingRsiMustNotFabricateADirectionTest(unittest.TestCase):
    """★ 2026-10「不许假数据」：RSI 缺失时**不许**凭空产出 ±15 趋势分。

    原实现 `rsi = _num(_pick(tm, "rsi_14"), 50.0)`：RSI 缺失 ⇒ 兜底 50.0 ⇒
    `rsi >= 50` ⇒ **+15 分**（趋势分本来是在判方向，用"中性=50"当方向证据是编造）。
    另有一个更隐蔽的坑（自查抓到）：`_pick` 对**值为 None** 的键返回 `_MISSING` 哨兵，
    哨兵 `is not None` 为真 ⇒ 只判 `is not None` 会漏过去，再经 `_num(哨兵)→0.0`
    变成"RSI<50"⇒ **−15 分**。两条都必须钉死。
    """

    def _score(self, rsi_14):
        from scripts.factors import scoring
        from scripts.factors.defaults import build_default_factors
        f = build_default_factors("BTC-USDT-SWAP", "BTC")
        f["trend_momentum"]["adx_1h"] = 30.0          # 越过 ADX 门槛，趋势项必然参与
        f["trend_momentum"]["rsi_14"] = rsi_14
        return scoring.score_composite_alpha(f)

    def test_missing_rsi_contributes_nothing(self):
        self.assertEqual(self._score(None), 0.0,
                         "RSI 缺失却产出了分（50.0 兜底 ⇒ +15，哨兵漏判 ⇒ −15）")

    def test_absent_key_contributes_nothing(self):
        from scripts.factors import scoring
        from scripts.factors.defaults import build_default_factors
        f = build_default_factors("BTC-USDT-SWAP", "BTC")
        f["trend_momentum"]["adx_1h"] = 30.0
        f["trend_momentum"].pop("rsi_14", None)        # 键不存在（旧"不写"形态）
        self.assertEqual(scoring.score_composite_alpha(f), 0.0)

    def test_real_rsi_still_scores_both_directions(self):
        self.assertEqual(self._score(70.0), 15.0)
        self.assertEqual(self._score(30.0), -15.0)
