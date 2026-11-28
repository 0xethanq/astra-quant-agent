"""Agent 多会话、消息轨迹与变更提案 SQLite WAL 持久化存储。"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

ROOT = Path(__file__).resolve().parents[2]
BJ_TZ = timezone(timedelta(hours=8))

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS agent_sessions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  actor TEXT NOT NULL,
  model_id TEXT NOT NULL DEFAULT 'auto',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  reasoning TEXT NOT NULL DEFAULT '',
  tool_calls_json TEXT NOT NULL DEFAULT '[]',
  proposal_ids_json TEXT NOT NULL DEFAULT '[]',
  usage_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id, id);

CREATE TABLE IF NOT EXISTS agent_proposals (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK(status IN ('pending','applied','rejected','partially_applied','failed')),
  items_json TEXT NOT NULL DEFAULT '[]',
  snapshot_hash TEXT NOT NULL DEFAULT '',
  pre_state_json TEXT NOT NULL DEFAULT '{}',
  applied_result_json TEXT NOT NULL DEFAULT '{}',
  actor TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  resolved_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_agent_proposals_session ON agent_proposals(session_id, created_at);
"""


def _db_path() -> Path:
    override = os.environ.get("ASTRA_AGENT_DB", "").strip()
    if override:
        return Path(override)
    data_dir = os.environ.get("ASTRA_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / "astra_agent.db"
    return ROOT / "data" / "astra_agent.db"


def _now_text() -> str:
    return datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _json_loads(raw: Any, default: Any) -> Any:
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


class AgentStore:
    """线程安全的 Agent 会话、消息与审批提案仓储（调用期解析数据库路径以适配测试沙箱）。"""

    def __init__(self, path: Optional[Path] = None):
        self._explicit_path = Path(path) if path is not None else None
        self._initialized_paths: set[str] = set()

    def resolved_path(self) -> Path:
        return self._explicit_path if self._explicit_path is not None else _db_path()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db_file = self.resolved_path()
        db_file.parent.mkdir(parents=True, exist_ok=True)
        key = str(db_file.resolve())
        conn = sqlite3.connect(str(db_file), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if key not in self._initialized_paths or not db_file.exists():
                conn.executescript(SCHEMA)
                self._initialized_paths.add(key)
                try:
                    os.chmod(db_file, 0o600)
                except OSError:
                    pass
            with conn:
                yield conn
        finally:
            conn.close()

    def _row_to_session(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "actor": str(row["actor"]),
            "model_id": str(row["model_id"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _row_to_message(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": int(row["id"]),
            "session_id": str(row["session_id"]),
            "role": str(row["role"]),
            "content": str(row["content"]),
            "reasoning": str(row["reasoning"]),
            "tool_calls": _json_loads(row["tool_calls_json"], []),
            "proposal_ids": _json_loads(row["proposal_ids_json"], []),
            "usage": _json_loads(row["usage_json"], {}),
            "created_at": str(row["created_at"]),
        }

    def _row_to_proposal(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": str(row["id"]),
            "session_id": str(row["session_id"]),
            "title": str(row["title"]),
            "summary": str(row["summary"]),
            "status": str(row["status"]),
            "items": _json_loads(row["items_json"], []),
            "snapshot_hash": str(row["snapshot_hash"]),
            "pre_state": _json_loads(row["pre_state_json"], {}),
            "applied_result": _json_loads(row["applied_result_json"], {}),
            "actor": str(row["actor"]),
            "created_at": str(row["created_at"]),
            "resolved_at": str(row["resolved_at"]),
        }

    def create_session(self, actor: str, title: str = "新会话", model_id: str = "auto") -> Dict[str, Any]:
        sid = f"sess_{uuid.uuid4().hex[:12]}"
        now = _now_text()
        clean_title = (title or "新会话").strip()[:80] or "新会话"
        clean_model = (model_id or "auto").strip() or "auto"
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO agent_sessions(id, title, actor, model_id, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (sid, clean_title, actor or "admin", clean_model, now, now),
            )
            row = conn.execute("SELECT * FROM agent_sessions WHERE id = ?", (sid,)).fetchone()
        return self._row_to_session(row)

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        lim = max(1, min(int(limit), 200))
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_sessions ORDER BY updated_at DESC, rowid DESC LIMIT ?",
                (lim,),
            ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM agent_sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row_to_session(row) if row else None

    def rename_session(self, session_id: str, title: Optional[str] = None, model_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        now = _now_text()
        with self.connect() as conn:
            existing = conn.execute("SELECT * FROM agent_sessions WHERE id = ?", (session_id,)).fetchone()
            if not existing:
                return None
            new_title = (title.strip()[:80] if isinstance(title, str) and title.strip() else str(existing["title"]))
            new_model = (model_id.strip() if isinstance(model_id, str) and model_id.strip() else str(existing["model_id"]))
            conn.execute(
                "UPDATE agent_sessions SET title = ?, model_id = ?, updated_at = ? WHERE id = ?",
                (new_title, new_model, now, session_id),
            )
            row = conn.execute("SELECT * FROM agent_sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row_to_session(row) if row else None

    def touch_session(self, session_id: str) -> None:
        now = _now_text()
        with self.connect() as conn:
            conn.execute("UPDATE agent_sessions SET updated_at = ? WHERE id = ?", (now, session_id))

    def delete_session(self, session_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM agent_sessions WHERE id = ?", (session_id,))
        return cur.rowcount > 0

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str = "",
        reasoning: str = "",
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        proposal_ids: Optional[List[str]] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = _now_text()
        tc_json = json.dumps(tool_calls or [], ensure_ascii=False)
        prop_json = json.dumps(proposal_ids or [], ensure_ascii=False)
        usage_json = json.dumps(usage or {}, ensure_ascii=False)
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO agent_messages(session_id, role, content, reasoning, tool_calls_json, proposal_ids_json, usage_json, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (session_id, role, content or "", reasoning or "", tc_json, prop_json, usage_json, now),
            )
            msg_id = int(cur.lastrowid)
            conn.execute("UPDATE agent_sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            row = conn.execute("SELECT * FROM agent_messages WHERE id = ?", (msg_id,)).fetchone()
        return self._row_to_message(row)

    def list_messages(self, session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        lim = max(1, min(int(limit), 500))
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                (session_id, lim),
            ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def create_proposal(
        self,
        session_id: str,
        title: str,
        items: List[Dict[str, Any]],
        summary: str = "",
        actor: str = "",
    ) -> Dict[str, Any]:
        pid = f"prop_{uuid.uuid4().hex[:12]}"
        now = _now_text()
        items_json = json.dumps(items or [], ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_proposals(id, session_id, title, summary, status, items_json, actor, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (pid, session_id, (title or "策略变更提案")[:120], summary or "", "pending", items_json, actor or "", now),
            )
            conn.execute("UPDATE agent_sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            row = conn.execute("SELECT * FROM agent_proposals WHERE id = ?", (pid,)).fetchone()
        return self._row_to_proposal(row)

    def get_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM agent_proposals WHERE id = ?", (proposal_id,)).fetchone()
        return self._row_to_proposal(row) if row else None

    def list_proposals(self, session_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_proposals WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
                (session_id,),
            ).fetchall()
        return [self._row_to_proposal(r) for r in rows]

    def update_proposal(
        self,
        proposal_id: str,
        status: str,
        *,
        snapshot_hash: str = "",
        pre_state: Optional[Dict[str, Any]] = None,
        applied_result: Optional[Dict[str, Any]] = None,
        actor: str = "",
    ) -> Optional[Dict[str, Any]]:
        now = _now_text()
        with self.connect() as conn:
            existing = conn.execute("SELECT * FROM agent_proposals WHERE id = ?", (proposal_id,)).fetchone()
            if not existing:
                return None
            pre_json = json.dumps(pre_state if pre_state is not None else _json_loads(existing["pre_state_json"], {}), ensure_ascii=False)
            res_json = json.dumps(applied_result if applied_result is not None else _json_loads(existing["applied_result_json"], {}), ensure_ascii=False)
            snap = snapshot_hash or str(existing["snapshot_hash"] or "")
            act = actor or str(existing["actor"] or "")
            conn.execute(
                """
                UPDATE agent_proposals
                SET status = ?, snapshot_hash = ?, pre_state_json = ?, applied_result_json = ?, actor = ?, resolved_at = ?
                WHERE id = ?
                """,
                (status, snap, pre_json, res_json, act, now, proposal_id),
            )
            row = conn.execute("SELECT * FROM agent_proposals WHERE id = ?", (proposal_id,)).fetchone()
        return self._row_to_proposal(row) if row else None
