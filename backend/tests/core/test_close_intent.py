"""平仓意图：**令牌一次性、口令逐字、指纹漂移即拒、不平则明确报错**（第二百七十刀，开新面 close_intent.py）。

先打印整个文件（151 行）再动笔。它与 OKX 平仓契约同构：服务端随机令牌登记 · 90 秒时效 ·
环境绑定 · 口令短语全等 · 消费前仓位数量二次校验 · 平仓后回读归零核验。
"""

import threading
import unittest
from unittest import mock

from astra_backend import close_intent as CI


class _AdapterBase:
    def __init__(self, rows, result=None, stays_open=False):
        self.rows = list(rows)
        self.result = {"closed": True} if result is None else result
        self.stays_open = stays_open
        self.close_calls = []

    def positions(self):
        return list(self.rows)

    def _close(self, symbol, **kwargs):
        self.close_calls.append((symbol, kwargs))
        if not self.stays_open:
            self.rows = []
        return self.result


class _AdapterWithSide(_AdapterBase):
    def fast_close_position(self, symbol, pos_side=None):
        return self._close(symbol, pos_side=pos_side)


class _AdapterNoSide(_AdapterBase):
    def fast_close_position(self, symbol):
        return self._close(symbol)


def _row(base="BTC", size_signed=2.0, symbol="BTC-USDT-SWAP", with_base=True):
    row = {"symbol": symbol, "size_signed": size_signed}
    if with_base:
        row["base"] = base
    return row


class _IntentBase(unittest.TestCase):
    def _start(self, patcher):
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def setUp(self):
        self.now = 10_000.0
        CI._INTENTS.clear()
        self.addCleanup(CI._INTENTS.clear)
        self.clock = self._start(mock.patch.object(CI.time, "time",
                                                   side_effect=lambda: self.now))
        self.sleeper = self._start(mock.patch.object(CI.time, "sleep"))

    def _new(self, **over):
        params = {"venue": "binance", "environment": "demo",
                  "display_inst": "BTC-USDT-SWAP", "symbol": "BTC",
                  "pos_side": "long", "expected_size": 2.0}
        params.update(over)
        return CI.create(**params)


class AdapterEnvironmentTests(unittest.TestCase):
    def test_pass_through(self):
        self.assertEqual(CI.adapter_environment("okx", "demo"), "demo")
        self.assertEqual(CI.adapter_environment("okx", "live"), "live")
        self.assertEqual(CI.adapter_environment("okx", "weird"), "weird")

    def test_single_source_of_truth_aliases(self):
        self.assertIs(CI._ADAPTER_ENV, CI.ADAPTER_ENV)

    def test_pos_side_is_decided_by_sign(self):
        self.assertEqual(CI._pos_side(1.0), "long")
        self.assertEqual(CI._pos_side(0.0), "short")
        self.assertEqual(CI._pos_side(-3.0), "short")


class CreateTests(_IntentBase):
    def test_confirmation_phrase_format(self):
        token, confirmation = self._new()
        self.assertEqual(confirmation, "CLOSE BINANCE DEMO BTC-USDT-SWAP LONG 2")
        self.assertTrue(token)
        self.assertNotEqual(token, "token-venue-fake")
        self.assertGreater(len(token), 20, "必须是服务端随机令牌")

    def test_fractional_size_is_rendered_compactly(self):
        _, confirmation = self._new(expected_size=0.5)
        self.assertIn("0.5", confirmation)
        self.assertNotIn("0.50000", confirmation)

    def test_token_is_unique_per_call(self):
        first, _ = self._new()
        second, _ = self._new()
        self.assertNotEqual(first, second)

    def test_expiry_is_ninety_seconds_out(self):
        token, _ = self._new()
        self.assertEqual(CI.peek(token)["expires_at"], self.now + CI.INTENT_TTL_SECONDS)
        self.assertEqual(CI.INTENT_TTL_SECONDS, 90)

    def test_stale_intents_are_pruned_on_the_next_create(self):
        old, _ = self._new()
        self.now += CI.INTENT_TTL_SECONDS + 1
        self._new()
        self.assertIsNone(CI.peek(old), "过期意图必须被顺手清掉")
        self.assertEqual(len(CI._INTENTS), 1)

    def test_credential_fingerprint_is_recorded(self):
        token, _ = self._new(credential_fingerprint="FP1")
        self.assertEqual(CI.peek(token)["credential_fingerprint"], "FP1")
        default, _ = self._new()
        self.assertEqual(CI.peek(default)["credential_fingerprint"], "")


class PeekAndConsumeTests(_IntentBase):
    def test_peek_is_read_only_and_returns_a_copy(self):
        token, _ = self._new()
        peeked = CI.peek(token)
        peeked["expected_size"] = 999
        self.assertEqual(CI.peek(token)["expected_size"], 2.0,
                         "peek 必须返回副本，改它不能污染登记表")
        self.assertIsNone(CI.peek("nope"))

    def test_consume_is_one_shot(self):
        token, _ = self._new()
        self.assertEqual(CI.consume(token)["symbol"], "BTC")
        with self.assertRaises(ValueError) as ctx:
            CI.consume(token)
        self.assertIn("无效或已使用", str(ctx.exception))

    def test_unknown_token_raises(self):
        with self.assertRaises(ValueError):
            CI.consume("nope")

    def test_expired_token_raises_and_is_still_consumed(self):
        token, _ = self._new()
        self.now += CI.INTENT_TTL_SECONDS + 1
        with self.assertRaises(ValueError) as ctx:
            CI.consume(token)
        self.assertIn("已过期", str(ctx.exception))
        self.assertNotIn(token, CI._INTENTS, "过期令牌先 pop 再判 ⇒ 已被消费，不能重试")

    def test_ttl_boundary_is_exclusive(self):
        token, _ = self._new()
        self.now += CI.INTENT_TTL_SECONDS - 0.001
        self.assertEqual(CI.consume(token)["symbol"], "BTC")


class CredentialFingerprintTests(_IntentBase):
    def test_current_fingerprint_uses_the_venue_credentials(self):
        vc = self._start(mock.patch("astra_backend.exchanges.venue_credentials",
                                    return_value=("APIKEY", "SECRET")))
        cf = self._start(mock.patch("astra_backend.exchanges.identity.credential_fingerprint",
                                    return_value="FP"))
        self.assertEqual(CI._current_credential_fp("binance", "demo"), "FP")
        vc.assert_called_once_with("binance", "demo")
        cf.assert_called_once_with("APIKEY")

    def test_credential_lookup_failure_falls_back_to_an_empty_key(self):
        self._start(mock.patch("astra_backend.exchanges.venue_credentials",
                               side_effect=RuntimeError("凭证库坏了")))
        cf = self._start(mock.patch("astra_backend.exchanges.identity.credential_fingerprint",
                                    return_value="EMPTY-FP"))
        self.assertEqual(CI._current_credential_fp("gate", "sandbox"), "EMPTY-FP")
        cf.assert_called_once_with("")


class VenueFastCloseDecommissionedTest(unittest.TestCase):
    def test_foreign_venues_are_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            CI.venue_fast_close("binance", "demo", "tok", "phrase")
        self.assertIn("不支持的平仓场所", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            CI.venue_fast_close("gate", "demo", "tok", "phrase")
        self.assertIn("不支持的平仓场所", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            CI.venue_fast_close("okx", "demo", "tok", "phrase")
        self.assertIn("不支持的平仓场所", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
