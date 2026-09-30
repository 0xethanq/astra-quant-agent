"""Prompt Cache Warmer 测试（2026-09-29 重写后）。

事故形状（旧实现为什么必然 0 命中，逐字记在这里免得再犯）：

- 预热发的是 `scripts.ai_brain_trader.SYSTEM_PROMPT`（base 版，8165 字符），
  而生产真正发送的是 `get_effective_system_prompt()` —— 两者在**第 4460 个字符**处
  就分歧（profile 模块文本替换）。前缀缓存要求逐字节相同的前缀，而上游按
  ~4092 token（≈6500 字符）**分块**上报，第一块整块落在分歧点之后 ⇒
  预热前缀永远匹配不上生产的第一块，日志里 4 条全是 `缓存: 0/4940`，白烧请求。
- 同时实测：缓存寿命只有分钟级（间隔 2 分钟命中、5 分钟已出现过期），trader 周期
  15 分钟 ⇒ 每轮必然冷启；可缓存上限只有稳定头 7.7k token 的一块（≈4076），
  而够长的预热请求必须为不可缓存的尾巴付全价 ⇒ **预热比省下的还贵**。

故默认 `off`（零网络请求），`jit` 只是被遥测盯着的实验模式。
"""
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import astra_gateway.cache_warmer as cw

#: 生产快照的真实格式（`scripts/brain/cycle_parts.py::build_effective_prompt_text`）。
SYSTEM_BODY = "系统正文与硬约束。" * 800
USER_HEAD = "静态任务说明与长期记忆。" * 700
DYNAMIC_TAIL = "【全网实时重大快讯与宏观情报】\n本轮快讯随时变，不可缓存。\n"


def _write_snapshot(directory: str, *, mtime: float | None = None, mtime_ago: float = 0.0) -> Path:
    path = Path(directory) / "ai_brain_last_prompt.txt"
    path.write_text(
        f"【SYSTEM PROMPT】：\n{SYSTEM_BODY.strip()}"
        f"\n\n{'=' * 70}\n"
        f"【USER PROMPT (2026-09-29 15:15:22)】：\n{USER_HEAD.strip()}\n{DYNAMIC_TAIL}",
        encoding="utf-8",
    )
    if mtime is not None or mtime_ago:
        stamp = mtime if mtime is not None else time.time() - mtime_ago
        os.utime(path, (stamp, stamp))
    return path


class SnapshotPrefixTests(unittest.TestCase):
    def test_extracts_system_and_stable_head(self):
        with TemporaryDirectory() as td:
            path = _write_snapshot(td)
            prefix = cw.load_snapshot_prefix(path=path)
        self.assertIsNotNone(prefix)
        self.assertEqual(prefix["system"], SYSTEM_BODY.strip(), "分隔线必须被剥掉（请求体里没有它）")
        self.assertEqual(prefix["user"], USER_HEAD.strip())
        self.assertNotIn("快讯", prefix["user"], "动态段绝不进前缀")

    def test_prefix_is_a_literal_prefix_of_the_snapshot_payload(self):
        """真前缀的硬契约：`user` 必须是快照正文的字面前缀，`system` 必须原样出现在其中。

        这正是旧实现违反的那一条（它发的是 base SYSTEM_PROMPT，4460 字符后即分歧）。
        """
        with TemporaryDirectory() as td:
            path = _write_snapshot(td)
            prefix = cw.load_snapshot_prefix(path=path)
            raw = path.read_text(encoding="utf-8")
        body = raw.split(cw.USER_MARKER, 1)[1].split("\n", 1)[1]
        self.assertTrue(body.startswith(prefix["user"]))
        self.assertIn(prefix["system"], raw)

    def test_missing_or_stale_snapshot_yields_none(self):
        with TemporaryDirectory() as td:
            self.assertIsNone(cw.load_snapshot_prefix(path=Path(td) / "nope.txt"))
            stale = _write_snapshot(td, mtime_ago=cw.SNAPSHOT_MAX_AGE_SECONDS + 60)
            self.assertIsNone(cw.load_snapshot_prefix(path=stale), "陈旧快照宁可不预热")

    def test_short_prefix_yields_none(self):
        """实测 5.4k token 以下的上游前缀完全不触发缓存 ⇒ 太短就别发请求。"""
        with TemporaryDirectory() as td:
            path = Path(td) / "short.txt"
            path.write_text("【SYSTEM PROMPT】：\n短\n\n【USER PROMPT (x)】：\n也短\n", encoding="utf-8")
            self.assertIsNone(cw.load_snapshot_prefix(path=path))


