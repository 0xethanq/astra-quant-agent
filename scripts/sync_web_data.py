#!/usr/bin/env python3
"""Generate local ASTRA dashboard cache without an external console dependency."""

import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from astra_backend.time_utils import beijing_day
import json
from typing import Any, Dict, Optional
import time
import subprocess
import datetime

import scripts.okx_rest as okx_rest
import scripts.okx_runtime as okx_runtime

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
LOGS_DIR = os.path.join(WORKSPACE_DIR, "logs")
LEDGER_JSON_FILE = os.path.join(DATA_DIR, "trading_ledger.json")
SNAPSHOTS_JSON_FILE = os.path.join(DATA_DIR, "snapshots.json")
LOG_FILE = os.path.join(LOGS_DIR, "trading.log")
DATA_JSON_PATH = os.path.join(DATA_DIR, "trading_data.json")

from instrument_pool import load_instruments
from market_data_service import fetch_tickers_bulk, fetch_ticker

TARGET_INSTRUMENTS = load_instruments()

def get_disk_info():
    try:
        import shutil
        total, used, free = shutil.disk_usage(WORKSPACE_DIR)
        return {
            "total_gb": round(total / (1024**3), 2),
            "used_gb": round(used / (1024**3), 2),
            "free_gb": round(free / (1024**3), 2),
            "percent": round((used / total) * 100, 1)
        }
    except Exception:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}

def _load_json_list(path: str, *, default=None):
    """读 JSON 并缓存 —— **同一函数内重复读同一文件**是本文件的既有浪费
    （第六十二刀修）：`generate_trading_data` 里 `snapshots.json` 与
    `trading_ledger.json` 各被打开、解析**两次**，第二次完全浪费一次磁盘
    读 + 一次全量 JSON 解析（台账可到数千行）。

    ⚠️ 语义与原实现逐条对齐：
    - 每处调用**各自** `try/except`（本函数内不捕获）——
      原代码是两个独立 try，不能合并成一个 try（那会改变异常传播路径）；
    - 失败/文件缺失一律回落 `default`（原实现是 `pass` 让变量保持初值）；
    - 返回值**不做拷贝**：缓存对象在调用点只读（已逐处确认无 `del`/`append`/
      `[i]=` 等原地修改）。

    函数的取值必须**惰性**：原代码只在各自 `os.path.exists(...)` 成立时才读，
    若改成函数一进来就预读，`disk_usage` 的失败顺序会变。
    """
    if _JSON_CACHE.get(path, _CACHE_MISS) is _CACHE_MISS:
        try:
            with open(path, "r", encoding="utf-8") as f:
                _JSON_CACHE[path] = json.load(f)
        except Exception:
            _JSON_CACHE[path] = default
    cached = _JSON_CACHE[path]
    # ⚠️ 用哨兵而不是 None 表示"未缓存" —— 否则文件内容恰为 `null`
    #    （合法 JSON）时，每次都判为未缓存，退化成**每调用一次读一次**。
    return default if cached is _CACHE_MISS else cached


_CACHE_MISS = object()
_JSON_CACHE: dict = {}


