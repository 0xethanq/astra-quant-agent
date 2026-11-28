"""回归测试：LLM 覆盖下的止损冷却硬闸门、归一化 MACD 加速度透传、智能下单阈值与 R:R 对齐。"""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.trader import brackets, entry_execution, order_submit


def _run_entry_scan(*, all_factors, brain_cache, trackers=None, evaluate_fn=None, pyramiding_fn=None):
    submits = []
    actions = []
    sig = inspect.signature(entry_execution.execute_entry_scan)
    kw = {
        "all_factors": all_factors,
        "brain_cache": brain_cache,
        "cb_active": False,
        "entries_blocked": False,
        "executed_actions": actions,
        "pending_inst_ids": set(),
        "trackers": trackers if trackers is not None else {},
        "usdt_available": 1000.0,
        "ASSET_MARGIN_CAP": 600.0,
        "reserved_long_count": 0,
        "reserved_short_count": 0,
        "reserved_slot_count": 0,
        "ASSET_CLASS_PROFILES": {"crypto": {"max_leverage": 10, "default_leverage": 5, "sl_atr_mult": 1.8}},
        "MAX_CONCURRENT_POSITIONS": 4,
        "MAX_LEVERAGE": 10,
        "MAX_SAME_DIRECTION_POSITIONS": 3,
        "MAX_SCALE_IN_COUNT": 1,
        "MIN_ENTRY_CONFIDENCE": 68.0,
        "MIN_LEVERAGE": 1,
        "MIN_SCALE_IN_CONFIDENCE": 75.0,
        "MIN_SCALE_IN_PROFIT_RATIO": 0.008,
        "build_order_intent": lambda *a, **k: ("buy", "long", {"confidence": k.get("ai_conf", 90.0), "intent_id": "test"}),
        "clamp_ai_leverage": lambda lev, *a, **k: (float(lev or 5.0), False),
        "entry_action_message": lambda *a, **k: "ok",
        "entry_failure_message": lambda *a, **k: "fail",
        "equity_margin_cap": lambda total_eq, ratio=0.5: 1000.0,
        "evaluate_asset_signal": evaluate_fn or (lambda item: (70, "HOLD", [], "T", "desc")),
        "instrument_profile": lambda f, asset_type=None: {"ctVal": 0.01, "minSz": 0.01, "precision": 1, "lever": 5},
        "is_tradfi_market_liquid": lambda *a, **k: (True, ""),
        "load_adaptive_config": lambda: {"mode": "normal"},
        "max_size_within_margin": lambda *a, **k: 10.0,
        "normalize_bracket_prices": brackets.normalize_bracket_prices,
        "notify_trade_open": lambda *a, **k: None,
        "order_margin_gate": lambda *a, **k: (True, float(k.get("margin", 50.0)), ""),
        "pyramiding_gate": pyramiding_fn or (lambda **k: (False, False)),
        "quantize_size": lambda *a, **k: float(a[0] if a else 0.05),
        "resolve_entry_prices": lambda *a, **k: (90000.0, 93000.0, 88500.0),
        "save_trackers": lambda t: None,
        "size_for_decision": lambda *a, **k: 0.05,
        "submit_protected_limit_order": lambda *a, **k: (submits.append((a, k)) or (True, "ok")),
        "trade_open_kwargs": lambda *a, **k: {},
        "venue_executed_facts": lambda *a, **k: (50.0, 4500.0),
    }
    assert set(kw) == set(sig.parameters)
    entry_execution.execute_entry_scan(**kw)
    return submits, actions


def _sample_factor(**extra):
    base = {
        "instId": "BTC-USDT-SWAP",
        "name": "BTC",
        "type": "crypto",
        "price": 90000.0,
        "atr": 900.0,
        "atr_1h": 900.0,
        "precision": 1,
        "ctVal": 0.01,
        "minSz": 0.01,
        "sz": 0.05,
        "leverage": 5,
        "trend_4h": "UPTREND",
        "trend_1h": "UPTREND",
        "bid_px": 89999.0,
        "ask_px": 90001.0,
        "position": None,
    }
    base.update(extra)
    return base


