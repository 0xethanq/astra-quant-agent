"""Unit tests for Strategy Plaza (策略广场) endpoints and security gates."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from astra_backend.app import app
from astra_backend.plaza_share import (
    DEFAULT_PLAZA_SETTINGS,
    assemble_plaza_public_profile,
    is_live_trading_node,
    load_plaza_settings,
    sanitize_public_payload,
    save_plaza_settings,
)


class StrategyPlazaApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_default_settings_structure(self):
        settings = load_plaza_settings()
        self.assertIn("enabled", settings)
        self.assertIn("nickname", settings)
        self.assertIn("show_performance", settings)
        self.assertIn("show_balance", settings)
        self.assertIn("show_model", settings)
        self.assertIn("show_strategy_params", settings)

    def test_public_profile_disabled_by_default(self):
        with mock.patch("astra_backend.plaza_share.load_plaza_settings", return_value={"enabled": False}):
            res = self.client.get("/api/v1/public/plaza/profile")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "disabled")
            self.assertIn("未开启", data["message"])

    def test_public_profile_live_only_guard_rejects_demo_mode(self):
        with mock.patch("astra_backend.plaza_share.load_plaza_settings", return_value={"enabled": True}):
            with mock.patch("astra_backend.plaza_share.is_live_trading_node", return_value=False):
                res = self.client.get("/api/v1/public/plaza/profile")
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["status"], "rejected")
                self.assertEqual(data["code"], "LIVE_ONLY")
                self.assertFalse(data["is_live"])
                self.assertIn("仅接收真实实盘", data["message"])

    def test_public_profile_live_success_structure(self):
        fake_settings = {
            "enabled": True,
            "nickname": "0xTestTrader",
            "show_performance": True,
            "show_balance": False,
            "show_model": True,
            "show_strategy_params": True,
        }
        with mock.patch("astra_backend.plaza_share.load_plaza_settings", return_value=fake_settings):
            with mock.patch("astra_backend.plaza_share.is_live_trading_node", return_value=True):
                res = self.client.get("/api/v1/public/plaza/profile")
                self.assertEqual(res.status_code, 200)
                data = res.json()
                self.assertEqual(data["status"], "ok")
                self.assertEqual(data["node_info"]["nickname"], "0xTestTrader")
                self.assertTrue(data["node_info"]["is_live"])
                self.assertEqual(data["node_info"]["environment"], "live")

                # Verify performance visibility & balance masking
                self.assertTrue(data["performance"]["visible"])
                self.assertIn("win_rate_pct", data["performance"])
                self.assertIn("total_roi_pct", data["performance"])
                self.assertIsNone(data["performance"]["equity_usdt"])
                self.assertIsNone(data["performance"]["total_pnl_usdt"])

                # Verify model specs visibility
                self.assertTrue(data["model_specs"]["visible"])
                self.assertIn("primary_model", data["model_specs"])

                # Verify strategy params visibility
                self.assertTrue(data["strategy_clone_payload"]["visible"])
                self.assertIn("risk_settings", data["strategy_clone_payload"])

    def test_privacy_toggles_hide_data(self):
        fake_settings = {
            "enabled": True,
            "nickname": "0xStealth",
            "show_performance": False,
            "show_balance": False,
            "show_model": False,
            "show_strategy_params": False,
        }
        with mock.patch("astra_backend.plaza_share.load_plaza_settings", return_value=fake_settings):
            with mock.patch("astra_backend.plaza_share.is_live_trading_node", return_value=True):
                res = self.client.get("/api/v1/public/plaza/profile")
                data = res.json()
                self.assertEqual(data["status"], "ok")
                self.assertFalse(data["performance"]["visible"])
                self.assertFalse(data["model_specs"]["visible"])
                self.assertFalse(data["strategy_clone_payload"]["visible"])

    def test_show_balance_reveals_equity_when_opted_in(self):
        fake_settings = {
            "enabled": True,
            "nickname": "0xOpenTrader",
            "show_performance": True,
            "show_balance": True,
            "show_model": True,
            "show_strategy_params": True,
        }
        with mock.patch("astra_backend.plaza_share.load_plaza_settings", return_value=fake_settings):
            with mock.patch("astra_backend.plaza_share.is_live_trading_node", return_value=True):
                res = self.client.get("/api/v1/public/plaza/profile")
                data = res.json()
                self.assertIsNotNone(data["performance"]["equity_usdt"])

    def test_zero_secret_leakage_physical_sanitizer(self):
        dirty_payload = {
            "status": "ok",
            "safe_field": "123",
            "secret_key": "MUST_BE_REMOVED",
            "apiKey": "MUST_BE_REMOVED",
            "nested": {
                "token": "MUST_BE_REMOVED",
                "normal_text": "sk-123456789012345678901234567890",
            },
        }
        cleaned = sanitize_public_payload(dirty_payload)
        self.assertNotIn("secret_key", cleaned)
        self.assertNotIn("apiKey", cleaned)
        self.assertNotIn("token", cleaned["nested"])
        self.assertEqual(cleaned["nested"]["normal_text"], "[REDACTED_SECRET]")

    def test_admin_settings_requires_auth(self):
        res = self.client.get("/api/v1/admin/plaza/settings")
        self.assertIn(res.status_code, (401, 403))

        res_post = self.client.post("/api/v1/admin/plaza/settings", json={"enabled": True})
        self.assertIn(res_post.status_code, (401, 403))

    def test_admin_settings_success_with_auth(self):
        with mock.patch("astra_backend.routers.plaza.require_admin_header", return_value={"username": "admin"}):
            res = self.client.get("/api/v1/admin/plaza/settings")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("settings", data)
            self.assertIn("is_live", data)
            self.assertEqual(data["public_url_path"], "/api/v1/public/plaza/profile")

            update_res = self.client.post(
                "/api/v1/admin/plaza/settings",
                json={
                    "enabled": True,
                    "nickname": "0xEthanUpdated",
                    "show_balance": True,
                },
            )
            self.assertEqual(update_res.status_code, 200)
            up_data = update_res.json()
            self.assertTrue(up_data["ok"])
            self.assertEqual(up_data["settings"]["nickname"], "0xEthanUpdated")
            self.assertTrue(up_data["settings"]["enabled"])


if __name__ == "__main__":
    unittest.main()
