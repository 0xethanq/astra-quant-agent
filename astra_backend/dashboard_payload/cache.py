"""仪表盘缓存持久化与 STALE 兜底注入（结构优化阶段 2 / B2 第五刀）。

`_inject_local_data_into_stale` 会调用 6 个**同门面**的函数（它们各自也读门面路径
常量）并直接读 6 个路径文件。为让 `patch.object(dashboard, "LOG_FILE", tmp)` 这类
打桩继续生效，门面薄壳把**可调用对象**与**路径常量**一并在调用时注入，核心只使用
注入项 —— 若直接重导出，核心会读到真实项目文件（本阶段反复出现的事故形态）。
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Callable

from astra_backend.dashboard_payload.market import _is_meaningful_dashboard_snapshot

__all__ = ["load_persisted_dashboard_cache", "persist_dashboard_cache",
           "_inject_local_data_into_stale"]



def load_persisted_dashboard_cache(cache_file: str | os.PathLike[str], ):
    try:
        with open(cache_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if _is_meaningful_dashboard_snapshot(data) else {}
    except Exception:
        return {}


def persist_dashboard_cache(cache_file: str | os.PathLike[str], data_dir: str | os.PathLike[str], data):
    if not _is_meaningful_dashboard_snapshot(data):
        return
    cache_dir = os.path.dirname(cache_file) or data_dir
    os.makedirs(cache_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".dashboard-cache-", suffix=".json", dir=cache_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, cache_file)
        os.chmod(cache_file, 0o600)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _inject_local_data_into_stale(load_factor_lib: Callable[..., Any], load_cross_venue: Callable[..., Any], load_portfolio_risk: Callable[..., Any], build_factors: Callable[..., Any], build_health: Callable[..., Any], load_memory_md: Callable[..., Any], news_file: str | os.PathLike[str], history_file: str | os.PathLike[str], report_file: str | os.PathLike[str], last_prompt_file: str | os.PathLike[str], log_file: str | os.PathLike[str], ledger_file: str | os.PathLike[str], stale, positions, timestamp_full):
    """Inject local-only data (factor library, factors, news, review) into a stale cache.

    When OKX private endpoints are unavailable, the dashboard enters STALE mode
    and returns the last-known-good snapshot. However, local files like
    factor_library_snapshot.json, trading_state.json, ai_brain_decisions.json,
    news_sentiment.json and the review report do NOT depend on OKX private API
    and should always reflect their latest on-disk state.
    """
    # Factor library — the source of calculus_dynamics, definite_integrals,
    # smart_money_derivatives, probability_theory, microstructure, etc.
    stale["factor_library"] = load_factor_lib()

    # US-007：跨所快照同为本地文件（venue_health + decisions xvenue），STALE 下保持新鲜
    stale["cross_venue"] = load_cross_venue()
    stale["portfolio_risk"] = load_portfolio_risk()

    # Factors list — rebuilt from local trading_state + ai_brain_decisions
    factors_list, state_data = build_factors(positions, timestamp_full)
    if factors_list:
        stale["factors"] = factors_list
        stale["state_snapshot"] = state_data

    # News intelligence — local file, no OKX dependency
    if os.path.exists(news_file):
        try:
            with open(news_file, "r", encoding="utf-8") as f:
                stale["news_intelligence"] = json.load(f)
        except Exception:
            pass

    # AI brain history — local file
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                stale["ai_brain_history"] = json.load(f)
        except Exception:
            pass

    # AI 决策健康度同为本地口径：STALE 模式下也必须新鲜（决策停更的原因正在这里）
    try:
        stale["ai_health"] = build_health(stale.get("ai_brain_history") or [])
    except Exception:
        pass

    # Review report — local file
    if os.path.exists(report_file):
        try:
            with open(report_file, "r", encoding="utf-8") as f:
                stale["review"] = json.load(f)
        except Exception:
            pass

    # AI last prompt — local file
    if os.path.exists(last_prompt_file):
        try:
            with open(last_prompt_file, "r", encoding="utf-8") as f:
                stale["ai_last_prompt"] = f.read()
        except Exception:
            pass

    # AI trading memory — structured store first, legacy markdown as fallback
    try:
        stale["ai_trading_memory_md"] = load_memory_md()
    except Exception:
        pass

    # Log lines — local file
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                stale["logs"] = [l.strip() for l in lines[-60:] if l.strip()]
        except Exception:
            pass

    # Trades table — local ledger file
    if os.path.exists(ledger_file):
        try:
            with open(ledger_file, "r", encoding="utf-8") as f:
                stale["trades"] = json.load(f)[:60]
        except Exception:
            pass

    return stale