class CooldownAndRoutingGatesTests(unittest.TestCase):
    def test_llm_action_cannot_bypass_stop_cooldown(self):
        # 多头处于止损冷却中时，即使 LLM 给 BUY_LONG + conf=95，也必须拦住置 HOLD
        f = _sample_factor()
        brain_cache = {
            "BTC-USDT-SWAP": {
                "decision": {
                    "action": "BUY_LONG",
                    "confidence": 95,
                    "entry_price": 90000.0,
                    "tp_price": 93000.0,
                    "sl_price": 88500.0,
                    "leverage": 5,
                    "summary_reason": "test",
                }
            }
        }

        def eval_long_cooldown(item):
            item["_stop_cooldown"] = {"long": True, "short": False}
            return 80, "HOLD", ["cooling"], "冷却", "多头冷却"

        submits, _ = _run_entry_scan(
            all_factors=[f], brain_cache=brain_cache, evaluate_fn=eval_long_cooldown
        )
        self.assertEqual(submits, [])
        self.assertTrue(entry_execution.ENTRY_DIAGNOSTICS)
        self.assertIn("风控冷却拦截", entry_execution.ENTRY_DIAGNOSTICS[-1]["reason"])

        # 反向控制：只有空头在冷却时，BUY_LONG 正常放行
        f2 = _sample_factor()

        def eval_short_only_cooldown(item):
            item["_stop_cooldown"] = {"long": False, "short": True}
            return 80, "BUY_LONG", [], "顺势", "多头放行"

        submits2, _ = _run_entry_scan(
            all_factors=[f2], brain_cache=brain_cache, evaluate_fn=eval_short_only_cooldown
        )
        self.assertEqual(len(submits2), 1)

    def test_resolve_effective_order_mode_tighter_thresholds_and_spread_guard(self):
        self.assertEqual(
            brackets.resolve_effective_order_mode(
                "smart", planned_px=99.75, market_px=100.0, is_long=True, confidence=75.0
            ),
            "limit",
        )
        self.assertEqual(
            brackets.resolve_effective_order_mode(
                "smart", planned_px=99.85, market_px=100.0, is_long=True, confidence=75.0
            ),
            "market",
        )
        self.assertEqual(
            brackets.resolve_effective_order_mode(
                "smart", planned_px=99.5, market_px=100.0, is_long=True, confidence=85.0
            ),
            "market",
        )
        self.assertEqual(
            brackets.resolve_effective_order_mode(
                "smart", planned_px=99.1, market_px=100.0, is_long=True, confidence=85.0
            ),
            "limit",
        )
        self.assertEqual(
            brackets.resolve_effective_order_mode(
                "smart", planned_px=99.9, market_px=100.0, is_long=True, confidence=90.0, spread_pct=0.0020
            ),
            "limit",
        )

    def test_order_submit_does_not_clamp_below_80_conf_rr_floor(self):
        src = Path(order_submit.__file__).read_text(encoding="utf-8")
        self.assertIn("COUNTER_4H_MIN_CONFIDENCE", src)
        self.assertIn("1.2 if _ai_conf >= _high_conf_gate else None", src)
        self.assertIn("1.2 if _ai_conf >= _high_conf_gate else 0.0", src)

    def test_entry_execution_reads_normalized_macd_accel_pct_and_flat_quadrant(self):
        f = _sample_factor(
            macd_accel=90.0,  # 归一化 = 90 / 90000 * 100 = +0.10%
            oi_price_quadrant="LONG_LIQUIDATION",
            position={
                "pos": "1.0",
                "side": "long",
                "avgPx": "88000.0",
                "upl": 20.0,
                "uplRatio": "0.02",
                "margin": "100.0",
            },
        )
        brain_cache = {
            "BTC-USDT-SWAP": {
                "decision": {
                    "action": "BUY_LONG",
                    "confidence": 90,
                    "entry_price": 90000.0,
                    "tp_price": 93000.0,
                    "sl_price": 88500.0,
                    "leverage": 5,
                    "summary_reason": "test",
                }
            }
        }
        captured = []

        def fake_pyramiding(**kwargs):
            captured.append((kwargs.get("c_accel"), kwargs.get("oi_quadrant")))
            return False, False

        submits, _ = _run_entry_scan(
            all_factors=[f],
            brain_cache=brain_cache,
            trackers={"BTC-USDT-SWAP_long": {"scale_count": 0, "trailingStopPx": 88500.0}},
            pyramiding_fn=fake_pyramiding,
        )
        self.assertEqual(submits, [])
        self.assertEqual(len(captured), 1)
        self.assertAlmostEqual(captured[0][0], 0.1, places=4)
        self.assertEqual(captured[0][1], "LONG_LIQUIDATION")


if __name__ == "__main__":
    unittest.main()
