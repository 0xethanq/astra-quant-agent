"""Layer 0 历史行情、资金费率与 OI 批量入库脚本（存入 MarketReplayWarehouse）。"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from astra_backend.sandbox.data_warehouse import DEFAULT_DB_PATH, MarketReplayWarehouse


def _okx_public_json(path: str, params: Dict[str, Any], timeout: float = 8.0) -> List[Any]:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    headers = {"User-Agent": "Mozilla/5.0"}
    for host in ("https://www.okx.com", "https://aws.okx.com"):
        url = f"{host}{path}?{qs}" if qs else f"{host}{path}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if isinstance(payload, dict) and payload.get("code") == "0":
                data = payload.get("data")
                return list(data) if isinstance(data, list) else []
        except Exception:
            continue
    return []


def fetch_paginated_okx_candles(
    inst_id: str,
    bar: str = "1H",
    *,
    days: int = 90,
    max_pages: int = 120,
    request_fn=None,
) -> List[List[Any]]:
    """分页拉取 OKX 历史 K 线（时间正序 `[[ts_ms, o, h, l, c, v], ...]`）。"""
    req = request_fn or _okx_public_json
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - int(max(1, days) * 86400 * 1000)
    seen: Dict[int, List[Any]] = {}
    after: Optional[str] = None

    for page in range(max_pages):
        params: Dict[str, Any] = {"instId": inst_id, "bar": bar, "limit": 100}
        if after is not None:
            params["after"] = after
        path = "/api/v5/market/candles" if page == 0 else "/api/v5/market/history-candles"
        rows = req(path, params)
        if not rows and page == 0:
            rows = req("/api/v5/market/history-candles", params)
        if not rows:
            break
        oldest_ts = None
        for c in rows:
            try:
                ts_ms = int(c[0])
                rec = [ts_ms, float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5]) if len(c) > 5 else 0.0]
            except (ValueError, TypeError, IndexError):
                continue
            seen[ts_ms] = rec
            if oldest_ts is None or ts_ms < oldest_ts:
                oldest_ts = ts_ms
        if oldest_ts is None or oldest_ts <= cutoff_ms or len(rows) < 50:
            break
        after = str(oldest_ts)
        time.sleep(0.08)

    return [seen[k] for k in sorted(seen.keys()) if k >= cutoff_ms]


def fetch_okx_funding_history(
    inst_id: str,
    *,
    days: int = 90,
    max_pages: int = 15,
    request_fn=None,
) -> List[Dict[str, Any]]:
    """拉取 OKX 历史资金费率序列。"""
    req = request_fn or _okx_public_json
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - int(max(1, days) * 86400 * 1000)
    by_ts: Dict[int, Dict[str, Any]] = {}
    after: Optional[str] = None
    for _ in range(max_pages):
        params: Dict[str, Any] = {"instId": inst_id, "limit": 100}
        if after is not None:
            params["after"] = after
        rows = req("/api/v5/public/funding-rate-history", params)
        if not rows:
            break
        oldest = None
        for r in rows:
            try:
                ts_ms = int(r.get("fundingTime") or 0)
            except (TypeError, ValueError):
                continue
            if ts_ms <= 0:
                continue
            by_ts[ts_ms] = r
            if oldest is None or ts_ms < oldest:
                oldest = ts_ms
        if oldest is None or oldest <= cutoff_ms or len(rows) < 50:
            break
        after = str(oldest)
        time.sleep(0.08)
    return [by_ts[k] for k in sorted(by_ts.keys()) if k >= cutoff_ms]


def ingest_universe_history(
    warehouse: Optional[MarketReplayWarehouse] = None,
    *,
    symbols: Optional[Sequence[str]] = None,
    bars: Sequence[str] = ("15m", "1H", "4H"),
    days: int = 90,
    include_funding: bool = True,
    request_fn=None,
) -> Dict[str, Any]:
    """批量抓取标的池多周期 K 线与资金费率存入本地 SQLite Replay Warehouse。"""
    wh = warehouse or MarketReplayWarehouse(DEFAULT_DB_PATH)
    if symbols is None:
        from instrument_pool import load_instruments
        symbols = [item["instId"] for item in load_instruments() if item.get("instId")]

    summary: Dict[str, Any] = {"days": int(days), "symbols": {}}
    for sym in symbols:
        sym_stat: Dict[str, int] = {}
        for bar in bars:
            candles = fetch_paginated_okx_candles(sym, bar=bar, days=days, request_fn=request_fn)
            sym_stat[f"candles_{bar.lower()}"] = wh.ingest_candles("okx", sym, bar, candles)
        if include_funding:
            funding = fetch_okx_funding_history(sym, days=days, request_fn=request_fn)
            sym_stat["funding"] = wh.ingest_funding_history("okx", sym, funding)
        summary["symbols"][sym] = sym_stat
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest 90-180d OKX history into MarketReplayWarehouse")
    parser.add_argument("--days", type=int, default=90, help="Lookback days (default 90)")
    parser.add_argument("--bars", default="15m,1H,4H", help="Comma-separated bars")
    parser.add_argument("--symbols", default="", help="Comma-separated instIds (empty = pool)")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Warehouse SQLite path")
    args = parser.parse_args()

    wh = MarketReplayWarehouse(Path(args.db))
    syms = [s.strip() for s in args.symbols.split(",") if s.strip()] or None
    bars = [b.strip() for b in args.bars.split(",") if b.strip()]
    res = ingest_universe_history(wh, symbols=syms, bars=bars, days=args.days)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
