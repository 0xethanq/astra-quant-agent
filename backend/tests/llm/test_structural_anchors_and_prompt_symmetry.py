"""回归测试：LLM 主脑真实结构锚定注入、多空对等体制门禁、decisions 回退与投委会口径对齐。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ai_brain_trader as abt
from astra_backend.council.consensus import calculate_symbol_consensus, format_consensus_docket
from astra_backend.council.debate import _load_council_risk_bounds
from scripts.brain.decisions import assemble_decision_cache
from scripts.factors.okx_quant_factors import compute_structural_anchors
from scripts.prompt_library import active_profile


def _candle_series(n: int, *, start: float = 100.0, step: float = 0.5) -> list[list[float]]:
    rows = []
    for i in range(n):
        c = start + i * step
        rows.append([1_700_000_000_000 + i * 3_600_000, c - 0.3, c + 0.8, c - 0.8, c, 1000.0 + i * 20.0])
    return list(reversed(rows))  # newest first


class StructuralAnchorsAndPromptSymmetryTests(unittest.TestCase):
    def test_compute_structural_anchors_returns_emas_swings_and_candidate_zones(self):
        raw_1h = _candle_series(65, start=90.0, step=0.4)
        ordered = list(reversed(raw_1h))
        closes_1h = [r[4] for r in ordered]
        highs_1h = [r[2] for r in ordered]
        lows_1h = [r[3] for r in ordered]
        raw_15m = _candle_series(16, start=114.0, step=0.1)
        raw_4h = _candle_series(25, start=85.0, step=1.2)
        c4 = [r[4] for r in reversed(raw_4h)]
        h4 = [r[2] for r in reversed(raw_4h)]
        l4 = [r[3] for r in reversed(raw_4h)]

        anchors = compute_structural_anchors(
            closes_1h=closes_1h,
            highs_1h=highs_1h,
            lows_1h=lows_1h,
            raw_1h=raw_1h,
            raw_15m=raw_15m,
            closes_4h=c4,
            highs_4h=h4,
            lows_4h=l4,
            price=closes_1h[-1],
            atr_1h=1.8,
            sl_atr_mult=2.0,
        )
        for key in (
            "ema21_1h",
            "ema55_1h",
            "ema21_4h",
            "swing_high_1h_15",
            "swing_low_1h_15",
            "swing_high_1h_48",
            "swing_low_1h_48",
            "swing_high_4h",
            "swing_low_4h",
            "bar_summary_1h",
            "bar_summary_15m",
            "long_anchor",
            "short_anchor",
        ):
            self.assertIn(key, anchors)
        self.assertLess(anchors["long_anchor"]["sl"], anchors["long_anchor"]["entry"])
        self.assertGreater(anchors["long_anchor"]["tp"], anchors["long_anchor"]["entry"])
        self.assertGreater(anchors["short_anchor"]["sl"], anchors["short_anchor"]["entry"])
        self.assertLess(anchors["short_anchor"]["tp"], anchors["short_anchor"]["entry"])

    def test_construct_full_market_prompt_renders_structural_anchors_and_rs_cleanly(self):
        pkg = {
            "name": "SOL",
            "instId": "SOL-USDT-SWAP",
            "data_quality": "valid",
            "price": 150.0,
            "chg24h": 2.1,
            "bidPx": 149.95,
            "askPx": 150.05,
            "smart_money": {},
            "adx_1h": 27.0,
            "recent_15m": [],
            "recent_1h": [],
            "recent_4h": [],
            "atr_1h": 2.4,
            "quant_factors": {"trend_momentum": {"rsi_1h": 58.0, "macd_hist": 0.4, "macd_accel": 0.1}},
            "structural_anchors": {
                "ema21_1h": 148.5,
                "ema21_1h_dev_pct": 1.01,
                "ema55_1h": 146.2,
                "ema55_1h_dev_pct": 2.6,
                "ema21_4h": 145.0,
                "swing_low_1h_15": 144.0,
                "swing_high_1h_15": 152.5,
                "bar_summary_1h": "1H[-2]:+0.42%(体68%,下影24%,量1.4x)",
                "long_anchor": {"entry": 148.5, "sl": 143.7, "tp": 159.5},
            },
            "relative_strength": {
                "btc_beta": 1.35,
                "residual_ret_4h_pct": 2.14,
                "rs_rank": 1,
                "pool_size": 11,
                "perp_spot_basis_bps": 4.2,
                "rv_ratio_6h_72h": 0.68,
            },
        }
        missing = "/tmp/astra-nonexistent-phase4"
        with (
            patch.object(abt, "NEWS_SENTIMENT_FILE", missing),
            patch.object(abt, "AI_MEMORY_MD_FILE", missing),
            patch.object(abt, "AI_MEMORY_FILE", missing),
        ):
            prompt = abt.construct_full_market_prompt(
                [pkg], current_time_str="2026-11-28 12:00:00", usdt_available=5000.0
            )
        for expected in (
            "1H EMA21=148.5(+1.01%)",
            "EMA55=146.2(+2.60%)",
            "4H EMA21=145.0",
            "1H摆动15=[144.0, 152.5]",
            "1H近3闭合=1H[-2]:+0.42%(体68%,下影24%,量1.4x)",
            "多参考[入=148.5/SL=143.7/TP=159.5]",
            "BTC_Beta=1.35",
            "4H特质残差=+2.14%",
            "RS排名=1/11",
            "期现基差=+4.2bps",
        ):
            self.assertIn(expected, prompt)
        self.assertNotIn("K线(倒序", prompt)

    def test_system_prompt_is_symmetric_and_free_of_retired_terms(self):
        prompt = abt.get_effective_system_prompt(active_profile())
        self.assertIn("做多确认", prompt)
        self.assertIn("做空确认", prompt)
        self.assertNotIn("做空额外门槛", prompt)
        self.assertNotIn("做多不设额外门槛", prompt)
        self.assertNotIn("1H 负功率衰竭", prompt)
        self.assertIn("1H 动能反转失效", prompt)

    def test_decisions_cache_falls_back_to_reasoning_and_sanitizes_funding_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkgs = [
                {
                    "instId": "BTC-USDT-SWAP",
                    "name": "BTC",
                    "price": 90000.0,
                    "bidPx": 89990.0,
                    "askPx": 90010.0,
                    "chg24h": 1.0,
                    "vol24h": 100.0,
                    "fundingRate": "--",
                    "data_quality": "valid",
                },
                {
                    "instId": "ETH-USDT-SWAP",
                    "name": "ETH",
                    "price": 3000.0,
                    "bidPx": 2999.0,
                    "askPx": 3001.0,
                    "chg24h": 1.0,
                    "vol24h": 100.0,
                    "fundingRate": "0.005%",
                    "data_quality": "valid",
                },
            ]
            decisions = {
                "BTC-USDT-SWAP": {
                    "action": "BUY_LONG",
                    "confidence": 82,
                    "entry_price": 90000.0,
                    "stop_loss_price": 88000.0,
                    "take_profit_price": 95000.0,
                    "reasoning": "【CIO批复】采纳多头结构回踩方案",
                }
            }
            cache = assemble_decision_cache(
                pkgs,
                decisions,
                set(),
                {},
                "2026-11-28 12:00:00",
                "宏观中性",
                data_dir=tmp,
                max_leverage=5,
                min_leverage=2,
                safe_float=lambda v, d=0.0: float(v or d),
                get_system_version_tag=lambda: "v9.3.0",
                validate=lambda *a: ("BUY_LONG", "", 2.5),
            )
            self.assertEqual(cache["BTC-USDT-SWAP"]["decision"]["summary_reason"], "【CIO批复】采纳多头结构回踩方案")
            self.assertEqual(cache["BTC-USDT-SWAP"]["decision"]["model_reason"], "【CIO批复】采纳多头结构回踩方案")
            self.assertEqual(cache["BTC-USDT-SWAP"]["raw_funding_rate"], "--")
            self.assertEqual(cache["ETH-USDT-SWAP"]["raw_funding_rate"], "0.005%")

    def test_council_bounds_and_conflict_split_guidance_are_neutral_and_consistent(self):
        with patch.dict("os.environ", {"ASTRA_STOP_LOSS_ATR_MULT": "2.4"}, clear=False):
            bounds = _load_council_risk_bounds()
        self.assertEqual(bounds["sl_atr_mult"], 2.4)

        roles = {
            "a": {"name": "A", "weight": 0.5},
            "b": {"name": "B", "weight": 0.5},
        }
        consensus = {
            "by_symbol": {
                "BTC-USDT-SWAP": calculate_symbol_consensus(
                    "BTC-USDT-SWAP",
                    {
                        "a": {"action": "BUY_LONG", "confidence": 80},
                        "b": {"action": "SELL_SHORT", "confidence": 75},
                    },
                    roles,
                )
            }
        }
        docket = format_consensus_docket(consensus)
        self.assertIn("严重分歧", docket)
        self.assertNotIn("无压倒性胜率时建议审慎观望 WAIT", docket)


if __name__ == "__main__":
    unittest.main()
