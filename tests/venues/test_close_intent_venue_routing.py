"""三所平权后台平仓意图（close_intent）封闭单测。

覆盖 ASTRA-BUGFIX 2026-09-13：合并快照曾为 Binance/Gate 伪造 `token-venue-*` 假令牌，
平仓端点只认 OKX _INTENTS → 非 OKX 仓位平仓必然「平仓令牌无效或已使用」。
本测试不触网（封闭三律·律①）：适配器与 sleep 全部 patch。
"""
from __future__ import annotations
import unittest
from unittest.mock import patch

from astra_backend import close_intent


class _FakeAdapter:
    """可控持仓：fast_close_position 被调用后持仓归零。"""

    def __init__(self, size_signed: float):
        self.sizes = [size_signed]
        self.close_calls: list[str] = []

    def positions(self):
        return [{"venue": "binance", "inst_id": "ETHUSDT", "base": "ETH",
                 "size_signed": s, "unrealized_pnl": 0.1} for s in self.sizes if abs(s) > 1e-12]

    def fast_close_position(self, symbol: str):
        self.close_calls.append(symbol)
        self.sizes = [0.0]
        return {"orderId": "12345"}


class CloseIntentTests(unittest.TestCase):
    def setUp(self):
        close_intent._INTENTS.clear()
        # 封闭三律·律①：禁止真实网络与真实休眠
        self._sleep = patch.object(close_intent.time, "sleep")
        self._sleep.start()
        self.addCleanup(self._sleep.stop)

    def _make_intent(self, size=0.275, env="demo"):
        return close_intent.create(venue="binance", environment=env, display_inst="ETH-USDT-SWAP",
                                   symbol="ETH", pos_side="long", expected_size=size)

    def test_create_registers_real_one_time_token(self):
        token, confirmation = self._make_intent()
        self.assertGreaterEqual(len(token), 20)
        self.assertNotIn("token-binance", token)  # 旧伪令牌形态绝迹
        self.assertEqual(confirmation, "CLOSE BINANCE DEMO ETH-USDT-SWAP LONG 0.275")
        self.assertIsNone(close_intent.peek("no-such-token"))
        self.assertIsNotNone(close_intent.peek(token))
        rec = close_intent.consume(token)
        self.assertEqual(rec["venue"], "binance")
        with self.assertRaises(ValueError) as ctx:
            close_intent.consume(token)  # 一次性：重复消费必失败
        self.assertIn("无效或已使用", str(ctx.exception))

    def test_expired_intent_is_swept_and_rejected(self):
        token, _ = self._make_intent()
        close_intent._INTENTS[token]["expires_at"] = close_intent.time.time() - 1
        # 新签发触发清扫
        self._make_intent(size=1.5)
        self.assertNotIn(token, close_intent._INTENTS)
        with self.assertRaises(ValueError) as ctx:
            close_intent.consume(token)
        self.assertIn("无效或已使用", str(ctx.exception))

    def test_removed_venues_are_refused_fail_closed(self):
        token, confirmation = self._make_intent()
        for v in ("binance", "gate", "hyperliquid"):
            with self.assertRaises(ValueError) as ctx:
                close_intent.venue_fast_close(v, "demo", token, confirmation)
            self.assertIn("不支持的平仓场所", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
