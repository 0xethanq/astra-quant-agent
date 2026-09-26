"""审计 C4 封闭单测：equity_history 环境隔离 + 未知状态不得当已平。"""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import astra_backend.routers.dashboard as dash


class EquityHistoryIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()

    def _run(self, rows, mode="demo"):
        (self.root / "data" / "trading_ledger.json").write_text(
            json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        (self.root / "data" / "account_initial_state.json").write_text(
            json.dumps({"initial_capital": 1000.0}), encoding="utf-8")
        env = SimpleNamespace(mode=mode, configured=True, simulated=(mode == "demo"))
        import scripts.okx_runtime as rt
        with patch.object(rt, "current_environment", lambda: env), \
             patch.object(dash, "ROOT", self.root):
            return dash.equity_history(days=30)

    def test_other_environment_rows_excluded(self):
        out = self._run([
            {"id": "a", "status": "closed", "environment": "demo", "close_time": "2026-09-13 10:00:00", "net_pnl": 5.0},
            {"id": "b", "status": "closed", "environment": "live", "close_time": "2026-09-13 11:00:00", "net_pnl": -900.0},
        ], mode="demo")
        self.assertEqual(out["environment"], "demo")
        self.assertEqual(out["excluded_rows"]["other_environment"], 1)
        total = sum(d["equity"] for d in out["days"])
        self.assertGreater(total, 0)  # live 的 -900 不得混入 demo 曲线

    def test_unknown_status_not_counted_as_closed(self):
        out = self._run([
            {"id": "a", "status": "closed", "environment": "demo", "close_time": "2026-09-13 10:00:00", "net_pnl": 5.0},
            {"id": "b", "status": "持仓中", "environment": "demo", "close_time": "2026-09-13 12:00:00", "net_pnl": -700.0},
            {"id": "c", "environment": "demo", "close_time": "2026-09-13 12:30:00", "net_pnl": -300.0},
        ], mode="demo")
        day_vals = {d["date"]: d["equity"] for d in out["days"]}
        self.assertEqual(day_vals["2026-09-13"], 1005.0)

    def test_unlabeled_legacy_rows_kept_and_counted(self):
        out = self._run([
            {"id": "a", "status": "closed", "close_time": "2026-09-13 10:00:00", "net_pnl": 7.0},
        ], mode="demo")
        self.assertEqual(out["excluded_rows"]["unlabeled_environment"], 1)
        day_vals = {d["date"]: d["equity"] for d in out["days"]}
        self.assertEqual(day_vals["2026-09-13"], 1007.0)


if __name__ == "__main__":
    unittest.main()
