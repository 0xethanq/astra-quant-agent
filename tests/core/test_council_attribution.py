"""单元测试：投委会席位战绩与胜率归因统计 (attribution.py)。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from astra_backend.council.attribution import compute_council_seat_performance


class CouncilAttributionTests(unittest.TestCase):
    def test_empty_directory_returns_default_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            perf = compute_council_seat_performance(data_dir=tmp)
            self.assertIn("roles", perf)
            self.assertIn("trader_trend", perf["roles"])
            self.assertIn("trader_momentum", perf["roles"])
            self.assertIn("trader_quant", perf["roles"])
            self.assertIn("cio", perf["roles"])
            self.assertEqual(perf["total_council_trades"], 0)
            self.assertEqual(perf["total_council_pnl_usdt"], 0.0)

    def test_stats_computed_from_ledger_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            # 模拟历史采纳数据
            history = [
                {
                    "time": "2026-10-01 10:00:00",
                    "top_opportunities": [
                        {"instId": "BTC-USDT-SWAP", "action": "BUY_LONG", "council_adopted": "trader_trend"},
                        {"instId": "ETH-USDT-SWAP", "action": "BUY_LONG", "council_adopted": "trader_momentum"},
                    ],
                },
                {
                    "time": "2026-10-01 10:15:00",
                    "top_opportunities": [
                        {"instId": "SOL-USDT-SWAP", "action": "BUY_LONG", "council_adopted": "trader_trend"},
                    ],
                },
            ]
            (p / "ai_brain_history.json").write_text(json.dumps(history), encoding="utf-8")

            # 模拟平仓台账数据
            trades = [
                {
                    "inst": "BTC",
                    "net_pnl": 25.50,
                    "council": {"adopted_role": "trader_trend"},
                },
                {
                    "inst": "SOL",
                    "net_pnl": -10.00,
                    "council": {"adopted_role": "trader_trend"},
                },
                {
                    "inst": "ETH",
                    "net_pnl": 15.00,
                    "council": {"adopted_role": "trader_momentum"},
                },
                {
                    "inst": "DOGE",
                    "net_pnl": -5.00,
                    "council": None,  # 无采纳
                },
            ]
            (p / "trading_ledger.json").write_text(json.dumps(trades), encoding="utf-8")

            perf = compute_council_seat_performance(data_dir=p)
            roles = perf["roles"]

            # trader_trend: 2 次采纳历史, 2 笔平仓(1 盈 1 亏), 胜率 50.0%, 净利 15.5
            tt = roles["trader_trend"]
            self.assertEqual(tt["adopted_count"], 2)
            self.assertEqual(tt["total_trades"], 2)
            self.assertEqual(tt["win_trades"], 1)
            self.assertEqual(tt["loss_trades"], 1)
            self.assertEqual(tt["win_rate"], 50.0)
            self.assertEqual(tt["total_pnl_usdt"], 15.50)
            self.assertEqual(tt["profit_factor"], 2.55)

            # trader_momentum: 1 次采纳历史, 1 笔平仓(1 盈 0 亏), 胜率 100.0%, 净利 15.0
            tm = roles["trader_momentum"]
            self.assertEqual(tm["adopted_count"], 1)
            self.assertEqual(tm["total_trades"], 1)
            self.assertEqual(tm["win_trades"], 1)
            self.assertEqual(tm["loss_trades"], 0)
            self.assertEqual(tm["win_rate"], 100.0)
            self.assertEqual(tm["total_pnl_usdt"], 15.00)

            self.assertEqual(perf["total_council_trades"], 3)
            self.assertEqual(perf["total_council_pnl_usdt"], 30.50)


if __name__ == "__main__":
    unittest.main()
