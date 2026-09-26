"""SQLite-backed durable event and per-channel delivery queue."""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Any

from astra_gateway.events import GatewayEvent

BJ_TZ = timezone(timedelta(hours=8))
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  priority INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL REFERENCES events(event_id),
  channel TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL,
  last_error TEXT NOT NULL DEFAULT '',
  delivered_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(event_id, channel)
);
CREATE INDEX IF NOT EXISTS idx_deliveries_due ON deliveries(status, next_attempt_at);
CREATE TABLE IF NOT EXISTS job_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_name TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL DEFAULT '',
  return_code INTEGER,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_job_runs_name ON job_runs(job_name, id DESC);
CREATE TABLE IF NOT EXISTS runtime_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  caller TEXT NOT NULL,
  model TEXT NOT NULL,
  reasoning_effort TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  duration_ms INTEGER NOT NULL,
  input_chars INTEGER NOT NULL,
  output_chars INTEGER NOT NULL,
  prompt_fingerprint TEXT NOT NULL,
  prompt_transport TEXT NOT NULL DEFAULT 'python-direct',
  input_tokens INTEGER,
  output_tokens INTEGER,
  total_tokens INTEGER,
  error_type TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_model_calls_caller ON model_calls(caller, id DESC);
"""


class GatewayStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
        self._secure_files()

    def _secure_files(self) -> None:
        for candidate in (self.path, Path(str(self.path)+"-wal"), Path(str(self.path)+"-shm")):
            try:
                if candidate.exists(): candidate.chmod(0o600)
            except OSError: pass

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        self._secure_files()
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def publish(self, event: GatewayEvent, channels: list[str]) -> str:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event.event_id, event.event_type, event.title, event.message, json.dumps(event.payload, ensure_ascii=False), event.priority, event.created_at),
            )
            for channel in channels:
                connection.execute(
                    "INSERT OR IGNORE INTO deliveries(event_id, channel, next_attempt_at, created_at) VALUES (?, ?, ?, ?)",
                    (event.event_id, channel, event.created_at, event.created_at),
                )
        return event.event_id

    def claim_due(self, limit: int = 20, lease_seconds: int = 120) -> list[dict[str, Any]]:
        """领取到点投递；带**租约老化**（审计#11 2026-09-13）：领取同时把
        next_attempt_at 推到 now+lease，崩溃/被杀遗留的 'processing' 行在租约到期后
        可被重新领取——旧实现只在进程启动时 recover_processing() 一次性收编，
        运行中挂掉的行永久卡死（不重启就永不重投）。
        与慢发送的竞态按 at-least-once 语义容忍（重复投优于永久漏投）。"""
        now_dt = datetime.now(BJ_TZ)
        now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
        lease_until = (now_dt + timedelta(seconds=max(30, lease_seconds))).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT d.id, d.channel, d.attempts, e.* FROM deliveries d
                   JOIN events e ON e.event_id=d.event_id
                   WHERE (d.status IN ('pending','retry')
                          OR (d.status='processing' AND d.next_attempt_at<=?))
                     AND d.next_attempt_at<=?
                   ORDER BY e.priority DESC, d.id ASC LIMIT ?""",
                (now, now, limit),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                marks = ",".join("?" for _ in ids)
                connection.execute(
                    f"UPDATE deliveries SET status='processing', next_attempt_at=? WHERE id IN ({marks})",
                    [lease_until, *ids])
            return [dict(row) for row in rows]

    def complete(self, delivery_id: int, status: str = "delivered", detail: str = "") -> None:
        if status not in {"delivered", "accepted"}:
            raise ValueError("delivery completion status must be delivered or accepted")
        now = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as connection:
            connection.execute(
                "UPDATE deliveries SET status=?, delivered_at=?, last_error=? WHERE id=?",
                (status, now, detail[:1000] if status == "accepted" else "", delivery_id),
            )

    def fail(self, delivery_id: int, attempts: int, error: str, max_attempts: int = 6) -> None:
        new_attempts = attempts + 1
        status = "dead" if new_attempts >= max_attempts else "retry"
        delay = min(3600, 30 * (2 ** min(new_attempts - 1, 7)))
        next_at = (datetime.now(BJ_TZ) + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as connection:
            connection.execute(
                "UPDATE deliveries SET status=?, attempts=?, next_attempt_at=?, last_error=? WHERE id=?",
                (status, new_attempts, next_at, error[:1000], delivery_id),
            )

    def recover_processing(self) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE deliveries SET status='retry' WHERE status='processing'")

    def replay_dead(self, delivery_id: int) -> bool:
        now = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE deliveries SET status='pending', attempts=0, next_attempt_at=?, last_error='', delivered_at='' WHERE id=? AND status='dead'",
                (now, delivery_id),
            )
            return cursor.rowcount == 1

    def begin_job(self, job_name: str) -> int:
        now = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as connection:
            cursor = connection.execute("INSERT INTO job_runs(job_name,status,started_at) VALUES (?,'running',?)", (job_name, now))
            return int(cursor.lastrowid)

    def recover_stale_job_runs(self) -> int:
        """审计#12(2026-09-13)：worker 被杀/崩溃时 running 行无人收尾——面板「运行中」
        永久假亮。新 worker 启动时收编为 interrupted（诚实标注，不冒充 success/failed）。"""
        now = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE job_runs SET status='interrupted', finished_at=?, detail='进程终止未收尾——worker 启动时收编僵尸 running 行'"
                " WHERE status='running'", (now,))
            return cursor.rowcount

    def finish_job(self, run_id: int, return_code: int, detail: str) -> None:
        now = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
        status = "success" if return_code == 0 else "failed"
        with self.connect() as connection:
            connection.execute(
                "UPDATE job_runs SET status=?, finished_at=?, return_code=?, detail=? WHERE id=?",
                (status, now, return_code, detail[-2000:], run_id),
            )

    def prune_job_runs(self, keep_days: int | None = None,
                       vacuum: bool = True) -> dict[str, Any]:
        """删除超过保留期的**已结束**作业历史行，并按需 VACUUM 回收空间。

        设计约束（每条都有实测理由，勿放宽）：

        - **绝不删 `running` 行**，哪怕它很老：worker 启动时靠
          `recover_stale_job_runs()` 把僵尸 running 行收编为 interrupted，
          删掉等于销毁"进程崩过"的证据，面板「运行中」也会失真；
        - **只动 `job_runs`**：`events` / `deliveries` / `model_calls` 各有消费方；
        - 时间戳是 `%Y-%m-%d %H:%M:%S` 的**字符串**（北京时区）⇒ 直接按字符串比较
          （该格式字典序 == 时间序）；
        - 只有真删了行才 VACUUM；VACUUM 需独占写锁，可能被并发写挤掉 ⇒ 失败不算错误，
          返回 `vacuumed=False`，下一个周期还有机会回收；
        - 保留天数默认 **7 天**，可用 `ASTRA_JOB_RUNS_KEEP_DAYS` 覆盖（**每次调用读取**，
          便于测试与运行期调整）。
        """
        days = keep_days if keep_days is not None else int(os.getenv("ASTRA_JOB_RUNS_KEEP_DAYS", "7"))
        if days < 1:
            raise ValueError("keep_days 必须 >= 1：0 或负数会清空全部历史")
        cutoff = (datetime.now(BJ_TZ) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM job_runs WHERE started_at < ? AND status <> 'running'", (cutoff,))
            deleted = cursor.rowcount or 0
        vacuumed = False
        if deleted and vacuum:
            try:
                with self.connect() as connection:      # VACUUM 必须是该连接的首条语句
                    connection.execute("VACUUM")
                vacuumed = True
            except sqlite3.Error:
                vacuumed = False
        return {"deleted": deleted, "vacuumed": vacuumed, "keep_days": days, "cutoff": cutoff}

    def job_runs(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM job_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [dict(row) for row in rows]

    def record_model_call(self, record: dict[str, Any]) -> int:
        columns = (
            "caller", "model", "reasoning_effort", "status", "started_at", "duration_ms",
            "input_chars", "output_chars", "prompt_fingerprint", "prompt_transport",
            "input_tokens", "output_tokens", "total_tokens", "error_type",
        )
        with self.connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO model_calls({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(record.get(column) for column in columns),
            )
            return int(cursor.lastrowid)

    def model_calls(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM model_calls ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)).fetchall()
        return [dict(row) for row in rows]

    def model_stats(self) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT COUNT(*) total_calls,
                   SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) successful_calls,
                   COALESCE(ROUND(AVG(duration_ms)),0) avg_duration_ms,
                   COALESCE(SUM(total_tokens),0) total_tokens
                   FROM model_calls"""
            ).fetchone()
        return {key: int(row[key] or 0) for key in ("total_calls", "successful_calls", "avg_duration_ms", "total_tokens")}

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as connection:
            connection.execute("INSERT INTO runtime_state(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def get_state(self, key: str, default: str = "") -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM runtime_state WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def event_health(self) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """SELECT
                   SUM(CASE WHEN priority>=90 THEN 1 ELSE 0 END) critical_total,
                   SUM(CASE WHEN priority>=90 AND accepted=0 AND delivery_count>0 THEN 1 ELSE 0 END) critical_unmet,
                   SUM(CASE WHEN priority>=90 AND accepted=0 AND delivery_count>0 AND dead=delivery_count THEN 1 ELSE 0 END) critical_failed,
                   SUM(CASE WHEN priority>=90 AND delivery_count=0 THEN 1 ELSE 0 END) critical_unroutable
                   FROM (
                     SELECT e.event_id,e.priority,COUNT(d.id) delivery_count,
                       SUM(CASE WHEN d.status IN ('delivered','accepted') THEN 1 ELSE 0 END) accepted,
                       SUM(CASE WHEN d.status='dead' THEN 1 ELSE 0 END) dead
                     FROM events e LEFT JOIN deliveries d ON d.event_id=e.event_id GROUP BY e.event_id
                   )"""
            ).fetchone()
        return {key: int(row[key] or 0) for key in ("critical_total", "critical_unmet", "critical_failed", "critical_unroutable")}

    def stats(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute("SELECT status, COUNT(*) count FROM deliveries GROUP BY status").fetchall()
        result = {"pending": 0, "processing": 0, "retry": 0, "accepted": 0, "delivered": 0, "dead": 0}
        result.update({row["status"]: row["count"] for row in rows})
        return result

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT d.id, d.channel, d.status, d.attempts, d.last_error, d.delivered_at,
                          e.event_id, e.event_type, e.title, e.message, e.priority, e.created_at
                   FROM deliveries d JOIN events e ON e.event_id=d.event_id
                   ORDER BY d.id DESC LIMIT ?""",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(row) for row in rows]
