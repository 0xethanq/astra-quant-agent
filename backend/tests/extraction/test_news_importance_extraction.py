"""`scripts/news/importance.py`（阶段 4·B3 第四十四刀）回归。

## 抽了什么

`scripts/news_sentiment_harvester.py` 里两块**纯判断**逻辑（57 行）：

| 函数 | 作用 |
|---|---|
| `_classify_importance` | 标题+摘要 → `high` / `mid` / `low` |
| `_extract_coins` | 文本 → 涉及的币种（含中文别名） |

| | 之前 | 之后 |
|---|---|---|
| `news_sentiment_harvester.py` | 502 行 | **453 行** |
| `news/importance.py` | — | 111 行（新） |

## 为什么这个文件**能**抽（与同批其它"低锚点文件"不同）

本阶段此前几次发现：锚点密度低的文件往往靠 **patch 模块常量**做接缝注入
（`patch.object(nh, "NEWS_CACHE_FILE", ...)`）。把那些函数搬进子模块，
它们会在 import 期绑定路径副本 → **补丁静默失效**，正是仓库
`tests/test_llm_seam_discipline.py` 警告的事故类型。

而 `_classify_importance` / `_extract_coins` **不读任何模块常量**（纯文本进、纯值出），
故外提后门面接缝完全不受影响。测试里专门有一条
`test_seam_still_patchable` 守住这件事。

## 四条必须原样保留的行为

1. **`high` 优先于 `mid`**；
2. **涨跌不对称**：`"暴跌"`/`"崩盘"` 是高危，`"暴涨"`/`"突破"` 只是中危
   —— 涨不恐慌、跌才恐慌，**勿"统一"**；
3. **中文别名用子串、ASCII 别名用词边界**（中文无词边界，用 `\\b` 会漏匹配）；
4. **`found[:4]` 最多 4 个币**（控制晨报长度，既有行为，不是笔误）。
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

MODULE = SCRIPTS / "news" / "importance.py"
FACADE = SCRIPTS / "news_sentiment_harvester.py"

from scripts.news.importance import (  # noqa: E402
    COIN_ALIASES,
    HIGH_KEYWORDS,
    MAX_COINS,
    MID_KEYWORDS,
    _classify_importance,
    _extract_coins,
)


class ClassifyTest(unittest.TestCase):
    def test_high_crisis(self):
        self.assertEqual(_classify_importance("USDT 出现严重脱锚危机", "市场暴跌"), "high")

    def test_high_halt_withdrawals(self):
        self.assertEqual(_classify_importance("某交易所暂停提币", "用户无法提现"), "high")

    def test_high_hacked(self):
        self.assertEqual(_classify_importance("HACKED: exploit found", "funds stolen"), "high")

    def test_mid_macro(self):
        self.assertEqual(_classify_importance("美联储宣布降息50个基点", "CPI超预期"), "mid")

    def test_mid_ath(self):
        self.assertEqual(_classify_importance("比特币突破历史新高", "机构大额增持"), "mid")

    def test_low_ordinary(self):
        self.assertEqual(_classify_importance("某社区召开日常研讨会", ""), "low")

    def test_low_on_empty(self):
        self.assertEqual(_classify_importance("", ""), "low")

    def test_high_wins_over_mid_in_same_text(self):
        """⚠️ 同一段文本同时含高危与中危词时，必须判 `high`。"""
        self.assertEqual(_classify_importance("美联储降息但市场暴跌", ""), "high")

    def test_up_down_asymmetry(self):
        """⚠️ 涨跌方向不对称：`暴跌` 高危、`暴涨` 仅中危。

        这是**有意**的（涨不恐慌、跌才恐慌），改成对称会改变晨报的告警级别。
        """
        self.assertEqual(_classify_importance("暴跌", ""), "high")
        self.assertEqual(_classify_importance("暴涨", ""), "mid")
        self.assertEqual(_classify_importance("突破", ""), "mid")

    def test_case_insensitive(self):
        self.assertEqual(_classify_importance("CRASH", ""), "high")
        self.assertEqual(_classify_importance("Crash", ""), "high")

    def test_summary_is_also_scanned(self):
        self.assertEqual(_classify_importance("普通标题", "随后暴跌"), "high")

    def test_keyword_tables_are_nonempty_and_disjoint(self):
        self.assertTrue(HIGH_KEYWORDS)
        self.assertTrue(MID_KEYWORDS)
        self.assertEqual(set(HIGH_KEYWORDS) & set(MID_KEYWORDS), set(),
                         "高危与中危词表不应有交集（有交集时 high 会稳赢，中危项形同虚设）")


class ExtractCoinsTest(unittest.TestCase):
    def test_english_codes(self):
        self.assertEqual(_extract_coins("BTC and ETH rally", "", ["BTC", "ETH"]),
                         ["BTC", "ETH"])

    def test_chinese_aliases(self):
        self.assertEqual(_extract_coins("比特币突破新高", "以太坊跟随", ["BTC", "ETH", "SOL"]),
                         ["BTC", "ETH"])

    def test_solana_alias(self):
        self.assertEqual(_extract_coins("Solana 主网升级", "", ["SOL"]), ["SOL"])

    def test_dogecoin_alias(self):
        self.assertEqual(_extract_coins("狗狗币大涨", "", ["DOGE"]), ["DOGE"])

    def test_avalanche_alias(self):
        self.assertEqual(_extract_coins("雪崩协议", "", ["AVAX"]), ["AVAX"])

    def test_ripple_alias(self):
        self.assertEqual(_extract_coins("瑞波胜诉", "", ["XRP"]), ["XRP"])

    def test_no_coin(self):
        self.assertEqual(_extract_coins("无币种新闻", "", ["BTC"]), [])

    def test_empty(self):
        self.assertEqual(_extract_coins("", "", []), [])

    def test_none_targets_tolerated(self):
        self.assertEqual(_extract_coins("BTC", "", None), ["BTC"])

    def test_caps_at_four(self):
        """⚠️ 最多返回 4 个币（既有行为，控制晨报长度）。"""
        got = _extract_coins("BTC ETH SOL DOGE LINK AVAX", "", [])
        self.assertEqual(len(got), 4)
        self.assertEqual(len(got), MAX_COINS)

    def test_extra_target_coin_appended(self):
        """表里没有、但调用方指定的目标币，只要文本出现词边界命中就补进结果。

        ⚠️ **目标币故意用小写**。我第一版用的是 `["PEPE"]`（大写）——
        负向验证随即指出"删掉 `tc.upper()`"**测不出来**：因为 `text` 已被
        `.upper()`，传入大写目标币时 `re.escape("PEPE")` 与
        `re.escape("PEPE".upper())` 完全相同，那个 `.upper()` 看起来是冗余的。

        用小写目标币才真正钉住这条归一化：调用方（`TARGET_COINS` 来自
        `instrument_pool`）**不能保证**给的是大写。
        修正后该注入由 OK 变为 **RED**。
        """
        got = _extract_coins("PEPE rallying hard", "", ["pepe"])
        self.assertEqual(got, ["PEPE"], "小写目标币必须被归一化为大写后命中")

    def test_extra_target_coin_uppercase_also_works(self):
        self.assertEqual(_extract_coins("PEPE rallying hard", "", ["PEPE"]), ["PEPE"])

    def test_ascii_aliases_use_word_boundary(self):
        """⚠️ ASCII 别名用 `\\b`：`ETH` 不应命中 `TOGETHER` 这类词内子串。"""
        self.assertEqual(_extract_coins("TOGETHER we stand", "", []), [])

    def test_chinese_aliases_use_substring(self):
        """⚠️ 中文无词边界，必须用子串（用 `\\b` 会漏）。"""
        self.assertIn("BTC", _extract_coins("比特币行情", "", []))

    def test_result_is_uppercase_codes(self):
        for c in _extract_coins("bitcoin ethereum", "", []):
            self.assertEqual(c, c.upper())

    def test_case_insensitive_input(self):
        self.assertIn("BTC", _extract_coins("bTc up", "", []))

    def test_aliases_table_covers_hashrate_majors(self):
        for code in ("BTC", "ETH", "SOL", "DOGE", "LINK", "AVAX", "SUI", "ADA", "XRP"):
            self.assertIn(code, COIN_ALIASES)


class FacadeWiringTest(unittest.TestCase):
    def test_facade_reexports_both(self):
        import news_sentiment_harvester as nh
        self.assertTrue(callable(nh._classify_importance))
        self.assertTrue(callable(nh._extract_coins))

    def test_facade_identity_matches_module(self):
        import news_sentiment_harvester as nh
        import scripts.news.importance as imp
        self.assertIs(nh._classify_importance, imp._classify_importance)
        self.assertIs(nh._extract_coins, imp._extract_coins)

    def test_seam_still_patchable(self):
        """⚠️ **本刀最关键的一条**：外提只搬纯函数，门面的路径常量接缝必须仍然生效。

        既有测试用 `patch.object(nh, "NEWS_CACHE_FILE", ...)` 重定向到沙箱；
        若把**读常量的函数**也搬走，补丁会静默失效（读真实路径）。
        这里验证：补丁确实改到了门面属性，且门面仍持有这些常量。
        """
        import news_sentiment_harvester as nh
        with patch.object(nh, "NEWS_CACHE_FILE", "/tmp/__probe_news.json"):
            self.assertEqual(nh.NEWS_CACHE_FILE, "/tmp/__probe_news.json")
        with patch.object(nh, "CIRCUIT_BREAKER_FILE", "/tmp/__probe_cb.json"):
            self.assertEqual(nh.CIRCUIT_BREAKER_FILE, "/tmp/__probe_cb.json")

    def test_constant_reading_functions_stay_in_facade(self):
        """读路径常量的函数**必须**仍在门面（否则接缝失效）。"""
        src = FACADE.read_text(encoding="utf-8")
        for name in ("def trigger_circuit_breaker", "def is_circuit_breaker_active",
                     "def fetch_and_analyze_news_sentiment"):
            self.assertIn(name, src, f"{name} 必须留在门面")

    def test_facade_no_longer_defines_the_moved_functions(self):
        src = FACADE.read_text(encoding="utf-8")
        self.assertNotIn("def _classify_importance", src)
        self.assertNotIn("def _extract_coins", src)
        self.assertIn("from scripts.news.importance import", src)

    def test_module_does_not_read_module_level_paths(self):
        """新模块必须是纯的：不 import os / pathlib，不读文件。"""
        src = MODULE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imported |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                imported.add(n.module or "")
        self.assertNotIn("os", imported)
        self.assertNotIn("pathlib", imported)
        self.assertNotIn("json", imported)

    def test_module_has_no_module_level_side_effects(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        bare = [n for n in tree.body
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
        self.assertEqual(bare, [], "模块层不应有裸调用")


if __name__ == "__main__":
    unittest.main()
