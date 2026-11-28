"""回归测试：TP1/TP2 严格几何排序、minSz 仓位精度、0.30% 手续费保本垫。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.trader import protection, scale_out, tp1


class Tp1Tp2OrderingTests(unittest.TestCase):
    def test_compute_tp1_clamps_strictly_inside_tp2_when_headroom_allows(self):
        # 多单: entry=100, sl=95 (1R=5), atr=5 -> 默认 candidate=110，与 tp2=110 重叠 -> 应内收至 < 110
        got = tp1.compute_tp1(100.0, 5.0, True, prec=2, initial_stop_px=95.0, tp2_px=110.0)
        self.assertIsNotNone(got)
        self.assertGreater(got, 100.0)
        self.assertLess(got, 110.0)

        # 空单对称: entry=100, sl=105, atr=5, tp2=90 -> TP1 必须满足 90 < TP1 < 100
        got_short = tp1.compute_tp1(100.0, 5.0, False, prec=2, initial_stop_px=105.0, tp2_px=90.0)
        self.assertIsNotNone(got_short)
        self.assertLess(got_short, 100.0)
        self.assertGreater(got_short, 90.0)

    def test_bnb_live_failure_headroom_aborts_split_cleanly(self):
        # 复现实盘 BNB 空单事故: entry=552.21, sl=565.65 (1R=13.44), tp2=545.0 (7.21 < 1.45*R)
        got = tp1.compute_tp1(
            552.21, 3.0, False, prec=2, initial_stop_px=565.65, tp2_px=545.0
        )
        self.assertIsNone(got)

        tracker = {"initialStopPx": 565.65, "takeProfitPx": 545.0}
        res = tp1.freeze_tp1(
            tracker, entry_px=552.21, atr=3.0, is_long=False, prec=2,
            initial_stop_px=565.65, tp2_px=545.0,
        )
        self.assertEqual(res, 0.0)
        self.assertIsNone(tracker["scale_out_tp"])

    def test_position_exit_disables_inverted_tp1_instead_of_splitting(self):
        import scripts.ai_factor_trader as aft

        f = {
            "instId": "BNB-USDT-SWAP",
            "name": "BNB",
            "price": 550.0,
            "atr": 3.0,
            "precision": 2,
            "ctVal": 0.01,
            "minSz": 1.0,
            "type": "crypto",
            "market_data_valid": True,
        }
        curr_pos = {"pos": "4.0", "side": "short", "avgPx": "552.21", "upl": 0.8}
        trackers = {
            "BNB-USDT-SWAP_short": {
                "entry_sz": 4.0,
                "initialStopPx": 565.65,
                "trailingStopPx": 565.65,
                "takeProfitPx": 545.0,
                "scale_out_tp": 543.4,  # 倒挂：TP1 < TP2
                "scale_out_phase": 0,
                "lowWaterMark": 550.0,
            }
        }
        actions = []
        ensure_calls = []
        with patch.object(aft, "ensure_cloud_position_protection",
                          lambda *a, **k: (ensure_calls.append((a, k)), (True, "ok"))[1]), \
             patch.object(aft, "protection_signals", lambda **k: False), \
             patch.object(aft, "sync_cloud_algo_stop", lambda *a, **k: True):
            closed, _ = aft.manage_position_tp_and_trailing(
                f, curr_pos, trackers, "2026-11-28 15:00:00", actions
            )
        self.assertFalse(closed)
        t = trackers["BNB-USDT-SWAP_short"]
        self.assertEqual(t["scale_out_phase"], -1)
        self.assertIsNone(t["scale_out_tp"])
        self.assertTrue(len(ensure_calls) >= 1)
        # 确保只调用单腿整仓保护，不会透传 scale_out_tp=543.4
        _, kw = ensure_calls[0]
        self.assertIsNone(kw.get("scale_out_tp"))

    def test_scale_out_uses_min_sz_precision_not_price_precision(self):
        # BTC 典型配置: precision=1 (tickSz=0.1), minSz=0.01, pos_sz=0.05, ratio=0.35
        # 旧逻辑按 round(0.0175, 1) -> 0.0 静默失败；修复后应取 sz_prec=2 -> 0.01
        okx = MagicMock()
        okx.place_order.return_value = [{"ordId": "1"}]
        okx.pending_algo_orders.return_value = []
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        events_path = Path(tmp.name) / "scale_out.jsonl"

        f = {
            "instId": "BTC-USDT-SWAP",
            "name": "BTC",
            "price": 92000.0,
            "atr": 500.0,
            "precision": 1,
            "ctVal": 0.01,
            "minSz": 0.01,
            "type": "crypto",
            "market_data_valid": True,
        }
        curr_pos = {"pos": "0.10", "side": "long", "avgPx": "90000.0", "lever": "5", "venue": "okx"}
        t = {"entry_sz": 0.10, "scale_out_tp": 91000.0, "takeProfitPx": 94000.0, "scale_out_phase": 0}
        actions = []

        with patch.object(scale_out, "SCALE_OUT_EVENTS_FILE", events_path), \
             patch("scripts.trader.scale_out.SCALE_OUT_ENABLED", True), \
             patch("scripts.trader.scale_out.SCALE_OUT_RATIO", 0.35), \
             patch("scripts.trader.scale_out.SCALE_OUT_TRIGGER_ATR", 2.0):
            ok, reason = scale_out.execute_scale_out_if_eligible(
                f,
                curr_pos,
                {"BTC-USDT-SWAP_long": t},
                "2026-11-28 15:00:00",
                actions,
                okx_rest=okx,
                ensure_cloud_position_protection=lambda *a, **k: (True, "ok"),
                record_trade=None,
                notify_trade_close=None,
                close_fee=None,
                close_trade_payload=None,
            )
        self.assertTrue(ok, reason)
        okx.place_order.assert_called_once()
        # 0.10 * 0.35 = 0.035 -> 按 sz_prec=2 对齐为 0.03（若按 price prec=1 会被错抹成 0.0）
        self.assertEqual(okx.place_order.call_args.args[2], "0.03")

    def test_breakeven_cushion_covers_round_trip_fees_and_slippage(self):
        floor_long, desc = protection.ratcheted_trailing_stop(
            is_long=True,
            entry_px=10000.0,
            atr=100.0,
            prec=2,
            peak_profit_px=160.0,
            old_sl=9800.0,
            tier1_breakeven_trigger=150.0,
            tier2_lock_trigger=220.0,
        )
        self.assertEqual(floor_long, 10030.0)
        self.assertIn("已推保本", desc)

        floor_short, _ = protection.ratcheted_trailing_stop(
            is_long=False,
            entry_px=10000.0,
            atr=100.0,
            prec=2,
            peak_profit_px=160.0,
            old_sl=10200.0,
            tier1_breakeven_trigger=150.0,
            tier2_lock_trigger=220.0,
        )
        self.assertEqual(floor_short, 9970.0)


if __name__ == "__main__":
    unittest.main()
