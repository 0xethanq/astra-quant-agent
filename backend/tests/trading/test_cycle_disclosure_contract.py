"""周期披露与防抖状态的**契约**（第二百一十五刀）。

两条本会话反复出现的语义在这里都有明确落点：

1. **读不到 ≠ 没有**：`_load_watchdog_state` 刻意区分两种"空" —— 文件不存在 ⇒ `{}`
   （首次运行，合法空态）；**不可读/损坏 ⇒ `None`**（调用方拿到 `None` 必须不写单）。
   把这两者混为一谈，正是"读不出来当成没有缺口"那一类缺陷。
2. **报告器不得成为新的单点故障**：`cycle_disclosure_payload` 绝不抛（非 dict 的巡检报告、
   `None` 集合、含 `None` 的列表一律宽容）；`write_cycle_disclosure_snapshot` 失败只返回 False。

另外 `cycle_disclosure_summary` 是**唯一**把载荷渲染成一行的地方（第 51 刀定的单一事实源），
它必须每轮都出现，且把"未开闸"这种"没在跑的保护"也写出来（不是错误，但必须被看见）。
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.trader.cycle_stages import (cycle_disclosure_payload,
                                         cycle_disclosure_summary,
                                         write_cycle_disclosure_snapshot)


class DisclosurePayloadTest(unittest.TestCase):
    def test_broken_venues_are_deduped_and_sorted(self):
        p = cycle_disclosure_payload(broken_venues=["gate", "binance", "gate", "", None])
        self.assertEqual(p["broken_venues"], ["binance", "gate"])
        self.assertEqual(p["broken_venue_count"], 2)
        self.assertFalse(p["clean"], "有坏所就不算干净")

    def test_clean_cycle(self):
        p = cycle_disclosure_payload()
        self.assertTrue(p["clean"])
        self.assertEqual(p["broken_venue_count"], 0)
        self.assertEqual(cycle_disclosure_summary(p), "[周期披露] 本轮无跳过/未核验项")

    def test_entries_blocked_is_disclosed_and_not_clean(self):
        p = cycle_disclosure_payload(entries_blocked=True)
        self.assertFalse(p["clean"], "禁本轮新开仓不算干净周期")
        self.assertIn("禁本轮新开仓", cycle_disclosure_summary(p))

    def test_shape_violations_are_counted_with_a_head(self):
        p = cycle_disclosure_payload(shape_violations=["a", "b", "c", "d", "e"])
        self.assertEqual(p["shape_violation_count"], 5)
        self.assertEqual(p["shape_violation_head"], ["a", "b", "c"], "只截前三作为摘要")
        line = cycle_disclosure_summary(p)
        self.assertIn("数据形状违规=5", line)
        self.assertIn("共5条", line, "超过三条要写总数，否则读者以为只有三条")

    def test_summary_tolerates_non_dict_payload(self):
        self.assertEqual(cycle_disclosure_summary(None), "[周期披露] 本轮无跳过/未核验项")
        self.assertEqual(cycle_disclosure_summary("字符串"), "[周期披露] 本轮无跳过/未核验项")


class SessionRestrictionDisclosureTest(unittest.TestCase):
    """交易时段降级必须在披露里可见（2026-09-30）。

    降级不是错误，但它是"这一轮什么都没做"的原因 —— 而披露行是每轮都打印、
    且可检索的唯一常驻线索。把原因藏起来，评审就会以为"系统坏了"。
    """

    FULL = {"mode": "full", "restricted": False, "reason": "运行中"}

    def test_full_session_keeps_the_payload_byte_identical(self):
        base = cycle_disclosure_payload()
        with_full = cycle_disclosure_payload(session=self.FULL)
        self.assertEqual(base, with_full, "窗口内/未启用时载荷必须**逐键不变**")
        self.assertTrue(with_full["clean"])
        for key in ("session_mode", "session_reason", "session_restricted"):
            self.assertNotIn(key, with_full, "仅 full 时不得引入任何 session_* 键")

    def test_manage_only_is_disclosed_and_not_clean(self):
        payload = cycle_disclosure_payload(session={"mode": "manage_only", "restricted": True,
                                                    "reason": "休市中（窗口外）：只做机械风控"})
        self.assertTrue(payload["session_restricted"])
        self.assertEqual(payload["session_mode"], "manage_only")
        self.assertFalse(payload["clean"], "降级跑的周期不算干净周期")
        line = cycle_disclosure_summary(payload)
        self.assertIn("时段限制=只做机械风控", line)

    def test_off_is_disclosed_separately(self):
        payload = cycle_disclosure_payload(session={"mode": "off", "restricted": True,
                                                    "reason": "休市中（窗口外）：完全停跑巡检"})
        line = cycle_disclosure_summary(payload)
        self.assertIn("时段限制=完全停跑", line)

    def test_garbage_session_is_tolerated(self):
        for raw in (None, "x", 5, [], {"mode": None}, {}):
            with self.subTest(raw=raw):
                payload = cycle_disclosure_payload(session=raw)
                self.assertIn("clean", payload)
                self.assertNotIn("session_restricted", payload)

    def test_truthy_restricted_flag_is_reported_rather_than_hidden(self):
        """非布尔但真值的 `restricted`（上游形状漂移）⇒ **报出来**。

        方向选择：多报一次"降级"只是多一行日志，漏报一次就会让"这轮什么都没做"
        变成无解之谜 —— 所以这里刻意不把 `restricted` 强制成 `is True`。
        """
        payload = cycle_disclosure_payload(session={"restricted": "yes"})
        self.assertTrue(payload["session_restricted"])
        self.assertFalse(payload["clean"])


class SnapshotWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="astra-wd-")
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "disclosure.json"

    def test_snapshot_write_returns_false_on_failure(self):
        def boom(path, body):
            raise OSError("atomic boom")
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = write_cycle_disclosure_snapshot(path=str(self.path), payload={"clean": True},
                                                _atomic_write_json=boom)
        self.assertFalse(ok, "可观测性失败绝不拖垮周期")
        self.assertIn("快照写入失败", buf.getvalue())

    def test_snapshot_write_adds_freshness_stamp(self):
        captured = {}

        def fake(path, body):
            captured.update(body)

        self.assertTrue(write_cycle_disclosure_snapshot(path=str(self.path),
                                                       payload={"clean": True},
                                                       _atomic_write_json=fake))
        self.assertIn("written_at_ms", captured)
        self.assertGreater(captured["written_at_ms"], 1_600_000_000_000,
                           "毫秒级时间戳：让「很久没更新」与「本轮很干净」在指标上可区分")


if __name__ == "__main__":
    unittest.main()
