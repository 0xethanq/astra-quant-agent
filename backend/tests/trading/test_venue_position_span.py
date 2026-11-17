"""「持仓构成」口径回归（OKX 专用版）。

巡检通知与 AI 提示词共用纯函数 `venue_position_span`。
OKX 专用化后，系统只剩 OKX 单一场所，全量口径只报 OKX。
两处调用点（`cycle_stages.py` 的巡检通知与 `pos_desc`）都必须共用它。
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.trader import cycle_stages  # noqa: E402
from scripts.trader.cycle_snapshot import venue_position_span  # noqa: E402


class VenuePositionSpanTest(unittest.TestCase):
    def test_okx_position_span_shape(self):
        span = venue_position_span(
            okx_count=2, okx_long=1, okx_short=1, max_positions=9)
        self.assertEqual(span, "持仓 2/9 (多1/空1)｜okx 2")

    def test_zero_positions_shape(self):
        span = venue_position_span(
            okx_count=0, okx_long=0, okx_short=0, max_positions=5)
        self.assertEqual(span, "持仓 0/5 (多0/空0)｜okx 0")


class SpanIsActuallyWiredTest(unittest.TestCase):
    """只抽函数不接线 = 通知照旧写死 ⇒ 接线点必须单独钉住。"""

    def _persist(self, td, **over):
        kw = dict(
            venue_position_span=venue_position_span,
            active_pos_count=2, all_factors=[], cb_active=False, cb_reason="",
            executed_actions=[], long_count=1, short_count=1,
            timestamp_full="2026-09-26 18:30:00", DATA_DIR=td,
            LEDGER_AUTOSYNC_ENABLED=False, LOG_FILE=os.path.join(td, "t.log"),
            MAX_CONCURRENT_POSITIONS=9, WORKSPACE_DIR=td, __version__="test",
            _atomic_write_json=lambda path, payload: None,
            _run_captured=lambda *a, **k: None,
            build_state_payload=lambda **k: {"ok": True},
            evaluate_asset_signal=lambda *a, **k: None, os=os)
        kw.update(over)
        cycle_stages.persist_state_and_sync_ledger(**kw)

    def test_notification_line_carries_the_venue_composition(self):
        with tempfile.TemporaryDirectory() as td:
            self._persist(td)
            line = Path(td, "t.log").read_text(encoding="utf-8")
        self.assertIn("巡检完成", line)
        self.assertIn("okx 2", line)

    def test_prompt_position_description_carries_the_venue_composition(self):
        """喂给主脑的 `pos_desc` 必须同源。"""
        seen = {}
        cycle_stages.scan_risk_gates_and_ai_brain(
            venue_position_span=venue_position_span,
            active_pos_count=2, all_factors=[], executed_actions=[], long_count=1,
            short_count=1, timestamp_full="2026-09-26 18:30:00", trackers={},
            usdt_available=1000.0,
            MAX_CONCURRENT_POSITIONS=9,
            _collect_okx_position_payloads=lambda *a, **k: [],
            effective_single_asset_margin=lambda u: 123.0,
            execute_ai_position_management=lambda *a, **k: None,
            execute_batch_ai_brain_cycle=lambda pos_desc, *a, **k: seen.update(desc=pos_desc) or {},
            is_circuit_breaker_active=lambda u: (False, ""),
            pool_is_trustworthy=lambda: True, pool_state=lambda: {},
            query_positions=lambda: (True, [], ""), read_cycle_health=lambda: {},
            real_pos_dict={},
            save_trackers=lambda t: None)
        self.assertIn("desc", seen, "主脑批次没被调用，用例失去意义")
        self.assertIn("okx 2", seen["desc"])

    def test_facade_passes_the_pure_helper_not_a_local_copy(self):
        """门面必须把**同一个**纯函数传进去（不许在段内另写一份口径）。"""
        tree = ast.parse((ROOT / "scripts" / "ai_factor_trader.py").read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id in ("persist_state_and_sync_ledger",
                                   "scan_risk_gates_and_ai_brain")]
        self.assertEqual(len(calls), 2, "两个接线点应各恰一处")
        for call in calls:
            passed = {k.arg: ast.unparse(k.value) for k in call.keywords}
            self.assertEqual(passed.get("venue_position_span"), "venue_position_span",
                             f"{call.func.id} 未按同名传入纯函数")


if __name__ == "__main__":
    unittest.main()
