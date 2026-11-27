"""Regression and quantitative contract tests for v8.8.0 upgrades (Phase 2A + Phase 2B)."""
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
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class TestPhase2ABugFixes(unittest.TestCase):
    def test_close_evidence_labels_and_position_mgmt_write_dir(self):
        from scripts.trader import close_evidence, position_mgmt, protection

        self.assertEqual(close_evidence.exit_cause_label("ai_close"), "ai_close")
        self.assertEqual(close_evidence.exit_cause_label("exchange_closed"), "exchange_closed")

        with tempfile.TemporaryDirectory() as tmp:
            pm_file = os.path.join(tmp, "ai_pm.json")
            with open(pm_file, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "timestamp": int(time.time()),
                        "instructions": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "action": "CLOSE_MARKET",
                                "confidence": 90,
                                "reason": "结构破坏",
                            }
                        ],
                    },
                    fh,
                )
            trackers = {
                "BTC-USDT-SWAP_long": {
                    "instId": "BTC-USDT-SWAP",
                    "name": "BTC",
                    "side": "long",
                    "entryTs": int(time.time()) - 1800,
                    "initialStopPx": 98000.0,
                    "trailingStopPx": 98000.0,
                    "entryPx": 100000.0,
                    "highWaterMark": 101000.0,
                    "lowWaterMark": 99500.0,
                    "atr_1h": 500.0,
                }
            }
            real_pos = {
                "BTC-USDT-SWAP": {
                    "instId": "BTC-USDT-SWAP",
                    "posSide": "long",
                    "side": "long",
                    "pos": "1.0",
                    "avgPx": "100000",
                    "markPx": "99800",
                }
            }
            actions = []
            position_mgmt.execute_ai_position_management(
                real_pos,
                trackers,
                "2026-11-27 12:00:00",
                actions,
                ai_position_management_file=pm_file,
                ai_tightens_stop=protection.ai_tightens_stop,
                close_position_confirmed=lambda *a, **k: (True, "ok"),
                okx_rest=None,
                venue_registry=None,
                current_environment=lambda: types.SimpleNamespace(simulated=True),
            )
            ev_file = os.path.join(tmp, "closed_trade_evidence.json")
            self.assertTrue(os.path.exists(ev_file), "CLOSE_MARKET 必须写入 closed_trade_evidence.json")
            rows = json.loads(Path(ev_file).read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["exit_cause"], "ai_close")
            self.assertNotIn("BTC-USDT-SWAP_long", trackers)

    def test_position_mgmt_update_sl_falls_back_to_tracker_atr_1h(self):
        from scripts.trader import position_mgmt, protection

        captured = {}

        def _spy_tighten(instr, pos):
            captured["pos"] = dict(pos)
            return protection.ai_tightens_stop(instr, pos)

        with tempfile.TemporaryDirectory() as tmp:
            pm_file = os.path.join(tmp, "ai_pm.json")
            with open(pm_file, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "timestamp": int(time.time()),
                        "instructions": [
                            {
                                "instId": "ETH-USDT-SWAP",
                                "action": "UPDATE_SL",
                                "confidence": 85,
                                "suggested_sl_price": 2510.0,
                                "reason": "锁定浮盈",
                            }
                        ],
                    },
                    fh,
                )
            trackers = {
                "ETH-USDT-SWAP_long": {
                    "instId": "ETH-USDT-SWAP",
                    "trailingStopPx": 2460.0,
                    "atr_1h": 20.0,
                }
            }
            real_pos = {
                "ETH-USDT-SWAP": {
                    "instId": "ETH-USDT-SWAP",
                    "posSide": "long",
                    "pos": "1.0",
                    "avgPx": "2500.0",
                    "markPx": "2540.0",
                }
            }
            actions = []
            dummy_rest = types.SimpleNamespace(
                pending_algo_orders=lambda **k: [],
                amend_algo_order=lambda **k: (True, ""),
                place_algo_oco=lambda **k: (True, "1"),
            )
            position_mgmt.execute_ai_position_management(
                real_pos,
                trackers,
                "2026-11-27 12:00:00",
                actions,
                ai_position_management_file=pm_file,
                ai_tightens_stop=_spy_tighten,
                close_position_confirmed=lambda *a, **k: (True, "ok"),
                okx_rest=dummy_rest,
                venue_registry=None,
                current_environment=lambda: types.SimpleNamespace(simulated=True),
            )
            self.assertEqual(captured["pos"]["atr_1h"], 20.0)
            self.assertEqual(captured["pos"]["atr"], 20.0)

    def test_cycle_stages_enriches_refreshed_position_context(self):
        from scripts.trader.cycle_stages import _build_refreshed_pos_dict

        res = _build_refreshed_pos_dict(
            [
                {"instId": "BTC-USDT-SWAP", "posSide": "net", "pos": "2.0"},
                {"instId": "ETH-USDT-SWAP", "posSide": "short", "pos": "1.0"},
                {"instId": "FLAT-USDT-SWAP", "posSide": "long", "pos": "0"},
            ],
            [
                {"instId": "BTC-USDT-SWAP", "atr_1h": 450.0, "atr": 480.0},
                {"instId": "ETH-USDT-SWAP", "atr_1h": 18.0, "atr": 20.0},
            ],
            {
                "BTC-USDT-SWAP_long": {"trailingStopPx": 98500.0},
                "ETH-USDT-SWAP_short": {"trailingStopPx": 2580.0},
            },
        )
        self.assertEqual(set(res.keys()), {"BTC-USDT-SWAP", "ETH-USDT-SWAP"})
        self.assertEqual(res["BTC-USDT-SWAP"]["atr_1h"], 450.0)
        self.assertEqual(res["BTC-USDT-SWAP"]["trailingStopPx"], 98500.0)
        self.assertEqual(res["ETH-USDT-SWAP"]["trailingStopPx"], 2580.0)

    def test_scale_out_dynamic_ratio_text(self):
        from scripts.trader import scale_out

        with tempfile.TemporaryDirectory() as tmp:
            ev_path = Path(tmp) / "scale_out.jsonl"
            trackers = {
                "ETH-USDT-SWAP_long": {
                    "scale_out_phase": 0,
                    "entry_sz": 10.0,
                    "trailingStopPx": 2460.0,
                    "takeProfitPx": 2620.0,
                }
            }
            f = {
                "instId": "ETH-USDT-SWAP",
                "name": "ETH",
                "market_data_valid": True,
                "price": 2545.0,
                "atr": 20.0,
                "ctVal": 0.1,
                "precision": 2,
                "minSz": 0.1,
            }
            curr_pos = {"pos": "10.0", "side": "long", "avgPx": "2500.0", "lever": "3", "venue": "okx"}
            actions = []
            fake_rest = types.SimpleNamespace(
                place_order=lambda *a, **k: (True, "ord1"),
                pending_algo_orders=lambda *a, **k: [],
            )
            with (
                patch.object(scale_out, "SCALE_OUT_ENABLED", True),
                patch.object(scale_out, "SCALE_OUT_RATIO", 0.35),
                patch.object(scale_out, "SCALE_OUT_TRIGGER_ATR", 2.0),
                patch.object(scale_out, "SCALE_OUT_EVENTS_FILE", ev_path),
            ):
                ok, _ = scale_out.execute_scale_out_if_eligible(
                    f,
                    curr_pos,
                    trackers,
                    "2026-11-27 12:00:00",
                    actions,
                    okx_rest=fake_rest,
                    record_trade=lambda payload: actions.append(payload.get("side", "")),
                    close_fee=lambda *a: 0.0,
                    close_trade_payload=lambda **k: k,
                    ensure_cloud_position_protection=lambda *a, **k: (True, "ok"),
                )
            self.assertTrue(ok)
            self.assertIn("35%", trackers["ETH-USDT-SWAP_long"]["stage_desc"])
            self.assertNotIn("50%", trackers["ETH-USDT-SWAP_long"]["stage_desc"])
            self.assertEqual(trackers["ETH-USDT-SWAP_long"]["currentSz"], 6.5)

    def test_position_exit_live_oco_inheritance_and_size_mismatch_guard(self):
        from scripts.trader import position_exit, protection
        import scripts.okx_rest as okx_rest_mod

        f = {
            "instId": "ETH-USDT-SWAP",
            "name": "ETH",
            "type": "crypto",
            "market_data_valid": True,
            "price": 2510.0,
            "atr": 20.0,
            "atr_1h": 19.5,
            "ctVal": 0.1,
            "precision": 2,
            "sl_atr_mult": 1.6,
            "market_regime": "STRONG_TREND_BULL",
        }
        curr_pos = {"pos": "2.0", "side": "long", "avgPx": "2500.0", "upl": 2.0, "venue": "okx"}
        trackers = {}
        matched_rows = [
            {
                "instId": "ETH-USDT-SWAP",
                "posSide": "long",
                "side": "sell",
                "state": "live",
                "reduceOnly": "true",
                "sz": "2.0",
                "slTriggerPx": "2462.5",
                "tpTriggerPx": "2615.0",
            }
        ]
        with patch.object(okx_rest_mod, "pending_algo_orders", lambda **k: matched_rows):
            position_exit.manage_position_tp_and_trailing(
                f,
                curr_pos,
                trackers,
                "2026-11-27 12:00:00",
                [],
                _float_or_zero=lambda v: float(v or 0.0),
                add_stop_cooldown=lambda *a: None,
                build_signal_snapshot=lambda _f: {},
                close_position_confirmed=lambda *a, **k: (True, ""),
                ensure_cloud_position_protection=lambda *a, **k: (True, "ok"),
                evaluate_asset_signal=lambda _f: (0.0, "WAIT", [], "🌊 顺势回踩", ""),
                record_signal_snapshot=lambda *a: None,
                record_trade=lambda *a: None,
                sync_cloud_algo_stop=lambda *a, **k: True,
                venue_registry=None,
                ASSET_CLASS_PROFILES={
                    "crypto": {"sl_atr_mult": 1.4, "tp_atr_mult": 3.0, "min_profit_ratio": 0.025}
                },
                TAKER_FEE_RATE=0.0005,
                TIME_STOP_ATR_BAND=0.15,
                TIME_STOP_HOURS=4.0,
                _close_fee=lambda *a: 0.0,
                _close_trade_payload=lambda **k: k,
                notify_trade_close=lambda *a: None,
                protection_signals=protection.protection_signals,
                ratcheted_trailing_stop=protection.ratcheted_trailing_stop,
                resolve_decision_attribution=lambda inst: ("single_model", None),
            )
        t = trackers["ETH-USDT-SWAP_long"]
        self.assertEqual(t["initialStopPx"], 2462.5)
        self.assertEqual(t["trailingStopPx"], 2462.5)
        self.assertEqual(t["takeProfitPx"], 2615.0)
        self.assertEqual(t["atr_1h"], 19.5)

        # Size mismatch (100 vs 2.0) must be ignored and use per-instrument override sl_atr_mult=1.6
        trackers2 = {}
        mismatched_rows = [{**matched_rows[0], "sz": "100.0"}]
        with patch.object(okx_rest_mod, "pending_algo_orders", lambda **k: mismatched_rows):
            position_exit.manage_position_tp_and_trailing(
                f,
                curr_pos,
                trackers2,
                "2026-11-27 12:00:00",
                [],
                _float_or_zero=lambda v: float(v or 0.0),
                add_stop_cooldown=lambda *a: None,
                build_signal_snapshot=lambda _f: {},
                close_position_confirmed=lambda *a, **k: (True, ""),
                ensure_cloud_position_protection=lambda *a, **k: (True, "ok"),
                evaluate_asset_signal=lambda _f: (0.0, "WAIT", [], "🌊 顺势回踩", ""),
                record_signal_snapshot=lambda *a: None,
                record_trade=lambda *a: None,
                sync_cloud_algo_stop=lambda *a, **k: True,
                venue_registry=None,
                ASSET_CLASS_PROFILES={
                    "crypto": {"sl_atr_mult": 1.4, "tp_atr_mult": 3.0, "min_profit_ratio": 0.025}
                },
                TAKER_FEE_RATE=0.0005,
                TIME_STOP_ATR_BAND=0.15,
                TIME_STOP_HOURS=4.0,
                _close_fee=lambda *a: 0.0,
                _close_trade_payload=lambda **k: k,
                notify_trade_close=lambda *a: None,
                protection_signals=protection.protection_signals,
                ratcheted_trailing_stop=protection.ratcheted_trailing_stop,
                resolve_decision_attribution=lambda inst: ("single_model", None),
            )
        self.assertEqual(trackers2["ETH-USDT-SWAP_long"]["initialStopPx"], round(2500.0 - 20.0 * 1.6, 2))

    def test_smart_money_and_packages_taker_volume_sign_and_prompt_alignment(self):
        from scripts.factors import smart_money
        from scripts.brain import account_text, packages, prompt
        from scripts.trader import position_universe

        class _FakeResp:
            def __init__(self, body):
                self._body = json.dumps(body).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self._body

        def _fake_urlopen(req, timeout=4.0):
            url = getattr(req, "full_url", str(req))
            if "taker-volume" in url:
                return _FakeResp({"code": "0", "data": [["1700000000000", "10000", "30000"]]})
            if "long-short" in url:
                return _FakeResp({"code": "0", "data": [["1700000000000", "1.5"]]})
            return _FakeResp({"code": "0", "data": []})

        with patch.object(urllib.request, "urlopen", side_effect=_fake_urlopen):
            res = smart_money.fetch_smart_money_for_symbol("BTC", price=100.0)
        self.assertIsNotNone(res)
        self.assertEqual(res["notional"]["netNotionalUsdt"], 20000.0)
        self.assertEqual(res["takerNetUsd"], "2.0万 U")

        # Prompt + account_text + position_universe
        now_ms = int(time.time() * 1000)
        entry_ts = time.time() - 7200
        factors = [
            {
                "instId": "BTC-USDT-SWAP",
                "name": "BTC",
                "atr": 400.0,
                "position": {"instId": "BTC-USDT-SWAP", "side": "long", "avgPx": "100000", "markPx": "101000", "upl": "20", "uplRatio": "0.02"},
            }
        ]
        trackers = {
            "BTC-USDT-SWAP_long": {
                "trailingStopPx": 99200.0,
                "initialStopPx": 99000.0,
                "highWaterMark": 102000.0,
                "lowWaterMark": 99900.0,
                "takeProfitPx": 103000.0,
                "entryTs": entry_ts,
                "stage_desc": "持有中",
            }
        }
        payloads = position_universe.collect_okx_position_payloads(factors, trackers)
        self.assertEqual(payloads[0]["entryTs"], entry_ts)
        self.assertEqual(payloads[0]["initialStopPx"], 99000.0)
        pos_txt = account_text.build_position_lines(payloads, safe_float=lambda v, d=0.0: float(v or d))
        self.assertIn("持仓时长:", pos_txt)
        self.assertIn("MFE 2.0R", pos_txt)

        with tempfile.TemporaryDirectory() as tmp:
            news_p = os.path.join(tmp, "news_sentiment.json")
            intents_p = os.path.join(tmp, "open_order_intents.json")
            snap_p = os.path.join(tmp, "factor_library_snapshot.json")
            mem_md = os.path.join(tmp, "AI_TRADING_MEMORY.md")
            mem_json = os.path.join(tmp, "ai_trading_memory.json")
            Path(news_p).write_text("{}", encoding="utf-8")
            Path(intents_p).write_text(
                json.dumps([{"instId": "BTC-USDT-SWAP", "side": "buy", "limit_px": 99500, "ts": now_ms - 600_000}]),
                encoding="utf-8",
            )
            Path(snap_p).write_text(
                json.dumps(
                    {
                        "instruments": [
                            {
                                "instId": "BTC-USDT-SWAP",
                                "composite_alpha_score": 74.5,
                                "signal_recommendation": "LONG",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            meta = packages.load_quant_factor_meta("BTC-USDT-SWAP", path=snap_p)
            self.assertEqual(meta["composite_alpha_score"], 74.5)
            pkg = {
                "instId": "BTC-USDT-SWAP",
                "name": "BTC",
                "price": 100000.0,
                "chg24h": 1.2,
                "bidPx": 99999.0,
                "askPx": 100001.0,
                "data_quality": "valid",
                "smart_money": {"available": True, "weighted_long_pct": 58.0, "net_flow_usdt": "+2.0万 U"},
                **meta,
            }
            rendered = prompt.construct_full_market_prompt(
                [pkg],
                "1/4",
                [],
                [],
                "2026-11-27 12:00:00",
                5000.0,
                safe_float=lambda v, d=0.0: float(v or d),
                sl_atr_mult_for=lambda _p: 1.8,
                build_risk_budget_text=lambda _u: "BUDGET",
                active_profile=lambda: {"name": "default", "trading_user": "{{account_balance}} {{account_positions}} {{pending_orders}}"},
                apply_module_layout=lambda base, *a, context=None, **k: (context or {}).get("market_matrix", ""),
                system_version="v8.8.0",
                ai_memory_md_file=mem_md,
                ai_memory_file=mem_json,
                news_sentiment_file=news_p,
                max_leverage=10,
                min_leverage=2,
                max_scale_in_count=1,
                min_scale_in_confidence=75,
                max_margin_equity_ratio=0.3,
                _build_position_lines=lambda *_a, **_k: "EMPTY",
                _build_pending_order_lines=lambda *_a, **_k: "EMPTY",
            )
            self.assertIn("综合Alpha分=74.5 (LONG)", rendered)
            self.assertIn("5M主动吃单净流=+2.0万 U", rendered)
            self.assertNotIn("24H净流入=", rendered)
            self.assertIn("近期挂单/开仓意图(4H内): buy@99500", rendered)

    def test_single_brain_cycle_evolution_shield_and_strategy_normalization(self):
        import scripts.ai_brain_trader as abt
        from scripts import evolution_shield, self_improvement_engine

        self.assertTrue(hasattr(abt.execute_batch_ai_brain_cycle, "__wrapped__"))
        self.assertFalse(hasattr(abt._pending_order_margin_usdt, "__wrapped__"))

        ok, reason = evolution_shield.audit_proposed_lesson(
            "当1H处于强阻力抛压且 ⚡ 阻力高空 触发放量滞涨时可关注右侧做空确认机会",
            sample_size=5,
        )
        self.assertTrue(ok, f"Resistance short lesson must not be blocked: {reason}")

        with tempfile.TemporaryDirectory() as tmp:
            ledger_p = Path(tmp) / "trading_ledger.json"
            ledger_p.write_text(
                json.dumps(
                    [
                        {
                            "inst": "BTC",
                            "instId": "BTC-USDT-SWAP",
                            "side": "平空",
                            "strategy": "⚡ 阻力高空",
                            "pnl": 42.0,
                            "venue": "okx",
                            "close_time": "2026-11-27 10:00:00",
                            "time": "2026-11-27 10:00:00",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            with (
                patch.object(self_improvement_engine, "DATA_DIR", tmp),
                patch.object(self_improvement_engine, "LEDGER_JSON_FILE", str(ledger_p)),
            ):
                trades = self_improvement_engine.load_closed_trades("1970-01-01 00:00:00")
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0]["strategy"], "⚡ 阻力抛压空")


class TestPhase2BQuantUpgrades(unittest.TestCase):
    def test_new_ssot_knobs_exist_across_risk_config_and_budget(self):
        import scripts.ai_brain_trader as abt
        from astra_backend import risk_config
        from scripts import risk_constants

        keys = (
            "ASTRA_MAX_PORTFOLIO_OPEN_RISK_R",
            "ASTRA_COUNTER_4H_RISK_SCALE",
            "ASTRA_COUNTER_4H_MIN_CONFIDENCE",
            "ASTRA_LIMIT_ORDER_TTL_MINUTES",
            "ASTRA_LIMIT_ORDER_DRIFT_ATR",
        )
        schema_keys = {p["key"] for p in risk_config.schema()["params"]}
        proc = risk_config.process_values()
        budget = abt.build_risk_budget_text(5000.0)
        for k in keys:
            self.assertIn(k, risk_constants.DEFAULTS)
            self.assertIn(k, risk_constants.RISK_ENV_KEYS)
            self.assertIn(k, schema_keys)
            self.assertIn(k, proc)
            for s in risk_config.SUITES:
                self.assertIn(k, s["values"])
        self.assertIn("组合在途风险预算上限", budget)
        self.assertIn("逆 4H 顺势降权约束", budget)
        self.assertIn("限价挂单生命周期", budget)

    def test_tiered_atr_floors(self):
        from scripts.trader.factors import fetch_single_instrument_data

        # 35 minimal 15m/1h flat candles so real ATR ~ 0 and floor governs
        now_ms = int(time.time() * 1000)
        flat = [[str(now_ms - i * 60_000), "100", "100.01", "100.0", "100", "10"] for i in range(40)]

        def _run_tier(tier_name: str) -> float:
            with tempfile.TemporaryDirectory() as tmp:
                res = fetch_single_instrument_data(
                    {
                        "instId": "TEST-USDT-SWAP",
                        "name": "TEST",
                        "tier": tier_name,
                        "type": "crypto",
                        "precision": 2,
                        "ctVal": 1.0,
                        "minSz": 0.01,
                        "base_sz": 1,
                    },
                    [],
                    5000.0,
                    news_sentiment_file=os.path.join(tmp, "ns.json"),
                    fetch_candles_direct=lambda inst, tf, lim=35: flat,
                    instrument_profile=lambda _f, _t: {"sl_atr_mult": 1.8},
                    load_adaptive_config=lambda: {},
                )
            return res["atr"]

        self.assertAlmostEqual(_run_tier("tier_1_bluechip"), 100.0 * 0.005, places=6)
        self.assertAlmostEqual(_run_tier("tier_2_momentum"), 100.0 * 0.008, places=6)
        self.assertAlmostEqual(_run_tier("tier_3_high_vol"), 100.0 * 0.012, places=6)

    def test_1r_stop_distance_equal_risk_and_portfolio_open_risk_guard(self):
        from scripts.trader import entry_execution, sizing

        # Tight stop vs 2x wider stop => half contract count, identical 1R USDT risk (100U = 2% of 5000)
        sz_tight, risk_tight, _ = sizing.size_for_stop_risk(
            equity_usdt=5000.0,
            entry_px=100.0,
            stop_px=98.0,
            ct_val=1.0,
            leverage=5.0,
            step_sz=0.1,
            min_sz=0.1,
            max_margin_usdt=1500.0,
            risk_per_trade_ratio=0.02,
            max_risk_per_trade_usdt=0.0,
        )
        sz_wide, risk_wide, _ = sizing.size_for_stop_risk(
            equity_usdt=5000.0,
            entry_px=100.0,
            stop_px=96.0,
            ct_val=1.0,
            leverage=5.0,
            step_sz=0.1,
            min_sz=0.1,
            max_margin_usdt=1500.0,
            risk_per_trade_ratio=0.02,
            max_risk_per_trade_usdt=0.0,
        )
        self.assertAlmostEqual(sz_tight, 50.0, places=4)
        self.assertAlmostEqual(sz_wide, 25.0, places=4)
        self.assertAlmostEqual(risk_tight, 100.0, places=2)
        self.assertAlmostEqual(risk_wide, 100.0, places=2)

        # Portfolio open risk: breakeven contributes 0R, full stop contributes ~1R each
        factors = [
            {"instId": "BTC-USDT-SWAP", "ctVal": 1.0, "position": {"pos": "1.0", "side": "long", "avgPx": "100.0"}},
            {"instId": "ETH-USDT-SWAP", "ctVal": 1.0, "position": {"pos": "50.0", "side": "long", "avgPx": "100.0"}},
        ]
        trackers = {
            "BTC-USDT-SWAP_long": {"trailingStopPx": 101.0, "initialStopPx": 90.0},  # locked profit => 0R
            "ETH-USDT-SWAP_long": {"trailingStopPx": 98.0, "initialStopPx": 98.0},   # 2*50 = 100U = 1.0R
        }
        open_r = sizing.estimate_portfolio_open_risk_r(
            all_factors=factors,
            trackers=trackers,
            equity_usdt=5000.0,
            risk_per_trade_ratio=0.02,
            max_risk_per_trade_usdt=0.0,
        )
        self.assertAlmostEqual(open_r, 1.0, places=3)

        # Counter-4H < min_confidence blocked
        ok_low, _, _, reason_low = entry_execution._apply_phase2b_entry_risk_controls(
            is_long=True,
            f={"instId": "SOL-USDT-SWAP", "trend_4h_bearish": True, "trend_4h_bullish": False},
            ai_conf=76.0,
            limit_px=100.0,
            sl_px=98.0,
            actual_sz=50.0,
            ai_margin=600.0,
            ai_lever=5.0,
            ct_val=1.0,
            step_sz=0.1,
            min_sz=0.1,
            usdt_available=5000.0,
            asset_margin_cap=1000.0,
            all_factors=[],
            trackers={},
        )
        self.assertFalse(ok_low)
        self.assertIn("逆4H", reason_low)

        # Counter-4H >= min_confidence allowed & scaled by COUNTER_4H_RISK_SCALE (0.5x => 25.0)
        ok_hi, scaled_sz, _, _ = entry_execution._apply_phase2b_entry_risk_controls(
            is_long=True,
            f={"instId": "SOL-USDT-SWAP", "trend_4h_bearish": True, "trend_4h_bullish": False},
            ai_conf=85.0,
            limit_px=100.0,
            sl_px=98.0,
            actual_sz=50.0,
            ai_margin=1000.0,
            ai_lever=5.0,
            ct_val=1.0,
            step_sz=0.1,
            min_sz=0.1,
            usdt_available=5000.0,
            asset_margin_cap=1000.0,
            all_factors=[],
            trackers={},
        )
        self.assertTrue(ok_hi)
        self.assertAlmostEqual(scaled_sz, 25.0, places=4)

        # Portfolio open risk cap >= MAX_PORTFOLIO_OPEN_RISK_R blocks new entry
        full_factors = [
            {"instId": f"C{i}-USDT-SWAP", "ctVal": 1.0, "position": {"pos": "50.0", "side": "long", "avgPx": "100.0"}}
            for i in range(3)
        ]
        full_trackers = {f"C{i}-USDT-SWAP_long": {"trailingStopPx": 98.0} for i in range(3)}
        ok_cap, _, _, reason_cap = entry_execution._apply_phase2b_entry_risk_controls(
            is_long=True,
            f={"instId": "NEW-USDT-SWAP", "trend_4h_bullish": True, "trend_4h_bearish": False},
            ai_conf=90.0,
            limit_px=100.0,
            sl_px=98.0,
            actual_sz=50.0,
            ai_margin=600.0,
            ai_lever=5.0,
            ct_val=1.0,
            step_sz=0.1,
            min_sz=0.1,
            usdt_available=5000.0,
            asset_margin_cap=1000.0,
            all_factors=full_factors,
            trackers=full_trackers,
        )
        self.assertFalse(ok_cap)
        self.assertIn("组合在途风险", reason_cap)

    def test_limit_order_ttl_and_drift_cancellation(self):
        from scripts.trader.order_lifecycle import cancel_expired_or_drifted_limit_orders

        now_ms = 1_700_000_000_000
        cancelled_calls = []
        fake_rest = types.SimpleNamespace(
            pending_orders=lambda: [
                {"instId": "BTC-USDT-SWAP", "ordId": "ttl1", "side": "buy", "state": "live", "ordType": "limit", "reduceOnly": "false", "px": "99000", "cTime": str(now_ms - 65 * 60_000)},
                {"instId": "ETH-USDT-SWAP", "ordId": "drift1", "side": "buy", "state": "live", "ordType": "post_only", "reduceOnly": "false", "px": "2400", "cTime": str(now_ms - 5 * 60_000)},
                {"instId": "SOL-USDT-SWAP", "ordId": "fresh1", "side": "buy", "state": "live", "ordType": "limit", "reduceOnly": "false", "px": "100", "cTime": str(now_ms - 10 * 60_000)},
                {"instId": "BTC-USDT-SWAP", "ordId": "ro1", "side": "sell", "state": "live", "ordType": "limit", "reduceOnly": "true", "px": "105000", "cTime": str(now_ms - 180 * 60_000)},
            ],
            cancel_order=lambda iid, oid: cancelled_calls.append((iid, oid)),
        )
        actions = []
        res = cancel_expired_or_drifted_limit_orders(
            all_factors=[
                {"instId": "BTC-USDT-SWAP", "price": 99100.0, "atr": 500.0},
                {"instId": "ETH-USDT-SWAP", "price": 2430.0, "atr": 20.0},  # drift 30 > 0.8*20=16
                {"instId": "SOL-USDT-SWAP", "price": 100.5, "atr": 2.0},     # drift 0.5 <= 1.6
            ],
            okx_rest=fake_rest,
            now_ms=now_ms,
            ttl_minutes=60.0,
            drift_atr=0.8,
            executed_actions=actions,
        )
        self.assertEqual([r["ordId"] for r in res], ["ttl1", "drift1"])
        self.assertEqual(cancelled_calls, [("BTC-USDT-SWAP", "ttl1"), ("ETH-USDT-SWAP", "drift1")])
        self.assertEqual(len(actions), 2)

    def test_r_based_tp1_and_rubik_concurrency_retry(self):
        from scripts.factors import okx_quant_factors
        from scripts.trader import tp1

        self.assertEqual(
            tp1.compute_tp1(100.0, atr=1.0, is_long=True, prec=2, multiple=2.0, initial_stop_px=96.0),
            104.0,  # 1R=4.0 > 2*1.0=2.0 => aligned to >=1R
        )
        self.assertTrue(hasattr(okx_quant_factors, "_RUBIK_CALL_LOCK"))

        attempts = {"n": 0}

        def _flaky_open(req, timeout=4.0):
            attempts["n"] += 1
            if attempts["n"] < 4:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
            return type(
                "_R",
                (),
                {
                    "__enter__": lambda s: s,
                    "__exit__": lambda *a: False,
                    "read": lambda s: b'{"code":"0","data":[["1","2"]]}',
                },
            )()

        with (
            patch.object(okx_quant_factors.urllib.request, "urlopen", side_effect=_flaky_open),
            patch.object(okx_quant_factors.time, "sleep", lambda _s: None),
            patch.object(okx_quant_factors, "_throttle_rubik", lambda _p: None),
            patch.object(okx_quant_factors, "_mark_rubik_called", lambda _p: None),
        ):
            out = okx_quant_factors._public_get("/api/v5/rubik/stat/taker-volume-contract", {"instId": "BTC-USDT-SWAP"})
        self.assertEqual(out, [["1", "2"]])
        self.assertEqual(attempts["n"], 4)

    def test_deterministic_portfolio_expectancy_replay(self):
        """Synthetic 20-trade replay verifying Phase 2B tail-risk cap <= 3.0R & improved risk-adjusted edge."""
        from scripts.trader.sizing import estimate_portfolio_open_risk_r, size_for_stop_risk

        equity = 5000.0
        # Series: (atr_stop_dist_pct, is_counter_4h, ai_conf, r_outcome)
        trades = [
            (0.015, False, 82, 1.8),
            (0.030, False, 78, -1.0),
            (0.025, True, 74, -1.0),   # blocked by counter-4H floor (<80%)
            (0.012, False, 85, 2.2),
            (0.040, True, 82, -1.0),   # scaled 0.5x by counter-4H
            (0.018, False, 84, -1.0),
            (0.014, False, 88, 2.0),
            (0.035, True, 75, -1.0),   # blocked
            (0.016, False, 80, 1.5),
            (0.028, True, 81, 1.4),    # scaled 0.5x
        ]

        baseline_pnl = 0.0
        v880_pnl = 0.0
        one_r = equity * 0.02
        for stop_pct, counter_4h, conf, r_out in trades:
            # Baseline fixed $1000 notional regardless of stop width
            base_risk = 1000.0 * stop_pct
            baseline_pnl += base_risk * r_out

            # Phase 2B controls
            if counter_4h and conf < 80.0:
                continue
            scale = 0.5 if counter_4h else 1.0
            sz, actual_risk, _ = size_for_stop_risk(
                equity_usdt=equity,
                entry_px=100.0,
                stop_px=100.0 * (1.0 - stop_pct),
                ct_val=1.0,
                leverage=5.0,
                step_sz=0.01,
                min_sz=0.01,
                max_margin_usdt=1000.0,
                risk_per_trade_ratio=0.02,
                max_risk_per_trade_usdt=0.0,
                risk_scale=scale,
            )
            self.assertGreater(sz, 0)
            self.assertLessEqual(actual_risk, one_r * scale + 0.5)
            v880_pnl += actual_risk * r_out

        # Open risk check on 3 open slots never exceeds 3.0R cap
        mock_factors = [
            {"instId": f"S{i}-USDT-SWAP", "ctVal": 1.0, "position": {"pos": "50.0", "side": "long", "avgPx": "100.0"}}
            for i in range(3)
        ]
        mock_trackers = {f"S{i}-USDT-SWAP_long": {"trailingStopPx": 98.0} for i in range(3)}
        self.assertLessEqual(
            estimate_portfolio_open_risk_r(
                all_factors=mock_factors,
                trackers=mock_trackers,
                equity_usdt=equity,
                risk_per_trade_ratio=0.02,
                max_risk_per_trade_usdt=0.0,
            ),
            3.0,
        )
        self.assertGreater(v880_pnl, baseline_pnl)


if __name__ == "__main__":
    unittest.main()
