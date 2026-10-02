"""应用层精确哈希缓存（L1 Exact Query Cache）。

针对测试探针、策略提示词工坊调试、自进化复盘等场景提供带 TTL 的请求级精确匹配缓存。
实盘决策（trading_brain）默认不走缓存（TTL=0），确保每次获取大模型针对最新行情的真实推演。
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB = _ROOT / "data" / "astra_gateway.db"

_CACHE_LOCK = threading.Lock()
_LRU_MAX_SIZE = 500
_LRU_CACHE: collections.OrderedDict[str, Dict[str, Any]] = collections.OrderedDict()

_STATS = {
    "hits": 0,
    "misses": 0,
    "saved_tokens": 0,
}


def _get_db_path() -> Path:
    return Path(os.environ.get("ASTRA_GATEWAY_DB") or _DEFAULT_DB)


def _ensure_db_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_query_cache (
            cache_key TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            base_url TEXT NOT NULL,
            content TEXT NOT NULL,
            reasoning TEXT NOT NULL,
            usage_json TEXT NOT NULL,
            latency_ms INTEGER NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_query_cache_expires ON llm_query_cache(expires_at)"
    )


def compute_cache_key(
    model: str,
    base_url: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    """计算规范化的请求签名哈希（精确匹配），消除键序与空格抖动。"""
    cleaned_messages = []
    for m in messages:
        if isinstance(m, dict):
            cleaned_messages.append({
                "role": str(m.get("role", "")).strip(),
                "content": str(m.get("content", "")).strip(),
            })

    sig_payload = {
        "model": str(model or "").strip().lower(),
        "base_url": str(base_url or "").strip().rstrip("/"),
        "messages": cleaned_messages,
        "temperature": round(float(temperature), 4) if temperature is not None else None,
        "response_format": response_format if isinstance(response_format, dict) else None,
    }
    raw = json.dumps(sig_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def get_cached_query(cache_key: str, now: Optional[float] = None) -> Optional[Tuple[str, str, Dict[str, Any], int]]:
    """查询 L1 缓存；命中返回 (content, reasoning, usage, latency_ms)，否则返回 None。"""
    now_ts = time.time() if now is None else float(now)
    with _CACHE_LOCK:
        # 1. 优先内存 LRU
        if cache_key in _LRU_CACHE:
            entry = _LRU_CACHE[cache_key]
            if entry["expires_at"] > now_ts:
                _LRU_CACHE.move_to_end(cache_key)
                _STATS["hits"] += 1
                usage = dict(entry["usage"])
                usage["cached_tokens"] = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                usage["cache_reported"] = True
                usage["cache_source"] = "l1_exact_cache"
                _STATS["saved_tokens"] += int(usage.get("cached_tokens") or 0)
                return entry["content"], entry["reasoning"], usage, entry["latency_ms"]
            else:
                _LRU_CACHE.pop(cache_key, None)

    # 2. 回退 SQLite 存储
    db_path = _get_db_path()
    if not db_path.exists():
        with _CACHE_LOCK:
            _STATS["misses"] += 1
        return None

    try:
        with sqlite3.connect(db_path, timeout=3.0) as conn:
            _ensure_db_table(conn)
            cur = conn.cursor()
            cur.execute(
                "SELECT content, reasoning, usage_json, latency_ms, expires_at FROM llm_query_cache WHERE cache_key = ?",
                (cache_key,),
            )
            row = cur.fetchone()
            if row:
                content, reasoning, usage_raw, latency_ms, expires_at = row
                if float(expires_at) > now_ts:
                    try:
                        usage = json.loads(usage_raw)
                    except Exception:
                        usage = {}
                    usage["cached_tokens"] = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                    usage["cache_reported"] = True
                    usage["cache_source"] = "l1_exact_cache"
                    with _CACHE_LOCK:
                        _STATS["hits"] += 1
                        _STATS["saved_tokens"] += int(usage.get("cached_tokens") or 0)
                        # 回填内存 LRU
                        _LRU_CACHE[cache_key] = {
                            "content": content,
                            "reasoning": reasoning,
                            "usage": usage,
                            "latency_ms": latency_ms,
                            "expires_at": expires_at,
                        }
                    return content, reasoning, usage, int(latency_ms)
                else:
                    cur.execute("DELETE FROM llm_query_cache WHERE cache_key = ?", (cache_key,))
                    conn.commit()
    except Exception:
        pass

    with _CACHE_LOCK:
        _STATS["misses"] += 1
    return None


def put_cached_query(
    cache_key: str,
    model: str,
    base_url: str,
    content: str,
    reasoning: str,
    usage: Dict[str, Any],
    latency_ms: int,
    ttl_seconds: float,
    now: Optional[float] = None,
) -> None:
    """写入缓存条目。"""
    if ttl_seconds <= 0:
        return
    now_ts = time.time() if now is None else float(now)
    expires_at = now_ts + float(ttl_seconds)

    entry = {
        "content": str(content or ""),
        "reasoning": str(reasoning or ""),
        "usage": usage if isinstance(usage, dict) else {},
        "latency_ms": int(latency_ms),
        "expires_at": expires_at,
    }

    with _CACHE_LOCK:
        if len(_LRU_CACHE) >= _LRU_MAX_SIZE:
            _LRU_CACHE.popitem(last=False)
        _LRU_CACHE[cache_key] = entry

    db_path = _get_db_path()
    try:
        os.makedirs(db_path.parent, exist_ok=True)
        with sqlite3.connect(db_path, timeout=5.0) as conn:
            _ensure_db_table(conn)
            conn.execute(
                """
                INSERT OR REPLACE INTO llm_query_cache
                (cache_key, model, base_url, content, reasoning, usage_json, latency_ms, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    str(model or ""),
                    str(base_url or ""),
                    entry["content"],
                    entry["reasoning"],
                    json.dumps(entry["usage"], ensure_ascii=False),
                    entry["latency_ms"],
                    now_ts,
                    expires_at,
                ),
            )
            # 定期清理已过期的旧条目（1/20 概率或自然淘汰）
            if int(now_ts) % 20 == 0:
                conn.execute("DELETE FROM llm_query_cache WHERE expires_at < ?", (now_ts,))
            conn.commit()
    except Exception:
        pass


