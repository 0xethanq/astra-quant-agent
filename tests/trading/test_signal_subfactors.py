"""评分引擎的**子因子账本**与四大机构形态（第二百五十四刀）。

上限（记在代码注释里的区间）与实际累加必须对得上 —— 这里逐个因子单独隔离测，
再测形态识别：形态是 `raw_alpha_score` 的**下限/上限覆盖**（`max`/`min`），
即「形态一旦成立，分数至少/至多是它」——这就是为什么形态能压过因子分歧。

| 子因子 | 区间 | 触发 |
|---|---|---|
| 趋势 | ±1.5 | 单边趋势 + 斜率（`HH_HL`/`LH_LL` 加 0.3）；否则 EMA 三线排列 ±0.6 |
| 量能 | ±1.5 | MACD 加速度 ±0.6；OBV 流向 ±0.5；放量 K 线 ±0.4 |
| 均值回归 | ±1.2 | VWAP 极值 ±1.2；顺势健康区间 ±0.5 |
| 情绪 | ±0.8 | `sentiment_score * 1.5` 夹取 |
| 7 梯队因子共振 | ±1.5 | T4 MACD 柱×加速度同向 ±0.6、背离 ±0.5；T0.5 CVD×Taker 比 ±0.4；T1 OBI ±0.3；T3 VWAP 乖离 ±0.2；T0 OI 四象限 ±0.3；`EXHAUSTED` 减半 |
"""

import unittest

from scripts.trader import signals


class _Base(unittest.TestCase):
    def setUp(self):
        self.cfg = {}

        def _load():
            return self.cfg

        self._load = _load

    def _score(self, **over):
        """中性基线：所有子因子为 0，且**不触发任何形态**（便于隔离单个因子）。"""
        f = {"market_data_valid": True, "instId": "BTC-USDT-SWAP", "name": "BTC",
             "price": 100.0, "ema9": 100.0, "ema21": 100.0, "ema55": 100.0,
             "rsi": 50.0, "vwap_bias": 0.0, "vol_ratio": 1.0, "obv_flow": "NEUTRAL",
             "macd_hist": 0.0, "macd_accel": 0.0, "market_regime": "CHOP"}
        f.update(over)
        score, action, reasons, tag, desc = signals.evaluate_asset_signal(
            f, asset_class_profiles={"crypto": {"entry_threshold": 2.2}},
            is_in_stop_cooldown=lambda *_: False, load_adaptive_config=self._load)
        return score, action, tag


class TrendFactorTest(_Base):
    def test_bull_trend_with_structure_bonus(self):
        score, _, _ = self._score(market_regime="BULL_TREND", ema21_slope_pct=0.05,
                                  structure_1h="HH_HL", rsi=60.0)
        self.assertEqual(score, 1.5, "1.2 + 0.3（HH_HL 结构加成）")

    def test_bear_trend_with_structure_bonus(self):
        score, _, _ = self._score(market_regime="BEAR_TREND", ema21_slope_pct=-0.05,
                                  structure_1h="LH_LL", rsi=35.0)
        self.assertEqual(score, -1.5)

    def test_ema_alignment_without_trend_regime(self):
        up, _, _ = self._score(ema9=103.0, ema21=102.0, ema55=101.0)
        self.assertEqual(up, 0.6, "三线多头排列（无单边 regime）⇒ +0.6")
        down, _, _ = self._score(ema9=97.0, ema21=98.0, ema55=99.0, rsi=35.0)
        self.assertEqual(down, -0.6)


class VolumeFactorTest(_Base):
    def test_macd_acceleration_both_directions(self):
        self.assertEqual(self._score(macd_accel=0.5, macd_hist=0.5)[0], 0.6)
        self.assertEqual(self._score(macd_accel=-0.5, macd_hist=-0.5)[0], -0.6)

    def test_obv_flow_both_directions(self):
        self.assertEqual(self._score(obv_flow="BULL_FLOW")[0], 0.5)
        self.assertEqual(self._score(obv_flow="BULL_ACCUMULATION")[0], 0.5)
        self.assertEqual(self._score(obv_flow="BEAR_DISTRIBUTION")[0], -0.5)

    def test_volume_spike_candle_needs_the_matching_candle_direction(self):
        """放量**必须与 K 线方向同向**才计分（放量阳线加分、放量阴线减分）。"""
        self.assertEqual(self._score(vol_ratio=1.25, is_bull_candle_15m=True)[0], 0.4)
        self.assertEqual(self._score(vol_ratio=1.25, is_bear_candle_15m=True)[0], -0.4)
        self.assertEqual(self._score(vol_ratio=1.25)[0], 0.0, "只看量、没有对应 K 线 ⇒ 不计分")

    def test_factors_sum(self):
        score, _, _ = self._score(macd_accel=0.5, macd_hist=0.5, obv_flow="BULL_FLOW",
                                  vol_ratio=1.25, is_bull_candle_15m=True)
        self.assertEqual(score, 1.5, "0.6 + 0.5 + 0.4")


