"""审计监控面封闭单测：ai_health 旁车跨轮计数（失败累加/成功清零/total 不减）。"""
from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

import scripts.ai_brain_trader as abt


class AiHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(abt, "DATA_DIR", self.tmp.name)
        p.start()
        self.addCleanup(p.stop)

    def _path(self):
        return Path(self.tmp.name) / "ai_health.json"

    def test_missing_file_reads_empty(self):
        self.assertEqual(abt.read_cycle_health(), {})

    def test_failures_accumulate_and_success_resets(self):
        abt._record_cycle_health("failed", "402 INSUFFICIENT_BALANCE")
        h = abt.read_cycle_health()
        self.assertEqual(h["consecutive_failures"], 1)
        self.assertEqual(h["total_failures"], 1)
        self.assertEqual(h["last_error"], "402 INSUFFICIENT_BALANCE")

        abt._record_cycle_health("failed", "timeout")
        h = abt.read_cycle_health()
        self.assertEqual(h["consecutive_failures"], 2)
        self.assertEqual(h["total_failures"], 2)
        self.assertIsNone(h.get("last_ok_at"))

        abt._record_cycle_health("ok")
        h = abt.read_cycle_health()
        self.assertEqual(h["consecutive_failures"], 0)
        self.assertEqual(h["last_status"], "ok")
        self.assertEqual(h["total_failures"], 2)   # 累计不清零
        self.assertIsNotNone(h["last_ok_at"])
        self.assertTrue(self._path().exists())

    def test_corrupt_file_survives(self):
        self._path().write_text("{broken", encoding="utf-8")
        self.assertEqual(abt.read_cycle_health(), {})
        abt._record_cycle_health("failed", "after corrupt")
        self.assertEqual(abt.read_cycle_health()["consecutive_failures"], 1)


if __name__ == "__main__":
    unittest.main()
