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
        """★ 2026-10 重钉：包体改为**7 梯队因子透传**（原 `calculus` 块已退场）。

        注意本包的两个关键性质，它们就是这组用例要守的东西：
        1. `quant_factors` 里全是**真实因子值**（MACD 柱/加速度、CVD、OBI、VWAP/POC…）；
        2. 完全**没有** `recent_15m/1h/4h` 原始 K 线 —— 提示词里也一个字节都不许出现。
        """
        return {
            "name": "BTC", "instId": "BTC-USDT-SWAP", "data_quality": "valid",
            "price": 60000, "chg24h": 1.2, "bidPx": 59999, "askPx": 60001,
            "smart_money": {}, "adx_1h": 28, "recent_15m": [], "recent_1h": [], "recent_4h": [],
            "fundingRate": 0.01, "oiUsd": 1000000, "lsRatio": 1.1, "takerNetUsd": 12000,
            "atr_1h": 850.0, "rsi_1h": 61.5, "rsi_15m": 55.0, "vol_ratio": 1.8,
            "obv_flow": "BULL_FLOW",
            "quant_factors": {
                "trend_momentum": {
                    "adx_1h": 28.0, "rsi_14": 61.5, "rsi_1h": 61.5, "rsi_15m": 55.0,
                    "rsi_zone": "BULL_MOMENTUM", "rsi_divergence": "NONE",
                    "macd_dif": 128.4, "macd_dea": 83.2, "macd_hist": 45.2,
                    "macd_accel": 12.8, "macd_momentum_state": "ACCELERATING",
                    "macd_divergence": "NONE", "vwap_bias_pct": 0.44,
                    "trend_regime": "UPTREND",
                },
                "volatility_channel": {"atr_14": 620.0, "atr_pct": 1.03,
                                       "atr_1h": 850.0, "atr_1h_pct": 1.42,
                                       "bb_width_1h": 4.2, "bb_squeeze": False},
                "volume_money_flow": {
                    "vol_ratio_15m": 1.8, "obv_flow": "BULL_FLOW", "cmf_1h": 0.11,
                    "taker_buy_sell_ratio": 1.19, "cvd_5m_usd": 6800000.0,
                    "cvd_1h_usd": 14200000.0, "cvd_divergence": "NONE",
                    "taker_net_usd": "68.0万 U",
                },
                "microstructure": {
                    "bid_ask_depth_ratio": 1.42, "depth_ratio_20": 1.31,
                    "obi_pct": 28.5, "depth_bias": "STRONG_BID",
                    "spread_bps": 0.33, "spread_pct": 0.0033,
                },
                "smart_money_derivatives": {
                    "funding_rate_pct": 0.0036, "next_funding_rate_pct": 0.0041,
                    "funding_crowding": "NEUTRAL", "oi_usd": "23.44亿 U",
                    "oi_chg_1h_pct": 3.2, "oi_price_quadrant": "LONG_BUILDUP",
                    "long_short_ratio": "1.1", "elite_account_ratio": 1.16,
                    "elite_position_ratio": 0.96, "elite_divergence": "NEUTRAL",
                    "liquidation_long_usd": 1200000.0, "liquidation_short_usd": 3400000.0,
                    "liquidation_net_usd": -2200000.0, "liquidation_bias": "SHORT_SQUEEZE",
                    "basis_annualized_pct": 7.4, "loan_rate_usdt": 0.0002,
                },
                "volume_profile": {
                    "vwap_24h": 61850.0, "vwap_sigma_pct": 0.72, "vah": 62400.0,
                    "val": 61200.0, "vpvr_poc": 61680.0,
                    "value_area_position": "INSIDE_VALUE_AREA",
                    "vwap_extreme_band": "NORMAL",
                },
                "options_structure": {
                    "available": True, "atm_iv_pct": 42.5,
                    "risk_reversal_25d_pct": 3.1, "put_call_oi_ratio": 0.73,
                    "max_pain_price": "--", "expiry": "261030", "reason": "",
                },
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
        # ★ 2026-10 重钉：三大数理基石（微积分/定积分/概率论）已整体退场，
        # 同一"证据优先级"意图现由 **7 梯队因子** 承载 —— 故改钉因子口径，
        # 并新增反向断言（下一条用例）确认旧口径不再出现。
        for required in ("因子证据与决策优先级", "MACD(12,26,9)", "RSI(14) 动态区间",
                         "P0 不可覆盖硬约束", "订单簿失衡度 OBI", "VPVR 筹码密集峰 POC"):
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
        self.assertIn("1H MACD 柱收缩是打折买点而不是离场信号", prompt)
        self.assertIn("待命状态", prompt)                       # 空仓 = 待命，不是永久禁令
        self.assertIn("不允许因怕亏而放掉已达标的机会", prompt)
        self.assertIn("按置信度弹性取【本周期风险预算】常规区间", prompt)  # 分歧用仓位收缩处理
        # 批5 P3-4 口径同源：目标 R:R / 盈亏比底线指向运行期推导值，不再硬编码
        self.assertIn("目标盈亏比不得低于执行层声明的硬底线", prompt)

    def test_user_prompt_injects_real_1h_math_values(self):
        missing = "/tmp/astra-test-file-does-not-exist"
        with patch.object(ai_brain_trader, "NEWS_SENTIMENT_FILE", missing), patch.object(ai_brain_trader, "AI_MEMORY_MD_FILE", missing), patch.object(ai_brain_trader, "AI_MEMORY_FILE", missing):
            prompt = ai_brain_trader.construct_full_market_prompt([self.package()], current_time_str="2026-09-01 12:00:00", usdt_available=4000)
        # ⭐ 7 梯队的**真实数值**必须逐项出现在用户提示词里
        for required in ("1H MACD(12,26,9) 柱=45.2", "加速度=12.8",
                         "5M CVD=6800000.0U", "1H CVD=14200000.0U",
                         "Taker买卖比=1.19", "订单簿失衡度(OBI)=28.5%",
                         "24H VWAP=61850.0", "VPVR筹码密集峰(POC)=61680.0",
                         "1H RSI(14)=61.5", "平值IV=42.5%",
                         "精英账户比=1.16", "Put/Call OI比=0.73",
                         "季度基差年化=7.4%"):
            self.assertIn(required, prompt, f"用户提示词缺梯队因子：{required}")
        self.assertIn("无可验证新闻输入", prompt)

    def test_system_prompt_no_longer_carries_the_retired_math_foundations(self):
        """⚠️ 反向断言：系统提示词里**不得**再出现微积分/定积分/概率论口径。

        这三块正是用户点名的"噱头"。它们一旦回流，模型又会被引导去引用
        `calculus_dynamics`/`math_prob_rationale`，而执行层早已不再产出这些字段。
        """
        from scripts.ai_brain_trader import get_effective_system_prompt
        from scripts.prompt_library import active_profile
        prompt = get_effective_system_prompt(active_profile())
        for banned in ("因果微积分动力学", "定积分能量学", "概率论与统计风险",
                       "偏度与超额峰度", "VaR／CVaR", "calculus_dynamics",
                       "math_prob_rationale", "三大数理基石", "数理证据"):
            self.assertNotIn(banned, prompt, f"系统提示词仍残留退役口径：{banned}")
        self.assertIn("factor_evidence", prompt)

    def test_user_prompt_no_longer_carries_raw_klines_or_math_foundations(self):
        """⭐⭐ 本仓库最贵的一次减法：原始 K 线与数理噱头**必须彻底消失**。

        每标的原本塞 32 根 `[O,H,L,C,V]` 浮点数组 + 5 行微积分/定积分/概率论，
        这是用户明确点名的 token 浪费与"噱头"。这条用例是那次决策的哨兵：
        只要有人"顺手接回来"，它立刻红。
        """
        missing = "/tmp/astra-test-file-does-not-exist"
        with patch.object(ai_brain_trader, "NEWS_SENTIMENT_FILE", missing), patch.object(ai_brain_trader, "AI_MEMORY_MD_FILE", missing), patch.object(ai_brain_trader, "AI_MEMORY_FILE", missing):
            prompt = ai_brain_trader.construct_full_market_prompt([self.package()], current_time_str="2026-09-01 12:00:00", usdt_available=4000)
        for banned in ("K线(倒序", "三阶微积分", "微积分动力学", "定积分能量学",
                       "概率论与统计风险", "路径偏离面积积分", "分周期速度/加速度/冲量",
                       "三大数理基石"):
            self.assertNotIn(banned, prompt, f"用户提示词仍在注入已退役内容：{banned}")
        import json as _json
        raw = _json.dumps(self.package())
        self.assertNotIn("K线", raw, "测试包本身就不该带原始 K 线")

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
        原文的"因子快照不可观测/NO_CHANGE/不得编造"三个锚点在 JSON 模块
        「证据纪律与宿主宪章（硬约束）」与「复盘与长期记忆进化任务」里逐字存在。

        ⚠️ 2026-10 更正措辞锚点：`数理快照不可观测` → **`因子快照不可观测`**。
        JSON 权威里本来就是"因子快照"（4 处），此前该门能过只是因为**代码层宪章**
        用的是旧词"数理"；本轮把宪章对齐到 7 梯队因子现实（并剥离退役因子词汇）后，
        门禁才暴露它一直在钉一个与权威不一致的词。
        """
        from scripts.evolution.review_context import build_host_constitution
        from scripts.prompt_library import active_profile, apply_module_layout, base_template_text
        prof = active_profile()
        prompt = apply_module_layout(base_template_text("evolution_system"), prof,
                                     "evolution_system", "t")
        prompt = prompt.rstrip() + build_host_constitution(
            observability_brief="（回归用例桩：0 笔可观测）")
        self.assertGreater(len(prompt), 500, "effective evolution prompt 为空 —— 定位错了对象")
        for required in ("因子快照不可观测", "NO_CHANGE", "不得编造"):
            self.assertIn(required, prompt)

    def test_no_change_preserves_existing_memory(self):
        status, lessons, preserved = self_improvement_engine.resolve_memory_update("NO_CHANGE", [], ["existing lesson"])
        self.assertEqual(status, "NO_CHANGE")
        self.assertEqual(lessons, ["existing lesson"])
        self.assertTrue(preserved)
        status, lessons, preserved = self_improvement_engine.resolve_memory_update("ADD", ["new lesson"], ["old"])
        self.assertEqual(lessons, ["new lesson"])
        self.assertFalse(preserved)

    # ── 2026-10：策略插件系统整套裁撤 ⇒ 以下「策略性闸门」已移除 ─────────────
    # 开不开单由大模型自己判断；本层只做物理必然性校验（数据完整性 / 反向持仓冲突 /
    # 报价几何与 R:R）。旧用例断言的是已删除的行为（4H 逆势一刀切 / 置信度死底线 /
    # DOGE 80% 硬编码 / ADX 杂波门禁），故整组替换为「不再拦截」+「物理仍 fail-closed」。

    def test_counter_trend_order_is_no_longer_blocked(self):
        p = self.package()
        p["macro_4h"] = "4H_MACRO_BULL (大级别多头通道)"
        d = {"action": "SELL_SHORT", "confidence": 85.0, "entry_price": 60000,
             "stop_loss_price": 61000, "take_profit_price": 57000}
        act, reason, rr = ai_brain_trader.validate_and_filter_decision(p, d, set(), {})
        self.assertEqual(act, "SELL_SHORT", f"4H 逆势不应再由底座一票否决: {reason}")
        self.assertEqual(reason, "")
        self.assertGreaterEqual(rr, 2.0)

    def test_low_confidence_is_no_longer_blocked(self):
        p = self.package()
        d = {"action": "BUY_LONG", "confidence": 70.0, "entry_price": 60000,
             "stop_loss_price": 59000, "take_profit_price": 63000}
        act, reason, _ = ai_brain_trader.validate_and_filter_decision(p, d, set(), {})
        self.assertEqual(act, "BUY_LONG", f"置信度死底线已移除: {reason}")

    def test_low_adx_chop_is_no_longer_blocked(self):
        p = self.package()
        p["adx_1h"] = 15.0
        d = {"action": "BUY_LONG", "confidence": 85.0, "entry_price": 60000,
             "stop_loss_price": 59000, "take_profit_price": 63000}
        act, reason, _ = ai_brain_trader.validate_and_filter_decision(p, d, set(), {})
        self.assertEqual(act, "BUY_LONG", f"ADX 杂波门禁已移除: {reason}")

    def test_incomplete_market_data_still_fails_closed(self):
        p = self.package()
        p["data_quality"] = "invalid"
        d = {"action": "BUY_LONG", "confidence": 90.0, "entry_price": 60000,
             "stop_loss_price": 59000, "take_profit_price": 63000}
        act, reason, _ = ai_brain_trader.validate_and_filter_decision(p, d, set(), {})
        self.assertEqual(act, "WAIT")
        self.assertIn("行情不完整", reason)

    def test_opposing_position_collision_still_fails_closed(self):
        p = self.package()
        d = {"action": "SELL_SHORT", "confidence": 90.0, "entry_price": 60000,
             "stop_loss_price": 61000, "take_profit_price": 57000}
        act, reason, _ = ai_brain_trader.validate_and_filter_decision(
            p, d, {"BTC-USDT-SWAP"}, {"BTC-USDT-SWAP": "long"})
        self.assertEqual(act, "WAIT")
        self.assertIn("反向或不兼容持仓", reason)

    def test_illegal_quote_geometry_still_fails_closed(self):
        p = self.package()
        d = {"action": "BUY_LONG", "confidence": 90.0, "entry_price": 60000,
             "stop_loss_price": 61000, "take_profit_price": 63000}
        act, reason, _ = ai_brain_trader.validate_and_filter_decision(p, d, set(), {})
        self.assertEqual(act, "WAIT")
        self.assertIn("买多几何不合法", reason)

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
class MissingTierDataNeverRendersAsAPlausibleNumberTest(unittest.TestCase):
    """★ 2026-10「不许假数据」提示词总门：源全挂时**一个假读数都不许出现**。

    提示词是模型判断的唯一输入。默认块里那些"看起来合理"的常量
    （`50.0`/`1.0`/`0.0`/`NEUTRAL`）一旦被渲染出来，模型就会把它们当**观测到的市场状态**
    写进 `factor_evidence`（实盘出现过"RSI=50 中性""深度均衡"这类引用）。
    本门用"所有源都失败"的因子块渲染一次提示词，逐项排查假读数。
    """

    def _failed_tier_package(self):
        from tests.llm.test_prompt_math_foundations import PromptMathFoundationsTests  # noqa
        from scripts.factors.defaults import build_default_factors
        from scripts.factors import okx_quant_factors as qf
        from scripts.factors.candles_15m import mark_15m_missing

        tiers = build_default_factors("BTC-USDT-SWAP", "BTC")
        qf.apply_momentum_tier(tiers, closes_1h=[], closes_15m=[], trend="", price=0.0)
        qf.apply_volume_profile_tier(tiers, raw_candles_15m=[], price=0.0)
        qf.apply_microstructure_tier(tiers, depth=None, price=0.0)
        qf.apply_orderflow_tier(tiers, taker_5m=None, taker_1h=None, closes_1h=[])
        qf.apply_derivatives_tier(tiers, snapshot={}, ct_val=None, price_chg_1h_pct=None)
        mark_15m_missing(tiers)
        tiers["trend_momentum"]["adx_1h"] = None
        qf.mark_momentum_missing(tiers)
        qf.mark_volume_profile_missing(tiers)

        pkg = PromptMathFoundationsTests().package()
        pkg["quant_factors"] = {k: v for k, v in tiers.items() if isinstance(v, dict)}
        return pkg

    def _prompt(self, pkg):
        import ai_brain_trader
        missing = "/tmp/astra-test-file-does-not-exist"
        with patch.object(ai_brain_trader, "NEWS_SENTIMENT_FILE", missing), \
                patch.object(ai_brain_trader, "AI_MEMORY_MD_FILE", missing), \
                patch.object(ai_brain_trader, "AI_MEMORY_FILE", missing):
            return ai_brain_trader.construct_full_market_prompt(
                [pkg], current_time_str="2026-10-01 12:00:00", usdt_available=4000)

    def test_no_plausible_placeholder_ever_reaches_the_prompt(self):
        prompt = self._prompt(self._failed_tier_package())
        # 每一条都对应一个曾经会渲染出来的"假结论"
        for fake in ("RSI(14)=50.0", "=50.0 (", "CVD=0.0U", "24H VWAP=0.0",
                     "买卖深度比=1.0", "Top20深度比=1.0", "Taker买卖比=1.0",
                     "ADX=0.0", "量比=1.0x", "VWAP乖离=0.0", "POC=0.0",
                     "失衡度=0.0"):
            self.assertNotIn(fake, prompt, f"提示词里出现了假读数：{fake}")

    def test_missing_fields_are_visibly_missing(self):
        prompt = self._prompt(self._failed_tier_package())
        self.assertIn("--", prompt, "缺失必须显式显示 `--`，否则模型会以为拿到了数据")
        self.assertIn("INSUFFICIENT_DATA", prompt, "状态类字段要说清楚是数据不足")
