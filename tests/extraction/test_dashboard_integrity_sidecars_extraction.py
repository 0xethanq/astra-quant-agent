"""`astra_backend/dashboard_payload/integrity_sidecars.py`（B3 第二十七刀）回归。

## 这个测试在守什么

`data_health.status` 只有 `LIVE` / `PARTIAL` 两态，判据是 **`source_errors` 是否为空**。
于是"数据不全"必须**主动变成一条 source_error** —— 否则面板以「完整」示人。
历史上两次真实故障都是这个形态（台账逐所失败不可见、AI 连败 14 轮巡检仍全绿）。

故本文件钉住的是**"不可见性"的防线**，四处易错点：

| # | 细节 | 错了会怎样 |
|---|---|---|
| 1 | 新鲜度窗口 **2700 秒**，按 `generated_at` **自带时区**比较 | 用本地时间裸减会因时区差误判新鲜度 |
| 2 | `failed` 与 `truncated` 是 **`elif`** | 同一所报两条，前端重复告警 |
| 3 | 原因串截断到 **120 字符** | 整段异常正文灌进载荷 |
| 4 | AI 阈值是 **`>= 2`** | 单次抖动就降 PARTIAL（误报） |

## 为什么这些"尽力而为"的路径更值得测

两段都被 `except Exception: pass` 包着 —— **出错时静默**。静默路径最容易被
"改坏了也没人知道"，且它们的输出（少一条 error）恰恰是**面板说真话的唯一依据**。
"""

from __future__ import annotations

import ast
import datetime
import json
import tempfile
import unittest
from pathlib import Path

from astra_backend.dashboard_payload.integrity_sidecars import (
    AI_CONSECUTIVE_FAILURE_THRESHOLD,
    LEDGER_STALE_SECONDS,
    REASON_TRUNCATE,
    merge_ai_health_failures,
    merge_all_integrity_sidecars,
    merge_ledger_sync_status,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "astra_backend" / "dashboard_payload" / "integrity_sidecars.py"

BJ = datetime.timezone(datetime.timedelta(hours=8))


def _iso(dt: datetime.datetime) -> str:
    return dt.isoformat()


class _FrozenDatetime:
    """`datetime` 注入用的替身：只提供被测代码真正用到的两件事。

    ⚠️ `datetime` 在本模块是**函数参数**（由门面调用期注入），不是模块属性 ——
    所以**不能** `patch.object(module, "datetime")`（我第一版就这么写，
    三条用例直接 AttributeError）。要控时间就得**传一个替身进去**。
    """

    def __init__(self, now: datetime.datetime):
        self._now = now
        self.datetime = self          # 让 `datetime.datetime` 指回自己

    def fromisoformat(self, value):
        return datetime.datetime.fromisoformat(value)

    def now(self, tz=None):
        return self._now if tz is None else self._now.astimezone(tz)


class _TmpDir(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.dir = self._td.name

    def _write(self, name, payload):
        p = Path(self.dir) / name
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return p


class LedgerFreshnessTest(_TmpDir):
    NOW = datetime.datetime(2026, 9, 14, 16, 0, tzinfo=BJ)

    def _now(self):
        return self.NOW

    def _dt(self):
        """冻结的 `datetime` 替身。**所有**用例都该用它 —— 用真实 datetime 会让
        用例随时间变红（本文件实测过：16:0x 绿、16:5x 红）。"""
        return _FrozenDatetime(self.NOW)

    def test_fresh_status_is_merged(self):
        """⚠️ 必须**冻住时间**，不能依赖真实 `datetime`。

        我第一版写的是「`generated_at = self._now()`（固定的 16:00）+ 真实
        `datetime`」。那么这条用例在 **16:45 之前跑是绿的、之后变红** ——
        因为固定的 16:00 会超出 2700 秒（45 分钟）窗口。

        它当时确实绿着通过了（我跑那次是 16:0x），随后在 16:5x 的全量套件里翻红。
        **一条随墙上时钟变色的测试，比没有测试更糟**：它会让人怀疑无关的改动。
        故改为注入 `_FrozenDatetime`，与该类其他用例一致。
        """
        self._write("ledger_sync_status.json", {
            "generated_at": _iso(self._now()),
            "venues": {"binance": {"status": "failed", "reason": "boom"}},
        })
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir,
                                 datetime=_FrozenDatetime(self._now()))
        self.assertEqual(len(errs), 1)
        self.assertIn("ledger-binance", errs[0])
        self.assertIn("台账同步失败", errs[0])
        self.assertIn("boom", errs[0])

    def test_exactly_at_the_window_is_still_fresh(self):
        """`<= 2700` 是**含**边界。"""
        gen = self._now() - datetime.timedelta(seconds=LEDGER_STALE_SECONDS)
        self._write("ledger_sync_status.json", {
            "generated_at": _iso(gen),
            "venues": {"binance": {"status": "failed", "reason": "x"}},
        })
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir,
                                 datetime=_FrozenDatetime(self._now()))
        self.assertEqual(len(errs), 1, "恰好 2700 秒应仍算新鲜")

    def test_one_second_over_the_window_is_skipped(self):
        gen = self._now() - datetime.timedelta(seconds=LEDGER_STALE_SECONDS + 1)
        self._write("ledger_sync_status.json", {
            "generated_at": _iso(gen),
            "venues": {"binance": {"status": "failed", "reason": "x"}},
        })
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir,
                                 datetime=_FrozenDatetime(self._now()))
        self.assertEqual(errs, [], "过旧应整段跳过（由台账文件新鲜度通道兜底 STALE）")

    def test_timezone_offset_is_respected(self):
        """`generated_at` 带 +08:00，与 UTC 的同一时刻必须等价。

        若实现按"本地时间裸减"（忽略 tzinfo），8 小时时差会让 45 分钟窗口
        永远判错：UTC 表示会被当成"8 小时前"→ 跳过，于是**告警永远不出现**。
        """
        now_bj = self._now()
        # 同一时刻用 UTC 表示，字符串形态不同、时刻相同
        gen_utc = now_bj.astimezone(datetime.timezone.utc) - datetime.timedelta(minutes=1)
        self._write("ledger_sync_status.json", {
            "generated_at": _iso(gen_utc),
            "venues": {"gate": {"status": "failed", "reason": "utc-form"}},
        })
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir,
                                 datetime=_FrozenDatetime(now_bj))
        self.assertEqual(len(errs), 1,
                         "按 tzinfo 比较时，UTC 表示的 1 分钟前应判新鲜")

    def test_unparsable_generated_at_skips_whole_block(self):
        self._write("ledger_sync_status.json", {
            "generated_at": "not-a-date",
            "venues": {"binance": {"status": "failed", "reason": "x"}},
        })
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir,
                                 datetime=_FrozenDatetime(self._now()))
        self.assertEqual(errs, [], "generated_at 解析失败 → 整段跳过（_fresh=False）")

    def test_missing_generated_at_skips(self):
        self._write("ledger_sync_status.json",
                    {"venues": {"binance": {"status": "failed", "reason": "x"}}})
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir,
                                 datetime=_FrozenDatetime(self._now()))
        self.assertEqual(errs, [])


