"""Unit tests for news intelligent selection, weighting, and prompt formatting."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from scripts.news.selection import (
    is_crypto_news,
    is_macro_news,
    select_weighted_news,
    format_news_for_prompt,
)
import scripts.ai_brain_trader as abt


class TestNewsSelection(unittest.TestCase):
    def test_is_crypto_news_by_coins(self):
        item = {"title": "Network update announced", "summary": "", "coins": ["ETH"]}
        ok, coins = is_crypto_news(item)
        self.assertTrue(ok)
        self.assertEqual(coins, ["ETH"])

    def test_is_crypto_news_by_platform(self):
        item = {"title": "Regulator speaks on digital markets", "summary": "", "platforms": ["CoinDesk"]}
        ok, coins = is_crypto_news(item)
        self.assertTrue(ok)

    def test_is_crypto_news_by_keywords(self):
        item = {"title": "Vitalik shares roadmap for rollups", "summary": "Layer2 fees are dropping"}
        ok, _ = is_crypto_news(item)
        self.assertTrue(ok)

        item_zh = {"title": "以太坊现货ETF今日净流入超5000万美元", "summary": ""}
        ok_zh, _ = is_crypto_news(item_zh)
        self.assertTrue(ok_zh)

    def test_is_crypto_news_rejects_irrelevant(self):
        item = {"title": "特斯拉降价引发车主不满", "summary": "汽车工业展望"}
        ok, _ = is_crypto_news(item)
        self.assertFalse(ok)

    def test_is_macro_news(self):
        item_fed = {"title": "美联储维持基准利率不变，鲍威尔暗示降息时机未到", "summary": "FOMC决议"}
        ok, is_high = is_macro_news(item_fed)
        self.assertTrue(ok)
        self.assertFalse(is_high)

        item_high = {"title": "地缘冲突加剧引发全球流动性危机", "summary": "", "importance": "high"}
        ok2, is_high2 = is_macro_news(item_high)
        self.assertTrue(ok2)
        self.assertTrue(is_high2)

    def test_select_weighted_news_empty(self):
        self.assertEqual(select_weighted_news([]), [])

    def test_select_weighted_news_prioritizes_target_coins(self):
        news = [
            {"id": "1", "time": "2026-09-27 22:00:00", "title": "Random Altcoin pumps", "coins": ["ADA"]},
            {"id": "2", "time": "2026-09-27 21:00:00", "title": "ETH Layer2 upgrade complete", "coins": ["ETH"]},
            {"id": "3", "time": "2026-09-27 23:00:00", "title": "美联储非农数据超预期", "importance": "high"},
            {"id": "4", "time": "2026-09-27 20:00:00", "title": "SOL validator cluster online", "coins": ["SOL"]},
            {"id": "5", "time": "2026-09-27 19:00:00", "title": "普通企业财报发布", "importance": "low"},
        ]
        target_coins = {"ETH", "SOL"}
        selected = select_weighted_news(news, target_coins=target_coins, total_limit=4, crypto_quota=2, macro_quota=1)

        selected_titles = [x["title"] for x in selected]
        # Target coins ETH and SOL should be selected in crypto quota
        self.assertIn("ETH Layer2 upgrade complete", selected_titles)
        self.assertIn("SOL validator cluster online", selected_titles)
        # Macro item should be selected
        self.assertIn("美联储非农数据超预期", selected_titles)
        # Irrelevant low-importance company report should NOT be selected
        self.assertNotIn("普通企业财报发布", selected_titles)

    def test_select_weighted_news_dynamic_fallback(self):
        """当币圈资讯只有 1 条时，自动用宏观或常规资讯填补配额，保持信息饱满。"""
        news = [
            {"id": "1", "time": "2026-09-27 22:00:00", "title": "BTC ETF 资金流向转正", "coins": ["BTC"]},
            {"id": "2", "time": "2026-09-27 21:00:00", "title": "美联储利率点阵图更新", "importance": "high"},
            {"id": "3", "time": "2026-09-27 20:00:00", "title": "美国8月核心CPI年率保持韧性", "importance": "mid"},
            {"id": "4", "time": "2026-09-27 19:00:00", "title": "欧洲央行行长拉加德发言", "importance": "mid"},
        ]
        selected = select_weighted_news(news, target_coins={"BTC"}, total_limit=3, crypto_quota=3, macro_quota=1)
        self.assertEqual(len(selected), 3)
        self.assertEqual(selected[0]["title"], "BTC ETF 资金流向转正")

    def test_format_news_for_prompt(self):
        items = [
            {
                "time": "2026-09-27 22:29:13",
                "title": "Vitalik Buterin maps Ethereum shift",
                "summary": "Sweeping update on roadmap",
                "coins": ["ETH"],
                "_derived_category": "crypto",
                "_matched_coins": ["ETH"],
            },
            {
                "time": "2026-09-27 23:00:00",
                "title": "一周展望：非农与PCE考验美联储利率路径",
                "summary": "重磅通胀与就业数据",
                "importance": "high",
                "_derived_category": "macro",
            },
        ]
        target_coins = {"ETH"}
        lines = format_news_for_prompt(items, target_coins=target_coins)
        self.assertEqual(len(lines), 2)
        # Target coin has lightning badge
        self.assertIn("[币圈·ETH ⚡]", lines[0])
        self.assertIn("[22:29]", lines[0])
        # High importance macro has globe badge
        self.assertIn("[宏观·重磅 🌐]", lines[1])
        self.assertIn("[23:00]", lines[1])

    def test_prompt_assembly_with_weighted_news(self):
        """测试全流程：把新闻写入临时 json，由 construct_full_market_prompt 组装。"""
        with tempfile.TemporaryDirectory() as td:
            news_file = os.path.join(td, "news_sentiment.json")
            data = {
                "macro_sentiment": "偏多震荡",
                "latest_news": [
                    {"time": "2026-09-27 23:30:00", "title": "无关快讯：某车企推出新车型", "summary": "", "importance": "low"},
                    {"time": "2026-09-27 23:00:00", "title": "无关快讯：黄金微涨0.1%", "summary": "", "importance": "low"},
                    {"time": "2026-09-27 22:50:00", "title": "以太坊Layer2结算量达历史极值", "summary": "", "coins": ["ETH"]},
                    {"time": "2026-09-27 22:40:00", "title": "Solana性能升级启动公测", "summary": "", "coins": ["SOL"]},
                    {"time": "2026-09-27 22:30:00", "title": "比特币现货ETF大额净流入", "summary": "", "coins": ["BTC"]},
                    {"time": "2026-09-27 22:20:00", "title": "瑞波与主流金融机构达成结算合作", "summary": "", "coins": ["XRP"]},
                    {"time": "2026-09-27 21:00:00", "title": "美联储主席鲍威尔就宏观货币政策发表讲话", "summary": "降息节奏取决于后续通胀", "importance": "high"},
                    {"time": "2026-09-27 20:30:00", "title": "美国8月核心CPI年率显示通胀趋缓", "summary": "", "importance": "mid"},
                ]
            }
            with open(news_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            packages = [{
                "name": "ETH",
                "instId": "ETH-USDT-SWAP",
                "price": "2600.0",
                "chg24h": "1.2",
                "bidPx": "2599.9",
                "askPx": "2600.1",
                "fundingRate": "0.01",
                "oiUsd": "100M",
                "lsRatio": "1.2",
                "takerNetUsd": "500K",
            }]
            with patch.object(abt, "NEWS_SENTIMENT_FILE", news_file):
                prompt = abt.construct_full_market_prompt(
                    packages,
                    usdt_available=1000.0,
                )
            # 必须包含加权优选后的币圈资讯与宏观重磅
            self.assertIn("[币圈·ETH ⚡]", prompt)
            self.assertIn("以太坊Layer2结算量达历史极值", prompt)
            self.assertIn("[宏观·重磅 🌐]", prompt)
            self.assertIn("美联储主席鲍威尔就宏观货币政策发表讲话", prompt)
            # 低价值汽车快讯不应出现在优选结果中
            self.assertNotIn("某车企推出新车型", prompt)
