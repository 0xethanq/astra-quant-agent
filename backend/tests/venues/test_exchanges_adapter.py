"""OKX 交易所适配层单元测试（全 mock、零网络、零真实交易所触碰）。

覆盖：符号转译、数量语义换算（张数向下取整）、规格解析、能力表声明、张数换算边界。
"""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from astra_backend.exchanges import (
    ExchangeCapabilityError,
    InstrumentSpec,
    canonical_base,
    get_adapter,
    registry,
)
from astra_backend.exchanges.okx import OKXAdapter

_AMBIENT: dict = {}


def setUpModule():
    import os
    global _AMBIENT
    _AMBIENT = {k: os.environ.pop(k, None) for k in list(os.environ)
                if k.startswith("ASTRA_") and ("EXECUTION" in k or "TESTNET" in k)}


def tearDownModule():
    import os
    for k, v in _AMBIENT.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


class TestSymbolMapping(unittest.TestCase):
    def setUp(self):
        self.okx = OKXAdapter(api_key="k", secret_key="s", passphrase="p", environment="demo")

    def test_canonical_base_matrix(self):
        cases = {"BTC": "BTC", "btc": "BTC", "BTC-USDT-SWAP": "BTC",
                 "BTCUSDT": "BTC", "BTC_USDT": "BTC", "PEPEUSDT": "PEPE",
                 "DOGE_USDT": "DOGE", " eth-usdt-swap ": "ETH"}
        for raw, want in cases.items():
            self.assertEqual(canonical_base(raw), want, raw)

    def test_native_symbol_okx(self):
        self.assertEqual(self.okx.native_symbol("BTC"), "BTC-USDT-SWAP")
        self.assertEqual(self.okx.native_symbol("btc_usdt"), "BTC-USDT-SWAP")
        self.assertEqual(self.okx.canonical("BTC-USDT-SWAP"), "BTC")

    def test_bar_mapping(self):
        self.assertEqual(self.okx.to_bar("1H"), "1H")


class TestQuantitySemantics(unittest.TestCase):
    def test_okx_contracts_floor(self):
        okx = OKXAdapter(api_key="k", secret_key="s", passphrase="p", environment="demo")
        spec = InstrumentSpec(venue="okx", inst_id="BTC-USDT-SWAP", base="BTC",
                              tick_size=0.1, step_size=1, ct_val=0.01,
                              min_size=1)
        # 450U @79650，每张名义 796.5U → 0.5649 张 → 0 张（低于最小 1 张）
        qty = okx.quote_qty_to_native(450.0, 79650.0, spec)
        self.assertEqual(qty, 0.0)

        # 450U @100，每张名义 1U (100*0.01) → 450 张
        qty2 = okx.quote_qty_to_native(450.0, 100.0, spec)
        self.assertEqual(qty2, 450.0)


class TestCapabilityTable(unittest.TestCase):
    def test_okx_semantics_declared(self):
        cap = OKXAdapter.capabilities
        self.assertEqual(cap.venue, "okx")
        self.assertEqual(cap.quantity_unit, "contracts")


class TestRegistry(unittest.TestCase):
    def test_registry_venues(self):
        self.assertEqual(registry.registered_venues(), ["okx"])
        with self.assertRaises(ExchangeCapabilityError):
            registry.get_adapter("hyperliquid")
        with self.assertRaises(ExchangeCapabilityError):
            registry.get_adapter("binance")
        with self.assertRaises(ExchangeCapabilityError):
            registry.get_adapter("gate")

    def test_instance_singleton(self):
        self.assertIs(get_adapter("okx"), get_adapter("OKX"))


class ContractsRoundingBoundTest(unittest.TestCase):
    """张数换算的**方向与界**（第一百五十三刀：按用户拍板改为**向下取整**）。"""

    @staticmethod
    def _ad(ct_val):
        from astra_backend.exchanges.base import InstrumentSpec
        ad = OKXAdapter(api_key="k", secret_key="s", passphrase="p", environment="demo")
        return ad, InstrumentSpec(venue="okx", inst_id="X-USDT-SWAP", base="X",
                                  tick_size=0.01, step_size=1,
                                  ct_val=ct_val, min_size=1)

    def test_contracts_never_exceed_the_target_notional(self):
        for per_contract in (7.965, 50.0, 300.0, 1234.5):
            notional = per_contract * 3.5      # 3.5 张 ⇒ floor 到 3 张
            ad, spec = self._ad(per_contract / 100.0)   # price=100 ⇒ 每张 = 100*ct_val
            qty = ad.quote_qty_to_native(notional, 100.0, spec)
            with self.subTest(per_contract=per_contract):
                self.assertEqual(qty, 3.0, "3.5 张必须 floor 到 3 张（不超买）")
                self.assertLessEqual(qty * per_contract, notional + 1e-9,
                                     "换算名义超出了目标（取整方向被改回四舍五入？）")

    def test_large_face_value_instrument_undershoots_instead_of_overshooting(self):
        """把幅度钉死：每张 300U、目标 450U ⇒ 1.5 张 ⇒ **1 张 = 300U（−33%，绝不超买）**。"""
        ad, spec = self._ad(3.0)             # price=100 ⇒ 每张 300U
        qty = ad.quote_qty_to_native(450.0, 100.0, spec)
        self.assertEqual(qty, 1.0, "四舍五入会给出 2 张（600U，+33%）——这正是被拍板改掉的")
        self.assertLessEqual(qty * 300.0, 450.0)

    def test_exact_division_is_not_lost_to_float_noise(self):
        """浮点噪声护栏：600/300 可能算成 1.9999999，`+1e-9` 必须保住 2 张。"""
        ad, spec = self._ad(3.0)
        self.assertEqual(ad.quote_qty_to_native(600.0, 100.0, spec), 2.0)


if __name__ == "__main__":
    unittest.main()
