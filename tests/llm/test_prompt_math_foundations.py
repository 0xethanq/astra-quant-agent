"""Regression tests for ASTRA mathematical foundations and prompt contracts."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ai_brain_trader
import self_improvement_engine


class PromptMathFoundationsTests(unittest.TestCase):
    def package(self):
        calc_1h = {
            "valid": True,
            "velocity": 0.61,
            "acceleration": 0.27,
            "jerk": 0.18,
            "impulse": 1.12,
            "regime": "BULL_ACCELERATING",
            "definite_integrals": {
                "energy_integral": 1.44,
                "deviation_area_integral": 0.82,
                "volume_action_integral": 0.31,
                "integral_regime": "POSITIVE_ENERGY_EXPANSION",
            },
            "probability_theory": {
                "continuation_prob_pct": 73.5,
                "breakdown_prob_pct": 26.5,
                "skewness": 0.42,
                "kurtosis": 1.2,
                "var_95_pct": 1.36,
                "cvar_95_pct": 1.82,
                "prob_regime": "HIGH_PROB_BULL_CONTINUATION",
                "is_fat_tail": False,
            },
        }
        return {
            "name": "BTC", "instId": "BTC-USDT-SWAP", "data_quality": "valid",
            "price": 60000, "chg24h": 1.2, "bidPx": 59999, "askPx": 60001,
            "smart_money": {}, "adx_1h": 28, "recent_15m": [], "recent_1h": [], "recent_4h": [],
            "fundingRate": 0.01, "oiUsd": 1000000, "lsRatio": 1.1, "takerNetUsd": 12000,
            "calculus": {
                "valid": True, "velocity": 0.4, "acceleration": 0.2, "impulse": 0.9,
                "max_abs_jerk": 0.18, "regime": "BULL_ACCELERATING", "quality": 0.95,
                "timeframes": {"1H": calc_1h},
                "definite_integrals": {"energy_integral": 1.2, "deviation_area_integral": 0.7, "volume_action_integral": 0.2, "regime": "POSITIVE_ENERGY_EXPANSION"},
                "probability_theory": {"continuation_prob_pct": 70, "breakdown_prob_pct": 30, "skewness": 0.3, "kurtosis": 1.0, "var_95_pct": 1.4, "cvar_95_pct": 1.9, "regime": "HIGH_PROB_BULL_CONTINUATION"},
            },
        }

    def test_system_prompt_keeps_three_math_foundations_and_priority(self):
        """三大数理基石、P0 与决策优先级必须出现在**模型真正收到的** System Prompt 上。

        ★ 2026-09-30 由提示词来源迁移重钉：正文不再住在 Python 常量里（`SYSTEM_PROMPT`
        现在只剩只读输出 JSON Schema，`ai_brain_trader.SYSTEM_PROMPT` 读不到军规），
        三大基石/P0/优先级改由 `data/prompt_library.json` 的 `trading_system` 模块承载。
        故锚点从「读常量」改为「读 effective 提示词」（= JSON 方案模块 ⊕ 只读 Schema 基座）。
        原锚点的 `Cornish-Fisher` 这一具体算法名已不在新正文；同一意图（统计风险基石）
        现由「偏度与超额峰度 + VaR／CVaR」承载，故改钉后者而非削弱断言。
        """
        from scripts.ai_brain_trader import get_effective_system_prompt
        from scripts.prompt_library import active_profile
        prompt = get_effective_system_prompt(active_profile())
        self.assertGreater(len(prompt), 1000, "effective system prompt 为空 —— 定位错了对象")
        for required in ("因果微积分动力学", "定积分能量学", "概率论与统计风险",
                         "P0 不可覆盖硬约束", "偏度与超额峰度", "VaR／CVaR"):
            self.assertIn(required, prompt)
        self.assertIn("执行层拥有最终否决权", prompt)

    def test_system_prompt_does_not_turn_soft_disagreement_into_permanent_wait(self):
        """轻微证据分歧不得被读成永久空仓：减速不是反转、仓位随置信度收缩、R:R 指向运行期预算。

        ★ 2026-09-30 重钉：旧措辞（"只有完美共振才允许交易"/"P2/P3 轻微分歧减小保证金"）
        是代码常量的原文，已随提示词迁移消失。同一意图现在由 JSON 方案模块
        「数理证据与决策优先级」「价格几何、止损与仓位标定」「首席交易官定位…总纲」承载，
        判据改落在 effective 提示词上。
        """
        from scripts.ai_brain_trader import get_effective_system_prompt
        from scripts.prompt_library import active_profile
        prompt = get_effective_system_prompt(active_profile())
        self.assertGreater(len(prompt), 1000)
        self.assertIn("减速不等于反转", prompt)
        self.assertIn("1H 减速回抽是打折买点而不是离场信号", prompt)
        self.assertIn("待命状态", prompt)                       # 空仓 = 待命，不是永久禁令
        self.assertIn("不允许因怕亏而放掉已达标的机会", prompt)
        self.assertIn("按置信度弹性取【本周期风险预算】常规区间", prompt)  # 分歧用仓位收缩处理
        # 批5 P3-4 口径同源：目标 R:R / 盈亏比底线指向运行期推导值，不再硬编码
        self.assertIn("目标盈亏比不得低于执行层声明的硬底线", prompt)

    def test_user_prompt_injects_real_1h_math_values(self):
        missing = "/tmp/astra-test-file-does-not-exist"
        with patch.object(ai_brain_trader, "NEWS_SENTIMENT_FILE", missing), patch.object(ai_brain_trader, "AI_MEMORY_MD_FILE", missing), patch.object(ai_brain_trader, "AI_MEMORY_FILE", missing):
            prompt = ai_brain_trader.construct_full_market_prompt([self.package()], current_time_str="2026-09-01 12:00:00", usdt_available=4000)
        for required in ("1H:v=0.61,a=0.27,j=0.18,I=1.12", "E=1.44,A=0.82", "P续=73.5%", "VaR=1.36%,CVaR=1.82%"):
            self.assertIn(required, prompt)
        self.assertIn("路径偏离面积积分", prompt)
        self.assertNotIn("VWAP偏离面积分", prompt)
        self.assertIn("无可验证新闻输入", prompt)

    def test_only_same_direction_scale_request_is_allowed(self):
        self.assertTrue(ai_brain_trader.is_same_direction_scale_request("long", "BUY_LONG"))
        self.assertTrue(ai_brain_trader.is_same_direction_scale_request("short", "SELL_SHORT"))
        self.assertFalse(ai_brain_trader.is_same_direction_scale_request("long", "SELL_SHORT"))
        self.assertFalse(ai_brain_trader.is_same_direction_scale_request("short", "BUY_LONG"))

    def test_evolution_prompt_forbids_unobserved_math_attribution(self):
        """复盘提示词禁止对**不可观测**的数理快照做事后编造归因。

        ★ 2026-09-30 由提示词来源迁移重钉：`self_improvement_engine.EVOLUTION_SYSTEM_PROMPT`
        已被清空为 `""`（正文迁入 `data/prompt_library.json`）。实发的复盘 System Prompt =
        JSON `evolution_system` 模块 layout **之后**再追加代码层 `build_host_constitution()`。
        故判据改落在该实发文本（方案模块 ⊕ 宿主宪章）上，而非已空的常量。
        原文的"数理快照不可观测/NO_CHANGE/不得编造"三个锚点在 JSON 模块
        「证据纪律与宿主宪章（硬约束）」与「复盘与长期记忆进化任务」里逐字存在。
        """
        from scripts.evolution.review_context import build_host_constitution
        from scripts.prompt_library import active_profile, apply_module_layout, base_template_text
        prof = active_profile()
        prompt = apply_module_layout(base_template_text("evolution_system"), prof,
                                     "evolution_system", "t")
        prompt = prompt.rstrip() + build_host_constitution(
            observability_brief="（回归用例桩：0 笔可观测）")
        self.assertGreater(len(prompt), 500, "effective evolution prompt 为空 —— 定位错了对象")
        for required in ("数理快照不可观测", "NO_CHANGE", "不得编造"):
            self.assertIn(required, prompt)

    def test_no_change_preserves_existing_memory(self):
        status, lessons, preserved = self_improvement_engine.resolve_memory_update("NO_CHANGE", [], ["existing lesson"])
        self.assertEqual(status, "NO_CHANGE")
        self.assertEqual(lessons, ["existing lesson"])
        self.assertTrue(preserved)
        status, lessons, preserved = self_improvement_engine.resolve_memory_update("ADD", ["new lesson"], ["old"])
        self.assertEqual(lessons, ["new lesson"])
        self.assertFalse(preserved)

    def test_counter_trend_short_rejected_in_bull_trend(self):
        p = self.package()
        p["macro_4h"] = "4H_MACRO_BULL (大级别多头通道)"
        d = {"action": "SELL_SHORT", "confidence": 85.0, "entry_price": 60000, "stop_loss_price": 61000, "take_profit_price": 57000}
        act, reason, rr = ai_brain_trader.validate_and_filter_decision(p, d, set(), {})
        self.assertEqual(act, "WAIT")
        self.assertIn("多头主升通道", reason)

    def test_counter_trend_long_rejected_in_bear_trend(self):
        p = self.package()
        p["macro_4h"] = "4H_MACRO_BEAR (大级别空头承压)"
        d = {"action": "BUY_LONG", "confidence": 85.0, "entry_price": 60000, "stop_loss_price": 59000, "take_profit_price": 63000}
        act, reason, rr = ai_brain_trader.validate_and_filter_decision(p, d, set(), {})
        self.assertEqual(act, "WAIT")
        self.assertIn("空头承压通道", reason)

    def test_low_confidence_rejected(self):
        p = self.package()
        p["macro_4h"] = "4H_MACRO_BULL (大级别多头通道)"
        d = {"action": "BUY_LONG", "confidence": 70.0, "entry_price": 60000, "stop_loss_price": 59000, "take_profit_price": 63000}
        act, reason, rr = ai_brain_trader.validate_and_filter_decision(p, d, set(), {})
        self.assertEqual(act, "WAIT")
        self.assertIn("置信度低于安全底线", reason)

    def test_adx_chop_rejected(self):
        p = self.package()
        p["macro_4h"] = "4H_MACRO_BULL (大级别多头通道)"
        p["adx_1h"] = 15.0
        d = {"action": "BUY_LONG", "confidence": 85.0, "entry_price": 60000, "stop_loss_price": 59000, "take_profit_price": 63000}
        act, reason, rr = ai_brain_trader.validate_and_filter_decision(p, d, set(), {})
        self.assertEqual(act, "WAIT")
        self.assertIn("无序震荡杂波市", reason)

    def test_doge_high_noise_threshold(self):
        p = self.package()
        p["name"] = "DOGE"
        p["instId"] = "DOGE-USDT-SWAP"
        p["macro_4h"] = "4H_MACRO_BULL (大级别多头通道)"
        d = {"action": "BUY_LONG", "confidence": 78.0, "entry_price": 0.10, "stop_loss_price": 0.09, "take_profit_price": 0.13}
        act, reason, rr = ai_brain_trader.validate_and_filter_decision(p, d, set(), {})
        self.assertEqual(act, "WAIT")
        self.assertIn("置信度低于安全底线", reason)

    def test_valid_trend_aligned_order_accepted(self):
        p = self.package()
        p["macro_4h"] = "4H_MACRO_BULL (大级别多头通道)"
        p["adx_1h"] = 28.0
        d = {"action": "BUY_LONG", "confidence": 85.0, "entry_price": 60000, "stop_loss_price": 59000, "take_profit_price": 63000}
        act, reason, rr = ai_brain_trader.validate_and_filter_decision(p, d, set(), {})
        self.assertEqual(act, "BUY_LONG")
        self.assertEqual(reason, "")
        self.assertGreaterEqual(rr, 2.0)


if __name__ == "__main__":
    unittest.main()
