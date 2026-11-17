"""`scripts/factors/smart_money.py` 单元测试与双源容灾验证。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from scripts.factors.smart_money import (
    fetch_smart_money_for_symbol,
    fetch_smart_money_pool,
    _fetch_from_okx_rubik,
)


class TestSmartMoneyExtraction(unittest.TestCase):
    def test_empty_symbol(self):
        self.assertIsNone(fetch_smart_money_for_symbol(""))
        self.assertIsNone(fetch_smart_money_for_symbol(None))  # type: ignore

    @patch("scripts.factors.smart_money._fetch_from_okx_rubik")
    def test_okx_success(self, mock_okx):
        mock_okx.return_value = {
            "longShortRatio": {"weightedLongRatio": 0.60, "longShortRatio": 1.5},
            "notional": {"netNotionalUsdt": 12000.0},
            "winRate": {},
            "takerNetUsd": "1.2万 U",
            "lsRatio": 1.5,
            "weighted_long_pct": 60.0,
        }
        res = fetch_smart_money_for_symbol("SOL")
        self.assertIsNotNone(res)
        self.assertEqual(res["weighted_long_pct"], 60.0)
        self.assertEqual(res["takerNetUsd"], "1.2万 U")

    @patch("scripts.factors.smart_money._fetch_from_okx_rubik", return_value=None)
    def test_graceful_none_when_okx_fails(self, mock_okx):
        res = fetch_smart_money_for_symbol("SOL")
        self.assertIsNone(res)

    @patch("scripts.factors.smart_money.fetch_smart_money_for_symbol")
    def test_fetch_smart_money_pool(self, mock_fetch):
        mock_fetch.side_effect = lambda ccy, **kw: {
            "longShortRatio": {"weightedLongRatio": 0.65},
            "notional": {"netNotionalUsdt": 10000},
            "winRate": {},
            "weighted_long_pct": 65.0,
        } if ccy == "SOL" else None

        instruments = [
            {"name": "SOL", "ccy": "SOL", "price": 106.0},
            {"name": "UNKNOWN", "ccy": "UNKNOWN", "price": 1.0},
        ]
        pool = fetch_smart_money_pool(instruments)
        self.assertIn("SOL", pool)
        self.assertNotIn("UNKNOWN", pool)
        self.assertEqual(pool["SOL"]["weighted_long_pct"], 65.0)


if __name__ == "__main__":
    unittest.main()
