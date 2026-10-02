"""单元测试：投委会报价单解析与数理共识度算法 (consensus.py)。"""
from __future__ import annotations

import unittest

from astra_backend.council.consensus import (
    calculate_council_consensus,
    calculate_symbol_consensus,
    extract_disputed_symbols,
    format_consensus_docket,
    parse_trader_quote_table,
)

SAMPLE_PROPOSAL_TABLE = """
【我的本轮实战作战方案】
经过全景行情研判，提交标准报价单如下：

标的 | 倾向 | 限价 | 止损 | 止盈 | 拟用保证金(USDT) | 置信度(0-100) | 一句话依据
BTC-USDT-SWAP | BUY_LONG | 78250.0 | 76500.0 | 81750.0 | 150.0 | 82 | 回踩支撑企稳放量
ETH-USDT-SWAP | WAIT | - | - | - | - | 55 | 箱体中段无明显形态
SOL-USDT-SWAP | SELL_SHORT | 185.5 | 192.0 | 172.5 | 120.0 | 75 | 触及 4H 上轨假突破受阻
| DOGE-USDT-SWAP | WAIT | - | - | - | - | 50 | 震荡无序 |
"""

SAMPLE_PROPOSAL_FREE_TEXT = """
针对以下标的给出建议：
- BTC-USDT-SWAP: BUY_LONG，重点关注回踩。
- ETH-USDT-SWAP: WAIT，建议观望。
"""


class CouncilConsensusParsingTests(unittest.TestCase):
    def test_parse_trader_quote_table_markdown(self):
        quotes = parse_trader_quote_table(SAMPLE_PROPOSAL_TABLE)
        self.assertEqual(len(quotes), 4)

        btc = next(q for q in quotes if q["symbol"] == "BTC-USDT-SWAP")
        self.assertEqual(btc["action"], "BUY_LONG")
        self.assertEqual(btc["limit_price"], 78250.0)
        self.assertEqual(btc["stop_loss"], 76500.0)
        self.assertEqual(btc["take_profit"], 81750.0)
        self.assertEqual(btc["margin"], 150.0)
        self.assertEqual(btc["confidence"], 82)
        self.assertIn("回踩", btc["reason"])

        eth = next(q for q in quotes if q["symbol"] == "ETH-USDT-SWAP")
        self.assertEqual(eth["action"], "WAIT")
        self.assertIsNone(eth["limit_price"])
        self.assertEqual(eth["confidence"], 55)

        sol = next(q for q in quotes if q["symbol"] == "SOL-USDT-SWAP")
        self.assertEqual(sol["action"], "SELL_SHORT")
        self.assertEqual(sol["limit_price"], 185.5)

        doge = next(q for q in quotes if q["symbol"] == "DOGE-USDT-SWAP")
        self.assertEqual(doge["action"], "WAIT")

    def test_parse_trader_quote_table_free_text_fallback(self):
        quotes = parse_trader_quote_table(SAMPLE_PROPOSAL_FREE_TEXT)
        self.assertEqual(len(quotes), 2)
        self.assertEqual(quotes[0]["symbol"], "BTC-USDT-SWAP")
        self.assertEqual(quotes[0]["action"], "BUY_LONG")
        self.assertEqual(quotes[1]["symbol"], "ETH-USDT-SWAP")
        self.assertEqual(quotes[1]["action"], "WAIT")

    def test_parse_empty_or_junk_returns_empty(self):
        self.assertEqual(parse_trader_quote_table(""), [])
        self.assertEqual(parse_trader_quote_table("纯分析，无标的表格"), [])