def generate_trading_data():
    # ⚠️ 缓存**只服务于本次调用**：调用方 `daemon_web_sync.py` 是**循环**调用的，
    #    若让缓存跨调用存活，第二轮就会读到第一轮的文件内容（陈旧数据）。
    #    原实现每次调用都重新 open，故这里必须逐调用清空。
    _JSON_CACHE.clear()
    env = okx_runtime.current_environment()
    if not env.configured:
        # fail-closed (2026-09-09 CLI removal): never overwrite the web cache with zeros
        raise okx_rest.OKXNotConfigured("OKX API Key 未配置 — Web 数据同步 fail-closed（保持既有 trading_data.json 不动）")

    tz_bj = datetime.timezone(datetime.timedelta(hours=8))
    now_bj = datetime.datetime.now(tz_bj)
    today_str = now_bj.strftime("%Y-%m-%d")

    # 1. Balance
    bal_data = okx_rest.balances()
    usdt_bal = {}
    if bal_data and isinstance(bal_data, list) and "details" in bal_data[0]:
        for d in bal_data[0]["details"]:
            if d.get("ccy") == "USDT":
                usdt_bal = d
                break

    total_eq = float(usdt_bal.get("eq", 0) or 0)
    avail_eq = float(usdt_bal.get("availEq", 0) or 0)
    cash_bal = float(usdt_bal.get("cashBal", 0) or 0)
    upl_acc = float(usdt_bal.get("upl", 0) or 0)

    # 2. Positions (V5 REST, replaces removed CLI)
    pos_data = okx_rest.positions()
    positions = []
    long_count = 0
    short_count = 0
    total_pos_upl = 0.0

    if isinstance(pos_data, list):
        for p in pos_data:
            pos_sz = float(p.get("pos", 0) or 0)
            if pos_sz == 0:
                continue
            pos_side = p.get("posSide", "net")
            if pos_side == "long":
                long_count += 1
            elif pos_side == "short":
                short_count += 1
            upl = float(p.get("upl", 0) or 0)
            total_pos_upl += upl
            positions.append({
                "instId": p.get("instId"),
                "posSide": pos_side,
                "pos": p.get("pos"),
                "lever": p.get("lever", "3"),
                "avgPx": float(p.get("avgPx", 0) or 0),
                "markPx": float(p.get("markPx", 0) or 0),
                "upl": upl,
                "uplRatio": float(p.get("uplRatio", 0) or 0) * 100,
                "liqPx": p.get("liqPx", "--"),
                "bePx": p.get("bePx", "--")
            })

    # Fallback to last valid snapshot if balance is 0
    if total_eq == 0 and os.path.exists(SNAPSHOTS_JSON_FILE):
        try:
            snaps = _load_json_list(SNAPSHOTS_JSON_FILE, default=[])
            if snaps:
                valid_snaps = [s for s in snaps if s.get("equity", 0.0) > 0]
                if valid_snaps:
                    last_s = valid_snaps[-1]
                    total_eq = float(last_s.get("equity", 0.0))
                    avail_eq = float(last_s.get("avail", 0.0))
                    total_pos_upl = float(last_s.get("upl", 0.0))
        except Exception:
            pass

    # 3. Bills & Today PnL
    bills_data = okx_rest.bills(limit=100)
    today_realized_gross = 0.0
    today_fees = 0.0
    today_funding = 0.0
    today_win_trades = 0
    today_loss_trades = 0

    if isinstance(bills_data, list) and bills_data:
        for b in bills_data:
            ts = int(b.get("ts", 0) or 0) / 1000.0
            dt = datetime.datetime.fromtimestamp(ts, tz=tz_bj)
            if dt.strftime("%Y-%m-%d") == today_str:
                pnl = float(b.get("pnl", 0) or 0)
                fee = float(b.get("fee", 0) or 0)
                sub_type = str(b.get("subType", ""))
                
                today_fees += fee
                if sub_type in ["5", "6"]:  # Close
                    today_realized_gross += pnl
                    if pnl > 0:
                        today_win_trades += 1
                    elif pnl < 0:
                        today_loss_trades += 1
                elif sub_type in ["173", "174"]:  # Funding
                    today_funding += pnl
    else:
        # Load from JSON ledger
        if os.path.exists(LEDGER_JSON_FILE):
            try:
                t_list = _load_json_list(LEDGER_JSON_FILE, default=[])
                if t_list:
                    for t in t_list:
                        # 审计 D5：台账行根本没有 "time" 键（真实键名 close_time）
                        # ——旧代码 beijing_day(t.get("time")) 恒 None，JSON 兜底
                        # 分支的当日胜负统计静默归零。同时补结清状态白名单。
                        if str(t.get("status", "")).strip().lower() not in ("closed", "已平仓", "completed"):
                            continue
                        if beijing_day(t.get("close_time") or t.get("time")) == today_str:
                            p = float(t.get("pnl", 0.0) or 0)
                            if p > 0:
                                today_win_trades += 1
                                today_realized_gross += p
                            elif p < 0:
                                today_loss_trades += 1
                                today_realized_gross += p
            except Exception:
                pass

    net_realized_pnl = today_realized_gross + today_fees + today_funding
    total_closed = today_win_trades + today_loss_trades
    win_rate = round((today_win_trades / total_closed) * 100, 1) if total_closed > 0 else 0.0

    # 4. Snapshots & Trades from JSON
    snapshots = []
    trades = []
    if os.path.exists(SNAPSHOTS_JSON_FILE):
        try:
            snapshots = _load_json_list(SNAPSHOTS_JSON_FILE, default=[])[-40:]
        except Exception:
            pass

    if os.path.exists(LEDGER_JSON_FILE):
        try:
            trades = list(reversed(_load_json_list(LEDGER_JSON_FILE, default=[])))[:60]
        except Exception:
            pass

    # 5. Multi-factor signals & AI Brain Decisions
    ai_decisions_file = os.path.join(DATA_DIR, "ai_brain_decisions.json")
    ai_decisions = {}
    if os.path.exists(ai_decisions_file):
        try:
            with open(ai_decisions_file, "r", encoding="utf-8") as f:
                ai_decisions = json.load(f)
        except Exception:
            pass

    factors = []
    # Fetch all tickers in one single direct REST call (eliminates 6 repetitive Node CLI launches)
    bulk_tickers = fetch_tickers_bulk(inst_type="SWAP")
    for item in TARGET_INSTRUMENTS:
        inst_id = item["instId"]
        name = item["name"]
        ticker = bulk_tickers.get(inst_id) or fetch_ticker(inst_id) or {}
        last_px = float(ticker.get("last", 0) or 0)
        open24h = float(ticker.get("open24h", 0) or 0)
        high24h = float(ticker.get("high24h", 0) or 0)
        low24h = float(ticker.get("low24h", 0) or 0)
        chg_24h = round(((last_px - open24h) / open24h * 100) if open24h > 0 else 0, 2)
        
        ai_data = ai_decisions.get(inst_id, {})
        ai_dec = ai_data.get("decision", {})
        ai_thought = ai_data.get("thought_process", {})
        
        action = ai_dec.get("action", "WAIT")
        score = 0.0
        if action == "BUY_LONG":
            score = 2.5
        elif action == "SELL_SHORT":
            score = -2.5

        factors.append({
            "instId": inst_id,
            "name": name,
            "lastPx": last_px,
            "high24h": high24h,
            "low24h": low24h,
            "chg24h": chg_24h,
            "score": score,
            "action": action,
            "confidence": ai_dec.get("confidence"),
            "reason": ai_dec.get("summary_reason", "等待高确定性行情出现"),
            "thought_process": ai_thought,
            "ai_decision": ai_dec
        })

    # 6. Recent Logs
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            res = subprocess.run(f"tail -n 60 {LOG_FILE}", shell=True, capture_output=True, text=True)
            logs = res.stdout.splitlines()
        except Exception:
            pass

    disk = get_disk_info()

    data = {
        "timestamp": now_bj.strftime("%Y-%m-%d %H:%M:%S (北京时间)"),
        "date": today_str,
        "auth": {
            "connection": "static-v5-api-key",
            "mode": env.mode,
            "configured": env.configured,
            "fingerprint": env.fingerprint
        },
        "account": {
            "total_eq": round(total_eq, 2),
            "avail_eq": round(avail_eq, 2),
            "cash_bal": round(cash_bal, 2),
            "upl": round(upl_acc, 2),
            "pos_upl_total": round(total_pos_upl, 2),
            "margin_usage_pct": round(((total_eq - avail_eq) / total_eq * 100) if total_eq > 0 else 0, 1)
        },
        "today_stats": {
            "realized_gross": round(today_realized_gross, 2),
            "fees_paid": round(today_fees, 2),
            "funding_paid": round(today_funding, 2),
            "net_realized": round(net_realized_pnl, 2),
            "total_pnl": round(net_realized_pnl + total_pos_upl, 2),
            "win_trades": today_win_trades,
            "loss_trades": today_loss_trades,
            "win_rate": win_rate
        },
        "positions_summary": {
            "total": len(positions),
            "max": 10,
            "long_count": long_count,
            "short_count": short_count,
            "items": positions
        },
        "factors": factors,
        "snapshots": snapshots,
        "trades": trades,
        "logs": logs,
        "system": {
            "disk": disk
        }
    }

    # Write atomic JSON to local project data cache
    os.makedirs(DATA_DIR, exist_ok=True)
    temp_path = DATA_JSON_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, DATA_JSON_PATH)

def main():
    """CLI entry point: missing credentials exit before any cache writes."""
    try:
        generate_trading_data()
        print("✅ Web data and JSON ledger synced successfully.")
    except okx_rest.OKXNotConfigured as exc:
        print(f"[NOT READY] {exc}")
        raise SystemExit(3)


if __name__ == "__main__":
    main()
