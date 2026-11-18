"""OKX 单所台账同步旁车：写入形状 + 与开仓熔断解耦（2026-11-17）。

## 契约变更

系统已收口为 OKX 单所。原“跨所同步完整性 → 禁开仓”闸门已无对象，用户拍板：

- `ledger_sync_status.json` 仍写入，并继续供 `data_health` 显示 PARTIAL；
- 但旁车的 failed / 过旧 / 损坏**不再**让 `is_circuit_breaker_active` 返回 True。

本文件钉住“写入形状仍在”与“再也不会因旁车误熔断”两件事。
律①：零网络零真实数据目录（DATA_DIR 全部 patch 到 tmp）。
"""
from __future__ import annotations
import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

import scripts.sync_full_ledger as sfl
import astra_backend.execution.circuit_breaker as cb


class SyncStatusSidecarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._p_sfl = patch.object(sfl, "DATA_DIR", self.tmp.name)
        self._p_sfl.start()
        self.addCleanup(self._p_sfl.stop)
        sfl._FETCH_STATUS.clear()
        self.addCleanup(sfl._FETCH_STATUS.clear)

    def test_write_and_shape_is_okx_only(self):
        sfl._mark("okx", "ok", truncated_at=100)

        class _Env:
            simulated = True

        sfl._write_sync_status(_Env())
        path = os.path.join(self.tmp.name, "ledger_sync_status.json")
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as fh:
            payload = json.loads(fh.read())
        self.assertEqual(payload["environment"], "demo")
        self.assertEqual(set(payload["venues"]), {"okx"})
        self.assertEqual(payload["venues"]["okx"]["status"], "ok")
        self.assertEqual(payload["venues"]["okx"]["truncated_at"], 100)
        # 时间戳必须带时区（读侧按 tz-aware 计算新鲜度）
        datetime.datetime.fromisoformat(payload["generated_at"])

    def test_failed_okx_is_still_recorded_for_data_health(self):
        sfl._mark("okx", "failed", reason="timeout")

        class _Env:
            simulated = False

        sfl._write_sync_status(_Env())
        with open(os.path.join(self.tmp.name, "ledger_sync_status.json"),
                  encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["environment"], "live")
        self.assertEqual(payload["venues"]["okx"]["status"], "failed")
        self.assertEqual(payload["venues"]["okx"]["reason"], "timeout")


class BreakerNoLongerGatesOnSidecarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger = self.root / "trading_ledger.json"
        self.ledger.write_text("[]", encoding="utf-8")
        for p in (
            patch.object(cb, "DATA_DIR", self.root),
            patch.object(cb, "LEDGER_JSON_FILE", self.ledger),
            patch.object(cb, "CIRCUIT_BREAKER_FILE", self.root / "circuit_breaker.json"),
            patch.object(cb, "check_black_swan_sentinel", lambda **kw: (False, "")),
        ):
            p.start()
            self.addCleanup(p.stop)

    def _write_sidecar(self, venues, minutes_ago=0.0):
        gen = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
               - datetime.timedelta(minutes=minutes_ago))
        (self.root / "ledger_sync_status.json").write_text(
            json.dumps({"generated_at": gen.isoformat(), "environment": "demo",
                        "venues": venues}), encoding="utf-8")

    def test_missing_sidecar_does_not_trip(self):
        active, reason = cb.is_circuit_breaker_active(usdt_available=1000.0)
        self.assertFalse(active, reason)

    def test_failed_okx_venue_does_not_trip(self):
        """核心回归：失败所就是 OKX 自己时，也不再触发“跨所同步不完整”熔断。"""
        self._write_sidecar({"okx": {"status": "failed", "reason": "TLS EOF"}})
        active, reason = cb.is_circuit_breaker_active(usdt_available=1000.0)
        self.assertFalse(active, f"旁车失败不应再熔断：{reason!r}")
        self.assertEqual(reason, "")

    def test_stale_sidecar_does_not_trip(self):
        self._write_sidecar({"okx": {"status": "ok"}}, minutes_ago=60)
        active, reason = cb.is_circuit_breaker_active(usdt_available=1000.0)
        self.assertFalse(active, f"旁车过旧不应再熔断：{reason!r}")

    def test_corrupt_sidecar_does_not_trip(self):
        (self.root / "ledger_sync_status.json").write_text("{ 半截", encoding="utf-8")
        active, reason = cb.is_circuit_breaker_active(usdt_available=1000.0)
        self.assertFalse(active, f"旁车损坏不应再熔断：{reason!r}")

    def test_daily_loss_limit_still_trips(self):
        """移除旁车闸门后，当日亏损限额这条独立风险闸门必须仍然有效。"""
        today = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d")
        self.ledger.write_text(json.dumps([
            {"status": "closed", "pnl": -500.0, "environment": "demo",
             "close_time": f"{today} 10:00:00"},
        ]), encoding="utf-8")
        with patch.object(cb, "effective_daily_loss_limit", lambda _u: 100.0), \
             patch("scripts.okx_runtime.current_environment",
                   lambda: type("E", (), {"mode": "demo"})()):
            active, reason = cb.is_circuit_breaker_active(usdt_available=1000.0)
        self.assertTrue(active)
        self.assertIn("今日累计回撤", reason)

    def test_sidecar_helpers_are_gone(self):
        """防止旧闸门以“兼容壳”的名义悄悄回潮。"""
        self.assertFalse(hasattr(cb, "_ledger_sync_sidecar_state"))
        self.assertFalse(hasattr(cb, "_ledger_sync_failed_venues"))
        self.assertFalse(hasattr(cb, "_trigger_ledger_sync_heal"))

    def test_trader_twin_does_not_read_the_sidecar(self):
        twin = (Path(__file__).resolve().parents[2] / "scripts" / "trader"
                / "circuit_guard.py").read_text(encoding="utf-8")
        self.assertNotIn("_ledger_sync_sidecar_state", twin)
        self.assertNotIn("_ledger_sync_failed_venues", twin)
        self.assertNotIn("台账跨所同步不完整", twin)
        self.assertIn("ledger_daily_closed_pnl", twin)
