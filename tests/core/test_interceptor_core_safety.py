"""Offline isolated unit tests for core safety floor, interceptor pipeline and final quote verification.
Strictly local, temporary mocked directory, zero network, zero real exchange calls.
"""
from __future__ import annotations

import copy
import math
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.order_risk import validate_quote_geometry_and_rr
import astra_backend.interceptor_manager as im


class CoreRiskAndInterceptorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.mock_root = Path(self.temp_dir.name)
        self.mock_plugins = self.mock_root / "plugins" / "interceptors"
        self.mock_plugins.mkdir(parents=True, exist_ok=True)
        self.mock_config = self.mock_root / "data" / "interceptor_plugins.json"

        # Patch paths in interceptor_manager
        self.patch_plugins_dir = patch.object(im, "PLUGINS_DIR", self.mock_plugins)
        self.patch_config_file = patch.object(im, "CONFIG_FILE", self.mock_config)
        self.patch_plugins_dir.start()
        self.patch_config_file.start()
        self.addCleanup(self.patch_plugins_dir.stop)
        self.addCleanup(self.patch_config_file.stop)

    def test_quote_geometry_and_rr_valid(self):
        # Long valid 2.5R
        ok, reason, rr = validate_quote_geometry_and_rr("BUY_LONG", 100.0, 125.0, 90.0)
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertAlmostEqual(rr, 2.5)

        # Short valid 2.0R
        ok, reason, rr = validate_quote_geometry_and_rr("SELL_SHORT", 100.0, 80.0, 110.0)
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertAlmostEqual(rr, 2.0)

    def test_quote_geometry_and_rr_invalid_geometry(self):
        # Long: sl >= entry
        ok, reason, _ = validate_quote_geometry_and_rr("BUY_LONG", 100.0, 120.0, 105.0)
        self.assertFalse(ok)
        self.assertIn("买多几何不合法", reason)

        # Short: tp >= entry
        ok, reason, _ = validate_quote_geometry_and_rr("SELL_SHORT", 100.0, 105.0, 110.0)
        self.assertFalse(ok)
        self.assertIn("卖空几何不合法", reason)

    def test_quote_geometry_and_rr_insufficient_rr(self):
        # Long: RR = (115 - 100) / (100 - 90) = 1.5 < 2.0
        ok, reason, rr = validate_quote_geometry_and_rr("BUY_LONG", 100.0, 115.0, 90.0)
        self.assertFalse(ok)
        self.assertIn("盈亏比不足 2.0", reason)
        self.assertAlmostEqual(rr, 1.5)

    def test_quote_geometry_and_rr_non_finite_or_nan(self):
        ok, reason, _ = validate_quote_geometry_and_rr("BUY_LONG", float("nan"), 120.0, 90.0)
        self.assertFalse(ok)
        self.assertIn("有限数值", reason)

        ok, reason, _ = validate_quote_geometry_and_rr("BUY_LONG", 100.0, float("inf"), 90.0)
        self.assertFalse(ok)
        self.assertIn("有限数值", reason)

    def test_pipeline_core_floor_active_when_all_plugins_disabled(self):
        # Set all plugins to disabled in config
        im.save_config({"pipeline_order": [], "enabled": {}})

        pkg = {"instId": "BTC-USDT-SWAP", "data_quality": "valid"}
        ctx = {"active_inst_ids": set(), "active_position_sides": {}}

        # Low confidence (< 75)
        dec = {"action": "BUY_LONG", "confidence": 70.0, "entry_price": 100.0, "take_profit_price": 130.0, "stop_loss_price": 90.0}
        act, reason, _ = im.run_interceptor_pipeline(pkg, dec, ctx)
        self.assertEqual(act, "WAIT")
        self.assertIn("置信度低于安全底线", reason)

        # Insufficient RR (< 2.0)
        dec = {"action": "BUY_LONG", "confidence": 85.0, "entry_price": 100.0, "take_profit_price": 110.0, "stop_loss_price": 90.0}
        act, reason, rr = im.run_interceptor_pipeline(pkg, dec, ctx)
        self.assertEqual(act, "WAIT")
        self.assertIn("盈亏比不足 2.0", reason)

        # DOGE confidence floor 80
        pkg_doge = {"instId": "DOGE-USDT-SWAP", "data_quality": "valid"}
        dec_doge = {"action": "BUY_LONG", "confidence": 78.0, "entry_price": 0.10, "take_profit_price": 0.13, "stop_loss_price": 0.09}
        act, reason, _ = im.run_interceptor_pipeline(pkg_doge, dec_doge, ctx)
        self.assertEqual(act, "WAIT")
        self.assertIn("80.0%", reason)

        # Valid trade passes core check even with no plugins enabled
        dec_valid = {"action": "BUY_LONG", "confidence": 85.0, "entry_price": 100.0, "take_profit_price": 125.0, "stop_loss_price": 90.0}
        act, reason, rr = im.run_interceptor_pipeline(pkg, dec_valid, ctx)
        self.assertEqual(act, "BUY_LONG")
        self.assertEqual(reason, "")
        self.assertAlmostEqual(rr, 2.5)

    def test_pipeline_fail_closed_when_plugin_missing_file_or_entry(self):
        # Configure an enabled plugin that does not exist on disk
        im.save_config({
            "pipeline_order": ["missing_filter.py", "bad_syntax.py"],
            "enabled": {"missing_filter.py": True, "bad_syntax.py": False}
        })

        pkg = {"instId": "BTC-USDT-SWAP", "data_quality": "valid"}
        ctx = {"active_inst_ids": set(), "active_position_sides": {}}
        dec = {"action": "BUY_LONG", "confidence": 85.0, "entry_price": 100.0, "take_profit_price": 125.0, "stop_loss_price": 90.0}

        act, reason, _ = im.run_interceptor_pipeline(pkg, dec, ctx)
        self.assertEqual(act, "WAIT")
        self.assertIn("文件缺失", reason)

        # Now create file but omit check_risk function
        no_entry = self.mock_plugins / "no_entry.py"
        no_entry.write_text("def other_function(): pass\n", encoding="utf-8")
        im.save_config({
            "pipeline_order": ["no_entry.py"],
            "enabled": {"no_entry.py": True}
        })
        act, reason, _ = im.run_interceptor_pipeline(pkg, dec, ctx)
        self.assertEqual(act, "WAIT")
        self.assertIn("缺少 check_risk 入口", reason)

    def test_pipeline_plugin_input_mutation_isolation(self):
        # Plugin attempts to mutate decision object
        mutating_plugin = self.mock_plugins / "mutator.py"
        mutating_plugin.write_text(
            "def check_risk(package, decision, context):\n"
            "    decision['confidence'] = 999.0\n"
            "    decision['entry_price'] = 0.0\n"
            "    return True, ''\n",
            encoding="utf-8"
        )
        im.save_config({
            "pipeline_order": ["mutator.py"],
            "enabled": {"mutator.py": True}
        })

        pkg = {"instId": "BTC-USDT-SWAP", "data_quality": "valid"}
        ctx = {"active_inst_ids": set(), "active_position_sides": {}}
        dec = {"action": "BUY_LONG", "confidence": 85.0, "entry_price": 100.0, "take_profit_price": 125.0, "stop_loss_price": 90.0}
        dec_copy = copy.deepcopy(dec)

        act, _, _ = im.run_interceptor_pipeline(pkg, dec, ctx)
        self.assertEqual(act, "BUY_LONG")
        # Ensure dec was not mutated by the plugin
        self.assertEqual(dec, dec_copy)


if __name__ == "__main__":
    unittest.main()
