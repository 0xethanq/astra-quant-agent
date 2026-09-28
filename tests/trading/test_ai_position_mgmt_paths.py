"""AI 持仓管理里那几条「不成功就不往下走」的分支（第二百二十四刀）。

`execute_ai_position_management` 只执行**新鲜、高置信、且确实收紧风险**的指令；
本刀钉住它的失败侧语义：

- 指令文件**读不动/坏 JSON** ⇒ 留痕并返回（绝不拿半份数据去动仓位）；
- 云端止损更新**失败**（原生改单被拒 / 抛异常）⇒ **`continue`**：既不谎报成功，
  也**不把本地跟踪器的 `trailingStopPx` 改成没生效的价位**（否则下一轮本地与云端不一致，
  本地以为已经保本）；
- 通知（QQ）失败 ⇒ **只吞掉**，不影响已经生效的止损状态。
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.trader.position_mgmt import execute_ai_position_management

INST = "BTC-USDT-SWAP"


class _MockOkx:
    def __init__(self, *, algo_orders=None, query_raises=False, amend_raises=False):
        self.algo_orders = algo_orders if algo_orders is not None else [
            {"state": "live", "posSide": "long", "slTriggerPx": "80.0", "algoId": "algo1"}
        ]
        self.query_raises = query_raises
        self.amend_raises = amend_raises

    def pending_algo_orders(self, inst_id):
        if self.query_raises:
            raise RuntimeError("查询挂单异常")
        return self.algo_orders

    def amend_algo_sl(self, algo_id, new_sl, inst_id, new_sl_ord_px="-1"):
        if self.amend_raises:
            raise RuntimeError("改单失败")
        return {"code": "0"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="astra-aim-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ai_position_management.json"
        self.actions = []
        self.trackers = {f"{INST}_long": {"trailingStopPx": 80.0}}

    def _write(self, *, action="UPDATE_SL", sl=95.0, confidence=90, ts=None):
        self.path.write_text(json.dumps({
            "timestamp": int(time.time()) if ts is None else ts,
            "instructions": [{"instId": INST, "action": action, "confidence": confidence,
                              "reason": "AI 收紧", "suggested_sl_price": sl}]}),
            encoding="utf-8")

    def _run(self, *, okx=None, venue="okx", pos_side="long"):
        okx = okx or _MockOkx()
        return execute_ai_position_management(
            {INST: {"posSide": pos_side, "venue": venue, "markPx": 100.0, "pos": 1.0,
                    "avgPx": 90.0}},
            self.trackers, "2026-09-21 12:00:00", self.actions,
            ai_position_management_file=str(self.path),
            ai_tightens_stop=lambda instr, pos: True,
            close_position_confirmed=lambda *a, **k: (True, "ok"),
            okx_rest=okx,
            venue_registry=None,
            current_environment=lambda: type("E", (), {"mode": "demo"})())


class AiInstructionFileTest(Base):
    def test_unreadable_instruction_file_is_disclosed_and_skipped(self):
        self.path.write_text("{ 坏 JSON", encoding="utf-8")
        self._run()
        self.assertTrue(any("AI持仓指令读取失败" in a for a in self.actions), self.actions)
        self.assertEqual(self.trackers[f"{INST}_long"]["trailingStopPx"], 80.0,
                         "读不动指令 ⇒ 一个仓位都不许动")

    def test_expired_instruction_is_skipped(self):
        self._write(ts=int(time.time()) - 10000)
        self._run()
        self.assertTrue(any("已过期" in a for a in self.actions), self.actions)
        self.assertEqual(self.trackers[f"{INST}_long"]["trailingStopPx"], 80.0)


class CloudStopUpdateFailureTest(Base):
    def test_rejected_amend_keeps_local_tracker_untouched(self):
        """原生改单被拒 ⇒ 不谎报成功，**本地跟踪器也不许改成没生效的价位**。"""
        self._write()
        self._run(okx=_MockOkx(amend_raises=True))
        self.assertTrue(any("云端止损更新失败" in a for a in self.actions),
                        self.actions)
        self.assertEqual(self.trackers[f"{INST}_long"]["trailingStopPx"], 80.0,
                         "改单没生效 ⇒ 本地 trailingStopPx 必须保持原值（否则本地以为已保本）")

    def test_adapter_exception_is_disclosed_and_skipped(self):
        self._write()
        self._run(okx=_MockOkx(query_raises=True))
        self.assertTrue(any("云端止损收紧失败" in a for a in self.actions), self.actions)
        self.assertEqual(self.trackers[f"{INST}_long"]["trailingStopPx"], 80.0)

    def test_missing_position_is_disclosed_when_action_is_not_hold(self):
        """外所持仓不在本路径字典里：AI 的非 HOLD 指令要**留痕**（不是静默跳过）。"""
        self._write()
        execute_ai_position_management(
            {}, self.trackers, "t", self.actions,
            ai_position_management_file=str(self.path),
            ai_tightens_stop=lambda *a: True, close_position_confirmed=lambda *a, **k: (True, ""),
            okx_rest=_MockOkx(), venue_registry=None,
            current_environment=lambda: type("E", (), {"mode": "demo"})())
        self.assertTrue(any("不在本路径持仓字典" in a for a in self.actions), self.actions)


class NotificationFailureTest(Base):
    def test_notify_failure_is_swallowed_after_a_successful_amend(self):
        """QQ 通知失败只吞掉：止损**已经生效**，本地状态必须照常更新。"""
        self._write()
        import sys
        import types
        fake = types.ModuleType("qq_notifier")

        def boom(*a, **k):
            raise RuntimeError("QQ 挂了")
        fake.notify_sl_updated = boom
        with patch.dict(sys.modules, {"qq_notifier": fake}):
            self._run()
        self.assertEqual(self.trackers[f"{INST}_long"]["trailingStopPx"], 95.0,
                         "通知失败不该影响已生效的止损状态")
        self.assertTrue(any("云端止损收紧至 95.0" in a for a in self.actions), self.actions)


if __name__ == "__main__":
    unittest.main()