class LedgerVenueSemanticsTest(_TmpDir):
    #: 冻住的时刻 —— 别用真实 `datetime.now()`：那会让这些用例随时间变红（见
    #: LedgerFreshnessTest.test_fresh_status_is_merged 的教训）。
    NOW = datetime.datetime(2026, 9, 14, 16, 0, tzinfo=BJ)

    def _fresh(self, venues):
        self._write("ledger_sync_status.json", {
            "generated_at": _iso(self.NOW),
            "venues": venues,
        })

    def _dt(self):
        return _FrozenDatetime(self.NOW)

    def test_failed_and_truncated_are_elif(self):
        """同一所同时标 failed 与 truncated 时**只报一条**（failed 优先）。"""
        self._fresh({"binance": {"status": "failed", "reason": "r",
                                 "truncated": True}})
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir, datetime=self._dt())
        self.assertEqual(len(errs), 1, "不得报两条")
        self.assertIn("台账同步失败", errs[0])
        self.assertNotIn("分页未取尽", errs[0])

    def test_truncated_flag_reported(self):
        self._fresh({"gate": {"status": "ok", "truncated": True}})
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir, datetime=self._dt())
        self.assertEqual(len(errs), 1)
        self.assertIn("ledger-gate", errs[0])
        self.assertIn("历史分页未取尽", errs[0])

    def test_truncated_at_also_triggers(self):
        self._fresh({"gate": {"status": "ok", "truncated_at": "2026-09-14"}})
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir, datetime=self._dt())
        self.assertEqual(len(errs), 1)
        self.assertIn("历史分页未取尽", errs[0])

    def test_ok_venue_reports_nothing(self):
        self._fresh({"gate": {"status": "ok"}})
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir, datetime=self._dt())
        self.assertEqual(errs, [])

    def test_non_dict_venue_entry_is_skipped(self):
        self._fresh({"gate": "not-a-dict", "binance": None})
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir, datetime=self._dt())
        self.assertEqual(errs, [])

    def test_multiple_failed_venues_all_reported(self):
        self._fresh({"binance": {"status": "failed", "reason": "b"},
                     "gate": {"status": "failed", "reason": "g"}})
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir, datetime=self._dt())
        self.assertEqual(len(errs), 2)
        self.assertTrue(any("ledger-binance" in e for e in errs))
        self.assertTrue(any("ledger-gate" in e for e in errs))

    def test_missing_venues_key(self):
        self._write("ledger_sync_status.json",
                    {"generated_at": _iso(datetime.datetime.now(BJ))})
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir, datetime=self._dt())
        self.assertEqual(errs, [])


