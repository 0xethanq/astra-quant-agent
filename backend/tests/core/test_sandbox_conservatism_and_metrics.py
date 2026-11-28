"""Regression tests for zero-lookahead sandbox conservatism, contract sizing/funding,
multi-bar annualization, Sortino/avg_R fixes, MarketReplayWarehouse, Walk-Forward,
and SQLite-cached LLM A/B replay.
"""
from __future__ import annotations

import gc
import math
import os
import shutil
import sys
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from astra_backend.sandbox.adapter import SandboxExchangeAdapter  # noqa: E402
from astra_backend.sandbox.data_warehouse import MarketReplayWarehouse  # noqa: E402
from astra_backend.sandbox.replay import PointInTimeReplayEngine  # noqa: E402
from scripts.backtest.ingest_history import ingest_universe_history  # noqa: E402
from scripts.backtest.llm_replay import (  # noqa: E402
    run_deterministic_walk_forward,
    run_llm_replay_ab,
    select_stratified_replay_points,
)


def _bar(ts_ms: int, o: float, h: float, low: float, c: float, vol: float = 100.0) -> dict:
    return {"ts": ts_ms, "ts_ms": ts_ms, "open": o, "high": h, "low": low, "close": c, "volume": vol}


def _make_ohlcv_series(n_bars: int = 240, *, base_ts: int = 1_700_000_000_000, step_ms: int = 3_600_000) -> dict:
    out = {}
    configs = [
        ("BTC-USDT-SWAP", 50000.0, 0.0025, 0.015),
        ("ETH-USDT-SWAP", 2600.0, 0.0032, 0.022),
        ("SOL-USDT-SWAP", 120.0, 0.0045, 0.030),
    ]
    for sym, start_px, drift, amp in configs:
        rows = []
        px = start_px
        for i in range(n_bars):
            ts = base_ts + i * step_ms
            wave = math.sin(i * 0.25) * amp + math.cos(i * 0.11) * (amp * 0.5)
            ret = drift * (1.0 if (i % 48) < 32 else -0.8) + wave * 0.25
            o = px
            c = max(1.0, o * (1.0 + ret))
            h = max(o, c) * 1.006
            low = min(o, c) * 0.994
            vol = 1000.0 + (i % 17) * 80.0
            rows.append([ts, round(o, 4), round(h, 4), round(low, 4), round(c, 4), vol])
            px = c
        out[sym] = rows
    return out


