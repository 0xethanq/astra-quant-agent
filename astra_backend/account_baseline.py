"""Atomic account performance baseline storage shared by admin and dashboard."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import ROOT

BASELINE_FILE = ROOT / "data" / "account_initial_state.json"
BJ_TZ = timezone(timedelta(hours=8))
DEFAULT_CAPITAL = 10_000.0
MIN_CAPITAL = 1.0
MAX_CAPITAL = 1_000_000_000.0


def _number(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def load_account_baseline() -> dict[str, Any]:
    data: dict[str, Any] = {}
    if BASELINE_FILE.exists():
        try:
            loaded = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    env_default = _number(os.getenv("INITIAL_CAPITAL"), DEFAULT_CAPITAL)
    capital = _number(data.get("initial_capital"), env_default)
    env_evo_start = str(os.getenv("ASTRA_EVOLUTION_START_TIME", "")).strip()
    evo_start = env_evo_start or str(data.get("evolution_start_time") or data.get("reset_time") or "2026-09-01 00:00:00")
    return {
        **data,
        "initial_capital": round(capital, 2),
        "reset_time": str(data.get("reset_time") or "1970-01-01 00:00:00"),
        "evolution_start_time": evo_start,
    }


def update_initial_capital(initial_capital: float) -> dict[str, Any]:
    capital = round(float(initial_capital), 2)
    if not MIN_CAPITAL <= capital <= MAX_CAPITAL:
        raise ValueError(f"初始本金必须在 {MIN_CAPITAL:.2f} 到 {MAX_CAPITAL:.2f} USDT 之间")
    from astra_backend.file_locks import file_lock

    with file_lock(BASELINE_FILE):
        return _write_baseline(capital)


def _write_baseline(capital: float) -> dict[str, Any]:
    """锁内完成 load → merge → 原子替换（审计 P3-6 家族收口）。"""
    previous = load_account_baseline()
    updated = {
        **previous,
        "initial_capital": capital,
        "capital_updated_at": datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".account-baseline-", suffix=".json", dir=BASELINE_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(updated, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, BASELINE_FILE)
        os.chmod(BASELINE_FILE, 0o600)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return {
        "previous_initial_capital": previous["initial_capital"],
        **updated,
    }


def update_evolution_start_time(start_time: str) -> dict[str, Any]:
    """更新自进化复盘起始时间（过滤更早的人工历史交易）。"""
    st = str(start_time or "").strip()
    if not st:
        st = "2026-09-01 00:00:00"
    if len(st) == 10:
        st = f"{st} 00:00:00"
    from astra_backend.file_locks import file_lock

    with file_lock(BASELINE_FILE):
        previous = load_account_baseline()
        updated = {
            **previous,
            "evolution_start_time": st,
            "evolution_start_updated_at": datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        }
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".account-baseline-", suffix=".json", dir=BASELINE_FILE.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(updated, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, BASELINE_FILE)
            os.chmod(BASELINE_FILE, 0o600)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        return updated