class WarmupPolicyTests(unittest.TestCase):
    def setUp(self):
        cw._last_warmed_slot = -1
        cw._consecutive_misses = 0
        cw._breaker_tripped = False
        cw._breaker_logged = False
        cw._drift_logged = False
        patcher = patch.object(cw, "_persist_status", lambda status: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_mode_is_off_and_sends_nothing(self):
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("ASTRA_CACHE_WARMUP_MODE", None)
            with patch.object(cw, "send_cache_warmup_ping") as ping:
                self.assertEqual(cw.warmup_mode(), "off")
                self.assertFalse(cw.check_and_warmup_cache(now=1000.0))
                ping.assert_not_called()

    def test_unknown_mode_falls_back_to_off(self):
        with patch.dict("os.environ", {"ASTRA_CACHE_WARMUP_MODE": "always-on-please"}):
            self.assertEqual(cw.warmup_mode(), "off")

    def test_jit_only_fires_inside_the_lead_window(self):
        base = 1_800_000_000 - (1_800_000_000 % cw.TRADER_INTERVAL_SECONDS)
        with TemporaryDirectory() as td:
            # 快照 mtime 必须落在同一条合成时间轴上，否则 "陈旧" 判定会把用例弄假红
            path = _write_snapshot(td, mtime=base)
            env = {"ASTRA_CACHE_WARMUP_MODE": "jit", "ASTRA_CACHE_WARMUP_LEAD_SECONDS": "90",
                   "ASTRA_CACHE_WARMUP_REPEATS": "1"}
            with patch.dict("os.environ", env), \
                 patch.object(cw, "SNAPSHOT_FILE", path), \
                 patch.object(cw, "send_cache_warmup_ping",
                              return_value={"ok": True, "cached_tokens": 4076}) as ping:
                self.assertFalse(cw.check_and_warmup_cache(now=base + 10),
                                 "槽位刚开始时不该预热")
                ping.assert_not_called()
                self.assertTrue(cw.check_and_warmup_cache(now=base + cw.TRADER_INTERVAL_SECONDS - 60))
                self.assertEqual(ping.call_count, 1)
                # 同一槽位只允许一次
                self.assertFalse(cw.check_and_warmup_cache(now=base + cw.TRADER_INTERVAL_SECONDS - 30))
                self.assertEqual(ping.call_count, 1)
                # 下一个槽位可以再来一次
                self.assertTrue(cw.check_and_warmup_cache(
                    now=base + 2 * cw.TRADER_INTERVAL_SECONDS - 60))
                self.assertEqual(ping.call_count, 2)

    def test_jit_without_usable_snapshot_sends_nothing(self):
        base = 1_800_000_000 - (1_800_000_000 % cw.TRADER_INTERVAL_SECONDS)
        env = {"ASTRA_CACHE_WARMUP_MODE": "jit", "ASTRA_CACHE_WARMUP_LEAD_SECONDS": "90"}
        with TemporaryDirectory() as td, patch.dict("os.environ", env), \
             patch.object(cw, "SNAPSHOT_FILE", Path(td) / "missing.txt"), \
             patch.object(cw, "send_cache_warmup_ping") as ping:
            self.assertFalse(cw.check_and_warmup_cache(now=base + cw.TRADER_INTERVAL_SECONDS - 10))
            ping.assert_not_called()

    def test_breaker_stops_after_consecutive_misses(self):
        base = 1_800_000_000 - (1_800_000_000 % cw.TRADER_INTERVAL_SECONDS)
        with TemporaryDirectory() as td:
            path = _write_snapshot(td, mtime=base)
            env = {"ASTRA_CACHE_WARMUP_MODE": "jit", "ASTRA_CACHE_WARMUP_LEAD_SECONDS": "90",
                   "ASTRA_CACHE_WARMUP_REPEATS": "1", "ASTRA_CACHE_WARMUP_MAX_MISSES": "2"}
            with patch.dict("os.environ", env), patch.object(cw, "SNAPSHOT_FILE", path), \
                 patch.object(cw, "send_cache_warmup_ping",
                              return_value={"ok": True, "cached_tokens": 0, "cache_reported": True}) as ping:
                cw.check_and_warmup_cache(now=base + cw.TRADER_INTERVAL_SECONDS - 60)
                cw.check_and_warmup_cache(now=base + 2 * cw.TRADER_INTERVAL_SECONDS - 60)
                self.assertEqual(ping.call_count, 2)
                self.assertTrue(cw._breaker_tripped, "连续非命中必须熔断")
                self.assertFalse(cw.check_and_warmup_cache(now=base + 3 * cw.TRADER_INTERVAL_SECONDS - 60))
                self.assertEqual(ping.call_count, 2, "熔断后一个请求都不许再发")

    def test_hit_resets_the_miss_counter(self):
        base = 1_800_000_000 - (1_800_000_000 % cw.TRADER_INTERVAL_SECONDS)
        with TemporaryDirectory() as td:
            path = _write_snapshot(td, mtime=base)
            env = {"ASTRA_CACHE_WARMUP_MODE": "jit", "ASTRA_CACHE_WARMUP_LEAD_SECONDS": "90",
                   "ASTRA_CACHE_WARMUP_REPEATS": "1", "ASTRA_CACHE_WARMUP_MAX_MISSES": "2"}
            with patch.dict("os.environ", env), patch.object(cw, "SNAPSHOT_FILE", path), \
                 patch.object(cw, "send_cache_warmup_ping",
                              side_effect=[{"ok": True, "cached_tokens": 0, "cache_reported": True},
                                           {"ok": True, "cached_tokens": 4076, "cache_reported": True},
                                           {"ok": True, "cached_tokens": 0, "cache_reported": True}]):
                for i in range(1, 4):
                    cw.check_and_warmup_cache(now=base + i * cw.TRADER_INTERVAL_SECONDS - 60)
        self.assertFalse(cw._breaker_tripped, "中间命中过 ⇒ 计数归零")


class SendPingTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(cw, "_persist_status", lambda status: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.prefix = {"system": SYSTEM_BODY.strip(), "user": USER_HEAD.strip(),
                       "payload_chars": len(SYSTEM_BODY) + len(USER_HEAD)}

    @patch("astra_backend.llm_manager.get_active_llm_runtime")
    def test_missing_runtime_is_reported_without_sending(self, mock_runtime):
        mock_runtime.return_value = {}
        res = cw.send_cache_warmup_ping(prefix=self.prefix)
        self.assertFalse(res["ok"])
        self.assertIn("No active LLM", res["reason"])

    def test_no_snapshot_prefix_means_no_request(self):
        with patch.object(cw, "load_snapshot_prefix", return_value=None), \
             patch("astra_backend.llm_manager.get_active_llm_runtime") as runtime:
            res = cw.send_cache_warmup_ping()
            runtime.assert_not_called()
        self.assertFalse(res["ok"])
        self.assertIn("snapshot", res["reason"])


if __name__ == "__main__":
    unittest.main()
