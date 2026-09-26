"""审计 C3（后半）封闭单测：跨所云端 SL 棘轮 amend_venue_stop_loss。

律①/③：纯 stub adapter，零网络零真实交易所调用。
锚定行为：
  1) Gate 样（有 amend_stop_loss）：原生改单、绝不重复 attach、TP 腿不碰；
  2) Binance 样（无 amend）：先挂新再撤旧（顺序即无裸仓窗口），只撤 STOP 腿；
  3) amend 抛错 → 回退先挂新再撤旧；
  4) 枚举旧单失败 → 仍挂新（收紧优先）且 note 诚实标注未能枚举。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

import scripts.ai_factor_trader as aft


class _GateLike:
    def __init__(self):
        self.calls = []

    def list_protective_orders(self, symbol):
        self.calls.append(("list", symbol))
        return [
            {"id": "11", "order": {"text": "t-astrasl9001"}},
            {"id": "12", "order": {"text": "t-astratp9001"}},
        ]

    def amend_stop_loss(self, symbol, pos_side, old_sl_id, new_sl_px, **kw):
        self.calls.append(("amend", symbol, old_sl_id, float(new_sl_px)))
        return old_sl_id

    def attach_protective_orders(self, symbol, pos_side, **kw):
        self.calls.append(("attach", symbol))
        return {"sl": "11"}

    def cancel_price_order(self, oid):
        self.calls.append(("cancel", oid))
        return {"cancelled": True}


class _BinanceLike:
    def __init__(self):
        self.calls = []

    def list_protective_orders(self, symbol):
        self.calls.append(("list", symbol))
        return [
            {"algo_id": "a1", "type": "STOP_MARKET"},
            {"algo_id": "a2", "type": "TAKE_PROFIT_MARKET"},
        ]

    def attach_protective_orders(self, symbol, pos_side, **kw):
        self.calls.append(("attach", symbol, kw.get("sl_px")))
        return {"sl": "a9"}

    def cancel_algo_order(self, *, algo_id=None, client_algo_id=None):
        self.calls.append(("cancel", str(algo_id)))
        return {"success": True}


class _AmendFails(_GateLike):
    def amend_stop_loss(self, symbol, pos_side, old_sl_id, new_sl_px, **kw):
        self.calls.append(("amend", symbol, old_sl_id, float(new_sl_px)))
        raise RuntimeError("sandbox does not support amend")

    def attach_protective_orders(self, symbol, pos_side, **kw):
        self.calls.append(("attach", symbol))
        return {"sl": "99"}


class _ListFails(_BinanceLike):
    def list_protective_orders(self, symbol):
        raise RuntimeError("boom-list")


class SlRatchetTests(unittest.TestCase):
    def test_gate_native_amend_no_attach_tp_untouched(self):
        ad = _GateLike()
        ok, note = aft.amend_venue_stop_loss(ad, "ETH", "long", 3100.0, 2.0)
        self.assertTrue(ok, note)
        self.assertIn(("amend", "ETH", "11", 3100.0), ad.calls)
        self.assertFalse(any(c[0] == "attach" for c in ad.calls))
        # TP 腿（12）与 SL 腿同号回改 → 无残余需撤
        self.assertFalse(any(c[0] == "cancel" for c in ad.calls))

    def test_binance_attach_new_before_cancel_old(self):
        ad = _BinanceLike()
        ok, note = aft.amend_venue_stop_loss(ad, "ETH", "long", 3100.0, 2.0)
        self.assertTrue(ok, note)
        kinds = [c[0] for c in ad.calls]
        self.assertLess(kinds.index("attach"), kinds.index("cancel"))  # 无裸仓窗口
        self.assertIn(("cancel", "a1"), ad.calls)                        # 只撤 STOP 腿
        self.assertFalse(any(c == ("cancel", "a2") for c in ad.calls))   # TP 保留

    def test_amend_failure_falls_back_to_place_then_cancel(self):
        ad = _AmendFails()
        ok, note = aft.amend_venue_stop_loss(ad, "ETH", "long", 3050.0, 1.0)
        self.assertTrue(ok, note)
        kinds = [c[0] for c in ad.calls]
        self.assertLess(kinds.index("amend"), kinds.index("attach"))
        self.assertIn(("cancel", "11"), ad.calls)

    def test_list_failure_still_tightens_with_honest_note(self):
        ad = _ListFails()
        ok, note = aft.amend_venue_stop_loss(ad, "ETH", "long", 3000.0, 1.0)
        self.assertTrue(ok)
        self.assertIn("未能枚举", note)
        self.assertTrue(any(c[0] == "attach" for c in ad.calls))


if __name__ == "__main__":
    unittest.main()
