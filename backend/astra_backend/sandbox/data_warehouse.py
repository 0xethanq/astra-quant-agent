"""Local historical K-Line candle data warehouse for point-in-time backtesting."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "candle_warehouse.db"


class CandleWarehouse:
    """Indexed SQLite storage for multi-venue, multi-resolution point-in-time market & replay data."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candles (
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    bar TEXT NOT NULL,
                    ts_ms INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    PRIMARY KEY(venue, symbol, bar, ts_ms)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candles_query
                ON candles (venue, symbol, bar, ts_ms ASC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS funding_history (
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    ts_ms INTEGER NOT NULL,
                    funding_rate REAL NOT NULL,
                    realized_rate REAL,
                    PRIMARY KEY(venue, symbol, ts_ms)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS oi_history (
                    venue TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    bar TEXT NOT NULL,
                    ts_ms INTEGER NOT NULL,
                    oi_usd REAL NOT NULL,
                    PRIMARY KEY(venue, symbol, bar, ts_ms)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    ts_ms INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(ts_ms, symbol)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_replay_cache (
                    prompt_hash TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_ts_ms INTEGER NOT NULL,
                    response_json TEXT NOT NULL,
                    latency_ms INTEGER DEFAULT 0,
                    PRIMARY KEY(prompt_hash, model)
                )
                """
            )

    def ingest_candles(self, venue: str, symbol: str, bar: str, rows: List[List[Any]]) -> int:
        """Upsert a list of candles [[ts_ms, open, high, low, close, volume], ...] idempotently."""
        if not rows:
            return 0
        v = str(venue).strip().lower()
        s = str(symbol).strip().upper()
        b = str(bar).strip().lower()

        records = []
        for r in rows:
            if len(r) < 5:
                continue
            ts_ms = int(r[0])
            open_px = float(r[1])
            high_px = float(r[2])
            low_px = float(r[3])
            close_px = float(r[4])
            vol = float(r[5]) if len(r) > 5 else 0.0
            records.append((v, s, b, ts_ms, open_px, high_px, low_px, close_px, vol))

        with self._get_conn() as conn:
            conn.executemany(
                """
                INSERT INTO candles (venue, symbol, bar, ts_ms, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(venue, symbol, bar, ts_ms) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume
                """,
                records,
            )
        return len(records)

    def query_candles(
        self,
        venue: str,
        symbol: str,
        bar: str,
        start_ts_ms: Optional[int] = None,
        end_ts_ms: Optional[int] = None,
        limit: int = 1000,
    ) -> List[List[Any]]:
        """Query candles strictly ascending by timestamp [[ts_ms, o, h, l, c, v], ...]."""
        v = str(venue).strip().lower()
        s = str(symbol).strip().upper()
        b = str(bar).strip().lower()

        sql = ["SELECT ts_ms, open, high, low, close, volume FROM candles WHERE venue = ? AND symbol = ? AND bar = ?"]
        params: List[Any] = [v, s, b]

        if start_ts_ms is not None:
            sql.append("AND ts_ms >= ?")
            params.append(int(start_ts_ms))
        if end_ts_ms is not None:
            sql.append("AND ts_ms <= ?")
            params.append(int(end_ts_ms))

        sql.append("ORDER BY ts_ms ASC LIMIT ?")
        params.append(int(limit))

        with self._get_conn() as conn:
            cursor = conn.execute(" ".join(sql), params)
            return [[int(row["ts_ms"]), row["open"], row["high"], row["low"], row["close"], row["volume"]] for row in cursor.fetchall()]

    def count_candles(self, venue: Optional[str] = None, symbol: Optional[str] = None, bar: Optional[str] = None) -> int:
        sql = ["SELECT COUNT(*) FROM candles WHERE 1=1"]
        params: List[Any] = []
        if venue:
            sql.append("AND venue = ?")
            params.append(str(venue).lower())
        if symbol:
            sql.append("AND symbol = ?")
            params.append(str(symbol).upper())
        if bar:
            sql.append("AND bar = ?")
            params.append(str(bar).lower())

        with self._get_conn() as conn:
            cur = conn.execute(" ".join(sql), params)
            row = cur.fetchone()
            return int(row[0] if row else 0)

    def list_available_ranges(self) -> List[Dict[str, Any]]:
        """Return available dataset coverage ranges by venue and symbol."""
        with self._get_conn() as conn:
            cur = conn.execute(
                """
                SELECT venue, symbol, bar, COUNT(*) as count, MIN(ts_ms) as min_ts, MAX(ts_ms) as max_ts
                FROM candles
                GROUP BY venue, symbol, bar
                ORDER BY venue, symbol, bar
                """
            )
            return [
                {
                    "venue": row["venue"],
                    "symbol": row["symbol"],
                    "bar": row["bar"],
                    "count": row["count"],
                    "min_ts_ms": row["min_ts"],
                    "max_ts_ms": row["max_ts"],
                }
                for row in cur.fetchall()
            ]

    def ingest_funding_history(self, venue: str, symbol: str, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        v = str(venue).strip().lower()
        s = str(symbol).strip().upper()
        records = []
        for r in rows:
            ts_ms = int(r.get("fundingTime") or r.get("ts_ms") or 0)
            if ts_ms <= 0:
                continue
            fr = float(r.get("fundingRate") if r.get("fundingRate") is not None else (r.get("funding_rate") or 0.0))
            rr_raw = r.get("realizedRate") if r.get("realizedRate") is not None else r.get("realized_rate")
            rr = float(rr_raw) if rr_raw is not None and rr_raw != "" else None
            records.append((v, s, ts_ms, fr, rr))
        if not records:
            return 0
        with self._get_conn() as conn:
            conn.executemany(
                """
                INSERT INTO funding_history (venue, symbol, ts_ms, funding_rate, realized_rate)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(venue, symbol, ts_ms) DO UPDATE SET
                    funding_rate=excluded.funding_rate,
                    realized_rate=excluded.realized_rate
                """,
                records,
            )
        return len(records)

    def query_funding_history(
        self,
        venue: str,
        symbol: str,
        start_ts_ms: Optional[int] = None,
        end_ts_ms: Optional[int] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        sql = ["SELECT ts_ms, funding_rate, realized_rate FROM funding_history WHERE venue = ? AND symbol = ?"]
        params: List[Any] = [str(venue).strip().lower(), str(symbol).strip().upper()]
        if start_ts_ms is not None:
            sql.append("AND ts_ms >= ?")
            params.append(int(start_ts_ms))
        if end_ts_ms is not None:
            sql.append("AND ts_ms <= ?")
            params.append(int(end_ts_ms))
        sql.append("ORDER BY ts_ms ASC LIMIT ?")
        params.append(int(limit))
        with self._get_conn() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()
            return [
                {"ts_ms": int(r["ts_ms"]), "funding_rate": float(r["funding_rate"]), "realized_rate": r["realized_rate"]}
                for r in rows
            ]

    def ingest_oi_history(self, venue: str, symbol: str, bar: str, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        v = str(venue).strip().lower()
        s = str(symbol).strip().upper()
        b = str(bar).strip().lower()
        records = []
        for r in rows:
            ts_ms = int(r.get("ts_ms") or r.get("ts") or 0)
            if ts_ms <= 0:
                continue
            oi = float(r.get("oi_usd") or r.get("oiUsd") or 0.0)
            records.append((v, s, b, ts_ms, oi))
        if not records:
            return 0
        with self._get_conn() as conn:
            conn.executemany(
                """
                INSERT INTO oi_history (venue, symbol, bar, ts_ms, oi_usd)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(venue, symbol, bar, ts_ms) DO UPDATE SET oi_usd=excluded.oi_usd
                """,
                records,
            )
        return len(records)

    def query_oi_history(
        self,
        venue: str,
        symbol: str,
        bar: str,
        start_ts_ms: Optional[int] = None,
        end_ts_ms: Optional[int] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        sql = ["SELECT ts_ms, oi_usd FROM oi_history WHERE venue = ? AND symbol = ? AND bar = ?"]
        params: List[Any] = [str(venue).strip().lower(), str(symbol).strip().upper(), str(bar).strip().lower()]
        if start_ts_ms is not None:
            sql.append("AND ts_ms >= ?")
            params.append(int(start_ts_ms))
        if end_ts_ms is not None:
            sql.append("AND ts_ms <= ?")
            params.append(int(end_ts_ms))
        sql.append("ORDER BY ts_ms ASC LIMIT ?")
        params.append(int(limit))
        with self._get_conn() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()
            return [{"ts_ms": int(r["ts_ms"]), "oi_usd": float(r["oi_usd"])} for r in rows]

    def save_market_snapshot(self, ts_ms: int, symbol: str, payload: Dict[str, Any]) -> None:
        sym = str(symbol).strip().upper()
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO market_snapshots (ts_ms, symbol, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(ts_ms, symbol) DO UPDATE SET payload_json=excluded.payload_json
                """,
                (int(ts_ms), sym, encoded),
            )

    def query_market_snapshots(
        self,
        symbol: Optional[str] = None,
        start_ts_ms: Optional[int] = None,
        end_ts_ms: Optional[int] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        sql = ["SELECT ts_ms, symbol, payload_json FROM market_snapshots WHERE 1=1"]
        params: List[Any] = []
        if symbol:
            sql.append("AND symbol = ?")
            params.append(str(symbol).strip().upper())
        if start_ts_ms is not None:
            sql.append("AND ts_ms >= ?")
            params.append(int(start_ts_ms))
        if end_ts_ms is not None:
            sql.append("AND ts_ms <= ?")
            params.append(int(end_ts_ms))
        sql.append("ORDER BY ts_ms ASC LIMIT ?")
        params.append(int(limit))
        with self._get_conn() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()
            out = []
            for r in rows:
                try:
                    data = json.loads(r["payload_json"])
                except Exception:
                    data = {}
                out.append({"ts_ms": int(r["ts_ms"]), "symbol": r["symbol"], "payload": data})
            return out

    def get_latest_market_snapshot_before(self, symbol: str, ts_ms: int) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT ts_ms, symbol, payload_json FROM market_snapshots
                WHERE symbol = ? AND ts_ms <= ?
                ORDER BY ts_ms DESC LIMIT 1
                """,
                (str(symbol).strip().upper(), int(ts_ms)),
            ).fetchone()
            if not row:
                return None
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                return None
            return {"ts_ms": int(row["ts_ms"]), "symbol": row["symbol"], "payload": payload}

    def get_cached_llm_response(self, prompt_hash: str, model: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT response_json, latency_ms, created_ts_ms FROM llm_replay_cache WHERE prompt_hash = ? AND model = ?",
                (str(prompt_hash), str(model)),
            ).fetchone()
            if not row:
                return None
            try:
                resp = json.loads(row["response_json"])
            except Exception:
                return None
            return {"response": resp, "latency_ms": int(row["latency_ms"] or 0), "created_ts_ms": int(row["created_ts_ms"] or 0)}

    def put_cached_llm_response(
        self,
        prompt_hash: str,
        model: str,
        response: Dict[str, Any],
        *,
        created_ts_ms: int = 0,
        latency_ms: int = 0,
    ) -> None:
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO llm_replay_cache (prompt_hash, model, created_ts_ms, response_json, latency_ms)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(prompt_hash, model) DO UPDATE SET
                    created_ts_ms=excluded.created_ts_ms,
                    response_json=excluded.response_json,
                    latency_ms=excluded.latency_ms
                """,
                (str(prompt_hash), str(model), int(created_ts_ms), encoded, int(latency_ms)),
            )


MarketReplayWarehouse = CandleWarehouse
