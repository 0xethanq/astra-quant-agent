"""Tests for Prompt Cache Warmer."""
import unittest
from unittest.mock import patch, MagicMock
import astra_gateway.cache_warmer as cw


class CacheWarmerTests(unittest.TestCase):
    def setUp(self):
        cw._last_warmup_time = 0.0

    @patch("astra_gateway.cache_warmer.send_cache_warmup_ping")
    def test_check_and_warmup_cache_respects_idle_threshold(self, mock_ping):
        mock_ping.return_value = {"ok": True, "cached_tokens": 4500}

        # Case 1: last warmup is 0.0 -> idle threshold exceeded -> triggers ping
        result = cw.check_and_warmup_cache(idle_threshold_seconds=270.0)
        self.assertTrue(result)
        mock_ping.assert_called_once()

        # Case 2: last warmup was just set -> idle threshold not reached -> does not trigger
        cw._last_warmup_time = 10000000000.0  # far in future
        mock_ping.reset_mock()
        result2 = cw.check_and_warmup_cache(idle_threshold_seconds=270.0)
        self.assertFalse(result2)
        mock_ping.assert_not_called()

    @patch("astra_backend.llm_manager.get_active_llm_runtime")
    def test_send_cache_warmup_ping_handles_missing_runtime(self, mock_get_runtime):
        mock_get_runtime.return_value = {}
        res = cw.send_cache_warmup_ping()
        self.assertFalse(res["ok"])
        self.assertIn("No active LLM", res["reason"])