class TruncationTest(_TmpDir):
    def test_reason_truncated_to_120(self):
        long_reason = "X" * 500
        self._write("ledger_sync_status.json", {
            "generated_at": _iso(datetime.datetime.now(BJ)),
            "venues": {"binance": {"status": "failed", "reason": long_reason}},
        })
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir, datetime=datetime)
        self.assertEqual(len(errs), 1)
        self.assertNotIn("X" * (REASON_TRUNCATE + 1), errs[0],
                         "原因串超过 120 字符必须被截断")
        self.assertIn("X" * REASON_TRUNCATE, errs[0])

    def test_ai_last_error_truncated(self):
        self._write("ai_health.json",
                    {"consecutive_failures": 5, "last_error": "E" * 500})
        errs: list[str] = []
        merge_ai_health_failures(errs, self.dir)
        self.assertEqual(len(errs), 1)
        self.assertNotIn("E" * (REASON_TRUNCATE + 1), errs[0])
        self.assertIn("E" * REASON_TRUNCATE, errs[0])


class AiHealthTest(_TmpDir):
    def _write_cf(self, n, last_error="boom"):
        self._write("ai_health.json",
                    {"consecutive_failures": n, "last_error": last_error})

    def test_threshold_is_two(self):
        self.assertEqual(AI_CONSECUTIVE_FAILURE_THRESHOLD, 2)

    def test_one_failure_is_not_reported(self):
        """**单次失败是瞬时抖动**，不降 PARTIAL。"""
        self._write_cf(1)
        errs: list[str] = []
        merge_ai_health_failures(errs, self.dir)
        self.assertEqual(errs, [], "连续 1 轮不应报")

    def test_two_failures_reported(self):
        self._write_cf(2)
        errs: list[str] = []
        merge_ai_health_failures(errs, self.dir)
        self.assertEqual(len(errs), 1)
        self.assertIn("AI决策链连续2轮失败", errs[0])
        self.assertIn("boom", errs[0])
        self.assertIn("本轮无新指令", errs[0])

    def test_zero_failures(self):
        self._write_cf(0)
        errs: list[str] = []
        merge_ai_health_failures(errs, self.dir)
        self.assertEqual(errs, [])

    def test_missing_consecutive_failures_key(self):
        self._write("ai_health.json", {"last_error": "x"})
        errs: list[str] = []
        merge_ai_health_failures(errs, self.dir)
        self.assertEqual(errs, [], "缺键应视作 0")

    def test_non_numeric_consecutive_failures_is_silent(self):
        """`int("abc")` 抛 ValueError → 被外层 except 吞掉，不追加。"""
        self._write("ai_health.json",
                    {"consecutive_failures": "abc", "last_error": "x"})
        errs: list[str] = []
        merge_ai_health_failures(errs, self.dir)
        self.assertEqual(errs, [])