class MeanReversionFactorTest(_Base):
    def test_healthy_pullback_zone_in_bull_trend(self):
        score, _, _ = self._score(market_regime="BULL_TREND", rsi=50.0)
        self.assertEqual(score, 0.5, "40~55 且处于多头趋势 ⇒ 顺势健康区间")

    def test_healthy_rally_zone_in_bear_trend(self):
        score, _, _ = self._score(market_regime="BEAR_TREND", rsi=50.0)
        self.assertEqual(score, -0.5, "45~60 且处于空头趋势 ⇒ 顺势空头区间")

    def test_vwap_extremes_dominate(self):
        self.assertEqual(self._score(vwap_bias=-0.75, rsi=35.0)[0], 1.2)
        self.assertEqual(self._score(vwap_bias=0.75, rsi=65.0)[0], -1.2)


class FactorResonanceTest(_Base):
    """Sub-Factor 5（2026-10 重钉）：7 梯队因子共振，取代原微积分/定积分/概率。

    ⚠️ 原 `CalculusFactorTest` 守的是"v/a/i 三通道 + 定积分 + 概率"。
    这三块整链退场后，同一条"方向证据"账目由**可观测因子**承载，
    故本类改名并把每一条触发逐项钉住 —— 判据强度不放水。
    """

    def _res(self, *, hist=0.0, accel=0.0, state="", div="", rsi_div="",
             cvd5=0.0, taker=1.0, obi=0.0, obi_reliable=False, vwap=0.0,
             quadrant="", **over):
        return self._score(
            trend_momentum={"macd_hist": hist, "macd_accel": accel,
                            "macd_momentum_state": state, "macd_divergence": div,
                            "rsi_divergence": rsi_div},
            volume_money_flow={"cvd_5m_usd": cvd5, "taker_buy_sell_ratio": taker},
            microstructure={"obi_pct": obi, "obi_robust_pct": obi,
                            "depth_reliable": obi_reliable},
            volume_profile={"vwap_bias_pct": vwap},
            smart_money_derivatives={"oi_price_quadrant": quadrant},
            **over)[0]

    def test_macd_bar_and_acceleration_must_agree(self):
        self.assertEqual(self._res(hist=1.0, accel=0.5), 0.6)
        self.assertEqual(self._res(hist=-1.0, accel=-0.5), -0.6)

    def test_macd_fading_bar_is_penalised_not_rewarded(self):
        """柱体仍正但在收缩 ⇒ **扣分**（反 FOMO）；反之空头动能衰减加分。"""
        self.assertEqual(self._res(hist=1.0, accel=-0.5), -0.3)
        self.assertEqual(self._res(hist=-1.0, accel=0.5), 0.3)

    def test_exhausted_state_halves_the_score(self):
        self.assertEqual(self._res(hist=1.0, accel=0.5, state="EXHAUSTED"), 0.3)
        self.assertEqual(self._res(hist=1.0, accel=0.5, state="BULL_EXHAUSTING"), 0.3)

    def test_divergence_flips_the_direction(self):
        self.assertEqual(self._res(div="BEARISH_DIVERGENCE"), -0.5)
        self.assertEqual(self._res(rsi_div="BULLISH_DIVERGENCE"), 0.5)
        self.assertEqual(self._res(div="BEARISH"), -0.5)
        self.assertEqual(self._res(rsi_div="BULLISH"), 0.5)

    def test_orderflow_needs_cvd_and_taker_ratio_to_agree(self):
        """单看一个大数容易被单笔大单骗 ⇒ CVD 与 Taker 比必须同向。"""
        self.assertEqual(self._res(cvd5=1e6, taker=1.10), 0.4)
        self.assertEqual(self._res(cvd5=-1e6, taker=0.90), -0.4)
        self.assertEqual(self._res(cvd5=1e6, taker=1.01), 0.0,
                         "Taker 比未过半门槛 ⇒ 不加分")
        self.assertEqual(self._res(cvd5=1e6, taker=0.85), 0.0, "互相矛盾 ⇒ 0")

    def test_obi_and_vwap_and_quadrant(self):
        # OBI 只在 `depth_reliable=True` 时采信（实测原始 OBI 会被单笔挂单支配）
        self.assertEqual(self._res(obi=25.0, obi_reliable=True), 0.3)
        self.assertEqual(self._res(obi=-25.0, obi_reliable=True), -0.3)
        self.assertEqual(self._res(obi=25.0, obi_reliable=False), 0.0,
                         "不可信盘口不得贡献方向分")
        self.assertEqual(self._res(obi=-25.0), 0.0, "缺省（未标注可信）同样不采信")
        self.assertEqual(self._res(vwap=-0.9), 0.2)
        self.assertEqual(self._res(vwap=0.9), -0.2)
        # ⚠️ 象限名取自 `classify_derivatives_quadrant()` 的词表
        self.assertEqual(self._res(quadrant="SHORT_COVERING"), 0.3)
        self.assertEqual(self._res(quadrant="LONG_LIQUIDATION"), -0.3)

    def test_the_sub_factor_is_clamped_to_its_band(self):
        """全部触发同向堆叠也**不得**越过 ±1.5（区间是账目契约）。"""
        hot = self._res(hist=1.0, accel=0.5, cvd5=1e6, taker=1.2, obi=30.0,
                        vwap=-1.0, quadrant="SHORT_COVERING")   # 0.6+0.4+0.3+0.2+0.3
        self.assertEqual(hot, 1.5, "1.8 被夹到区间上限 1.5")
        cold = self._res(hist=-1.0, accel=-0.5, cvd5=-1e6, taker=0.8, obi=-30.0,
                         vwap=1.0, quadrant="LONG_LIQUIDATION")
        self.assertEqual(cold, -1.5)

    def test_missing_tiers_are_neutral_not_directional(self):
        """梯队整体缺失 ⇒ 子因子必须是 0（**不许**把缺失读成中性偏多/偏空）。"""
        self.assertEqual(self._score()[0], 0.0)


