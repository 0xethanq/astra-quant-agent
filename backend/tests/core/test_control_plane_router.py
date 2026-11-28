"""Tests for direct control-plane API, quick toggles, risk preview/save, and async jobs."""
from __future__ import annotations

import os
import subprocess
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

import astra_backend.app as app_mod
from astra_backend import evolution_config, job_runner
from astra_backend.agent import tools_read
from tests.config_sandbox import isolate_config


class ControlPlaneRouterTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(isolate_config(self))

        self.env_file = self.root / ".env"
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        self.env_file.write_text("ASTRA_TRADING_PAUSED=0\nASTRA_ORDER_MODE=limit\n", encoding="utf-8")

        self.evo_file = self.root / "evolution_config.json"
        self.sess_file = self.root / "trading_session.json"
        self.archive_dir = self.root / "policy_archives"

        self.patchers = [
            patch("astra_backend.settings_store.ENV_FILE", self.env_file),
            patch("astra_backend.config.ROOT", self.root),
            patch("astra_backend.evolution_config.EVOLUTION_CONFIG_FILE", self.evo_file),
            patch("astra_backend.trading_session_store.TRADING_SESSION_FILE", self.sess_file),
            patch("astra_backend.policy_snapshot.ARCHIVE_DIR", self.archive_dir),
            patch("astra_backend.policy.archive.ARCHIVE_DIR", self.archive_dir),
            patch.dict(os.environ, {"ASTRA_TRADING_PAUSED": "0", "ASTRA_ORDER_MODE": "limit"}, clear=False),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

        self.client = TestClient(app_mod.app)
        self.superadmin = {"id": 1, "username": "root", "role": "superadmin", "enabled": 1}
        self.operator = {"id": 2, "username": "viewer", "role": "admin", "enabled": 1}
        self.council_state = {
            "enabled": False,
            "consensus_mode": "standard",
            "timeout_seconds": 240.0,
            "roles": {
                "trader_trend": {
                    "id": "trader_trend",
                    "name": "Trend Seat",
                    "enabled": True,
                    "weight": 0.4,
                    "model_id": "",
                    "reasoning_effort": "medium",
                    "temperature": 0.2,
                    "prompt": "follow trend",
                },
                "cio": {
                    "id": "cio",
                    "name": "CIO",
                    "enabled": True,
                    "weight": 0.6,
                    "model_id": "",
                    "reasoning_effort": "high",
                    "temperature": 0.2,
                    "prompt": "arbitrate final decision",
                    "is_arbitrator": True,
                },
            },
        }

    def _auth_headers(self, role: str = "superadmin") -> dict[str, str]:
        return {"X-Astra-Session": f"tok-{role}"}

    def _validate(self, session: str):
        if session == "tok-superadmin":
            return self.superadmin
        if session == "tok-admin":
            return self.operator
        return None

    def test_state_and_rbac_enforcement(self):
        with patch.object(app_mod.admin_auth, "validate_session", side_effect=self._validate), \
             patch("astra_backend.routers.control_plane.load_council_config", return_value=self.council_state), \
             patch("astra_backend.routers.control_plane.seat_model_health", return_value=[]):
            res_unauth = self.client.get("/api/v1/admin/control-plane/state")
            self.assertEqual(res_unauth.status_code, 401)

            res_admin = self.client.get("/api/v1/admin/control-plane/state", headers=self._auth_headers("admin"))
            self.assertEqual(res_admin.status_code, 200)
            body = res_admin.json()
            for k in ("trading_paused", "environment", "risk", "trading_session", "council", "prompt", "evolution", "jobs"):
                self.assertIn(k, body)
            self.assertIs(body["trading_paused"], False)

            # Standard admin must be rejected on superadmin write endpoints
            res_forbidden = self.client.post(
                "/api/v1/admin/control-plane/quick-toggle",
                json={"target": "trading_paused", "enabled": True},
                headers=self._auth_headers("admin"),
            )
            self.assertEqual(res_forbidden.status_code, 403)

    def test_quick_toggles_trading_paused_evolution_and_council(self):
        def _save_council(cfg, **_kw):
            self.council_state = cfg
            return cfg

        with patch.object(app_mod.admin_auth, "validate_session", side_effect=self._validate), \
             patch("astra_backend.routers.control_plane.audit_record"), \
             patch("astra_backend.routers.control_plane.load_council_config", side_effect=lambda: dict(self.council_state)), \
             patch("astra_backend.routers.control_plane.save_council_config", side_effect=_save_council), \
             patch("astra_backend.routers.control_plane._safe_auto_snapshot", return_value="snap_abc123"):
            hdrs = self._auth_headers("superadmin")

            # 1. Pause new entries toggle
            r1 = self.client.post(
                "/api/v1/admin/control-plane/quick-toggle",
                json={"target": "trading_paused", "enabled": True},
                headers=hdrs,
            )
            self.assertEqual(r1.status_code, 200)
            self.assertTrue(r1.json()["trading_paused"])
            self.assertEqual(os.environ.get("ASTRA_TRADING_PAUSED"), "1")
            summary = tools_read.build_state_summary()
            self.assertTrue(summary["trading_paused"])

            # 2. Evolution toggle persists to evolution_config.json
            r2 = self.client.post(
                "/api/v1/admin/control-plane/quick-toggle",
                json={"target": "evolution_enabled", "enabled": False},
                headers=hdrs,
            )
            self.assertEqual(r2.status_code, 200)
            self.assertFalse(evolution_config.load_evolution_config()["enabled"])

            # 3. Council master & role toggle preserve sibling fields
            r3 = self.client.post(
                "/api/v1/admin/control-plane/quick-toggle",
                json={"target": "council_enabled", "enabled": True},
                headers=hdrs,
            )
            self.assertEqual(r3.status_code, 200)
            self.assertTrue(self.council_state["enabled"])

            r4 = self.client.post(
                "/api/v1/admin/control-plane/quick-toggle",
                json={"target": "council_role_enabled", "item_id": "trader_trend", "enabled": False},
                headers=hdrs,
            )
            self.assertEqual(r4.status_code, 200)
            self.assertFalse(self.council_state["roles"]["trader_trend"]["enabled"])
            self.assertEqual(self.council_state["roles"]["trader_trend"]["prompt"], "follow trend")

            # 4. Trading session toggle
            r5 = self.client.post(
                "/api/v1/admin/control-plane/quick-toggle",
                json={"target": "trading_session_enabled", "enabled": True},
                headers=hdrs,
            )
            self.assertEqual(r5.status_code, 200)
            self.assertTrue(r5.json()["trading_session"]["enabled"])

            # 5. Unknown target -> 400
            r_bad = self.client.post(
                "/api/v1/admin/control-plane/quick-toggle",
                json={"target": "not_a_real_toggle", "enabled": True},
                headers=hdrs,
            )
            self.assertEqual(r_bad.status_code, 400)

    def test_risk_preview_detects_deadlock_and_save_archives_snapshot(self):
        with patch.object(app_mod.admin_auth, "validate_session", side_effect=self._validate), \
             patch("astra_backend.routers.control_plane.audit_record"), \
             patch("astra_backend.routers.control_plane.sync_pool_leverage_caps"), \
             patch("astra_backend.routers.control_plane._safe_auto_snapshot", return_value="pkg_hash_99") as snap_mock:
            # Preview deadlock: SL ATR 2.5, TP Cap ATR 3.0 -> max R:R 1.2 < MIN_RISK_REWARD 2.5
            r_prev = self.client.post(
                "/api/v1/admin/control-plane/risk/preview",
                json={
                    "values": {
                        "ASTRA_STOP_LOSS_ATR_MULT": 2.5,
                        "ASTRA_MAX_TAKE_PROFIT_ATR": 3.0,
                        "ASTRA_MIN_RISK_REWARD": 2.5,
                    }
                },
                headers=self._auth_headers("admin"),
            )
            self.assertEqual(r_prev.status_code, 200)
            pdata = r_prev.json()
            self.assertTrue(pdata["valid"])
            self.assertEqual(pdata["risk_audit"]["status"], "critical")
            self.assertIn("SL_TP_RR_DEADLOCK", [i["code"] for i in pdata["risk_audit"]["issues"]])

            # High-risk save without confirmation -> 400
            r_reject = self.client.post(
                "/api/v1/admin/control-plane/risk/save",
                json={"values": {"ASTRA_MAX_LEVERAGE": 12.0}},
                headers=self._auth_headers("superadmin"),
            )
            self.assertEqual(r_reject.status_code, 400)

            # High-risk save WITH exact HIGH RISK confirmation -> 200 + auto snapshot
            r_ok = self.client.post(
                "/api/v1/admin/control-plane/risk/save",
                json={"values": {"ASTRA_MAX_LEVERAGE": 12.0}, "confirmation": "HIGH RISK"},
                headers=self._auth_headers("superadmin"),
            )
            self.assertEqual(r_ok.status_code, 200)
            self.assertEqual(r_ok.json()["snapshot_hash"], "pkg_hash_99")
            snap_mock.assert_called()

    def test_council_role_partial_patch_preserves_other_fields(self):
        def _save_council(cfg, **_kw):
            self.council_state = cfg
            return cfg

        with patch.object(app_mod.admin_auth, "validate_session", side_effect=self._validate), \
             patch("astra_backend.routers.control_plane.audit_record"), \
             patch("astra_backend.routers.control_plane.load_council_config", side_effect=lambda: dict(self.council_state)), \
             patch("astra_backend.routers.control_plane.save_council_config", side_effect=_save_council), \
             patch("astra_backend.routers.control_plane._safe_auto_snapshot", return_value="snap_role_1"):
            res = self.client.patch(
                "/api/v1/admin/control-plane/council/role/trader_trend",
                json={"weight": 0.55},
                headers=self._auth_headers("superadmin"),
            )
            self.assertEqual(res.status_code, 200)
            self.assertAlmostEqual(self.council_state["roles"]["trader_trend"]["weight"], 0.55)
            self.assertEqual(self.council_state["roles"]["trader_trend"]["prompt"], "follow trend")

    def test_async_job_runner_prevents_concurrent_duplicate_runs(self):
        fake_script = self.root / "fake_script.py"
        fake_script.write_text("print('ok')\n", encoding="utf-8")

        def _slow_runner(cmd, *, timeout, env):
            time.sleep(0.15)
            return subprocess.CompletedProcess(cmd, 0, stdout="job finished\n", stderr="")

        with job_runner._LOCK:
            job_runner._RUNS.clear()

        with patch("astra_backend.job_runner.SCRIPTS_DIR", self.root), \
             patch.dict(job_runner.ALLOWED_JOBS, {
                 "factor_library": {"script": "fake_script.py", "args": [], "timeout": 30, "label": "Factor Test"}
             }, clear=False), \
             patch("astra_backend.job_runner.audit_record"):
            run = job_runner.trigger_job_async("factor_library", actor="root", runner=_slow_runner)
            self.assertEqual(run["status"], "running")

            with self.assertRaises(job_runner.JobAlreadyRunningError):
                job_runner.trigger_job_async("factor_library", actor="root", runner=_slow_runner)

            # Wait briefly for completion
            deadline = time.monotonic() + 2.0
            final = None
            while time.monotonic() < deadline:
                cur = job_runner.get_job_run(run["run_id"])
                if cur and cur["status"] != "running":
                    final = cur
                    break
                time.sleep(0.03)
            self.assertIsNotNone(final)
            self.assertEqual(final["status"], "success")
            self.assertIn("job finished", final["output_tail"])


if __name__ == "__main__":
    unittest.main()