class BestEffortTest(_TmpDir):
    """两段都必须是"尽力而为"：任何异常都不得冒出，也不得污染 source_errors。"""

    def test_missing_files_are_silent(self):
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir, datetime=datetime)
        merge_ai_health_failures(errs, self.dir)
        self.assertEqual(errs, [])

    def test_corrupt_json_is_silent(self):
        (Path(self.dir) / "ledger_sync_status.json").write_text("{not json", encoding="utf-8")
        (Path(self.dir) / "ai_health.json").write_text("]]]", encoding="utf-8")
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir, datetime=datetime)
        merge_ai_health_failures(errs, self.dir)
        self.assertEqual(errs, [])

    def test_nonexistent_dir_is_silent(self):
        errs: list[str] = []
        merge_ledger_sync_status(errs, "/nonexistent-xyz", datetime=datetime)
        merge_ai_health_failures(errs, "/nonexistent-xyz")
        self.assertEqual(errs, [])

    def test_json_list_instead_of_dict_is_silent(self):
        self._write("ai_health.json", [1, 2, 3])
        errs: list[str] = []
        merge_ai_health_failures(errs, self.dir)
        self.assertEqual(errs, [])

    def test_missing_ledger_file_is_silent_even_without_guard(self):
        """**缺文件必须静默** —— 这是契约；`os.path.exists()` 守卫则**不承重**。

        负向验证实测：把 `os.path.exists(_lss)` 去掉后测试**不翻红** ——
        因为 `open()` 抛的 `FileNotFoundError` 被同一层 `except Exception` 吞掉，
        行为完全一致。所以那条守卫是**冗余的**（保留无害，少一次异常往返）。

        本条钉的是**契约本身**（缺文件 → 无 error、无异常），而不是守卫的存在。
        这样即便后人删掉守卫，契约仍被守住；而若有人删掉**外层 except**，
        契约被破坏 → 本条会红。
        """
        errs: list[str] = []
        merge_ledger_sync_status(errs, self.dir, datetime=datetime)
        self.assertEqual(errs, [])

    def test_appends_to_existing_errors(self):
        errs = ["pre-existing"]
        merge_all_integrity_sidecars(errs, self.dir, datetime=datetime)
        self.assertEqual(errs, ["pre-existing"], "原地 append，不清空既有条目")


class OrderTest(_TmpDir):
    def test_both_sidecars_in_original_order(self):
        """台账在先、AI 在后 —— 顺序即前端展示顺序。"""
        self._write("ledger_sync_status.json", {
            "generated_at": _iso(datetime.datetime.now(BJ)),
            "venues": {"binance": {"status": "failed", "reason": "led"}},
        })
        self._write("ai_health.json",
                    {"consecutive_failures": 3, "last_error": "ai"})
        errs: list[str] = []
        merge_all_integrity_sidecars(errs, self.dir, datetime=datetime)
        self.assertEqual(len(errs), 2)
        self.assertIn("ledger-binance", errs[0])
        self.assertIn("ai-inference", errs[1])


class WiringTest(unittest.TestCase):
    APP = ROOT / "astra_backend" / "dashboard_cache.py"

    def test_impl_in_submodule_not_facade(self):
        app_src = self.APP.read_text(encoding="utf-8")
        mod_src = MODULE.read_text(encoding="utf-8")
        for fn in ("merge_ledger_sync_status", "merge_ai_health_failures",
                   "merge_all_integrity_sidecars"):
            self.assertIn(f"def {fn}(", mod_src)
            self.assertNotIn(f"def {fn}(", app_src)
        self.assertIn("_core_merge_all_integrity_sidecars(source_errors, DATA_DIR, datetime=datetime)",
                      app_src)

    def test_facade_no_longer_contains_inline_blocks(self):
        app_src = self.APP.read_text(encoding="utf-8")
        for gone in ("ledger_sync_status.json", "ai_health.json",
                     "台账同步失败", "AI决策链连续"):
            self.assertNotIn(gone, app_src, f"门面仍残留内联片段 {gone!r}")

    def test_datetime_and_data_dir_are_injected(self):
        """`datetime` 必须调用期注入（门面同名名字会被测试重定向）。"""
        mod_src = MODULE.read_text(encoding="utf-8")
        tree = ast.parse(mod_src)
        top_imports = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_imports |= {a.asname or a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                top_imports |= {a.asname or a.name for a in node.names}
        self.assertNotIn("datetime", top_imports,
                         "不得 import datetime 模块名（会遮蔽门面注入的 datetime）")

    def test_module_does_not_import_dashboard(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertFalse(a.name.startswith("astra_backend.dashboard_cache"))
            elif isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith("astra_backend.dashboard_cache"))

    def test_constants_are_named_not_magic(self):
        """2700 / 2 / 120 三个魔数须具名 —— 它们是行为契约的一部分。"""
        self.assertEqual(LEDGER_STALE_SECONDS, 2700)
        self.assertEqual(AI_CONSECUTIVE_FAILURE_THRESHOLD, 2)
        self.assertEqual(REASON_TRUNCATE, 120)


if __name__ == "__main__":
    unittest.main()
