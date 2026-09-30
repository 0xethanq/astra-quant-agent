"""交易时段配置存储：**缺文件给默认、坏文件也给默认、写入必须原子**（2026-09-30）。

与 `tests/core/test_schedule_store.py` 同族（同一套既有语义），但这份文件的性质不同：
它决定的是**实盘交易引擎允不允许跑**，所以两个方向都必须钉死：

| 语义 | 口径 | 为什么是这个方向 |
|---|---|---|
| ★ 缺文件 / 坏 JSON / **非对象 JSON** | 返回**未启用**的默认档（= 全天候运行） | "读不到 ≠ 停实盘"；改成"读不到就休市"等于让一个坏文件静默关掉交易 |
| ★ 默认档是**副本** | 改返回值不污染 `DEFAULT_SESSION` | `schedule_store` 那侧实测踩过共享 list 的坑 |
| ★ 原子写 | `mkstemp`→`fsync`→`os.replace`，失败路径清临时文件 | 半截 JSON 会被下一轮判成"配置损坏" |
| ★ 不做归一化 | 传什么写什么（归一化在 `scripts/trader/session.py`） | 保证"路由校验口径 == 运行时判定口径"只有一份实现 |
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from astra_backend import trading_session_store as TS


class _Base(unittest.TestCase):
    def _start(self, patcher):
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="astra-session-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.file = self.tmp / "data" / "trading_session.json"
        self._start(mock.patch.object(TS, "TRADING_SESSION_FILE", self.file))

    def _write(self, text):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(text, encoding="utf-8")


class LoadTests(_Base):
    def test_missing_file_returns_disabled_defaults(self):
        got = TS.load_trading_session()
        self.assertFalse(got["enabled"], "默认必须是「未启用」⇒ 部署后行为逐位不变")
        self.assertEqual(got["mode_outside"], "manage_only")
        self.assertEqual(got["windows"], [])
        self.assertEqual(got["timezone"], "Asia/Shanghai")

    def test_default_never_raises_even_when_the_backend_is_imported_bare(self):
        """`DEFAULT_SESSION` 的 try/except 兜底：独立运行/极早期 import 也不能炸。"""
        self.assertIn("enabled", TS.DEFAULT_SESSION)
        self.assertIn("windows", TS.DEFAULT_SESSION)

    def test_top_level_mutation_of_the_result_does_not_leak(self):
        got = TS.load_trading_session()
        got["enabled"] = True
        got["injected"] = 1
        fresh = TS.load_trading_session()
        self.assertFalse(fresh["enabled"])
        self.assertNotIn("injected", fresh)

    def test_windows_list_is_not_the_module_object(self):
        got = TS.load_trading_session()
        self.assertIsNot(got["windows"], TS.DEFAULT_SESSION["windows"],
                         "返回的 windows 必须是副本，否则一次 append 就污染全局默认")

    def test_corrupt_json_falls_back_to_defaults(self):
        self._write("{not json")
        self.assertFalse(TS.load_trading_session()["enabled"])

    def test_unreadable_file_falls_back_to_defaults(self):
        self.file.mkdir(parents=True, exist_ok=True)      # 目录冒充文件 ⇒ OSError
        self.assertFalse(TS.load_trading_session()["enabled"])

    def test_non_object_payload_falls_back_instead_of_raising(self):
        """⚠️ 与 `schedule_store` 的差异（有意为之）：那侧对 JSON 数组会 `TypeError` 上抛，
        而本文件的读者是**每 15 分钟一起的交易进程** —— 抛出去就是整周期崩掉。"""
        for text in ("[1, 2, 3]", '"just a string"', "42", "null"):
            with self.subTest(text=text):
                self._write(text)
                self.assertFalse(TS.load_trading_session()["enabled"])

    def test_partial_payload_is_merged_with_defaults(self):
        self._write(json.dumps({"enabled": True, "windows": [{"start": "09:00", "end": "11:00"}]}))
        loaded = TS.load_trading_session()
        self.assertTrue(loaded["enabled"])
        self.assertEqual(loaded["mode_outside"], "manage_only", "未提及的键回落默认")
        self.assertEqual(len(loaded["windows"]), 1)

    def test_extra_keys_are_preserved_for_forward_compatibility(self):
        self._write(json.dumps({"future_feature": {"enabled": True}}))
        self.assertEqual(TS.load_trading_session()["future_feature"], {"enabled": True})


class SaveTests(_Base):
    def test_round_trip_and_on_disk_format(self):
        payload = {"enabled": True, "mode_outside": "off",
                   "windows": [{"days": [0, 1], "start": "21:30", "end": "04:00"}],
                   "note": "中文原样"}
        TS.save_trading_session(payload)
        text = self.file.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertIn("\n  ", text, "必须是 indent=2 的可读格式")
        self.assertIn("中文原样", text, "ensure_ascii=False ⇒ 中文不转义")
        self.assertEqual(json.loads(text), payload)

    def test_save_writes_verbatim_without_normalising(self):
        """归一化**不在** store 侧：这是"校验口径 == 运行口径"的前提。"""
        TS.save_trading_session({"enabled": True, "windows": [{"start": "7:5", "end": "9:5"}]})
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8"))["windows"],
                         [{"start": "7:5", "end": "9:5"}])

    def test_parent_directory_is_created(self):
        self.assertFalse(self.file.parent.exists())
        TS.save_trading_session({"enabled": False})
        self.assertTrue(self.file.exists())

    def test_no_temp_files_are_left_behind(self):
        TS.save_trading_session({"enabled": True})
        self.assertEqual(list(self.file.parent.glob(".trading-session-*.tmp")), [])

    def test_failed_replace_still_cleans_the_temp_file(self):
        with mock.patch.object(TS.os, "replace", side_effect=OSError("磁盘满了")):
            with self.assertRaises(OSError):
                TS.save_trading_session({"enabled": True})
        self.assertEqual(list(self.file.parent.glob(".trading-session-*.tmp")), [],
                         "失败路径不得留下半截临时文件")
        self.assertFalse(self.file.exists())

    def test_write_failure_inside_the_file_handle_also_cleans_up(self):
        with mock.patch.object(TS.os, "fsync", side_effect=OSError("fsync 失败")):
            with self.assertRaises(OSError):
                TS.save_trading_session({"enabled": True})
        self.assertEqual(list(self.file.parent.glob(".trading-session-*.tmp")), [])

    def test_overwrite_keeps_the_file_at_the_same_path(self):
        TS.save_trading_session({"enabled": True, "version": 1})
        TS.save_trading_session({"enabled": True, "version": 2})
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8"))["version"], 2)
        self.assertEqual(list(self.file.parent.glob("*.json")), [self.file])


class DefaultSessionShapeTest(unittest.TestCase):
    def test_default_session_matches_the_pure_module(self):
        """默认值单一事实源：store 与 `scripts/trader/session.py` 不得漂移。"""
        from scripts.trader import session as S
        self.assertEqual(TS.default_session(), S.DEFAULT_SESSION)


if __name__ == "__main__":
    unittest.main()