class CouncilConsensusCalculationTests(unittest.TestCase):
    def setUp(self):
        self.roles = {
            "trader_trend": {"name": "资深交易员 A (顺势型)", "weight": 0.35},
            "trader_momentum": {"name": "资深交易员 B (动能型)", "weight": 0.35},
            "trader_quant": {"name": "资深交易员 C (量化型)", "weight": 0.30},
        }

    def test_unanimous_long_produces_strong_consensus(self):
        quotes = {
            "trader_trend": {"action": "BUY_LONG", "confidence": 80, "limit_price": 100},
            "trader_momentum": {"action": "BUY_LONG", "confidence": 85, "limit_price": 101},
            "trader_quant": {"action": "BUY_LONG", "confidence": 75, "limit_price": 99},
        }
        res = calculate_symbol_consensus("BTC-USDT-SWAP", quotes, self.roles)
        self.assertEqual(res["dominant_action"], "BUY_LONG")
        self.assertEqual(res["agreement_score"], 1.0)
        self.assertEqual(res["status"], "STRONG_CONSENSUS")
        self.assertEqual(res["weighted_confidence"], 80)
        self.assertIn("多(80)", res["distribution_summary"])

    def test_directional_conflict_produces_conflict_split(self):
        quotes = {
            "trader_trend": {"action": "BUY_LONG", "confidence": 80},
            "trader_momentum": {"action": "SELL_SHORT", "confidence": 75},
            "trader_quant": {"action": "WAIT", "confidence": 60},
        }
        res = calculate_symbol_consensus("ETH-USDT-SWAP", quotes, self.roles)
        self.assertEqual(res["status"], "CONFLICT_SPLIT")
        self.assertLessEqual(res["agreement_score"], 0.5)

    def test_two_vs_one_wait_produces_moderate_leaning(self):
        quotes = {
            "trader_trend": {"action": "BUY_LONG", "confidence": 80},
            "trader_momentum": {"action": "BUY_LONG", "confidence": 85},
            "trader_quant": {"action": "WAIT", "confidence": 60},
        }
        res = calculate_symbol_consensus("SOL-USDT-SWAP", quotes, self.roles)
        self.assertEqual(res["dominant_action"], "BUY_LONG")
        self.assertEqual(res["status"], "MODERATE_LEANING")
        self.assertGreater(res["agreement_score"], 0.6)

    def test_council_level_aggregation(self):
        proposals = {
            "trader_trend": {
                "status": "ok",
                "content": "标的 | 倾向 | 限价 | 止损 | 止盈 | 保证金 | 置信度 | 依据\nBTC-USDT-SWAP | BUY_LONG | 100 | 90 | 120 | 100 | 80 | 顺势\nETH-USDT-SWAP | BUY_LONG | 200 | 190 | 220 | 100 | 75 | 突破",
            },
            "trader_momentum": {
                "status": "ok",
                "content": "标的 | 倾向 | 限价 | 止损 | 止盈 | 保证金 | 置信度 | 依据\nBTC-USDT-SWAP | BUY_LONG | 100 | 90 | 120 | 100 | 85 | 动能\nETH-USDT-SWAP | SELL_SHORT | 200 | 210 | 180 | 100 | 70 | 阻力",
            },
            "trader_quant": {
                "status": "ok",
                "content": "标的 | 倾向 | 限价 | 止损 | 止盈 | 保证金 | 置信度 | 依据\nBTC-USDT-SWAP | BUY_LONG | 100 | 90 | 120 | 100 | 78 | 筹码\nETH-USDT-SWAP | WAIT | - | - | - | - | 50 | 观望",
            },
        }
        data = calculate_council_consensus(proposals, self.roles)
        self.assertEqual(data["total_symbols_evaluated"], 2)
        self.assertIn("BTC-USDT-SWAP", data["strong_consensus_symbols"])
        self.assertIn("ETH-USDT-SWAP", data["disputed_symbols"])
        self.assertEqual(extract_disputed_symbols(data), ["ETH-USDT-SWAP"])

        docket = format_consensus_docket(data)
        self.assertIn("BTC-USDT-SWAP", docket)
        self.assertIn("强共识", docket)
        self.assertIn("ETH-USDT-SWAP", docket)
        self.assertIn("严重分歧", docket)


if __name__ == "__main__":
    unittest.main()
