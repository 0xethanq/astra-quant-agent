"""单元测试：对抗辩论模式 (Debate Mode) 编排与共识注入。"""
from __future__ import annotations

import unittest
from unittest import mock

from astra_backend.council.debate import execute_council_debate

ROLES = {
    "cio": {"name": "首席投资官", "is_arbitrator": True, "prompt": "p"},
    "trader_a": {"name": "甲", "prompt": "p", "weight": 0.5},
    "trader_b": {"name": "乙", "prompt": "p", "weight": 0.5},
}
RESOLVED = {
    "model": "M",
    "base_url": "U",
    "api_key": "K",
    "api_format": "F",
    "effort": "high",
    "requested": "M-req",
    "registered": True,
    "fallback": False,
    "reason": "已登记",
}


class DebateModeOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.trader_calls = []
        self.debate_calls = []
        p = mock.patch("astra_backend.council.debate.time.sleep")
        self.sleep_mock = p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch("astra_backend.llm_manager.get_active_llm_runtime",
                        return_value={"model": "M"})
        p2.start()
        self.addCleanup(p2.stop)
        p3 = mock.patch("astra_backend.llm_manager.execute_llm_request",
                        return_value=('{"macro_assessment": {}, "position_management": [], "decisions": {}}', "思考", {}, 100))
        p3.start()
        self.addCleanup(p3.stop)
        p4 = mock.patch("astra_backend.council.debate._normalize_cio_adopted_roles")
        p4.start()
        self.addCleanup(p4.stop)

    def _run(self, timeout=150.0, proposal_for=None, time_seq=None):
        def _load_config():
            return {"roles": ROLES, "consensus_mode": "debate"}

        def _call_trader(*args, **kwargs):
            self.trader_calls.append(args)
            key = args[0]
            if proposal_for is not None:
                return proposal_for(key)
            return {
                "proposal_id": f"{key}_prop",
                "role_name": args[1].get("name", key),
                "status": "ok",
                "content": f"标的 | 倾向 | 限价 | 止损 | 止盈 | 保证金 | 置信度 | 依据\nBTC-USDT-SWAP | {'BUY_LONG' if key == 'trader_a' else 'SELL_SHORT'} | 100 | 90 | 120 | 100 | 80 | 论据",
                "weight": 0.5,
            }

        def _call_critique(*args, **kwargs):
            self.debate_calls.append(args)
            return {"role_id": args[0], "status": "ok", "content": f"{args[0]} 的辩论反驳", "weight": 0.5}

        patches = []
        if time_seq is not None:
            ticks = iter(time_seq)
            patches.append(mock.patch("astra_backend.council.debate.time.time",
                                      side_effect=lambda: next(ticks, 999.0)))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        try:
            return execute_council_debate(
                _load_config, lambda s: dict(RESOLVED), _call_trader, _call_critique,
                "市场全景", "系统底座", timeout=timeout, runtime_context=None
            ), None
        except Exception as exc:
            return None, exc

    def test_disputed_symbols_trigger_adversarial_debate(self):
        # 默认 proposal_for: trader_a 要多, trader_b 要空 (发生严重撕裂)
        res, exc = self._run(150.0)
        self.assertIsNone(exc)
        self.assertIsNotNone(res)
        out, transcript = res
        self.assertEqual(len(self.trader_calls), 2, "首轮提案正常发起")
        self.assertEqual(len(self.debate_calls), 2, "针对争议标的发起第二轮对抗辩论")

        # 验证 transcript 注入
        self.assertEqual(transcript["consensus_mode"], "debate")
        self.assertIn("consensus_metrics", transcript)
        self.assertIn("adversarial_debates", transcript)
        self.assertIn("BTC-USDT-SWAP", transcript["consensus_metrics"]["disputed_symbols"])

    def test_unanimous_symbols_skip_debate_round(self):
        # 双方均为看多 (无分歧)
        def _unanimous_proposals(key):
            return {
                "proposal_id": f"{key}_prop",
                "role_name": key,
                "status": "ok",
                "content": "标的 | 倾向 | 限价 | 止损 | 止盈 | 保证金 | 置信度 | 依据\nBTC-USDT-SWAP | BUY_LONG | 100 | 90 | 120 | 100 | 80 | 一致看多",
                "weight": 0.5,
            }

        res, exc = self._run(150.0, proposal_for=_unanimous_proposals)
        self.assertIsNone(exc)
        self.assertIsNotNone(res)
        out, transcript = res
        self.assertEqual(len(self.trader_calls), 2)
        self.assertEqual(len(self.debate_calls), 0, "全员高度共识时跳过第二轮辩论")
        self.assertEqual(transcript["adversarial_debates"]["trader_a"]["status"], "skipped")
        self.assertIn("高度共识", transcript["adversarial_debates"]["trader_a"]["content"])

    def test_low_budget_safe_degradation(self):
        # 时间不足 (< 7s) 时安全降级跳过对抗辩论，但仍保留 >= 5s 确保 CIO 终审
        seq = [0.0, 0.0, 4.0, 9.0, 9.5, 9.5]
        res, exc = self._run(15.0, time_seq=seq)
        self.assertIsNone(exc)
        self.assertIsNotNone(res)
        out, transcript = res
        self.assertEqual(len(self.trader_calls), 2)
        self.assertEqual(len(self.debate_calls), 0, "时间紧缺时安全跳过第二轮辩论")
        self.assertEqual(transcript["adversarial_debates"]["trader_a"]["status"], "skipped")
        self.assertIn("时间预算紧缺", transcript["adversarial_debates"]["trader_a"]["content"])


if __name__ == "__main__":
    unittest.main()