def clear_query_cache() -> int:
    """清空所有内存与持久化查询缓存。"""
    cleared = 0
    with _CACHE_LOCK:
        cleared += len(_LRU_CACHE)
        _LRU_CACHE.clear()

    db_path = _get_db_path()
    if db_path.exists():
        try:
            with sqlite3.connect(db_path, timeout=5.0) as conn:
                _ensure_db_table(conn)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM llm_query_cache")
                row = cur.fetchone()
                db_count = row[0] if row else 0
                cur.execute("DELETE FROM llm_query_cache")
                conn.commit()
                cleared += db_count
        except Exception:
            pass
    return cleared


def get_query_cache_stats() -> Dict[str, Any]:
    """返回缓存状态统计。"""
    with _CACHE_LOCK:
        in_memory = len(_LRU_CACHE)
        hits = _STATS["hits"]
        misses = _STATS["misses"]
        saved = _STATS["saved_tokens"]

    total = hits + misses
    hit_rate = round(hits / total * 100.0, 1) if total > 0 else 0.0

    db_entries = 0
    db_path = _get_db_path()
    if db_path.exists():
        try:
            with sqlite3.connect(db_path, timeout=3.0) as conn:
                _ensure_db_table(conn)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM llm_query_cache WHERE expires_at > ?", (time.time(),))
                row = cur.fetchone()
                db_entries = row[0] if row else 0
        except Exception:
            pass

    return {
        "in_memory_entries": in_memory,
        "persisted_entries": db_entries,
        "hits": hits,
        "misses": misses,
        "hit_rate_pct": hit_rate,
        "saved_tokens_total": saved,
    }