class SandboxConservatismTests(unittest.TestCase):
    def test_same_bar_stop_loss_checked_before_tp_and_be(self):
        adapter = SandboxExchangeAdapter(initial_balance=10000.0, slippage=0.0)
        ts0 = 1_700_000_000_000
        adapter.step({"BTC": _bar(ts0, 100.0, 100.0, 100.0, 100.0)})
        adapter.place_order(
            symbol="BTC-USDT-SWAP",
            side="buy",
            contracts=1.0,
            order_type="market",
            initial_sl_px=95.0,
            tp1_px=105.0,
        )
        adapter.attach_protective_orders("BTC-USDT-SWAP", "buy", tp_px=110.0, sl_px=95.0, contracts=1.0)
        # Same bar touches BOTH sl=95 and tp=110 -> STOP_LOSS must trigger first
        adapter.step({"BTC": _bar(ts0 + 3_600_000, 100.0, 112.0, 94.0, 108.0)})
        self.assertEqual(len(adapter._positions), 0)
        closed = [t for t in adapter._trades if "exit_reason" in t]
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["exit_reason"], "STOP_LOSS")
        self.assertLess(closed[0]["net_pnl"], 0.0)

    def test_limit_order_filled_on_bar_t_cannot_trigger_tp_on_same_bar_t(self):
        adapter = SandboxExchangeAdapter(initial_balance=10000.0, slippage=0.0)
        ts0 = 1_700_000_000_000
        adapter.step({"BTC": _bar(ts0, 105.0, 106.0, 104.0, 105.0)})
        adapter.place_order(symbol="BTC-USDT-SWAP", side="buy", contracts=1.0, price=100.0, order_type="limit")
        adapter.attach_protective_orders("BTC-USDT-SWAP", "buy", tp_px=108.0, sl_px=95.0, contracts=1.0)
        # Bar t fills limit at 100 AND also exceeds tp=108 -> triggers run BEFORE order matching
        adapter.step({"BTC": _bar(ts0 + 3_600_000, 105.0, 110.0, 99.0, 109.0)})
        self.assertIn("BTC:long", adapter._positions)
        closed = [t for t in adapter._trades if "exit_reason" in t]
        self.assertEqual(len(closed), 0)

    def test_partial_tp1_scales_out_and_moves_sl_to_be_for_subsequent_bar(self):
        adapter = SandboxExchangeAdapter(initial_balance=10000.0, slippage=0.0)
        ts0 = 1_700_000_000_000
        adapter.step({"BTC": _bar(ts0, 100.0, 100.0, 100.0, 100.0)})
        adapter.place_order(
            symbol="BTC-USDT-SWAP",
            side="buy",
            contracts=10.0,
            order_type="market",
            initial_sl_px=95.0,
            tp1_px=105.0,
            scale_out_ratio=0.35,
            be_offset_pct=0.0030,
        )
        adapter.attach_protective_orders("BTC-USDT-SWAP", "buy", tp_px=115.0, sl_px=95.0, contracts=10.0)
        # Bar hits TP1 (105) without hitting TP2 (115) -> 3.5 closed at 105, remaining 6.5 stays open, SL -> 100.3
        adapter.step({"BTC": _bar(ts0 + 3_600_000, 100.0, 106.0, 99.0, 105.5)})
        self.assertIn("BTC:long", adapter._positions)
        self.assertAlmostEqual(adapter._positions["BTC:long"]["amount"], 6.5, places=4)
        live_algos = adapter.list_protective_orders("BTC-USDT-SWAP")
        self.assertGreaterEqual(live_algos[0]["sl_trigger_px"], 100.29)

    def test_ct_val_8h_funding_and_liquidation(self):
        adapter = SandboxExchangeAdapter(
            initial_balance=1000.0,
            slippage=0.0,
            maker_fee=0.0,
            taker_fee=0.0,
            instrument_specs={"BTC": {"ctVal": 0.01}},
        )
        # Align ts0 directly before an 8H funding boundary (28_800_000 ms)
        ts_boundary = 1_700_006_400_000  # divisible by 28_800_000? Let's enforce exact modulo
        ts_boundary = (1_700_000_000_000 // 28_800_000 + 1) * 28_800_000
        adapter.step({"BTC": _bar(ts_boundary - 3_600_000, 10000.0, 10000.0, 10000.0, 10000.0)})
        adapter.place_order(symbol="BTC-USDT-SWAP", side="buy", contracts=10.0, order_type="market", leverage=10.0)
        # Notional = 10 * 0.01 * 10000 = 1000 USD; margin_locked = 1000 / 10 = 100 USD
        pos = adapter._positions["BTC:long"]
        self.assertAlmostEqual(pos["ct_val"], 0.01, places=6)
        self.assertAlmostEqual(pos["margin_locked"], 100.0, places=2)
        bal_before_funding = adapter.cash
        adapter.set_funding_rate("BTC-USDT-SWAP", 0.01)  # +1% funding paid by long
        adapter.step({"BTC": _bar(ts_boundary, 10000.0, 10020.0, 9990.0, 10000.0)})
        # Funding fee = 10 * 0.01 * 10000 * 0.01 = 10.0 USD deducted
        self.assertAlmostEqual(adapter.cash, bal_before_funding - 10.0, places=2)
        # Crash low far past liquidation threshold (margin_locked=100, mm=5, drop 15% => worst_upl=-150)
        adapter.step({"BTC": _bar(ts_boundary + 3_600_000, 10000.0, 10000.0, 8400.0, 8500.0)})
        self.assertEqual(len(adapter._positions), 0)
        liq = [t for t in adapter._trades if t.get("exit_reason") == "LIQUIDATION"]
        self.assertEqual(len(liq), 1)


class ReplayMetricsAndAnnualizationTests(unittest.TestCase):
    def test_bar_annualization_scales_by_sqrt_bars_per_year_and_sortino_uses_full_n(self):
        ts0 = 1_700_000_000_000
        # Build deterministic oscillating equity by opening/closing winning & losing market trades
        def _run_bar(bar: str, step_ms: int):
            candles = {
                "BTC": [
                    [ts0 + i * step_ms, px, px + 2.0, px - 2.0, px, 100.0]
                    for i, px in enumerate([100.0, 104.0, 102.0, 107.0, 105.0, 111.0, 108.0, 114.0])
                ]
            }
            def strat(adapter: SandboxExchangeAdapter, ts_ms: int):
                idx = round((ts_ms - ts0) / step_ms)
                if idx == 0:
                    return [{
                        "action": "OPEN_LONG",
                        "symbol": "BTC",
                        "contracts": 5.0,
                        "order_type": "market",
                        "sl_px": 92.0,
                        "tp_px": 120.0,
                    }]
                return None
            engine = PointInTimeReplayEngine(initial_balance=10000.0, slippage=0.0, maker_fee=0.0, taker_fee=0.0)
            return engine.run_replay(candles, strat, bar=bar)

        m_1h = _run_bar("1H", 3_600_000)
        m_15m = _run_bar("15m", 900_000)
        self.assertGreater(m_1h.sharpe_ratio, 0.0)
        self.assertGreater(m_1h.sortino_ratio, 0.0)
        # 15m has 4x periods/year vs 1H -> sqrt(4) = 2x Sharpe & Sortino
        self.assertAlmostEqual(m_15m.sharpe_ratio / m_1h.sharpe_ratio, 2.0, delta=0.08)
        self.assertAlmostEqual(m_15m.sortino_ratio / m_1h.sortino_ratio, 2.0, delta=0.08)

    def test_avg_r_multiple_uses_per_trade_recorded_r_multiple(self):
        ts0 = 1_700_000_000_000
        candles = {
            "ETH": [
                [ts0, 100.0, 100.5, 99.5, 100.0, 100.0],
                [ts0 + 3_600_000, 100.0, 111.0, 99.5, 110.5, 100.0],  # Hits TP=110 with SL=95 -> +2.0R
            ]
        }
        def strat(adapter: SandboxExchangeAdapter, ts_ms: int):
            if ts_ms == ts0:
                return [{
                    "action": "OPEN_LONG",
                    "symbol": "ETH",
                    "contracts": 2.0,
                    "order_type": "market",
                    "sl_px": 95.0,
                    "tp_px": 110.0,
                }]
            return None

        engine = PointInTimeReplayEngine(initial_balance=10000.0, slippage=0.0, maker_fee=0.0, taker_fee=0.0)
        metrics = engine.run_replay(candles, strat, bar="1H")
        self.assertEqual(metrics.total_trades, 1)
        self.assertAlmostEqual(metrics.avg_r_multiple, 2.0, delta=0.1)


class WarehouseAndWalkForwardReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="astra_replay_test_")
        self.db_path = Path(self.tmpdir) / "warehouse.db"

    def tearDown(self):
        gc.collect()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_market_replay_warehouse_point_in_time_and_llm_cache(self):
        wh = MarketReplayWarehouse(self.db_path)
        wh.ingest_funding_history("okx", "BTC-USDT-SWAP", [
            {"ts_ms": 1000, "funding_rate": 0.0001},
            {"ts_ms": 2000, "funding_rate": -0.0002},
        ])
        self.assertEqual(len(wh.query_funding_history("okx", "BTC-USDT-SWAP", start_ts_ms=1000, end_ts_ms=2000)), 2)

        wh.ingest_oi_history("okx", "BTC-USDT-SWAP", "1H", [{"ts_ms": 1000, "oi": 12345.0, "oi_ccy": 240.0}])
        self.assertEqual(len(wh.query_oi_history("okx", "BTC-USDT-SWAP", "1H")), 1)

        wh.save_market_snapshot(1000, "BTC-USDT-SWAP", {"price": 50000.0})
        wh.save_market_snapshot(3000, "BTC-USDT-SWAP", {"price": 52000.0})
        snap = wh.get_latest_market_snapshot_before("BTC-USDT-SWAP", 2500)
        self.assertIsNotNone(snap)
        self.assertEqual(snap["ts_ms"], 1000)
        self.assertEqual(snap["payload"]["price"], 50000.0)

        wh.put_cached_llm_response("hash_abc", "test-model", {"decisions": [{"instId": "BTC-USDT-SWAP", "action": "WAIT"}]}, created_ts_ms=1000, latency_ms=12)
        cached = wh.get_cached_llm_response("hash_abc", "test-model")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["response"]["decisions"][0]["action"], "WAIT")

    def test_snapshot_archival_and_shadow_eval_hook_fail_soft(self):
        from scripts.ai_factor_trader import _archive_snapshot_and_shadow_eval

        shadow_log = os.path.join(self.tmpdir, "shadow_eval.jsonl")
        factors = [{"instId": "BTC-USDT-SWAP", "price": 60000.0, "atr": 600.0, "regime": "TRENDING_BULL", "score": 35.0}]
        cache = {"BTC-USDT-SWAP": {"action": "WAIT", "confidence": 55}}
        old_val = os.environ.get("ASTRA_SHADOW_EVAL_ENABLED")
        try:
            os.environ["ASTRA_SHADOW_EVAL_ENABLED"] = "1"
            res = _archive_snapshot_and_shadow_eval(
                factors,
                cache,
                "2026-11-28 12:00:00",
                db_path=str(self.db_path),
                shadow_log_path=shadow_log,
            )
            self.assertEqual(res["archived"], 1)
            self.assertEqual(res["shadow_logged"], 1)
            self.assertTrue(os.path.exists(shadow_log))
            wh = MarketReplayWarehouse(self.db_path)
            snaps = wh.query_market_snapshots("BTC-USDT-SWAP")
            self.assertEqual(len(snaps), 1)
            self.assertEqual(snaps[0]["payload"]["price"], 60000.0)
        finally:
            if old_val is None:
                os.environ.pop("ASTRA_SHADOW_EVAL_ENABLED", None)
            else:
                os.environ["ASTRA_SHADOW_EVAL_ENABLED"] = old_val

    def test_walk_forward_returns_folds_and_oos_summary(self):
        candles = _make_ohlcv_series(240)
        res = run_deterministic_walk_forward(candles, n_folds=3, alpha_entry_threshold=12.0)
        self.assertEqual(len(res["folds"]), 3)
        oos = res["oos_summary"]
        self.assertIn("rank_ic", oos)
        self.assertIn("expectancy_r", oos)
        self.assertIn("fee_ratio_pct", oos)
        self.assertGreater(oos["n_folds"], 0)

    def test_llm_replay_ab_caches_and_deduplicates_second_run(self):
        candles = _make_ohlcv_series(160)
        pts = select_stratified_replay_points(candles, n_points=6)
        self.assertGreater(len(pts), 0)
        wh = MarketReplayWarehouse(self.db_path)
        calls = {"n": 0}

        def stub_llm(sys_prompt: str, user_prompt: str, model: str):
            calls["n"] += 1
            return {"decisions": [{"instId": "BTC-USDT-SWAP", "action": "WAIT", "confidence": 50}]}, 5

        first = run_llm_replay_ab(
            candles,
            llm_call_fn=stub_llm,
            system_prompt_a="SYSTEM_A",
            system_prompt_b="SYSTEM_B",
            model_name="stub-replay",
            prompt_builder_fn=lambda pkgs, tstr: f"{tstr}|{len(pkgs)}",
            warehouse=wh,
            replay_timestamps=pts,
        )
        self.assertEqual(calls["n"], 2 * len(pts))
        self.assertEqual(first["baseline"]["llm_calls"], len(pts))
        self.assertEqual(first["upgraded"]["llm_calls"], len(pts))

        second = run_llm_replay_ab(
            candles,
            llm_call_fn=stub_llm,
            system_prompt_a="SYSTEM_A",
            system_prompt_b="SYSTEM_B",
            model_name="stub-replay",
            prompt_builder_fn=lambda pkgs, tstr: f"{tstr}|{len(pkgs)}",
            warehouse=wh,
            replay_timestamps=pts,
        )
        # Repeat run hits SQLite llm_replay_cache -> zero extra LLM invocations
        self.assertEqual(calls["n"], 2 * len(pts))
        self.assertEqual(second["baseline"]["llm_calls"], 0)
        self.assertEqual(second["baseline"]["cache_hits"], len(pts))
        self.assertEqual(second["upgraded"]["cache_hits"], len(pts))

    def test_ingest_history_universe_records_candles_and_funding(self):
        wh = MarketReplayWarehouse(self.db_path)
        fake_candles = [
            [1_700_000_000_000, 50000.0, 50100.0, 49900.0, 50050.0, 120.0],
            [1_700_003_600_000, 50050.0, 50200.0, 50000.0, 50150.0, 150.0],
        ]
        fake_funding = [{"ts_ms": 1_700_000_000_000, "funding_rate": 0.0001}]
        with patch("scripts.backtest.ingest_history.fetch_paginated_okx_candles", return_value=fake_candles), \
             patch("scripts.backtest.ingest_history.fetch_okx_funding_history", return_value=fake_funding):
            res = ingest_universe_history(symbols=("BTC-USDT-SWAP",), bars=("1H",), days=1, warehouse=wh)
        self.assertEqual(res["symbols"]["BTC-USDT-SWAP"]["candles_1h"], 2)
        self.assertEqual(res["symbols"]["BTC-USDT-SWAP"]["funding"], 1)
        self.assertEqual(len(wh.query_candles("okx", "BTC-USDT-SWAP", "1H")), 2)
        self.assertEqual(len(wh.query_funding_history("okx", "BTC-USDT-SWAP")), 1)


if __name__ == "__main__":
    unittest.main()
