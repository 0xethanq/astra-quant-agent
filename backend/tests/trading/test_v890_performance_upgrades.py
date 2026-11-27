"""Performance, caching, prompt-slimming, and timeout regression tests for v8.9.0 (Phase 2C)."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import types
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.brain import packages as brain_packages  # noqa: E402
from scripts.brain import prompt as brain_prompt  # noqa: E402
from scripts.brain import snapshots as brain_snapshots  # noqa: E402
from scripts.factors import okx_quant_factors as qf  # noqa: E402
from scripts.factors import smart_money as sm  # noqa: E402
from scripts.trader import cycle_stages as cs  # noqa: E402
from scripts.trader.cycle_snapshot import venue_position_span  # noqa: E402


class _JsonResp:
    def __init__(self, payload, delay: float = 0.0):
        self._raw = json.dumps(payload).encode("utf-8")
        self._delay = delay

    def __enter__(self):
        if self._delay > 0:
            time.sleep(self._delay)
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._raw


class RubikPacingAndDiskCacheTests(unittest.TestCase):
    def setUp(self):
        qf._reset_cache_for_tests()
        self.addCleanup(qf._reset_cache_for_tests)

    def test_rubik_pacing_overlaps_http_rtt_without_serial_blocking(self):
        """Request starts are throttled, but HTTP RTT runs concurrently outside the call lock."""
        starts: list[float] = []

        def slow_urlopen(req, timeout=4.0):
            starts.append(time.monotonic())
            return _JsonResp({"code": "0", "data": [["t", "1", "2"]]}, delay=0.14)

        t0 = time.monotonic()
        with (
            patch.object(qf, "_RUBIK_MIN_INTERVAL", 0.07),
            patch.object(qf.urllib.request, "urlopen", side_effect=slow_urlopen),
        ):
            with ThreadPoolExecutor(max_workers=3) as ex:
                res = list(
                    ex.map(
                        lambda c: qf._public_get("/api/v5/rubik/stat/taker-volume", {"ccy": c}),
                        ["BTC", "ETH", "SOL"],
                    )
                )
        elapsed = time.monotonic() - t0
        self.assertEqual(len(res), 3)
        self.assertTrue(all(r == [["t", "1", "2"]] for r in res))
        self.assertEqual(len(starts), 3)
        starts.sort()
        # Start spacing stays paced (~0.07s); total time < 3*(0.07+0.14)=0.63s
        self.assertGreaterEqual(starts[1] - starts[0], 0.055)
        self.assertGreaterEqual(starts[2] - starts[1], 0.055)
        self.assertLess(elapsed, 0.45)

    def test_disk_cache_disabled_by_default_in_tests_and_persists_when_enabled(self):
        self.assertFalse(qf._disk_cache_enabled())
        with tempfile.TemporaryDirectory() as td:
            cache_file = os.path.join(td, "okx_ttl.json")
            with patch.dict(
                os.environ,
                {"ASTRA_OKX_DISK_CACHE": "1", "ASTRA_OKX_DISK_CACHE_FILE": cache_file},
            ):
                self.assertTrue(qf._disk_cache_enabled())
                qf._cache_put("lsratio:BTC", [["1700000000", "2.1"]])
                self.assertTrue(os.path.exists(cache_file))
                self.assertEqual([p.name for p in Path(td).iterdir()], ["okx_ttl.json"])

                # Simulate fresh subprocess loading from disk cache
                with qf._CACHE_LOCK:
                    qf._CACHE.clear()
                    qf._DISK_CACHE_SIG = (0, 0)
                hit = qf._cache_get("lsratio:BTC", ttl=300.0)
                self.assertEqual(hit, [["1700000000", "2.1"]])
                with patch.object(qf.time, "time", return_value=time.time() + 400.0):
                    self.assertIsNone(qf._cache_get("lsratio:BTC", ttl=300.0))

    def test_smart_money_shares_cache_and_memoizes_404_when_disk_cache_enabled(self):
        self.assertIsNone(sm._shared_cache_module())
        with tempfile.TemporaryDirectory() as td:
            cache_file = os.path.join(td, "okx_ttl.json")
            seen_urls: list[str] = []

            def fake_urlopen(req, timeout=3.5):
                url = req.full_url
                seen_urls.append(url)
                if "long-short-pos-ratio" in url:
                    raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
                if "long-short-account-ratio" in url:
                    return _JsonResp({"code": "0", "data": [["t", "2.5"]]})
                if "taker-volume" in url:
                    return _JsonResp({"code": "0", "data": [["t", "100", "600"]]})
                raise AssertionError(f"Unexpected URL: {url}")

            with (
                patch.dict(
                    os.environ,
                    {"ASTRA_OKX_DISK_CACHE": "1", "ASTRA_OKX_DISK_CACHE_FILE": cache_file},
                ),
                patch.object(sm.urllib.request, "urlopen", side_effect=fake_urlopen) as mock_open,
            ):
                first = sm.fetch_smart_money_for_symbol("SOL")
                self.assertIsNotNone(first)
                self.assertEqual(first["lsRatio"], 2.5)
                self.assertEqual(first["takerNetUsd"], "500.0 U")
                self.assertEqual(len(seen_urls), 3)

                # okx_quant_factors hits shared taker:5m and lsratio caches without HTTP
                seen_urls.clear()
                self.assertEqual(qf.fetch_taker_volume("SOL", "5m"), [["t", "100", "600"]])
                self.assertEqual(qf._cache_get("lsratio:SOL", 300.0), [["t", "2.5"]])
                self.assertEqual(seen_urls, [])

                # Simulate fresh process: zero HTTP calls needed even for 404 endpoint
                with qf._CACHE_LOCK:
                    qf._CACHE.clear()
                    qf._DISK_CACHE_SIG = (0, 0)
                seen_urls.clear()
                second = sm.fetch_smart_money_for_symbol("SOL")
                self.assertEqual(seen_urls, [])
                self.assertEqual(second["lsRatio"], 2.5)
                self.assertEqual(second["takerNetUsd"], "500.0 U")
                self.assertEqual(mock_open.call_count, 3)


class PreLlmSkipAndPackageCacheTests(unittest.TestCase):
    def test_preflight_skips_news_harvester_when_snapshot_is_fresh(self):
        with tempfile.TemporaryDirectory() as td:
            scripts_dir = Path(td) / "scripts"
            data_dir = Path(td) / "data"
            scripts_dir.mkdir()
            data_dir.mkdir()
            (scripts_dir / "news_sentiment_harvester.py").write_text("# stub\n", encoding="utf-8")
            news_file = data_dir / "news_sentiment.json"
            news_file.write_text('{"macro_sentiment": "中性", "latest_news": [1, 2]}', encoding="utf-8")

            ran: list[str] = []
            env = types.SimpleNamespace(configured=True, mode="demo")
            res = cs.preflight_reconcile_and_housekeeping(
                WORKSPACE_DIR=td,
                _run_captured=lambda path, **kw: ran.append(Path(path).name),
                clean_stale_open_orders=lambda **k: (True, ""),
                current_environment=lambda: env,
                datetime=__import__("datetime"),
                load_trackers=lambda: {},
                os=os,
                reconcile_pending_orders=lambda **k: (True, set()),
            )
            self.assertIsNotNone(res)
            self.assertEqual(ran, [])

            # Make snapshot stale (> 900s) -> must spawn harvester
            stale_ts = time.time() - 1200.0
            os.utime(news_file, (stale_ts, stale_ts))
            res2 = cs.preflight_reconcile_and_housekeeping(
                WORKSPACE_DIR=td,
                _run_captured=lambda path, **kw: ran.append(Path(path).name),
                clean_stale_open_orders=lambda **k: (True, ""),
                current_environment=lambda: env,
                datetime=__import__("datetime"),
                load_trackers=lambda: {},
                os=os,
                reconcile_pending_orders=lambda **k: (True, set()),
            )
            self.assertIsNotNone(res2)
            self.assertEqual(ran, ["news_sentiment_harvester.py"])

    def test_update_factor_library_snapshot_skips_when_fresh(self):
        fake = types.ModuleType("factor_library")
        fake.CALLS = []
        fake.update_factor_library = lambda: fake.CALLS.append(1)

        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            data_dir.mkdir()
            snap_file = data_dir / "factor_library_snapshot.json"
            snap_file.write_text(json.dumps({"timestamp": int(time.time()), "instruments": [{"instId": "BTC-USDT-SWAP"}]}), encoding="utf-8")

            with patch.dict(sys.modules, {"factor_library": fake}):
                brain_snapshots.update_factor_library_snapshot(WORKSPACE_DIR=td, os=os, sys=sys)
                self.assertEqual(fake.CALLS, [])

                stale_ts = time.time() - 300.0
                os.utime(snap_file, (stale_ts, stale_ts))
                brain_snapshots.update_factor_library_snapshot(WORKSPACE_DIR=td, os=os, sys=sys)
                self.assertEqual(fake.CALLS, [1])

    def test_load_factor_snapshot_index_and_cached_package_assembly(self):
        with tempfile.TemporaryDirectory() as td:
            snap_path = os.path.join(td, "factor_library_snapshot.json")
            entry = {
                "instId": "BTC-USDT-SWAP",
                "name": "BTC",
                "chg24h": 2.4,
                "composite_alpha_score": 48.5,
                "signal_recommendation": "LONG_BIAS",
                "trend_momentum": {
                    "adx_1h": 29.5,
                    "rsi_1h": 62.0,
                    "rsi_15m": 57.0,
                    "vwap_bias_pct": 0.45,
                    "macd_hist": 18.2,
                    "macd_accel": 4.1,
                },
                "volatility_channel": {"atr_1h": 640.0, "bb_width_1h": 2.3},
                "volume_money_flow": {
                    "taker_net_usd": "120.5万 U",
                    "cvd_5m_usd": 450000.0,
                    "cvd_1h_usd": 2100000.0,
                    "taker_buy_sell_ratio": 1.21,
                },
                "microstructure": {
                    "bid_px": 94990.0,
                    "ask_px": 95010.0,
                    "spread_bps": 2.1,
                    "obi_pct": 14.0,
                    "obi_robust_pct": 11.0,
                },
                "smart_money_derivatives": {
                    "available": True,
                    "weighted_long_pct": 63.5,
                    "smart_money_flow_usd": "85.0万 U",
                    "long_short_ratio": "1.74",
                    "funding_rate_pct": 0.01,
                    "oi_usd": "18.2亿 U",
                },
                "volume_profile": {"vwap_24h": 94600.0, "val": 93800.0, "vah": 95400.0, "vpvr_poc": 94500.0},
                "options_structure": {"available": True, "atm_iv_pct": 45.2},
            }
            Path(snap_path).write_text(
                json.dumps({"timestamp": int(time.time()), "instruments": [entry]}),
                encoding="utf-8",
            )

            idx = brain_packages.load_factor_snapshot_index(path=snap_path, max_age_seconds=300.0)
            self.assertIn("BTC-USDT-SWAP", idx)

            Path(snap_path).write_text(
                json.dumps({"timestamp": int(time.time()) - 500, "instruments": [entry]}),
                encoding="utf-8",
            )
            self.assertEqual(brain_packages.load_factor_snapshot_index(path=snap_path, max_age_seconds=300.0), {})

            item = {"instId": "BTC-USDT-SWAP", "name": "BTC", "ccy": "BTC", "type": "crypto", "precision": 1, "tier": "tier_1_bluechip", "sl_atr_mult": 1.6}
            prefetched = {
                "instId": "BTC-USDT-SWAP",
                "market_data_valid": True,
                "price": 95000.0,
                "bidPx": 94995.0,
                "askPx": 95005.0,
                "atr_1h": 650.0,
                "atr_15m": 220.0,
                "vol_ratio": 1.35,
                "obv_flow": "BULL_FLOW",
                "trend_1h_bullish": True,
                "trend_1h_bearish": False,
                "trend_4h_bullish": True,
                "trend_4h_bearish": False,
                "vol24h": 54321.0,
            }
            pkg = brain_packages.build_package_from_cached_sources(
                item,
                prefetched_factor=prefetched,
                snapshot_entry=idx["BTC-USDT-SWAP"],
            )
            self.assertIsNotNone(pkg)
            self.assertEqual(pkg["data_quality"], "valid")
            self.assertEqual(pkg["market_regime"], "STRONG_TREND_BULL")
            self.assertEqual(pkg["composite_alpha_score"], 48.5)
            self.assertTrue(pkg["smart_money"]["available"])
            self.assertEqual(pkg["smart_money"]["weighted_long_pct"], 63.5)
            self.assertEqual(pkg["smart_money"]["net_flow_usdt"], "85.0万 U")
            self.assertIn("options_structure", pkg["quant_factors"])

            # Fail-closed fallback cases
            self.assertIsNone(brain_packages.build_package_from_cached_sources(item, prefetched_factor=None, snapshot_entry=entry))
            self.assertIsNone(brain_packages.build_package_from_cached_sources(item, prefetched_factor={**prefetched, "market_data_valid": False}, snapshot_entry=entry))
            self.assertIsNone(brain_packages.build_package_from_cached_sources(item, prefetched_factor=prefetched, snapshot_entry=None))

    def test_scan_risk_gates_forwards_prefetched_factors_when_supported(self):
        seen: dict = {}
        factors_list = [{"instId": "BTC-USDT-SWAP", "market_data_valid": True}]

        def modern_brain(pos_desc, active_pos_list, usdt_available=None, prefetched_factors=None):
            seen["prefetched"] = prefetched_factors
            return {"BTC-USDT-SWAP": {"decision": {"action": "WAIT"}}}

        kwargs = dict(
            active_pos_count=0,
            all_factors=factors_list,
            executed_actions=[],
            long_count=0,
            short_count=0,
            timestamp_full="2026-11-27 18:00:00",
            trackers={},
            usdt_available=1000.0,
            venue_position_span=venue_position_span,
            MAX_CONCURRENT_POSITIONS=6,
            _collect_okx_position_payloads=lambda *a, **k: [],
            effective_single_asset_margin=lambda u: 120.0,
            execute_ai_position_management=lambda *a, **k: None,
            execute_batch_ai_brain_cycle=modern_brain,
            is_circuit_breaker_active=lambda u: (False, ""),
            pool_is_trustworthy=lambda: True,
            pool_state=lambda: {},
            query_positions=lambda: (True, [], ""),
            read_cycle_health=lambda: {},
            real_pos_dict={},
            save_trackers=lambda t: None,
        )
        cs.scan_risk_gates_and_ai_brain(**kwargs)
        self.assertIs(seen.get("prefetched"), factors_list)

        # Legacy 3-arg callable still works without TypeError
        kwargs["execute_batch_ai_brain_cycle"] = lambda desc, pos, usdt_available=None: {"BTC": {"action": "WAIT"}}
        got = cs.scan_risk_gates_and_ai_brain(**kwargs)
        self.assertEqual(got[1], {"BTC": {"action": "WAIT"}})


class PromptSlimmingTests(unittest.TestCase):
    def test_altcoin_boilerplate_is_compacted_while_btc_full_tiers_stay_intact(self):
        btc = {
            "instId": "BTC-USDT-SWAP",
            "name": "BTC",
            "type": "crypto",
            "precision": 1,
            "data_quality": "valid",
            "price": 95000.0,
            "chg24h": 1.2,
            "bidPx": 94995.0,
            "askPx": 95005.0,
            "atr_1h": 600.0,
            "macro_4h": "4H_MACRO_BULL",
            "structure_1h": "1H_SWING_BULL",
            "smart_money": {
                "available": True,
                "weighted_long_pct": 61.0,
                "net_flow_usdt": "42.0万 U",
                "avg_long_entry": "--",
                "avg_short_entry": "--",
                "top_win_rate": "--",
            },
            "quant_factors": {
                "options_structure": {
                    "available": True,
                    "atm_iv_pct": 44.1,
                    "risk_reversal_25d_pct": 1.8,
                    "put_call_oi_ratio": 0.72,
                    "expiry": "261225",
                    "max_pain_price": "94000",
                },
                "smart_money_derivatives": {
                    "basis_annualized_pct": 8.2,
                    "loan_rate_usdt": 1.5,
                },
                "trend_momentum": {},
                "volume_money_flow": {},
                "microstructure": {},
                "volume_profile": {},
            },
        }
        sol = {
            "instId": "SOL-USDT-SWAP",
            "name": "SOL",
            "type": "crypto",
            "precision": 2,
            "data_quality": "valid",
            "price": 210.0,
            "chg24h": -0.5,
            "bidPx": 209.9,
            "askPx": 210.1,
            "atr_1h": 3.5,
            "macro_4h": "4H_MACRO_RANGE",
            "structure_1h": "1H_SWING_CHOP",
            "smart_money": {
                "available": True,
                "weighted_long_pct": 58.0,
                "net_flow_usdt": "5.0万 U",
                "avg_long_entry": "--",
                "avg_short_entry": "--",
                "top_win_rate": "--",
            },
            "quant_factors": {
                "options_structure": {"available": False},
                "smart_money_derivatives": {"basis_annualized_pct": "--", "loan_rate_usdt": "--"},
                "trend_momentum": {},
                "volume_money_flow": {},
                "microstructure": {},
                "volume_profile": {},
            },
        }

        missing = "/tmp/astra-v890-prompt-test-none"
        rendered = brain_prompt.construct_full_market_prompt(
            [btc, sol],
            current_time_str="2026-11-27 18:00:00",
            usdt_available=4000.0,
            safe_float=lambda v, d=0.0: float(v if v is not None else d),
            sl_atr_mult_for=lambda p: 1.8,
            build_risk_budget_text=lambda u: "RISK_BUDGET",
            active_profile=lambda: {
                "name": "测试",
                "pipelines": {"trading_user": [{"id": "m", "title": "m", "enabled": True, "content": "{{market_matrix}}"}]},
            },
            apply_module_layout=lambda *a, **k: k["context"]["market_matrix"],
            system_version="8.9.0",
            ai_memory_md_file=missing,
            ai_memory_file=missing,
            news_sentiment_file=missing,
            max_leverage=12.0,
            min_leverage=6.0,
            max_scale_in_count=2,
            min_scale_in_confidence=70,
            max_margin_equity_ratio=0.35,
        )

        # BTC full option & T2 lines remain intact
        self.assertIn("平值IV=44.1%", rendered)
        self.assertIn("最大痛点(MaxPain)=94000", rendered)
        self.assertIn("T2 期限与资金成本: 季度基差年化=8.2% | 杠杆借贷利率=1.5%", rendered)

        # SOL empty option / T2 / SmartMoney `--` boilerplate is eliminated
        self.assertIn("- 🎯 T1.5 期权结构: 无期权市场", rendered)
        self.assertNotIn("该标的无期权市场", rendered)
        sol_section = rendered.split("【SOL (SOL-USDT-SWAP)】", 1)[1]
        self.assertNotIn("T2 期限与资金成本", sol_section)
        self.assertIn("加权做多占比=58.0% | 5M主动吃单净流=5.0万 U", sol_section)
        self.assertNotIn("多头均价=--", sol_section)
        self.assertNotIn("空头均价=--", sol_section)


if __name__ == "__main__":
    unittest.main()
