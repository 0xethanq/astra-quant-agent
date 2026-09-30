"""Tests for dynamic expectation and flexible R:R gates.
Ensures high-confidence trades with positive expected return (E >= +0.30R)
and R:R >= 1.2 can pass, while preserving the fail-closed 1.2 absolute bottom line.
"""
import unittest
import importlib.util
from pathlib import Path
from scripts.order_risk import validate_quote_geometry_and_rr

_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_gatekeeper_plugin():
    plugin_path = _ROOT / "plugins" / "interceptors" / "04_risk_reward_gatekeeper.py"
    spec = importlib.util.spec_from_file_location("plugin_04_gatekeeper", plugin_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DynamicExpectationGateTests(unittest.TestCase):
    def setUp(self):
        self.gatekeeper = _load_gatekeeper_plugin()

    def test_high_confidence_positive_expectation_passes_validate_quote(self):
        # Entry 100, SL 90, TP 114 -> Risk 10, Reward 14, R:R = 1.4
        # Confidence 85% -> E = 0.85 * 1.4 - 0.15 = 1.04R >= +0.30R, R:R >= 1.2
        ok, reason, rr = validate_quote_geometry_and_rr(
            "BUY_LONG", 100.0, 114.0, 90.0, confidence=85.0
        )
        self.assertTrue(ok, f"Expected pass, got rejected: {reason}")
        self.assertEqual(reason, "")
        self.assertAlmostEqual(rr, 1.4)

    def test_low_confidence_with_sub_2_rr_rejected_validate_quote(self):
        # Entry 100, SL 90, TP 114 -> R:R = 1.4
        # Confidence 70% (< 80%) -> Rejected for not meeting base 2.0 R:R
        ok, reason, rr = validate_quote_geometry_and_rr(
            "BUY_LONG", 100.0, 114.0, 90.0, confidence=70.0
        )
        self.assertFalse(ok)
        self.assertIn("盈亏比不足 2.0", reason)
        self.assertAlmostEqual(rr, 1.4)

    def test_sub_1_2_rr_strictly_rejected_even_with_high_confidence(self):
        # Entry 100, SL 90, TP 110 -> Risk 10, Reward 10, R:R = 1.0 < 1.2
        # Even with 99% confidence, must fail closed
        ok, reason, rr = validate_quote_geometry_and_rr(
            "BUY_LONG", 100.0, 110.0, 90.0, confidence=99.0
        )
        self.assertFalse(ok)
        self.assertAlmostEqual(rr, 1.0)

    def test_gatekeeper_plugin_dynamic_expectation(self):
        pkg = {"instId": "BTC-USDT-SWAP", "name": "BTC"}
        ctx = {}

        # 1. Standard 2.2R passes
        dec_standard = {
            "action": "BUY_LONG", "confidence": 82.0,
            "entry_price": 100.0, "take_profit_price": 122.0, "stop_loss_price": 90.0,
        }
        ok, reason = self.gatekeeper.check_risk(pkg, dec_standard, ctx)
        self.assertTrue(ok)

        # 2. Dynamic 1.4R with 85% confidence passes
        dec_dynamic = {
            "action": "BUY_LONG", "confidence": 85.0,
            "entry_price": 100.0, "take_profit_price": 114.0, "stop_loss_price": 90.0,
        }
        ok, reason = self.gatekeeper.check_risk(pkg, dec_dynamic, ctx)
        self.assertTrue(ok, f"Expected pass, got: {reason}")

        # 3. Dynamic 1.4R with 70% confidence rejected
        dec_low_conf = {
            "action": "BUY_LONG", "confidence": 70.0,
            "entry_price": 100.0, "take_profit_price": 114.0, "stop_loss_price": 90.0,
        }
        ok, reason = self.gatekeeper.check_risk(pkg, dec_low_conf, ctx)
        self.assertFalse(ok)
        self.assertIn("未满足全局风控", reason)

        # 4. 1.0R with 99% confidence rejected for sub-1.2 absolute bottom line
        dec_sub_floor = {
            "action": "BUY_LONG", "confidence": 99.0,
            "entry_price": 100.0, "take_profit_price": 110.0, "stop_loss_price": 90.0,
        }
        ok, reason = self.gatekeeper.check_risk(pkg, dec_sub_floor, ctx)
        self.assertFalse(ok)
        self.assertIn("低于系统绝对安全底线", reason)

    def test_adx_filter_allows_range_mean_reversion(self):
        adx_path = _ROOT / "plugins" / "interceptors" / "03_adx_volatility_filter.py"
        spec = importlib.util.spec_from_file_location("plugin_03_adx", adx_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        pkg = {"adx_1h": 14.5}
        ctx = {}

        # 1. Generic trade rejected under low ADX
        dec_generic = {"action": "BUY_LONG", "confidence": 85.0, "summary_reason": "顺势追涨突破"}
        ok, reason = mod.check_risk(pkg, dec_generic, ctx)
        self.assertFalse(ok)
        self.assertIn("无序震荡杂波市", reason)

        # 2. Box range mean reversion trade allowed under low ADX
        dec_range = {"action": "BUY_LONG", "confidence": 84.0, "summary_reason": "4H箱体下沿均值回归低吸企稳"}
        ok, reason = mod.check_risk(pkg, dec_range, ctx)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_macro_trend_filter_allows_s_class_reversal(self):
        macro_path = _ROOT / "plugins" / "interceptors" / "01_macro_trend_filter.py"
        spec = importlib.util.spec_from_file_location("plugin_01_macro", macro_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        pkg = {
            "macro_4h": "4H_MACRO_BULL (大级别多头通道)",
            "calculus": {"acceleration": -0.22, "kinematic_regime": "OVERSTRETCHED"},
        }
        ctx = {}

        # 1. Normal counter-trend short rejected
        dec_normal = {"action": "SELL_SHORT", "confidence": 80.0, "summary_reason": "普通摸顶"}
        ok, reason = mod.check_risk(pkg, dec_normal, ctx)
        self.assertFalse(ok)
        self.assertIn("多头主升通道", reason)

        # 2. S-class reversal with high confidence and sweep evidence allowed
        dec_reversal = {
            "action": "SELL_SHORT", "confidence": 88.0,
            "summary_reason": "流动性衰竭假突破反转 (Liquidity Sweep & Fail)，微积分曲率力竭",
        }
        ok, reason = mod.check_risk(pkg, dec_reversal, ctx)
        self.assertTrue(ok)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