class InstitutionalSetupTest(_Base):
    """形态是**分数的下限/上限覆盖**（`max`/`min`）：形态成立即可压过因子分歧。"""

    def test_setup1_institutional_pullback(self):
        score, action, tag = self._score(
            market_regime="BULL_TREND", rsi=50.0, is_bull_candle_15m=True)
        self.assertEqual(tag, "🌊 顺势回踩")
        self.assertEqual(score, 2.4, "raw = max(因子和, 2.4)")
        self.assertEqual(action, "BUY_LONG")

    def test_setup2_resistance_exhaustion(self):
        score, action, tag = self._score(
            market_regime="BEAR_TREND", rsi=50.0, is_bear_candle_15m=True)
        self.assertEqual(tag, "⚡ 阻力抛压")
        self.assertEqual(score, -2.4, "raw = min(因子和, -2.4)")
        self.assertEqual(action, "SELL_SHORT")

    def test_setup3_momentum_breakout(self):
        score, action, tag = self._score(
            price=100.0, ema9=99.0, ema21=98.0, ema55=97.0, rsi=60.0,
            vol_ratio=1.3, macd_accel=0.5, macd_hist=0.5, is_bull_candle_15m=True)
        self.assertEqual(tag, "🚀 动量突破")
        self.assertEqual(score, 2.5)
        self.assertEqual(action, "BUY_LONG")

    def test_setup4_breakdown_acceleration(self):
        score, action, tag = self._score(
            price=100.0, ema9=101.0, ema21=102.0, ema55=103.0, rsi=35.0,
            vol_ratio=1.3, macd_accel=-0.5, macd_hist=-0.5, is_bear_candle_15m=True)
        self.assertEqual(tag, "🌪️ 破位追空")
        self.assertEqual(score, -2.5)
        self.assertEqual(action, "SELL_SHORT")

    def test_volatility_shock_dampens_breakout_setups(self):
        """ATR% ≥ 4 的冲击行情 ⇒ **压制突破类形态**（Setup 1-4 都带 `not is_high_jerk_shock`）。

        2026-10 重钉：原判据是高 jerk（`max_abs_jerk ≥ 1.8` / `SHOCK_HIGH_JERK` regime），
        该字段随数理链退场；同一意图（极端波动里突破假信号率飙升）现由
        **ATR% 与有效点差**承载 —— 更直接，且不依赖已删除的动力学快照。
        """
        _, _, tag = self._score(
            price=100.0, ema9=99.0, ema21=98.0, ema55=97.0, rsi=60.0,
            vol_ratio=1.3, macd_accel=0.5, macd_hist=0.5, is_bull_candle_15m=True,
            volatility_channel={"atr_pct": 4.5})
        self.assertEqual(tag, "⚪ 观望", "冲击市场不许追突破")

    def test_wide_spread_also_dampens_breakout_setups(self):
        """点差走阔（≥15bps）＝流动性抽离，同样压制突破类形态。"""
        _, _, tag = self._score(
            price=100.0, ema9=99.0, ema21=98.0, ema55=97.0, rsi=60.0,
            vol_ratio=1.3, macd_accel=0.5, macd_hist=0.5, is_bull_candle_15m=True,
            microstructure={"spread_bps": 18.0})
        self.assertEqual(tag, "⚪ 观望")

    def test_normal_volatility_does_not_block_the_setup(self):
        """反向断言：正常波动（ATR% 1.0、点差 0.3bps）时必须**放行** ——
        否则上一条会因为"永远拦住"而空转。"""
        _, _, tag = self._score(
            price=100.0, ema9=99.0, ema21=98.0, ema55=97.0, rsi=60.0,
            vol_ratio=1.3, macd_accel=0.5, macd_hist=0.5, is_bull_candle_15m=True,
            volatility_channel={"atr_pct": 1.0}, microstructure={"spread_bps": 0.3})
        self.assertEqual(tag, "🚀 动量突破")
