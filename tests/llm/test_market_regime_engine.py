"""Tests for Macro Market Regime Auto-Detection Engine (ASTRA v8.0.0)."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from calculus_engine import (
    REGIME_LOW_VOL_CHOPPY,
    REGIME_TREND_EXPANSION,
    REGIME_VOLATILITY_SHOCK,
    REGIME_WIDE_OSCILLATION,
    detect_macro_market_regime,
)


class MarketRegimeEngineTest(unittest.TestCase):
    def test_empty_packages_fallback_safe(self):
        res = detect_macro_market_regime([])
        self.assertEqual(res["regime_id"], REGIME_LOW_VOL_CHOPPY)
        self.assertIn("窄幅低波", res["regime_name"])
        self.assertFalse(res["shock_risk"])
        self.assertIn("summary_text", res)

    def test_trend_expansion_detection(self):
        # 构造强单边趋势：高 ADX、4H BULL、速度加速度同向扩张
        packages = [
            {
                "instId": "BTC-USDT-SWAP",
                "price": 85000,
                "atr_1h": 1500,
                "adx_1h": 36.0,
                "macro_4h": "4H_MACRO_BULL",
                "calculus": {"velocity_1h": 0.22, "accel_1h": 0.15, "kinematic_regime": "BULL_ACCELERATING"},
            },
            {
                "instId": "ETH-USDT-SWAP",
                "price": 3200,
                "atr_1h": 80,
                "adx_1h": 32.0,
                "macro_4h": "4H_MACRO_BULL",
                "calculus": {"velocity_1h": 0.18, "accel_1h": 0.12, "kinematic_regime": "BULL_ACCELERATING"},
            },
            {
                "instId": "SOL-USDT-SWAP",
                "price": 180,
                "atr_1h": 5.0,
                "adx_1h": 30.0,
                "macro_4h": "4H_MACRO_BULL",
                "calculus": {"velocity_1h": 0.16, "accel_1h": 0.08, "kinematic_regime": "BULL_STABLE"},
            },
        ]
        res = detect_macro_market_regime(packages)
        self.assertEqual(res["regime_id"], REGIME_TREND_EXPANSION)
        self.assertGreaterEqual(res["trend_score"], 55.0)
        self.assertEqual(res["dominant_direction"], "BULL")
        self.assertEqual(res["recommended_profile"], "stable")

    def test_wide_range_oscillation_detection(self):
        # 构造宽幅震荡：低 ADX (<22)，高 ATR%，多空博弈冲突，多标的反转
        packages = [
            {
                "instId": "BTC-USDT-SWAP",
                "price": 65000,
                "atr_1h": 1400,  # ~2.1% 波动
                "adx_1h": 17.5,  # 无序震荡
                "macro_4h": "4H_MACRO_RANGE",
                "calculus": {"velocity_1h": 0.10, "accel_1h": -0.15, "kinematic_regime": "BULL_DECELERATING"},
            },
            {
                "instId": "ETH-USDT-SWAP",
                "price": 2800,
                "atr_1h": 70,  # 2.5% 波动
                "adx_1h": 18.0,
                "macro_4h": "4H_MACRO_BEAR",
                "calculus": {"velocity_1h": -0.09, "accel_1h": 0.14, "kinematic_regime": "BEAR_DECELERATING"},
            },
            {
                "instId": "SOL-USDT-SWAP",
                "price": 140,
                "atr_1h": 4.2,  # 3.0% 波动
                "adx_1h": 19.0,
                "macro_4h": "4H_MACRO_RANGE",
                "calculus": {"velocity_1h": -0.12, "accel_1h": 0.11, "kinematic_regime": "BEAR_REVERSING"},
            },
        ]
        res = detect_macro_market_regime(packages)
        self.assertEqual(res["regime_id"], REGIME_WIDE_OSCILLATION)
        self.assertGreaterEqual(res["oscillation_score"], 50.0)
        self.assertGreaterEqual(res["volatility_score"], 40.0)
        self.assertEqual(res["recommended_profile"], "wide_oscillation")
        self.assertIn("宽幅", res["summary_text"])

    def test_volatility_shock_detection(self):
        # 构造极端冲击黑天鹅：巨大 Jerk 和高波动
        packages = [
            {
                "instId": "BTC-USDT-SWAP",
                "price": 60000,
                "atr_1h": 2800,  # 异常高波
                "adx_1h": 40.0,
                "calculus": {"velocity_1h": -0.85, "accel_1h": -0.60, "jerk_1h": -2.2, "kinematic_regime": "SHOCK_HIGH_JERK"},
            },
            {
                "instId": "ETH-USDT-SWAP",
                "price": 2400,
                "atr_1h": 160,
                "adx_1h": 42.0,
                "calculus": {"velocity_1h": -0.90, "accel_1h": -0.70, "jerk_1h": -2.5, "kinematic_regime": "SHOCK_HIGH_JERK"},
            },
        ]
        res = detect_macro_market_regime(packages)
        self.assertEqual(res["regime_id"], REGIME_VOLATILITY_SHOCK)
        self.assertTrue(res["shock_risk"])
        self.assertIn("黑天鹅", res["regime_tag"])


if __name__ == "__main__":
    unittest.main()
