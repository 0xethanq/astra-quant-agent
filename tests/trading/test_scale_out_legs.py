"""分批止盈实盘化：TP1 单一真源 / 双腿编排 / 腿成交收尾 / 持仓中调整止盈。

## 这组测试守什么（2026-09-29 用户报"分批止盈是不是没生效"）

实测真相：分批止盈**一直在跑**（09-22~09-29 共 15 次，含模拟盘），但

1. **只在 15 分钟巡检那一瞬间判定一次** ⇒ 价格插上 TP1 又回落就整段错过
   （用户抱怨的"TP1 太晚"）；
2. 台账按 `net_pnl > 3.0` **猜**出场原因 ⇒ 分批止盈显示成"目标止盈达成"，
   人从后台看不出它发生过；
3. 模型**无法**在持仓中调整止盈（词表没有 UPDATE_TP、`amend_algo_sl` 的
   `newTpTriggerPx` 全仓无调用点、tracker 的 `takeProfitPx` 建仓后无写入点）。

本组测试把修好的三件事钉住：**TP1 冻结**、**双腿（先挂后撤/幂等/断路器）**、
**腿成交后的收尾与幂等**、**腿感知的止盈 amend（含单向律与下调开关）**。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.trader.legs import (leg_mode, legs_already_match, legs_enabled, plan_legs,
                                split_superseded_by_phase, sync_position_legs)
from scripts.trader.tp1 import (compute_tp1, format_trigger_text, freeze_tp1,
                               tp1_geometry_ok)
from scripts.trader.tp_sync import (allow_adverse, leg_direction_ok, min_step,
                                   sync_cloud_algo_tp)


class Tp1SingleSourceTests(unittest.TestCase):
    def test_tp1_is_frozen_not_recomputed(self):
        """ATR 变了也必须用建仓时冻结的值 —— 旧实现每轮重算，与云端挂单分叉。"""
        tracker = {}
        # `multiple` 显式传入：本用例钉的是"冻结语义"，不该随 .env 的门槛档位变化。
        first = freeze_tp1(tracker, entry_px=100.0, atr=2.0, is_long=True, prec=2, multiple=1.0)
        self.assertAlmostEqual(first, 102.0)
        again = freeze_tp1(tracker, entry_px=100.0, atr=9.9, is_long=True, prec=2, multiple=1.0)
        self.assertEqual(first, again, "TP1 一旦冻结就不得被后续 ATR 改写")

    def test_short_side_freezes_below_entry(self):
        tracker = {}
        tp1 = freeze_tp1(tracker, entry_px=1.14, atr=0.025, is_long=False, prec=4, multiple=1.0)
        self.assertLess(tp1, 1.14)

    def test_invalid_atr_falls_back_to_half_a_percent_of_price(self):
        tp1 = compute_tp1(1000.0, 0.0, True, 2, multiple=1.0)
        self.assertAlmostEqual(tp1, 1005.0)           # max(0, 1000×0.5%) = 5

    def test_geometry_guard_is_side_aware(self):
        self.assertTrue(tp1_geometry_ok(105.0, 110.0, 100.0, True))
        self.assertFalse(tp1_geometry_ok(95.0, 110.0, 100.0, True), "TP1 不能低于现价")
        self.assertFalse(tp1_geometry_ok(112.0, 110.0, 100.0, True), "TP1 不能越过 TP2")
        self.assertTrue(tp1_geometry_ok(95.0, 90.0, 100.0, False))
        self.assertFalse(tp1_geometry_ok(105.0, 90.0, 100.0, False))

    def test_threshold_text_shows_percent_for_cheap_assets(self):
        """旧文案对 ARB（0.2U）恒显示 `+0.00`，人无法判断门槛。"""
        text = format_trigger_text(0.0024, 0.2)
        self.assertIn("%", text)
        self.assertIn("1.2%", text)
        self.assertNotIn("+0.00 ", text)

    def test_threshold_text_reports_the_ratio_it_stands_for(self):
        # 相对量（阈/入场价）必须真的等于声明的百分比
        text = format_trigger_text(2.4, 200.0)
        self.assertIn("1.2%", text)


class LegPlanTests(unittest.TestCase):
    def test_plan_splits_exactly_and_respects_lot_step(self):
        plan = plan_legs(4731, 1.117, 1.07, 1.18, ratio=0.5, min_sz=1, prec=0, px_prec=4)
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]["sz"] + plan[1]["sz"], 4731, "两腿之和必须逐位等于持仓")
        self.assertEqual(plan[0]["role"], "tp1")
        self.assertGreater(plan[0]["tp"], plan[1]["tp"], "TP1 必在 TP2 之前到达（空头：更低）")

    def test_plan_returns_none_when_too_small_to_split(self):
        self.assertIsNone(plan_legs(1, 1.117, 1.07, 1.18, ratio=0.5, min_sz=1, prec=0))

    def test_plan_rejects_identical_tp1_and_tp2(self):
        self.assertIsNone(plan_legs(100, 1.05, 1.05, 1.1, ratio=0.5, min_sz=1, prec=2))

    def test_leg_mode_defaults_to_always_and_unknown_values_do_not_disable_protection(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASTRA_SCALE_OUT_LEG_MODE", None)
            self.assertEqual(leg_mode(), "always")
            os.environ["ASTRA_SCALE_OUT_LEG_MODE"] = "typo-mode"
            self.assertEqual(leg_mode(), "always", "拼错不得静默关掉双腿")
            os.environ["ASTRA_SCALE_OUT_LEG_MODE"] = "off"
            self.assertEqual(leg_mode(), "off")
            os.environ.pop("ASTRA_SCALE_OUT_LEG_MODE", None)

    def test_live_only_skips_the_simulated_environment(self):
        with patch.dict(os.environ, {"ASTRA_SCALE_OUT_LEG_MODE": "live_only"}, clear=False):
            self.assertFalse(legs_enabled(simulated=True))
            self.assertTrue(legs_enabled(simulated=False))

    def test_phase_one_stops_splitting(self):
        self.assertTrue(split_superseded_by_phase({"scale_out_phase": 1}))
        self.assertFalse(split_superseded_by_phase({"scale_out_phase": 0}))
        self.assertFalse(split_superseded_by_phase({}))


class _FakeOkx:
    """最小 OKX 桩：只实现双腿编排用到的东西（不发任何真实请求）。"""

    def __init__(self, pending=None, place_error=None, cancel_error=None):
        self.pending = list(pending or [])
        self.place_error = place_error
        self.cancel_error = cancel_error
        self.placed = []
        self.cancelled = []
        self._next = 9000

    def pending_algo_orders(self, inst_id=None, **kwargs):
        return list(self.pending)

    def place_algo_oco(self, inst_id, side, size, **kwargs):
        if self.place_error:
            raise RuntimeError(self.place_error)
        self._next += 1
        algo_id = str(self._next)
        self.placed.append({"inst_id": inst_id, "side": side, "sz": str(size), **kwargs})
        self.pending.append({"algoId": algo_id, "sz": str(size), "side": side,
                             "posSide": kwargs.get("pos_side", "short"),
                             "tpTriggerPx": str(kwargs.get("tp_trigger_px")),
                             "slTriggerPx": str(kwargs.get("sl_trigger_px")),
                             "state": "live", "reduceOnly": "true"})
        return [{"algoId": algo_id, "sCode": "0"}]

    def cancel_algo_orders(self, ids, inst_id=None, **kwargs):
        if self.cancel_error:
            raise RuntimeError(self.cancel_error)
        ids = [ids] if isinstance(ids, str) else list(ids)
        self.cancelled.extend(ids)
        self.pending = [row for row in self.pending if str(row.get("algoId")) not in ids]
        return [{"algoId": i, "sCode": "0"} for i in ids]

    def amend_algo_sl(self, algo_id, new_sl, **kwargs):
        for row in self.pending:
            if str(row.get("algoId")) == str(algo_id):
                row["slTriggerPx"] = str(new_sl)
                if kwargs.get("new_tp_trigger_px") is not None:
                    row["tpTriggerPx"] = str(kwargs["new_tp_trigger_px"])
                return [{"algoId": algo_id, "sCode": "0"}]
        raise RuntimeError("algo not found")


class LegSyncTests(unittest.TestCase):
    def _single_full_leg(self, sz="4731", tp="1.07"):
        return [{"algoId": "1", "sz": sz, "side": "buy", "posSide": "short", "state": "live",
                 "tpTriggerPx": tp, "slTriggerPx": "1.18", "reduceOnly": "true"}]

    def test_splitting_replaces_one_full_leg_with_two_sized_legs(self):
        okx = _FakeOkx(self._single_full_leg())
        state = {}
        ok, detail = sync_position_legs("SUI-USDT-SWAP", "short", 4731, tp1_px=1.117,
                                       tp2_px=1.07, sl_px=1.18, ratio=0.5, min_sz=1,
                                       prec=0, px_prec=4, okx_rest=okx, simulated=True, state=state)
        self.assertTrue(ok, detail)
        self.assertEqual(len(okx.placed), 2, "必须挂两条腿")
        self.assertEqual([p["sz"] for p in okx.placed], ["2365", "2366"])
        self.assertEqual(okx.cancelled, ["1"], "旧的全量腿必须被撤掉")
        self.assertEqual(state["leg_algo_ids"]["tp1"], "9001")
        self.assertEqual(state["leg_algo_ids"]["tp2"], "9002")

    def test_both_legs_carry_the_same_stop(self):
        """双腿必须各带同一个止损：TP-only 腿会被覆盖率统计整条排除。"""
        okx = _FakeOkx(self._single_full_leg())
        sync_position_legs("SUI-USDT-SWAP", "short", 4731, tp1_px=1.117, tp2_px=1.07,
                           sl_px=1.18, ratio=0.5, min_sz=1, prec=0, px_prec=4,
                           okx_rest=okx, state={})
        self.assertEqual([p["sl_trigger_px"] for p in okx.placed], [1.18, 1.18])

    def test_idempotent_when_geometry_already_matches(self):
        okx = _FakeOkx([
            {"algoId": "1", "sz": "2365", "side": "buy", "posSide": "short", "state": "live",
             "tpTriggerPx": "1.117", "slTriggerPx": "1.18", "reduceOnly": "true"},
            {"algoId": "2", "sz": "2366", "side": "buy", "posSide": "short", "state": "live",
             "tpTriggerPx": "1.07", "slTriggerPx": "1.18", "reduceOnly": "true"},
        ])
        ok, detail = sync_position_legs("SUI-USDT-SWAP", "short", 4731, tp1_px=1.117,
                                       tp2_px=1.07, sl_px=1.18, ratio=0.5, min_sz=1,
                                       prec=0, px_prec=4, okx_rest=okx, state={})
        self.assertTrue(ok)
        self.assertEqual(okx.placed, [], "几何已匹配 ⇒ 一次请求都不该发")
        self.assertEqual(okx.cancelled, [])

    def test_place_failure_keeps_the_old_protection(self):
        okx = _FakeOkx(self._single_full_leg(), place_error="OKX 51000")
        ok, detail = sync_position_legs("SUI-USDT-SWAP", "short", 4731, tp1_px=1.117,
                                       tp2_px=1.07, sl_px=1.18, ratio=0.5, min_sz=1,
                                       prec=0, px_prec=4, okx_rest=okx, state={})
        self.assertFalse(ok)
        self.assertIn("旧保护单保留", detail)
        self.assertEqual(okx.cancelled, [], "挂腿失败时绝不撤旧腿（先挂后撤）")

    def test_cancel_failure_is_bounded_by_a_breaker(self):
        """撤单失败 ⇒ 记下 stale id；下一轮先重试撤销，**不再挂新腿**（防腿数无界增长）。"""
        okx = _FakeOkx(self._single_full_leg(), cancel_error="network")
        state = {}
        ok, detail = sync_position_legs("SUI-USDT-SWAP", "short", 4731, tp1_px=1.117,
                                       tp2_px=1.07, sl_px=1.18, ratio=0.5, min_sz=1,
                                       prec=0, okx_rest=okx, state=state)
        self.assertTrue(ok, "新腿已挂上 ⇒ 覆盖仍在，结论是成功")
        self.assertIn("leg_stale_ids", state)
        placed_before = len(okx.placed)
        ok2, detail2 = sync_position_legs("SUI-USDT-SWAP", "short", 4731, tp1_px=1.117,
                                         tp2_px=1.07, sl_px=1.18, ratio=0.5, min_sz=1,
                                         prec=0, px_prec=4, okx_rest=okx, state=state)
        self.assertFalse(ok2)
        self.assertIn("只重试撤销", detail2)
        self.assertEqual(len(okx.placed), placed_before, "撤销未成功前不得再挂腿")

    def test_leg_mode_off_does_nothing(self):
        okx = _FakeOkx(self._single_full_leg())
        with patch.dict(os.environ, {"ASTRA_SCALE_OUT_LEG_MODE": "off"}, clear=False):
            ok, detail = sync_position_legs("SUI-USDT-SWAP", "short", 4731, tp1_px=1.117,
                                           tp2_px=1.07, sl_px=1.18, ratio=0.5, min_sz=1,
                                           prec=0, px_prec=4, okx_rest=okx, state={})
        self.assertFalse(ok)
        self.assertEqual(okx.placed, [])

    def test_match_requires_two_legs_of_the_right_shape(self):
        rows = [
            {"algoId": "1", "sz": "2365", "side": "buy", "posSide": "short", "state": "live",
             "tpTriggerPx": "1.117", "slTriggerPx": "1.18", "reduceOnly": "true"},
            {"algoId": "2", "sz": "2366", "side": "buy", "posSide": "short", "state": "live",
             "tpTriggerPx": "1.07", "slTriggerPx": "1.18", "reduceOnly": "true"},
        ]
        plan = plan_legs(4731, 1.117, 1.07, 1.18, ratio=0.5, min_sz=1, prec=0, px_prec=4)
        self.assertTrue(legs_already_match(rows, plan, "short"))
        rows[1]["slTriggerPx"] = ""       # TP-only 腿：必须判为"不匹配"（覆盖率会漏算）
        self.assertFalse(legs_already_match(rows, plan, "short"))


class TpAmendTests(unittest.TestCase):
    def _rows(self):
        return [
            {"algoId": "11", "sz": "2365", "side": "buy", "posSide": "short", "state": "live",
             "tpTriggerPx": "1.117", "slTriggerPx": "1.18", "reduceOnly": "true"},
            {"algoId": "22", "sz": "2366", "side": "buy", "posSide": "short", "state": "live",
             "tpTriggerPx": "1.07", "slTriggerPx": "1.18", "reduceOnly": "true"},
        ]

    def test_favourable_move_is_applied_and_tracker_follows(self):
        okx = _FakeOkx(self._rows())
        tracker = {"takeProfitPx": 1.07, "scale_out_tp": 1.117, "trailingStopPx": 1.18}
        ok, detail, applied = sync_cloud_algo_tp(
            "SUI-USDT-SWAP", "short", is_long=False, tp2_px=1.05, tp1_px=1.11,
            sl_px=1.18, phase=0, leg_algo_ids={"tp1": "11", "tp2": "22"},
            tracker=tracker, okx_rest=okx, atr=0.02, cur_px=1.14, px_prec=4)
        self.assertTrue(ok, detail)
        self.assertEqual(applied, {"tp1": 1.11, "tp2": 1.05})
        self.assertEqual(tracker["takeProfitPx"], 1.05, "真源必须跟着交易所改")
        self.assertEqual(tracker["scale_out_tp"], 1.11)
        self.assertFalse(tracker["last_tp_amend"]["adverse"])

    def test_adverse_move_is_refused_by_default(self):
        okx = _FakeOkx(self._rows())
        with patch.dict(os.environ, {"ASTRA_TP_ALLOW_ADVERSE": "0"}, clear=False):
            ok, detail, applied = sync_cloud_algo_tp(
                "SUI-USDT-SWAP", "short", is_long=False, tp2_px=1.20,
                leg_algo_ids={"tp1": "11", "tp2": "22"}, okx_rest=okx,
                atr=0.02, cur_px=1.14, px_prec=4)
        self.assertFalse(ok)
        self.assertIn("只允许向有利方向", detail)
        self.assertEqual(applied, {})

    def test_adverse_move_is_allowed_when_switched_on_and_flagged(self):
        okx = _FakeOkx(self._rows())
        tracker = {"takeProfitPx": 1.07}
        with patch.dict(os.environ, {"ASTRA_TP_ALLOW_ADVERSE": "1"}, clear=False):
            ok, detail, _ = sync_cloud_algo_tp(
                "SUI-USDT-SWAP", "short", is_long=False, tp2_px=1.20,
                leg_algo_ids={"tp1": "11", "tp2": "22"}, tracker=tracker,
                okx_rest=okx, atr=0.02, cur_px=1.14, px_prec=4)
        self.assertTrue(ok, detail)
        self.assertTrue(tracker["last_tp_amend"]["adverse"], "下调必须被标红记录")

    def test_after_scale_out_only_tp2_may_change(self):
        okx = _FakeOkx(self._rows())
        ok, detail, _ = sync_cloud_algo_tp(
            "SUI-USDT-SWAP", "short", is_long=False, tp1_px=1.11, phase=1,
            leg_algo_ids={"tp1": "11", "tp2": "22"}, okx_rest=okx, atr=0.02, cur_px=1.14, px_prec=4)
        self.assertFalse(ok)
        self.assertIn("分批已发生", detail)

    def test_amend_failure_does_not_touch_the_source_of_truth(self):
        class _BadAmend(_FakeOkx):
            def amend_algo_sl(self, *a, **k):
                raise RuntimeError("OKX 51000")

        okx = _BadAmend(self._rows())
        tracker = {"takeProfitPx": 1.07}
        ok, detail, applied = sync_cloud_algo_tp(
            "SUI-USDT-SWAP", "short", is_long=False, tp2_px=1.05,
            leg_algo_ids={"tp1": "11", "tp2": "22"}, tracker=tracker,
            okx_rest=okx, atr=0.02, cur_px=1.14, px_prec=4)
        self.assertFalse(ok)
        self.assertEqual(applied, {})
        self.assertEqual(tracker["takeProfitPx"], 1.07, "amend 失败 ⇒ 真源保持原值")

    def test_unregistered_leg_is_not_guessed(self):
        """认腿靠登记：登记缺失时**拒绝**改动，绝不按价格猜（改错腿=半仓错价成交）。"""
        okx = _FakeOkx(self._rows())
        ok, detail, _ = sync_cloud_algo_tp(
            "SUI-USDT-SWAP", "short", is_long=False, tp2_px=1.05,
            leg_algo_ids={}, okx_rest=okx, atr=0.02, cur_px=1.14, px_prec=4)
        self.assertFalse(ok)
        self.assertIn("未找到", detail)

    def test_min_step_blocks_hairline_changes(self):
        step = min_step(0.02, 1.14)
        self.assertGreater(step, 0)
        ok, why = leg_direction_ok(is_long=False, old_px=1.07, new_px=1.07 - step / 10,
                                   step=step, allow_adverse_move=True)
        self.assertFalse(ok)
        self.assertIn("最小步长", why)

    def test_allow_adverse_defaults_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASTRA_TP_ALLOW_ADVERSE", None)
            self.assertFalse(allow_adverse())


class ScaleOutFillFinalizeTests(unittest.TestCase):
    """交易所侧 TP1 腿成交后：只收尾，**不再市价平仓**，且只记一次。"""

    def _tracker(self, **over):
        base = {
            "instId": "SUI-USDT-SWAP", "name": "SUI", "side": "short",
            "entryPx": 1.142, "entry_sz": 4731.0, "currentSz": 4731.0,
            "initialSz": 4731.0, "scale_out_tp": 1.117, "takeProfitPx": 1.07,
            "trailingStopPx": 1.18, "stage_desc": "持有中 (首批止盈目标 TP1: 1.117)",
            "signal_snapshot": {},
        }
        base.update(over)
        return base

    def _factor(self):
        return {"instId": "SUI-USDT-SWAP", "name": "SUI", "price": 1.117, "atr": 0.025,
                "precision": 4, "ctVal": 1.0, "minSz": 1.0, "market_data_valid": True,
                "policy_version": "v8.4.0", "policy_hash": "h"}

    def _position(self, pos):
        return {"pos": pos, "side": "short", "avgPx": 1.142, "ctVal": 1.0, "minSz": 1.0,
                "precision": 0, "lever": 6.0, "venue": "okx"}

    def _run(self, tracker, pos_sz, **kwargs):
        from scripts.trader.scale_out import execute_scale_out_if_eligible
        executed = []
        recorded = []
        notified = []
        # ⚠️ 必须 patch **真实**落点常量：早先这里 patch 了一个不存在的名字
        # （`append_scale_out_event`），于是真实写入器把夹具行灌进了生产流水。
        import scripts.trader.scale_out as _so
        with tempfile.TemporaryDirectory(prefix="astra-scaleout-fill-") as _td, \
             patch.object(_so, "SCALE_OUT_EVENTS_FILE", Path(_td) / "scale_out_events.jsonl"), \
             patch("scripts.trader.scale_out.SCALE_OUT_ENABLED", True), \
             patch("scripts.trader.scale_out.SCALE_OUT_RATIO", 0.5):
            ok, reason = execute_scale_out_if_eligible(
                self._factor(), self._position(pos_sz),
                {"SUI-USDT-SWAP_short": tracker}, "2026-09-29 17:00:00", executed,
                okx_rest=None, venue_registry=None,
                record_trade=recorded.append,
                notify_trade_close=lambda **kw: notified.append(kw),
                close_fee=lambda sz, cv, px, rate: 0.0,
                close_trade_payload=lambda **kw: kw,
                TAKER_FEE_RATE=0.0005,
                ensure_cloud_position_protection=lambda *a, **k: (True, "ok"),
            )
        return ok, reason, tracker, executed, recorded, notified

    def test_a_shrunken_position_is_recognised_as_leg_fill_and_only_finalised(self):
        tracker = self._tracker()
        ok, reason, tracker, executed, recorded, notified = self._run(tracker, 2366)
        self.assertTrue(ok, reason)
        self.assertEqual(tracker["scale_out_phase"], 1)
        self.assertIsNone(tracker["scale_out_tp"])
        self.assertTrue(any("交易所成交" in line for line in executed), executed)
        self.assertEqual(len(recorded), 1, "台账只记一次")
        self.assertEqual(notified, [],
                         "金额通知**不再**由本路径发布（2026-09-30 通知单一事实源："
                         "改由台账路径发，它握有交易所真实成交价与手续费）")

    def test_ctval_missing_from_the_okx_position_falls_back_to_the_pool(self):
        """★ 2026-09-30 真机事故回归：OKX 持仓记录**没有** `ctVal`。

        现场：腿成交收尾自己从 `curr_pos` 取面值并 `or 1.0` 兜底 ⇒ 面值静默变 1，
        ETH（面值 0.1）盈亏/手续费被**放大 10×**（+24.33U 报成 +243.28U），
        ARB（面值 10）被**缩小 10×**（+17.10U 报成 1.84U）。
        本用例用**真实的 OKX 持仓形状**（不带 ctVal）跑收尾，断言金额取自合约池。
        """
        import scripts.trader.scale_out as so
        tracker = self._tracker(entryPx=2697.202098600933, entry_sz=15.01,
                                initialSz=15.01, currentSz=7.51,
                                scale_out_tp=2729.64, trailingStopPx=2651.76,
                                stage_desc="持有中")
        # 真实 OKX 持仓：只有 pos/side/avgPx/lever，**没有 ctVal**（见 factors.py）
        pos = {"pos": 7.51, "side": "long", "avgPx": 2697.202098600933,
               "lever": 9.0, "venue": "okx"}
        f = {"instId": "ETH-USDT-SWAP", "name": "ETH", "price": 2736.58, "atr": 32.46,
             "precision": 2, "ctVal": 0.1, "minSz": 0.01, "market_data_valid": True}
        executed, recorded = [], []
        events = Path(tempfile.mkdtemp(prefix="astra-ctval-")) / "events.jsonl"
        with patch.object(so, "SCALE_OUT_EVENTS_FILE", events), \
             patch("scripts.trader.scale_out.SCALE_OUT_ENABLED", True), \
             patch("scripts.trader.scale_out.SCALE_OUT_RATIO", 0.5):
            ok, reason = so.execute_scale_out_if_eligible(
                f, pos, {"ETH-USDT-SWAP_long": tracker}, "2026-09-29 19:45:00", executed,
                okx_rest=None, venue_registry=None,
                record_trade=lambda payload: recorded.append(payload),
                notify_trade_close=lambda **kw: None,
                close_fee=lambda sz, cv, px, rate: sz * cv * px * rate,
                close_trade_payload=lambda **kw: kw,
                TAKER_FEE_RATE=0.0005,
                ensure_cloud_position_protection=lambda *a, **k: (True, "ok"),
            )
        self.assertTrue(ok, reason)
        row = json.loads(events.read_text(encoding="utf-8").strip())
        # 真值 = 7.5 张 × 0.1 面值 × (2729.64 − 2697.2021) = 24.3284U
        self.assertAlmostEqual(row["realized_pnl"], 24.3284, places=3,
                               msg="面值必须取自合约池 0.1；取 1.0 会放大 10×")
        self.assertAlmostEqual(row["fee"], 7.5 * 0.1 * 2729.64 * 0.0005, places=4)
        # 余仓保证金文案同理：7.51 × 0.1 × 2736.58 / 9 ≈ 228.35U（旧实现写 2273.85U）
        self.assertIn("228.3", tracker["stage_desc"], tracker["stage_desc"])
        self.assertAlmostEqual(recorded[0]["pnl"], 24.3284, places=3)

    def test_a_full_position_is_not_mistaken_for_a_fill(self):
        tracker = self._tracker()
        ok, reason, tracker, _, recorded, _ = self._run(tracker, 4731)
        self.assertFalse(ok, "持仓没缩水 ⇒ 不能当作腿已成交")
        self.assertEqual(recorded, [])
        self.assertEqual(int(tracker.get("scale_out_phase", 0) or 0), 0)

    def test_legacy_tracker_without_entry_size_only_backfills(self):
        """老 tracker 没有 entry_sz ⇒ 本轮只补记，绝不判定（防误判历史持仓）。"""
        tracker = self._tracker()
        tracker.pop("entry_sz")
        ok, reason, tracker, _, recorded, _ = self._run(tracker, 2366)
        self.assertFalse(ok)
        self.assertEqual(tracker["entry_sz"], 2366)
        self.assertEqual(recorded, [])

    def test_finalize_is_idempotent_on_the_next_cycle(self):
        tracker = self._tracker()
        self._run(tracker, 2366)
        ok, reason, tracker, executed, recorded, notified = self._run(tracker, 2366)
        self.assertFalse(ok)
        self.assertEqual(recorded, [], "已收尾过的持仓不得重复记账")
        self.assertEqual(notified, [])


class ScaleOutEventLedgerTests(unittest.TestCase):
    """事件流水是可观测性的第一手证据（用户"看不出分批止盈发生过"的根治）。"""

    def test_event_is_appended_as_jsonl_at_the_patched_location(self):
        import scripts.trader.scale_out as so
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "scale_out_events.jsonl"
            with patch.object(so, "SCALE_OUT_EVENTS_FILE", target):
                self.assertTrue(so._append_scale_out_event(
                    {"ts": "t", "instId": "SUI-USDT-SWAP", "mode": "software"}))
            row = json.loads(target.read_text(encoding="utf-8").strip())
            self.assertEqual(row["mode"], "software")

    def test_writer_cannot_touch_the_production_log_from_a_test(self):
        """真实事故回归（2026-09-29）：用例把夹具行写进了**生产**事件流水。

        这份流水是"分批止盈是否真的发生"的第一手证据，被夹具污染后整个失去意义。
        防线有两条，且都**不依赖生产代码读测试环境变量**：
          ① 落点是模块常量 ⇒ 用例可 patch 到临时目录（正常姿势）；
          ② 该文件已登记进 `tests/__init__.py` 的写保护名单 ⇒ 忘 patch 时
             测试守卫直接拦下写入（生产文件一字节不动）。
        """
        import scripts.trader.scale_out as so
        prod = Path(so._PRODUCTION_EVENTS_FILE)
        before = prod.stat().st_size if prod.exists() else None
        so._append_scale_out_event({"ts": "t", "instId": "X", "mode": "software"})
        after = prod.stat().st_size if prod.exists() else None
        self.assertEqual(before, after, "生产流水内容不得发生任何变化（测试守卫必须拦下）")

    def test_production_log_path_is_a_patchable_module_constant(self):
        """落点必须是**模块常量**：函数内联路径无法被用例重定向（事故根因）。"""
        src = Path("scripts/trader/scale_out.py").read_text(encoding="utf-8")
        self.assertIn("SCALE_OUT_EVENTS_FILE = Path(__file__)", src)
        self.assertNotIn('path = _Path(__file__).resolve().parents[2] / "data" / "scale_out_events.jsonl"',
                         src, "写入器不得再用函数内联路径")

    def test_metrics_reader_counts_modes_and_pnl(self):
        from astra_backend.metrics import collect_scale_out_events
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "scale_out_events.jsonl"
            path.write_text(
                '{"mode":"exchange_leg","realized_pnl":17.09}\n'
                '{"mode":"software","realized_pnl":18.84}\n'
                '{"mode":"exchange_leg","realized_pnl":9.95}\n',
                encoding="utf-8")
            report = collect_scale_out_events(path)
            self.assertEqual(report["total"], 3)
            self.assertEqual(report["by_mode"], {"exchange_leg": 2, "software": 1})
            self.assertAlmostEqual(report["realized_pnl"], 45.88, places=2)

    def test_metrics_reader_returns_none_when_the_file_is_absent(self):
        from astra_backend.metrics import collect_scale_out_events
        self.assertIsNone(collect_scale_out_events(Path("/nonexistent/scale_out_events.jsonl")))

    def test_metrics_applies_face_value_corrections(self):
        """★ 2026-09-30：面值退化成 1 的历史行按 `mode: "correction"` 净掉。

        现场：流水里 ETH 那行写着 +243.2843U（真值 +24.3284U）、ARB 写着 +1.839U
        （真值 +18.39U）。历史行**不重写**（只追加），追加一条更正行把原行净掉，
        指标改按更正后的数字汇总，并暴露 `corrected` 计数。
        """
        from astra_backend.metrics import collect_scale_out_events
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "scale_out_events.jsonl"
            path.write_text(
                '{"ts":"t1","instId":"ETH-USDT-SWAP","mode":"exchange_leg","realized_pnl":243.2843}\n'
                '{"ts":"t2","instId":"ARB-USDT-SWAP","mode":"exchange_leg","realized_pnl":1.839}\n'
                '{"ts":"t1","instId":"ETH-USDT-SWAP","mode":"correction",'
                '"fixes":{"ts":"t1","instId":"ETH-USDT-SWAP"},'
                '"old_realized_pnl":243.2843,"realized_pnl":24.3284}\n'
                '{"ts":"t2","instId":"ARB-USDT-SWAP","mode":"correction",'
                '"fixes":{"ts":"t2","instId":"ARB-USDT-SWAP"},'
                '"old_realized_pnl":1.839,"realized_pnl":18.39}\n',
                encoding="utf-8")
            report = collect_scale_out_events(path)
            self.assertEqual(report["corrected"], 2)
            self.assertAlmostEqual(report["realized_pnl"], 42.72, places=2,
                                   msg="被更正的原行不得再计入（否则 243.28 会一直污染指标）")

    def test_correction_rows_carry_the_exchange_truth_shape(self):
        """更正行的形状约定：`fixes` 指向原行、保留旧值、面值显式落盘。

        为什么用构造夹具而不是读线上流水：本仓纪律明确禁止"断言依赖生产数据内容"
        （那条流水会随真实交易变化，测试会变成定时炸弹）。线上那两笔更正的核对
        属于**运维验收**动作（见提交说明），不写进常驻门禁。
        """
        row = {"mode": "correction", "ts": "2026-09-29 19:45:01", "instId": "ETH-USDT-SWAP",
               "fixes": {"ts": "2026-09-29 19:45:01", "instId": "ETH-USDT-SWAP"},
               "ct_val_true": 0.1, "old_realized_pnl": 243.2843, "realized_pnl": 24.3284,
               "old_fee": 10.2362, "fee": 1.0236}
        # 事故指纹：旧值 = 真值 / 面值（面值退化成 1 ⇒ 放大 1/ctVal 倍）
        self.assertAlmostEqual(row["old_realized_pnl"] / row["realized_pnl"], 10.0, places=3)
        self.assertAlmostEqual(row["old_fee"] / row["fee"], 10.0, places=3)
        self.assertAlmostEqual(row["realized_pnl"], 7.5 * 0.1 * (2729.64 - 2697.202098600933),
                               places=3)
        self.assertEqual(sorted(row["fixes"]), ["instId", "ts"], "更正行必须能指回原行")


class LedgerAttributionTests(unittest.TestCase):
    def test_source_labels_scale_out_and_ai_closes_distinctly(self):
        src = Path("scripts/ledger/okx_history.py").read_text(encoding="utf-8")
        self.assertIn('cl_ord_id.startswith("SO")', src)
        self.assertIn("首批分批止盈", src)
        self.assertIn("AI 主动止盈平仓", src)
        self.assertNotIn('exit_reason = "🎯 目标止盈达成" if net_pnl > 3.0 else ("🛑 止损离场"',
                         src, "不得再用盈亏金额猜出场原因")

    def test_scale_out_orders_are_tagged_with_the_SO_prefix(self):
        src = Path("scripts/trader/scale_out.py").read_text(encoding="utf-8")
        self.assertIn('f"SO{int(time.time())}"', src)


if __name__ == "__main__":
    unittest.main()


class ProductionWiringTests(unittest.TestCase):
    """**真链路**验证：真实 `okx_rest` 签名/请求体 + 真实 `cloud_protection` + 真实双腿。

    上面的用例把 `okx_rest` 换成桩，验证的是编排逻辑；这一组把 HTTP 层也换成
    V5 线级夹具（`tests/okx_algo_http_fixture.py`），于是"请求体是否真被 OKX 接受"
    这件事也被钉住 —— 尤其是：
      * `amend-algos` 的第二个位置参数是 **newSlTriggerPx**（不打算改止损时
        必须回传该腿**当前**止损价，传错等于把止损挪走）；
      * 终点状态必须仍是"两条腿、各带同一止损、之和等于持仓"。
    """

    INST = "ETH-USDT-SWAP"

    def _install(self):
        # `ai_factor_trader` 是 scripts/ 根层模块（测试进程默认没把 scripts/ 加进
        # sys.path）—— 与 `tests/llm/test_quant_system_calculus.py` 同一取法。
        import sys as _sys
        _scripts = str(Path(__file__).resolve().parents[2] / "scripts")
        if _scripts not in _sys.path:
            _sys.path.insert(0, _scripts)
        import ai_factor_trader
        from tests.okx_algo_http_fixture import install_http
        wire = install_http(self, ai_factor_trader)
        return ai_factor_trader, wire

    def test_protection_layer_really_splits_into_two_legs(self):
        trader, wire = self._install()
        # 交易所上现在是**一条全量 OCO 腿**（双腿改造前的形态）。
        wire.rows = [wire.row(side='long', size='4', inst=self.INST, sl='2400')]
        wire.rows[0]['tpTriggerPx'] = '2600'
        state: dict = {}
        ok, detail = trader.ensure_cloud_position_protection(
            self.INST, "long", 4, 2600.0, 2400.0,
            tp1_px=2500.0, scale_out_ratio=0.5, prec=0, px_prec=1, legs_state=state)
        self.assertTrue(ok, detail)
        placed = [body for _m, body in wire.calls('/api/v5/trade/order-algo')]
        # 只应有两笔下单：双腿已经把覆盖率填满，不该再补第三条腿。
        self.assertEqual(len(placed), 2, "双腿即已满足保护覆盖，不得多挂")
        new_legs = placed[:2]
        self.assertEqual([b['sz'] for b in new_legs], ['2', '2'], "两腿之和必须等于持仓 4 张")
        # 真实 okx_rest 用 `%g` 口径格式化触发价（`2500.0` → `"2500"`）。
        self.assertEqual([b['tpTriggerPx'] for b in new_legs], ['2500', '2600'])
        self.assertEqual([b['slTriggerPx'] for b in new_legs], ['2400', '2400'],
                         "两腿必须各带**同一个**止损（TP-only 腿会被覆盖率统计排除）")
        cancelled = wire.calls('/api/v5/trade/cancel-algos')
        self.assertTrue(cancelled, "旧的全量腿必须被撤掉")
        self.assertIn('algo_long', [i['algoId'] for i in cancelled[0][1]])
        self.assertEqual(state.get("leg_algo_ids"), {"tp1": "created-1", "tp2": "created-2"},
                         "角色→algoId 必须登记：持仓中调整止盈靠它认腿")

    def test_tp_amend_moves_only_the_named_leg_and_keeps_the_stop(self):
        trader, wire = self._install()
        wire.rows = [wire.row(side='long', size='4', inst=self.INST, sl='2400')]
        wire.rows[0]['tpTriggerPx'] = '2600'
        state: dict = {}
        trader.ensure_cloud_position_protection(
            self.INST, "long", 4, 2600.0, 2400.0,
            tp1_px=2500.0, scale_out_ratio=0.5, prec=0, px_prec=1, legs_state=state)
        from scripts.trader.tp_sync import sync_cloud_algo_tp
        legs = [r for r in trader.okx_rest.pending_algo_orders(self.INST)
                if str(r.get("tpTriggerPx")) == "2500"]
        self.assertTrue(legs, "找不到 TP1 腿")
        state["leg_algo_ids"] = {"tp1": legs[0]["algoId"], "tp2": "created-2"}
        tracker: dict = {"takeProfitPx": 2600.0, "scale_out_tp": 2500.0, "trailingStopPx": 2400.0}
        ok, detail, applied = sync_cloud_algo_tp(
            self.INST, "long", is_long=True, tp2_px=2620.0, sl_px=2400.0, phase=0,
            leg_algo_ids=state["leg_algo_ids"], tracker=tracker,
            okx_rest=trader.okx_rest, atr=20.0, cur_px=2450.0, px_prec=1)
        self.assertTrue(ok, detail)
        amends = wire.calls('/api/v5/trade/amend-algos')
        self.assertEqual(len(amends), 1, "只允许改被点名的那条腿")
        body = amends[0][1]
        self.assertEqual(str(body['newTpTriggerPx']), '2620')
        # 改的是**被点名的那条腿**：这次请求调的是 tp2，故必须落在 created-2 上，
        # 绝不能因为价格接近而落到 tp1 腿（认腿靠登记，不靠比价）。
        self.assertEqual(body['algoId'], 'created-2')
        # 关键不变量：止损原样回传该腿**当前**值（`amend-algos` 的第二个位置参数
        # 就是 newSlTriggerPx —— 传成别的价等于把止损挪到那里）。
        self.assertAlmostEqual(float(body['newSlTriggerPx']), 2400.0)
        self.assertEqual(tracker["last_tp_amend"]["applied"], {"tp2": 2620.0})

    def test_adverse_amend_never_reaches_the_wire(self):
        trader, wire = self._install()
        wire.rows = [wire.row(side='long', size='4', inst=self.INST, sl='2400')]
        wire.rows[0]['tpTriggerPx'] = '2600'
        from scripts.trader.tp_sync import sync_cloud_algo_tp
        with patch.dict(os.environ, {"ASTRA_TP_ALLOW_ADVERSE": "0"}, clear=False):
            ok, detail, _ = sync_cloud_algo_tp(
                self.INST, "long", is_long=True, tp2_px=2400.0, phase=0,
                leg_algo_ids={"tp1": "algo_long", "tp2": "algo_long"},
                okx_rest=trader.okx_rest, atr=20.0, cur_px=2500.0, px_prec=1)
        self.assertFalse(ok, detail)
        self.assertEqual(wire.calls('/api/v5/trade/amend-algos'), [],
                         "被拒的方向调整**不得**发出任何请求")


class SplitStabilityTests(unittest.TestCase):
    """腿一旦挂好，就**不许**因为持仓张数的微小漂移而每轮重挂。

    2026-09-29 实盘验证时踩到：BTC 双腿是 `1.4 + 1.5`（计划按当时的 2.9 张算），
    而下一轮持仓读数变成 2.85 ⇒ 逐位比对永远不相等 ⇒ 每 15 分钟"先挂后撤"重来一遍。
    判据改为"TP 集合一致 + 张数覆盖当前持仓"（TP 才是腿几何的本质）。
    """

    @staticmethod
    def _live(tp1, tp2, sz1, sz2, side="long"):
        close_side = "sell" if side == "long" else "buy"
        return [
            {"algoId": "L1", "sz": str(sz1), "side": close_side, "posSide": side, "state": "live",
             "tpTriggerPx": str(tp1), "slTriggerPx": "82632.8", "reduceOnly": "true"},
            {"algoId": "L2", "sz": str(sz2), "side": close_side, "posSide": side, "state": "live",
             "tpTriggerPx": str(tp2), "slTriggerPx": "82632.8", "reduceOnly": "true"},
        ]

    def test_a_shrunken_position_does_not_trigger_a_re_split(self):
        plan = plan_legs(2.85, 85051.0, 86872.7, 82632.8, ratio=0.5, min_sz=0.1, prec=1, px_prec=1)
        live = self._live(85051.0, 86872.7, 1.4, 1.5)
        self.assertTrue(legs_already_match(live, plan, "long", size=2.85, min_sz=0.1),
                        "张数只要求覆盖持仓：1.4+1.5 ≥ 2.85 ⇒ 必须判为已匹配（不重挂）")

    def test_a_grown_position_does_trigger_a_re_split(self):
        plan = plan_legs(3.6, 85051.0, 86872.7, 82632.8, ratio=0.5, min_sz=0.1, prec=1, px_prec=1)
        live = self._live(85051.0, 86872.7, 1.4, 1.5)
        self.assertFalse(legs_already_match(live, plan, "long", size=3.6, min_sz=0.1),
                         "持仓变大 ⇒ 现有腿盖不住 ⇒ 必须重挂")

    def test_a_tick_rounded_echo_still_counts_as_matched(self):
        """OKX 回读的触发价按 `tickSz` 回显，可能与下发值差 1 个 tick。

        实测（2026-09-29 线上）：ARB 下发 0.2138、回读 0.2137 —— 位相等判据会把
        "其实已经就位"的腿判成不匹配 ⇒ 每 15 分钟先挂后撤重来一遍。只差一个 tick
        必须算匹配；价差达到"真的改了止盈"的量级才算不匹配。
        """
        plan = plan_legs(859.1, 0.2138, 0.2215, 0.2035, ratio=0.5, min_sz=0.1, prec=1, px_prec=4)
        live = self._live(0.2137, 0.2214, 429.5, 429.6)
        self.assertTrue(legs_already_match(live, plan, "long", size=859.1, min_sz=0.1),
                        "一个 tick 的回显差不得触发重挂")

    def test_changed_tp_always_triggers_a_re_split(self):
        plan = plan_legs(2.85, 85500.0, 86872.7, 82632.8, ratio=0.5, min_sz=0.1, prec=1, px_prec=1)
        live = self._live(85051.0, 86872.7, 1.4, 1.5)
        self.assertFalse(legs_already_match(live, plan, "long", size=2.85, min_sz=0.1),
                         "TP 是腿几何的本质：TP 变了必须重挂")

    def test_legs_below_the_lot_floor_are_rejected(self):
        plan = plan_legs(2.85, 85051.0, 86872.7, 82632.8, ratio=0.5, min_sz=0.1, prec=1, px_prec=1)
        live = self._live(85051.0, 86872.7, 0.05, 2.85)
        self.assertFalse(legs_already_match(live, plan, "long", size=2.85, min_sz=0.1),
                         "单腿低于最小张数 ⇒ 不算就位")


class TpAmendPrecisionTests(unittest.TestCase):
    """真机探针抓到的两个缺陷（2026-09-29 夜）：价格精度混用 + 真源取"下发值"。

    现场证据：ARB 请求把 tp2 从 0.2214 上移到 `0.2214 + 2×步长 = 0.2236`，
    交易所回读却是 **0.22** —— 因为调用方把**张数**精度（ARB 无小数）当成了价格精度，
    取整到 2 位小数（差 1.6%）；同时 tracker 记下未取整的 0.2236，真源与交易所分叉。
    """

    def test_price_precision_is_honoured_not_size_precision(self):
        okx = _FakeOkx([
            {"algoId": "11", "sz": "1", "side": "sell", "posSide": "long", "state": "live",
             "tpTriggerPx": "0.2214", "slTriggerPx": "0.2035", "reduceOnly": "true"},
        ])
        ok, detail, applied = sync_cloud_algo_tp(
            "ARB-USDT-SWAP", "long", is_long=True, tp2_px=0.2236,
            leg_algo_ids={"tp2": "11"}, okx_rest=okx, atr=0.00428, cur_px=0.2087, px_prec=4)
        self.assertTrue(ok, detail)
        sent = okx.pending[0]["tpTriggerPx"]
        self.assertEqual(float(sent), 0.2236, f"必须按价格精度下发，实际下发 {sent}")

    def test_tracker_records_the_value_echoed_by_the_exchange(self):
        """OKX 按 tickSz 回显 ⇒ tracker 必须跟**回显值**（真源恒等于交易所）。"""

        class _Echoing(_FakeOkx):
            def amend_algo_sl(self, algo_id, new_sl, **kwargs):
                super().amend_algo_sl(algo_id, new_sl, **kwargs)
                for row in self.pending:            # 模拟交易所按 tick 回显
                    if str(row.get("algoId")) == str(algo_id):
                        row["tpTriggerPx"] = "0.2235"
                return [{"algoId": algo_id, "sCode": "0"}]

        okx = _Echoing([
            {"algoId": "11", "sz": "1", "side": "sell", "posSide": "long", "state": "live",
             "tpTriggerPx": "0.2214", "slTriggerPx": "0.2035", "reduceOnly": "true"},
        ])
        tracker = {"takeProfitPx": 0.2214}
        ok, detail, applied = sync_cloud_algo_tp(
            "ARB-USDT-SWAP", "long", is_long=True, tp2_px=0.2236, leg_algo_ids={"tp2": "11"},
            tracker=tracker, okx_rest=okx, atr=0.00428, cur_px=0.2087, px_prec=4)
        self.assertTrue(ok, detail)
        self.assertEqual(applied["tp2"], 0.2235, "applied 必须取回读值")
        self.assertEqual(tracker["takeProfitPx"], 0.2235,
                         "tracker 必须记交易所实际值，否则下一轮保护层会拿假价重建")

    def test_round_half_up_not_bankers(self):
        from scripts.trader.tp_sync import _round_px
        self.assertEqual(_round_px(0.22355, 4), 0.2236)   # 银行家舍入会得 0.2235
        self.assertEqual(_round_px(0.2236, 2), 0.22)
        self.assertEqual(_round_px(85051.449, 1), 85051.4)
