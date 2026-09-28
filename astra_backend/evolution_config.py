"""Atomic self-improvement & evolution configuration storage."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .config import ROOT
from .account_baseline import load_account_baseline, update_evolution_start_time

EVOLUTION_CONFIG_FILE = ROOT / "data" / "evolution_config.json"
BJ_TZ = timezone(timedelta(hours=8))
VALID_EFFORTS = {"low", "medium", "high", "max"}
DEFAULT_TIMEOUT = 300.0
MIN_TIMEOUT = 60.0
MAX_TIMEOUT = 600.0


def load_evolution_config() -> dict[str, Any]:
    """读取自进化专属配置；文件缺失时优雅回退并提供完整结构。"""
    data: dict[str, Any] = {}
    if EVOLUTION_CONFIG_FILE.exists():
        try:
            loaded = json.loads(EVOLUTION_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}

    baseline = load_account_baseline()
    start_time = str(data.get("start_time") or baseline.get("evolution_start_time") or "2026-09-01 00:00:00").strip()

    model_id = str(data.get("model_id") or "auto").strip()
    reasoning_effort = str(data.get("reasoning_effort") or "high").strip().lower()
    if reasoning_effort not in VALID_EFFORTS:
        reasoning_effort = "high"

    try:
        thinking_timeout = float(data.get("thinking_timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        thinking_timeout = DEFAULT_TIMEOUT
    thinking_timeout = max(MIN_TIMEOUT, min(MAX_TIMEOUT, thinking_timeout))

    analysis_depth = str(data.get("analysis_depth") or "deep").strip().lower()

    # 尝试解析当前有效模型 (effective_model_id)
    effective_model_id = model_id
    if not model_id or model_id == "auto":
        try:
            from astra_backend.llm_manager import get_active_llm_runtime
            active = get_active_llm_runtime()
            effective_model_id = active.get("model") or "auto"
        except Exception:
            effective_model_id = "auto"

    return {
        "model_id": model_id,
        "effective_model_id": effective_model_id,
        "reasoning_effort": reasoning_effort,
        "thinking_timeout": thinking_timeout,
        "analysis_depth": analysis_depth,
        "start_time": start_time,
        "updated_at": str(data.get("updated_at") or ""),
    }


def save_evolution_config(payload: dict[str, Any]) -> dict[str, Any]:
    """更新自进化专属配置（原子写入 + 锁保护）。"""
    from astra_backend.file_locks import file_lock

    previous = load_evolution_config()
    updated = {**previous}

    if "model_id" in payload:
        raw_mid = str(payload["model_id"] or "").strip()
        updated["model_id"] = raw_mid if raw_mid else "auto"

    if "reasoning_effort" in payload:
        effort = str(payload["reasoning_effort"] or "").strip().lower()
        if effort in VALID_EFFORTS:
            updated["reasoning_effort"] = effort

    if "thinking_timeout" in payload:
        try:
            t = float(payload["thinking_timeout"])
            updated["thinking_timeout"] = max(MIN_TIMEOUT, min(MAX_TIMEOUT, t))
        except (TypeError, ValueError):
            pass

    if "analysis_depth" in payload:
        depth = str(payload["analysis_depth"] or "").strip().lower()
        if depth in {"standard", "deep"}:
            updated["analysis_depth"] = depth

    if "start_time" in payload and payload["start_time"]:
        st = str(payload["start_time"]).strip()
        if len(st) == 10:
            st = f"{st} 00:00:00"
        updated["start_time"] = st
        try:
            update_evolution_start_time(st)
        except Exception:
            pass

    updated["updated_at"] = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")

    with file_lock(EVOLUTION_CONFIG_FILE):
        EVOLUTION_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".evolution-config-", suffix=".json", dir=EVOLUTION_CONFIG_FILE.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(updated, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, EVOLUTION_CONFIG_FILE)
            os.chmod(EVOLUTION_CONFIG_FILE, 0o600)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    # 刷新有效模型返回
    return load_evolution_config()


def resolve_evolution_llm_runtime(evo_cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """解析自进化运行时所用的完整模型参数（模型名、提供商、BaseURL、APIKey、超时等）。"""
    if evo_cfg is None:
        evo_cfg = load_evolution_config()

    model_id = evo_cfg.get("model_id") or "auto"
    reasoning_effort = evo_cfg.get("reasoning_effort") or "high"
    thinking_timeout = float(evo_cfg.get("thinking_timeout") or DEFAULT_TIMEOUT)

    from astra_backend.llm_manager import get_active_llm_runtime, resolve_model_runtime

    runtime: Dict[str, Any] = {}
    if model_id and model_id != "auto":
        resolved = resolve_model_runtime(model_id)
        if resolved and resolved.get("model"):
            runtime = dict(resolved)

    if not runtime:
        # 回退至交易主脑模型
        active = get_active_llm_runtime()
        runtime = dict(active) if active else {}

    # 覆盖专属推理参数
    if runtime:
        runtime["reasoning_effort"] = reasoning_effort
        runtime["thinking_timeout"] = thinking_timeout
        runtime["evolution_dedicated"] = (model_id != "auto")

    return runtime
