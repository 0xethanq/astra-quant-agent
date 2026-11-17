"""动态正期望与弹性 R:R 闸门的**纯函数**契约（`scripts/order_risk.py`）。

2026-10：策略插件系统（`plugins/interceptors/*`）整套裁撤后，本文件里针对
`01/03/04` 三个插件 `check_risk` 的用例与 `run_interceptor_pipeline` 的 Mutation
用例一并删除；保留的是**仍然生效**的单一事实源契约：

- 高置信度（≥80%）且数学期望 E = P·RR − (1−P) ≥ +0.30R 时，允许跌破默认 2.0 门槛，
  但绝不跌破 1.2 的**绝对安全底线**；
- 低置信度下仍按后台风控页配置的 `MIN_RISK_REWARD_RATIO`（默认 2.0）拒单。

这些行为由后台 `/admin/risk` 的 `MIN_RISK_REWARD_RATIO` 驱动，执行层
（`scripts/trader/order_submit.py` 终审复验）与决策落盘（`scripts/brain/decisions.py`）
共用同一函数对象。
"""
import unittest

from scripts.order_risk import validate_quote_geometry_and_rr


class DynamicExpectationGateTests(unittest.TestCase):
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

    def test_geometry_is_action_specific(self):
        # 买多：止损必须在入场之下；方向写反必须被拒（交易所 51001 族）
        ok, reason, _ = validate_quote_geometry_and_rr("BUY_LONG", 100.0, 130.0, 110.0)
        self.assertFalse(ok)
        self.assertIn("买多几何不合法", reason)

        # 卖空：止盈必须在入场之下
        ok, reason, _ = validate_quote_geometry_and_rr("SELL_SHORT", 100.0, 110.0, 130.0)
        self.assertFalse(ok)
        self.assertIn("卖空几何不合法", reason)

    def test_non_finite_prices_are_rejected(self):
        ok, reason, _ = validate_quote_geometry_and_rr("BUY_LONG", float("nan"), 130.0, 90.0)
        self.assertFalse(ok)
        self.assertIn("有限数值", reason)

        ok, reason, _ = validate_quote_geometry_and_rr("BUY_LONG", 100.0, float("inf"), 90.0)
        self.assertFalse(ok)
        self.assertIn("有限数值", reason)


if __name__ == "__main__":
    unittest.main()
