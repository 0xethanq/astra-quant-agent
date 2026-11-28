"""回归测试：因子管道修复（VWAP 零价守卫、TopTrader 口径、连续趋势评分、横截面 BTC Beta/残差/基差、英文黑天鹅）。"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.factors import candles_15m, okx_quant_factors as qf, scoring, smart_money
from scripts.factors.defaults import build_default_factors
import scripts.news_sentiment_harvester as harvester


class FactorPipelineUpgradesTests(unittest.TestCase):
    def test_zero_price_never_produces_minus_100_vwap_bias(self):
        # price=0.0 时必须显式置 None，而非算出 -100.0%
        raw = [[str(1_700_000_000_000 + i * 900_000), "100", "101", "99", "100", "10"] for i in range(20)]
        f = {"price": 0.0, "volatility_channel": {}, "trend_momentum": {}, "volume_money_flow": {}}
        candles_15m.compute_15m_indicators(raw, f, safe_float=lambda x: float(x or 0.0))
        self.assertIsNone(f["trend_momentum"]["vwap_bias_pct"])

    def test_scoring_smooth_rsi_ramp_removes_cliff_and_marks_missing_adx(self):
        # 缺失 ADX -> trend_regime = INSUFFICIENT_DATA（不再冒充 CHOP_RANGE）
        f_missing = build_default_factors("BTC-USDT-SWAP", "BTC")
        f_missing["trend_momentum"]["adx_1h"] = None
        scoring.score_composite_alpha(f_missing)
        self.assertEqual(f_missing["trend_momentum"]["trend_regime"], "INSUFFICIENT_DATA")

        # RSI=50.0 vs 49.9 不再有 ±30 分跳崖
        f50 = build_default_factors("BTC-USDT-SWAP", "BTC")
        f50["trend_momentum"].update({"adx_1h": 28.0, "rsi_14": 50.0})
        f499 = build_default_factors("BTC-USDT-SWAP", "BTC")
        f499["trend_momentum"].update({"adx_1h": 28.0, "rsi_14": 49.9})
        s50 = scoring.score_composite_alpha(f50)
        s499 = scoring.score_composite_alpha(f499)
        self.assertEqual(s50, 0.0)
        self.assertLess(abs(s50 - s499), 0.5)

    def test_smart_money_never_falls_back_to_retail_account_ratio(self):
        # 若两大 top-trader 端点都失败，必须返回 None（available=False），绝不退回全网散户比
        called_urls = []

        def fake_get(url, timeout=3.5, out_status=None):
            called_urls.append(url)
            return None

        with patch.object(smart_money, "_shared_cache_module", return_value=None), \
             patch.object(smart_money, "_okx_rubik_get", side_effect=fake_get):
            res = smart_money.fetch_smart_money_for_symbol("SOL", price=150.0)
        self.assertIsNone(res)
        self.assertTrue(all("top-trader" in u for u in called_urls))

    def test_empty_quarterly_basis_not_cached(self):
        qf._reset_cache_for_tests()
        self.addCleanup(qf._reset_cache_for_tests)
        with patch.object(qf, "_public_get", return_value=None):
            out = qf.fetch_quarterly_basis_inputs("BTC")
        self.assertEqual(out, {})
        self.assertIsNone(qf._cache_get("basis:BTC", 3600.0))

    def test_liquidation_window_filters_stale_altcoin_events(self):
        now_ms = 1_700_000_000_000
        det = [
            {"posSide": "short", "sz": "10", "bkPx": "100", "time": str(now_ms)},  # 最近 (+1000 short)
            {"posSide": "long", "sz": "50", "bkPx": "100", "time": str(now_ms - 10 * 3600 * 1000)},  # 10h前旧单
        ]
        long_u, short_u, bias = qf.summarize_liquidations(det, 1.0, window_hours=4.0)
        self.assertEqual(long_u, 0.0)
        self.assertEqual(short_u, 1000.0)
        self.assertEqual(bias, "SHORT_SQUEEZE")

    def test_btc_beta_residual_rv_basis_and_rs_rank(self):
        btc = [100.0 * (1.01 ** i) for i in range(80)]
        # SOL 与 BTC 同波动但最后 4h 大幅跑赢
        sol = [50.0 * (1.01 ** i) for i in range(76)] + [50.0 * (1.01 ** 76) * (1.03 ** k) for k in range(1, 5)]
        f_btc = build_default_factors("BTC-USDT-SWAP", "BTC")
        f_btc["relative_strength"] = {"_closes_1h": btc, "perp_spot_basis_bps": 4.0}
        f_sol = build_default_factors("SOL-USDT-SWAP", "SOL")
        f_sol["relative_strength"] = {"_closes_1h": sol, "perp_spot_basis_bps": 6.0}
        qf.assign_cross_sectional_rs_rank([f_btc, f_sol])
        self.assertEqual(f_sol["relative_strength"]["rs_rank"], 1)
        self.assertEqual(f_btc["relative_strength"]["rs_rank"], 2)
        self.assertGreater(f_sol["relative_strength"]["residual_ret_4h_pct"], 0.0)
        self.assertIsNotNone(f_sol["relative_strength"]["rv_ratio_6h_72h"])

    def test_english_black_swan_patterns_and_overall_score(self):
        hit = any(
            __import__("re").search(pat, "Binance halts withdrawals amid insolvency fears", __import__("re").IGNORECASE)
            for pat, _ in harvester.BLACK_SWAN_PATTERNS
        )
        self.assertTrue(hit)

        with patch.object(harvester, "fetch_okx_announcements", return_value=[]), \
             patch.object(harvester, "fetch_crypto_rss_news", return_value=[]), \
             patch.object(harvester, "fetch_jin10_macro_news", return_value=[]), \
             patch.object(harvester, "fetch_okx_rubik_sentiment", return_value=None), \
             patch.object(harvester, "load_instruments", return_value=[{"name": "BTC", "instId": "BTC-USDT-SWAP"}]):
            import tempfile
            with tempfile.TemporaryDirectory() as td, \
                 patch.object(harvester, "NEWS_CACHE_FILE", os.path.join(td, "news.json")), \
                 patch.object(harvester, "CIRCUIT_BREAKER_FILE", os.path.join(td, "cb.json")):
                payload = harvester.fetch_and_analyze_news_sentiment()
        self.assertIn("overall_score", payload)
        self.assertIsInstance(payload["overall_score"], float)


if __name__ == "__main__":
    unittest.main()
