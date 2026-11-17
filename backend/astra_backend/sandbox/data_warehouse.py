"""Local historical K-Line candle data warehouse for point-in-time backtesting."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "candle_warehouse.db"


class CandleWarehouse:
    """Indexed SQLite storage for multi-venue, multi-resolution historical candles."""

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
