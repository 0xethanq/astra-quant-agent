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

    def test_wrong_confirmation_does_not_burn_token(self):
        token, _ = self._make_intent()
        adapter = _FakeAdapter(0.275)
        with patch("astra_backend.exchanges.get_adapter", return_value=adapter):
            with self.assertRaises(ValueError) as ctx:
                close_intent.venue_fast_close("binance", "demo", token, "CLOSE ALL THE THINGS")
            self.assertIn("确认短语必须精确为", str(ctx.exception))
        self.assertIsNotNone(close_intent.peek(token))  # 预检失败不消费
        self.assertEqual(adapter.close_calls, [])

    def test_environment_switch_rejects_close(self):
        token, _ = self._make_intent(env="demo")
        adapter = _FakeAdapter(0.275)
        with patch("astra_backend.exchanges.get_adapter", return_value=adapter):
            with self.assertRaises(ValueError) as ctx:
                close_intent.venue_fast_close("binance", "live", token, "CLOSE BINANCE DEMO ETH-USDT-SWAP LONG 0.275")
            self.assertIn("环境已切换", str(ctx.exception))
        self.assertEqual(adapter.close_calls, [])

    def test_size_drift_rejects_close(self):
        token, _ = self._make_intent(size=0.275)
        adapter = _FakeAdapter(9.9)  # 意图登记 0.275，实际 9.9
        with patch("astra_backend.exchanges.get_adapter", return_value=adapter):
            with self.assertRaises(ValueError) as ctx:
                close_intent.venue_fast_close("binance", "demo", token, "CLOSE BINANCE DEMO ETH-USDT-SWAP LONG 0.275")
            self.assertIn("仓位数量已从", str(ctx.exception))
        self.assertEqual(adapter.close_calls, [])

    def test_position_gone_rejects_close(self):
        token, _ = self._make_intent()
        adapter = _FakeAdapter(0.0)  # 已无持仓
        with patch("astra_backend.exchanges.get_adapter", return_value=adapter):
            with self.assertRaises(ValueError) as ctx:
                close_intent.venue_fast_close("binance", "demo", token, "CLOSE BINANCE DEMO ETH-USDT-SWAP LONG 0.275")
            self.assertIn("目标仓位已不存在", str(ctx.exception))

    def test_credential_rotation_invalidates_token(self):
        # 审计 B3：签发与点击之间凭证轮换 → 指纹失配必须拒平（对齐 OKX identity 强度）
        token, confirmation = close_intent.create(venue="binance", environment="demo", display_inst="ETH-USDT-SWAP",
                                                  symbol="ETH", pos_side="long", expected_size=0.275,
                                                  credential_fingerprint="aaaa1111bbbb2222")
        adapter = _FakeAdapter(0.275)
        with patch("astra_backend.exchanges.get_adapter", return_value=adapter), \
             patch("astra_backend.exchanges.venue_credentials", return_value=("rotated-key", "rotated-secret")):
            with self.assertRaises(ValueError) as ctx:
                close_intent.venue_fast_close("binance", "demo", token, confirmation)
            self.assertIn("已轮换", str(ctx.exception))
        self.assertEqual(adapter.close_calls, [])
        self.assertIsNotNone(close_intent.peek(token))  # 预检失败不烧令牌

    def test_happy_path_closes_market_and_confirms_zero(self):
        token, confirmation = self._make_intent()
        adapter = _FakeAdapter(-1795.8)  # 空头
        with patch("astra_backend.exchanges.get_adapter", return_value=adapter):
            with self.assertRaises(ValueError):  # 方向不符：意图 LONG，实际 SHORT → 视为目标不存在
                close_intent.venue_fast_close("binance", "demo", token, confirmation)
        token, confirmation = close_intent.create(venue="binance", environment="demo", display_inst="SUI-USDT-SWAP",
                                                  symbol="ETH", pos_side="short", expected_size=1795.8)
        adapter = _FakeAdapter(-1795.8)
        with patch("astra_backend.exchanges.get_adapter", return_value=adapter):
            result = close_intent.venue_fast_close("binance", "demo", token, confirmation)
        self.assertEqual(result["status"], "confirmed_closed")
        self.assertEqual(result["venue"], "binance")
        self.assertEqual(result["closed_size"], 1795.8)
        self.assertEqual(result["instId"], "SUI-USDT-SWAP")
        self.assertEqual(adapter.close_calls, ["ETH"])
        self.assertIsNone(close_intent.peek(token))  # 已消费


if __name__ == "__main__":
    unittest.main()
