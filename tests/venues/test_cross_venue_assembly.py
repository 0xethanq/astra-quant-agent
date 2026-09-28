"""US-007：/api/all cross_venue 装配契约单测（dashboard._load_cross_venue_data）。

红线自检：零网络（被测函数只 open 本地 JSON）；读写全部钉到 tmp 目录；
不依赖生产 data/ 当前内容（venue_health.symbols / decisions.xvenue 均按
「可能缺席」设计断言——US-009 收尾者落库前后本测试都应为绿）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import astra_backend.dashboard_cache as dashboard


def _dec_entry(name: str, inst: str, last, xvenue) -> dict:
    entry = {
        "name": name,
        "instId": inst,
        "raw_ticker": {"last": last},
    }
    if xvenue is not None:
        entry["xvenue"] = xvenue
    return entry


class CrossVenueAssemblyTests(unittest.TestCase):
    """装配面：健康段透传 + by_asset 双源合并 + 逐键位/整体 fail-soft。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.vh = self.dir / "venue_health.json"
        self.dec = self.dir / "ai_brain_decisions.json"

    def _load(self):
        with patch.object(dashboard, "DATA_DIR", str(self.dir)), \
             patch.object(dashboard, "AI_DECISIONS_FILE", str(self.dec)):
            return dashboard._load_cross_venue_data()

    def _write(self, path: Path, obj):
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    # ---- ① 齐全：两路数据源都在，symbols 优先、xvenue 补缺 ----
    def test_full_both_sources_symbols_precedence(self):
        self._write(self.vh, {
            "updated_utc": "2026-09-09 19:00:00", "writer_pid": 1, "package_count": 10,
            "venues": {"okx": {"ok": ["BTC"]}},
            "symbols": {"BTC": {"okx": 79000.0}},
        })
        self._write(self.dec, {
            "BTC-USDT-SWAP": _dec_entry("BTC", "BTC-USDT-SWAP", 79000.0, None),
        })
        out = self._load()
        self.assertEqual(out["updated_utc"], "2026-09-09 19:00:00")
        self.assertEqual(out["package_count"], 10)
        self.assertIn("okx", out["venues"])
        self.assertIn("BTC", out["symbols"])
        row = out["by_asset"]["BTC"]
        self.assertEqual(row["okx_last"], 79000.0)

    # ---- ② 仅决策缓存 ----
    def test_xvenue_only_basis_computed(self):
        self._write(self.vh, {"updated_utc": "x", "package_count": 1,
                              "venues": {}})
        self._write(self.dec, {
            "ETH-USDT-SWAP": _dec_entry("ETH", "ETH-USDT-SWAP", 2500.0, None),
        })
        out = self._load()
        row = out["by_asset"]["ETH"]
        self.assertEqual(row["okx_last"], 2500.0)
        self.assertEqual(out["symbols"], {})

    # ---- ③ 容错：脏条目被跳过 ----
    def test_decisions_missing_or_partial_xvenue(self):
        self._write(self.dec, {
            "BTC-USDT-SWAP": _dec_entry("BTC", "BTC-USDT-SWAP", 100.0, None),
            "SOL-USDT-SWAP": _dec_entry("SOL", "SOL-USDT-SWAP", 200.0, None),
            "junk": "not-a-dict",                                               # 脏条目
        })
        out = self._load()
        self.assertEqual(out["updated_utc"], "")
        self.assertEqual(out["by_asset"]["BTC"]["okx_last"], 100.0)
        self.assertEqual(out["by_asset"]["SOL"]["okx_last"], 200.0)
        self.assertNotIn("JUNK", out["by_asset"])

    # ---- ④ symbols 独有资产（决策缓存没这个币）也要出现 ----
    def test_symbols_only_asset_included(self):
        self._write(self.vh, {"updated_utc": "u", "package_count": 2, "venues": {},
                              "symbols": {"PEPE": {"okx": 0.00001}}})
        self._write(self.dec, {})
        out = self._load()
        self.assertEqual(out["by_asset"]["PEPE"]["okx_last"], 0.00001)

    # ---- ⑤ 损坏：两路全烂 → 空态且不抛（整体 fail-soft 不影响响应其余部分） ----
    def test_both_corrupt_degrade_to_empty(self):
        self.vh.write_text("{ not json", encoding="utf-8")
        self.dec.write_text("[[[ broken", encoding="utf-8")
        out = self._load()
        self.assertEqual(out, {"updated_utc": "", "package_count": 0,
                               "venues": {}, "symbols": {}, "by_asset": {}})

    # ---- ⑥ 垃圾类型：合法 JSON 但结构烂 → 逐段防御 ----
    def test_bad_types_degrade(self):
        self._write(self.vh, {"venues": "not-a-dict", "symbols": [1, 2],
                              "package_count": "x", "updated_utc": None})
        self._write(self.dec, ["not", "a", "dict"])
        out = self._load()
        self.assertEqual(out["venues"], {})
        self.assertEqual(out["symbols"], {})
        self.assertEqual(out["by_asset"], {})
        self.assertEqual(out["package_count"], 0)
        self.assertEqual(out["updated_utc"], "")

    # ---- ⑦ 缺失：两个文件都不存在 → 空态（旧部署/首轮周期） ----
    def test_both_missing_empty_shape(self):
        out = self._load()
        self.assertEqual(out, {"updated_utc": "", "package_count": 0,
                               "venues": {}, "symbols": {}, "by_asset": {}})

    # ---- ⑧ 快照通道注入：STALE 降级路径也带 cross_venue 键 ----
    def test_stale_injection_carries_cross_venue(self):
        self._write(self.vh, {"updated_utc": "2026-09-09 20:00:00", "package_count": 3,
                              "venues": {"gate": {"ok": ["BTC"], "avg_ms": 120}},
                              "symbols": {}})
        self._write(self.dec, {})
        missing = lambda n: str(self.dir / ("__absent__" + n))
        with patch.object(dashboard, "DATA_DIR", str(self.dir)), \
             patch.object(dashboard, "AI_DECISIONS_FILE", str(self.dec)), \
             patch.object(dashboard, "FACTOR_LIBRARY_FILE", missing("fl")), \
             patch.object(dashboard, "NEWS_SENTIMENT_FILE", missing("ns")), \
             patch.object(dashboard, "AI_HISTORY_FILE", missing("ah")), \
             patch.object(dashboard, "REPORT_JSON_FILE", missing("rp")), \
             patch.object(dashboard, "AI_LAST_PROMPT_FILE", missing("ap")), \
             patch.object(dashboard, "LOG_FILE", missing("lg")), \
             patch.object(dashboard, "_build_factors_from_local_files", lambda *a: ([], {})), \
             patch.object(dashboard, "load_trading_memory_md", lambda: ""):
            stale = {"account": {}}
            dashboard._inject_local_data_into_stale(stale, [], "2026-09-09 20:01:00")
        self.assertEqual(stale["cross_venue"]["updated_utc"], "2026-09-09 20:00:00")
        self.assertIn("gate", stale["cross_venue"]["venues"])


if __name__ == "__main__":
    unittest.main()
