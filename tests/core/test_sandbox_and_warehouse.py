"""Unit tests for SandboxExchangeAdapter, CandleWarehouse, and PointInTimeReplayEngine."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from astra_backend.exchanges import get_adapter
from astra_backend.sandbox.adapter import SandboxExchangeAdapter
from astra_backend.sandbox.data_warehouse import CandleWarehouse
from astra_backend.sandbox.replay import PointInTimeReplayEngine, ReplayMetrics


class SandboxAdapterTests(unittest.TestCase):
    def setUp(self):
        self.adapter = SandboxExchangeAdapter(initial_balance=10000.0)

    def test_registry_integration(self):
        ad = get_adapter("sandbox")
        self.assertIsInstance(ad, SandboxExchangeAdapter)
        self.assertEqual(ad.capabilities.venue, "sandbox")
        self.assertTrue(ad.capabilities.supports_orders)
        self.assertTrue(ad.capabilities.supports_account)

    def test_point_in_time_candle_isolation(self):
        # 3 candles with ts_ms = 1000, 2000, 3000
        candles = [
            [1000, 100.0, 105.0, 99.0, 102.0, 10.0],
            [2000, 102.0, 108.0, 101.0, 106.0, 15.0],
            [3000, 106.0, 112.0, 105.0, 110.0, 20.0],
        ]
        self.adapter.set_historical_candles("BTC", "15m", candles)

        # Set simulation clock to 1500 ms
        self.adapter.sim_time_ms = 1500
        fetched = self.adapter.fetch_candles("BTC", bar="15m", limit=10)
        self.assertEqual(len(fetched), 1)
        self.assertEqual(fetched[0][0], 1000)

        # Step clock to 2500 ms
        self.adapter.sim_time_ms = 2500
        fetched = self.adapter.fetch_candles("BTC", bar="15m", limit=10)
        self.assertEqual(len(fetched), 2)
        self.assertEqual(fetched[1][0], 2000)

    def test_limit_order_fill_and_tp_trigger(self):
        # Place limit buy order at 100.0
        res = self.adapter.place_order("BTC", "buy", contracts=1.0, price=100.0, order_type="limit")
        ord_id = res["order_id"]
        self.assertEqual(len(self.adapter.open_orders()), 1)

        # Step 1: Bar low = 101.0 -> no fill
        self.adapter.step({"BTC": {"open": 105, "high": 108, "low": 101, "close": 104, "ts_ms": 1000}})
        self.assertEqual(len(self.adapter.open_orders()), 1)
        self.assertEqual(len(self.adapter.positions()), 0)

        # Step 2: Bar low = 98.0 -> filled!
        self.adapter.step({"BTC": {"open": 102, "high": 103, "low": 98, "close": 101, "ts_ms": 2000}})
        self.assertEqual(len(self.adapter.open_orders()), 0)
        positions = self.adapter.positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["base"], "BTC")
        self.assertEqual(positions[0]["amount"], 1.0)

        # Attach TP at 115.0 and SL at 90.0
        algo = self.adapter.attach_protective_orders("BTC", "long", tp_px=115.0, sl_px=90.0)
        self.assertIn("tp", algo)
        self.assertEqual(len(self.adapter.list_protective_orders("BTC")), 1)

        # Step 3: Bar high reaches 116.0 -> TP triggers and closes position!
        self.adapter.step({"BTC": {"open": 105, "high": 116, "low": 104, "close": 115, "ts_ms": 3000}})
        self.assertEqual(len(self.adapter.positions()), 0)
        self.assertGreater(self.adapter.equity, 10000.0)


class CandleWarehouseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_warehouse.db"
        self.warehouse = CandleWarehouse(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ingest_and_query_candles(self):
        rows = [
            [1700000000000, 50000.0, 50500.0, 49800.0, 50200.0, 12.5],
            [1700000900000, 50200.0, 50800.0, 50100.0, 50700.0, 18.2],
            [1700001800000, 50700.0, 51000.0, 50500.0, 50900.0, 22.0],
        ]
        inserted = self.warehouse.ingest_candles("okx", "BTC-USDT-SWAP", "15m", rows)
        self.assertEqual(inserted, 3)

        count = self.warehouse.count_candles("okx", "BTC-USDT-SWAP", "15m")
        self.assertEqual(count, 3)

        # Query range
        queried = self.warehouse.query_candles(
            "okx", "BTC-USDT-SWAP", "15m",
            start_ts_ms=1700000900000, end_ts_ms=1700001800000
        )
        self.assertEqual(len(queried), 2)
        self.assertEqual(queried[0][0], 1700000900000)
        self.assertEqual(queried[1][0], 1700001800000)

        # Ranges summary
        ranges = self.warehouse.list_available_ranges()
        self.assertEqual(len(ranges), 1)
        self.assertEqual(ranges[0]["symbol"], "BTC-USDT-SWAP")
        self.assertEqual(ranges[0]["count"], 3)


class PointInTimeReplayEngineTests(unittest.TestCase):
    def test_replay_metrics_calculation(self):
        engine = PointInTimeReplayEngine(initial_balance=10000.0)

        # Synthetic trend series
        candles = []
        base = 50000.0
        for i in range(50):
            p = base + (i * 100) if i < 30 else base + 3000 - ((i - 30) * 150)
            candles.append([1000 + i * 1000, p - 20, p + 50, p - 30, p, 10.0])

        def trend_strategy(adapter, ts_ms):
            # Simple strategy: open long on 5th bar with TP/SL
            if ts_ms == 1000 + 5 * 1000 and not adapter.positions():
                ticker = adapter.fetch_ticker("BTC")
                px = ticker["last"]
                return [{
                    "symbol": "BTC",
                    "action": "BUY",
                    "contracts": 0.5,
                    "order_type": "market",
                    "take_profit_price": px + 400.0,
                    "stop_loss_price": px - 200.0,
                }]
            return None

        metrics = engine.run_replay({"BTC": candles}, trend_strategy, bar="15m")
        self.assertIsInstance(metrics, ReplayMetrics)
        self.assertEqual(metrics.total_trades, 1)
        self.assertGreater(metrics.total_return_pct, 0.0)
        self.assertGreaterEqual(metrics.win_rate_pct, 100.0)
        self.assertGreater(len(metrics.equity_curve), 40)


if __name__ == "__main__":
    unittest.main()
