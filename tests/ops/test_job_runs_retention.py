r"""作业历史保留策略门（第一百四十刀）。

## 背景

`data/astra_gateway.db` 的 `job_runs` **没有任何自动清理机制**：`factor_library` 每分钟
跑一次，15 天就累计 19,215 / 22,521 行、DB 涨到 **23.5M**（实测）。用户确认加保留策略，
默认窗口 **7 天**，`ASTRA_JOB_RUNS_KEEP_DAYS` 可覆盖。

## 本门钉住的四条边界（每条都有理由，勿放宽）

1. **绝不删 `running` 行**，哪怕它很老 —— worker 启动时靠 `recover_stale_job_runs()`
   把僵尸 running 行收编为 interrupted；删掉等于销毁"进程崩过"的证据、面板「运行中」失真；
2. **只动 `job_runs`** —— `events` / `deliveries` / `model_calls` 各有消费方；
3. **窗口内的行不许动**；
4. **窗口必须是正数** —— `keep_days<=0` 会清空历史，直接拒绝（抛 ValueError）。

另钉两条工程性质：**幂等**（连跑两次第二次删 0 行）、**worker 真的挂了清理**
（启动一次 + 每 6 小时一次，失败不影响调度）。
"""
from __future__ import annotations

import ast
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from astra_gateway.store import BJ_TZ, GatewayStore  # noqa: E402


class PruneJobRunsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "gw.db"
        self.store = GatewayStore(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def _ts(self, days: float) -> str:
        return (datetime.now(BJ_TZ) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    def _insert_run(self, name: str, status: str, days: float) -> None:
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO job_runs(job_name,status,started_at) VALUES (?,?,?)",
                      (name, status, self._ts(days)))

    def _rows(self):
        with sqlite3.connect(self.db) as c:
            return c.execute("SELECT job_name,status,started_at FROM job_runs ORDER BY id").fetchall()

    def test_prunes_only_finished_rows_beyond_window(self):
        self._insert_run("factor_library", "success", 30)   # 超期已结束 ⇒ 删
        self._insert_run("trader", "success", 10)           # 超期已结束 ⇒ 删
        self._insert_run("stuck", "running", 20)            # 超期但仍在跑 ⇒ **留**
        self._insert_run("trader", "success", 1)            # 窗口内 ⇒ 留
        result = self.store.prune_job_runs(keep_days=7)
        self.assertEqual(result["deleted"], 2)
        rows = self._rows()
        kept = sorted((r[0], r[1]) for r in rows)
        self.assertEqual(kept, [("stuck", "running"), ("trader", "success")],
                         "保留集不对：窗口内的行与 running 行都必须留，其余删除")
        self.assertTrue(any(r[1] == "running" for r in rows), "running 行被误删！")

    def test_other_tables_untouched(self):
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO events(event_id,event_type,title,message,payload_json,"
                      "priority,created_at) VALUES ('e-old','t','T','M','{}',1,?)", (self._ts(90),))
            c.execute("INSERT INTO runtime_state(key,value) VALUES ('k','v')")
        self._insert_run("factor_library", "success", 90)
        self.store.prune_job_runs(keep_days=7)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1,
                             "events 不该被清理")
            self.assertEqual(c.execute("SELECT COUNT(*) FROM runtime_state").fetchone()[0], 1,
                             "runtime_state 不该被清理")

    def test_idempotent(self):
        self._insert_run("factor_library", "success", 30)
        self.assertEqual(self.store.prune_job_runs(keep_days=7)["deleted"], 1)
        self.assertEqual(self.store.prune_job_runs(keep_days=7)["deleted"], 0)

    def test_non_positive_window_is_refused(self):
        for bad in (0, -1):
            with self.subTest(keep_days=bad):
                with self.assertRaises(ValueError):
                    self.store.prune_job_runs(keep_days=bad)

    def test_default_window_is_seven_days(self):
        self._insert_run("factor_library", "success", 8)     # 默认 7 天 ⇒ 删
        self._insert_run("factor_library", "success", 6)     # ⇒ 留
        result = self.store.prune_job_runs()
        self.assertEqual(result["keep_days"], 7)
        self.assertEqual(result["deleted"], 1)

    def test_env_override(self):
        self._insert_run("factor_library", "success", 5)
        old = os.environ.get("ASTRA_JOB_RUNS_KEEP_DAYS")
        os.environ["ASTRA_JOB_RUNS_KEEP_DAYS"] = "3"
        try:
            result = self.store.prune_job_runs()
            self.assertEqual(result["keep_days"], 3)
            self.assertEqual(result["deleted"], 1, "3 天窗口应删掉 5 天前的行")
        finally:
            if old is None:
                os.environ.pop("ASTRA_JOB_RUNS_KEEP_DAYS", None)
            else:
                os.environ["ASTRA_JOB_RUNS_KEEP_DAYS"] = old

    def test_vacuum_can_be_skipped(self):
        self._insert_run("factor_library", "success", 30)
        result = self.store.prune_job_runs(keep_days=7, vacuum=False)
        self.assertEqual(result["deleted"], 1)
        self.assertFalse(result["vacuumed"])

    def test_vacuum_runs_after_deletion(self):
        for _ in range(200):
            self._insert_run("factor_library", "success", 30)
        result = self.store.prune_job_runs(keep_days=7)
        self.assertEqual(result["deleted"], 200)
        self.assertTrue(result["vacuumed"], "真删了行就应尝试 VACUUM 回收空间")


class WorkerWiringTest(unittest.TestCase):
    """清理必须真的挂在 worker 上，否则策略等于没生效。"""

    def _src(self) -> str:
        return (ROOT / "astra_gateway" / "worker.py").read_text(encoding="utf-8")

    def test_worker_prunes_on_start_and_periodically(self):
        src = self._src()
        self.assertIn("_prune_job_history(store)", src)
        self.assertIn("PRUNE_INTERVAL_SECONDS", src)
        tree = ast.parse(src)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_prune_job_history")
        body = ast.unparse(fn)
        self.assertIn("prune_job_runs", body)
        self.assertIn("except Exception", body, "维护动作必须自己吞异常，不能拖垮调度循环")
        interval = next(n for n in tree.body if isinstance(n, ast.Assign)
                        and getattr(n.targets[0], "id", "") == "PRUNE_INTERVAL_SECONDS")
        self.assertEqual(eval(compile(ast.Expression(interval.value), "<c>", "eval"), {}), 6 * 3600)


if __name__ == "__main__":
    unittest.main()
