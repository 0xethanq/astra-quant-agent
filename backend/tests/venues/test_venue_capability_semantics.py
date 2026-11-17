"""OKX 能力表真实语义与 attachAlgo 契约测试（全 mock、零网络、零真实凭证）。

覆盖：
1. OKX 能力表声明：attached conditional_family、failCode 保护语义；
2. OKX attachAlgo failCode 核验三态（纯函数零网络）。
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from astra_backend.exchanges.base import ExchangeCapabilityError, InstrumentSpec
from astra_backend.exchanges.okx import OKXPublicAdapter
from astra_backend import okx_trade_service as ots

_AMBIENT: dict = {}


def setUpModule():
    """隔离宿主 .env 的执行/档位旗标。"""
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


class TestCapabilityDeclarations(unittest.TestCase):
    def test_okx_attach_failcode_declared(self):
        cap = OKXPublicAdapter.capabilities
        self.assertEqual(cap.conditional_family, "attached")
        ps = cap.protection_semantics
        self.assertIn("failCode", ps)                # 受理≠生效，须核验
        self.assertIn("canceled", ps)                # 2026-08-20 直接终态语义
        self.assertIn("200", ps)                     # HTTP 200≠受保护字面钉住

    def test_new_fields_have_safe_defaults(self):
        import dataclasses
        names = ("order_id_type", "native_amend", "decimal_amount",
                 "position_modes", "conditional_family", "protection_semantics")
        for f in dataclasses.fields(OKXPublicAdapter.capabilities):
            if f.name in names:
                self.assertTrue(f.default is not dataclasses.MISSING
                                or f.default_factory is not dataclasses.MISSING, f.name)


# ----------------------------------------------------------------------
# OKX attachAlgo failCode 核验三态（纯函数零网络）
# ----------------------------------------------------------------------
class TestOkxAttachVerification(unittest.TestCase):
    LEG = {"kind": "sl", "side": "buy", "sz": "2", "x_price": "78000"}
    PEND = [{"instId": "BTC-USDT-SWAP", "side": "buy", "sz": "2.000",
             "xPrice": "78000.0", "algoId": "a1"}]

    def test_http_200_with_failcode_is_unprotected(self):
        r = ots.verify_attached_protection(
            inst_id="BTC-USDT-SWAP", expected_legs=[self.LEG],
            attach_rows=[{"sz": "2", "xPrice": "78000", "side": "buy",
                          "failCode": "51177", "failReason": "trigger price invalid"}],
            pending_rows=self.PEND, main_order_state="filled")
        self.assertEqual(r["status"], "UNPROTECTED")     # 回执有 failCode → 该腿未受理
        self.assertEqual(r["legs"][0]["state"], "failed")
        self.assertEqual(r["legs"][0]["failCode"], "51177")

    def test_pending_full_coverage_is_protected(self):
        r = ots.verify_attached_protection(
            inst_id="BTC-USDT-SWAP", expected_legs=[self.LEG],
            pending_rows=self.PEND, main_order_state="filled")
        self.assertEqual(r["status"], "PROTECTED")       # 十进制字符串比较 2==2.000

    def test_filled_but_missing_readback_is_pending_not_claimed(self):
        r = ots.verify_attached_protection(
            inst_id="BTC-USDT-SWAP", expected_legs=[self.LEG],
            pending_rows=[], main_order_state="new")
        self.assertEqual(r["status"], "PROTECTION_PENDING")  # 未回读绝不宣称受保护

    def test_post_only_direct_terminal_canceled_no_wait(self):
        r = ots.verify_attached_protection(
            inst_id="BTC-USDT-SWAP", expected_legs=[self.LEG],
            pending_rows=[], main_order_state="canceled")  # 2026-08-20 直达终态
        self.assertEqual(r["status"], "UNPROTECTED")
        self.assertIn("终态", r["detail"])                  # 不无限等待 live 的语义

    def test_other_instrument_row_cannot_satisfy(self):
        rows = [{"instId": "ETH-USDT-SWAP", "side": "buy", "sz": "2",
                 "xPrice": "78000"}]
        r = ots.verify_attached_protection(
            inst_id="BTC-USDT-SWAP", expected_legs=[self.LEG],
            pending_rows=rows, main_order_state="filled")
        self.assertNotEqual(r["status"], "PROTECTED")      # 账户/合约归属必须一致

    # ---- US-004 观察项②收口：覆盖数量结构性短缺显式 UNPROTECTED ----
    def _chk(self, sz_exp, rows, state="filled"):
        return ots.verify_attached_protection(
            inst_id="BTC-USDT-SWAP",
            expected_legs=[{"kind": "sl", "side": "buy", "sz": sz_exp,
                            "x_price": "78000"}],
            pending_rows=rows, main_order_state=state)

    def test_shortage_row_is_unprotected_with_gap_reason(self):
        r = self._chk("5", [{"instId": "BTC-USDT-SWAP", "side": "buy",
                             "sz": "4.000", "xPrice": "78000.0", "algoId": "a9"}])
        self.assertEqual(r["status"], "UNPROTECTED")          # 短缺≠尚未回读
        self.assertEqual(r["legs"][0]["state"], "coverage_shortfall")
        self.assertEqual(r["legs"][0]["reason"], "covered 4 < filled 5")
        self.assertEqual(r["legs"][0]["algo_ids"], ["a9"])

    def test_empty_readback_on_filled_stays_pending(self):
        r = self._chk("5", [])
        self.assertEqual(r["status"], "PROTECTION_PENDING")   # 行缺失=等待语义，非短缺

    def test_full_match_still_protected_after_shortage_split(self):
        r = self._chk("5", [{"instId": "BTC-USDT-SWAP", "side": "buy",
                             "sz": "5", "xPrice": "78000", "algoId": "a5"}])
        self.assertEqual(r["status"], "PROTECTED")
        self.assertEqual(r["legs"][0]["state"], "protected")

    def test_exact_row_wins_over_coexisting_shortage_rows(self):
        rows = [{"instId": "BTC-USDT-SWAP", "side": "buy", "sz": "1",
                 "xPrice": "78000", "algoId": "x"},
                {"instId": "BTC-USDT-SWAP", "side": "buy", "sz": "5",
                 "xPrice": "78000", "algoId": "y"}]
        r = self._chk("5", rows)
        self.assertEqual(r["status"], "PROTECTED")            # 精确行救场，不误杀

    def test_multi_short_rows_summing_below_expected_is_unprotected(self):
        rows = [{"instId": "BTC-USDT-SWAP", "side": "buy", "sz": "2",
                 "xPrice": "78000", "algoId": "m1"},
                {"instId": "BTC-USDT-SWAP", "side": "buy", "sz": "2",
                 "xPrice": "78000", "algoId": "m2"}]
        r = self._chk("5", rows)
        self.assertEqual(r["status"], "UNPROTECTED")
        self.assertEqual(r["legs"][0]["reason"], "covered 4 < filled 5")

    def test_multi_rows_summing_to_expected_stay_pending_not_promoted(self):
        # 多腿合计达期望但无单腿精确匹配：保守留在 PENDING（不冒充精确核验）
        rows = [{"instId": "BTC-USDT-SWAP", "side": "buy", "sz": "2",
                 "xPrice": "78000", "algoId": "p1"},
                {"instId": "BTC-USDT-SWAP", "side": "buy", "sz": "3",
                 "xPrice": "78000", "algoId": "p2"}]
        r = self._chk("5", rows)
        self.assertEqual(r["status"], "PROTECTION_PENDING")

    def test_oversized_or_incomparable_rows_never_claim_shortage(self):
        big = [{"instId": "BTC-USDT-SWAP", "side": "buy", "sz": "9",
                 "xPrice": "78000", "algoId": "b"}]
        r = self._chk("5", big)
        self.assertEqual(r["status"], "PROTECTION_PENDING")    # 超量：中间态保守
        mixed = [{"instId": "BTC-USDT-SWAP", "side": "buy", "sz": "1",
                  "xPrice": "78000", "algoId": "s"},
                 {"instId": "BTC-USDT-SWAP", "side": "buy", "sz": "x?",
                  "xPrice": "78000", "algoId": "g"}]
        r2 = self._chk("5", mixed)
        self.assertEqual(r2["status"], "PROTECTION_PENDING")   # 不可量化行挡短缺武断

    def test_differside_or_trigger_rows_not_counted_as_shortage(self):
        # side/触发值不匹配的行（如旧棘轮残留腿）不得拼成"短缺"错判
        rows = [{"instId": "BTC-USDT-SWAP", "side": "sell", "sz": "5",
                 "xPrice": "78000", "algoId": "sd"},
                {"instId": "BTC-USDT-SWAP", "side": "buy", "sz": "5",
                 "xPrice": "66000", "algoId": "tg"}]
        r = self._chk("5", rows)
        self.assertEqual(r["status"], "PROTECTION_PENDING")
        self.assertEqual(r["legs"][0]["state"], "pending_readback")

    def test_three_state_enum_declared(self):
        self.assertEqual(set(ots.PROTECTION_STATES),
                         {"PROTECTION_PENDING", "PROTECTED", "UNPROTECTED"})


if __name__ == "__main__":
    unittest.main()
