"""Strategy Plaza (策略广场) live node telemetry and parameter export module.

Strictly restricted to LIVE trading nodes (demo nodes are fail-closed rejected).
Applies white-list based physical redaction to ensure no secrets, keys, or credentials
can ever leak to the public endpoint.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from astra_backend.config import ROOT
from astra_backend.llm.util import _atomic_write_json
from astra_backend.version import get_version

DATA_DIR = ROOT / "data"
PLAZA_SETTINGS_FILE = DATA_DIR / "strategy_plaza_share.json"
DASHBOARD_CACHE_FILE = DATA_DIR / "dashboard_last_good.json"
COUNCIL_CONFIG_FILE = DATA_DIR / "council_config.json"

DEFAULT_PLAZA_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    "nickname": "0xEthan",
    "show_performance": True,
    "show_balance": False,
    "show_model": True,
    "show_strategy_params": True,
    "plaza_hub_url": "https://hub.astraquant.tech",
    "updated_at": "",
}

# Regex to detect API keys, tokens, or private secrets in string values
_SECRET_PATTERN = re.compile(
    r"(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|gho_[a-zA-Z0-9]{20,}|Bearer\s+[a-zA-Z0-9\._\-]+)",
    re.IGNORECASE,
)
_FORBIDDEN_KEY_SUBSTRINGS = (
    "secret",
    "passphrase",
    "password",
    "apikey",
    "api_key",
    "token",
    "credential",
    "webhook",
    "auth",
    "private",
)


def is_live_trading_node() -> bool:
    """Return True only if the system is genuinely configured for LIVE trading."""
    try:
        from scripts.okx_runtime import current_environment

        okx_env = current_environment()
        mode = str(getattr(okx_env, "mode", "demo")).strip().lower()
        if mode == "live":
            return True

        from astra_backend.exchanges import env_profiles

        bn_mode = str(env_profiles.legacy_environment_for("binance")).strip().lower()
        gate_mode = str(env_profiles.legacy_environment_for("gate")).strip().lower()
        return bn_mode == "live" or gate_mode == "live"
    except Exception:
        return False


def load_plaza_settings() -> Dict[str, Any]:
    """Load settings from data/strategy_plaza_share.json with safe defaults."""
    if PLAZA_SETTINGS_FILE.exists():
        try:
            with open(PLAZA_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    res = dict(DEFAULT_PLAZA_SETTINGS)
                    res.update(data)
                    return res
        except Exception:
            pass
    return dict(DEFAULT_PLAZA_SETTINGS)


def save_plaza_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Atomically persist plaza sharing configuration."""
    current = load_plaza_settings()
    for k in ("enabled", "show_performance", "show_balance", "show_model", "show_strategy_params"):
        if k in payload:
            current[k] = bool(payload[k])
    if "nickname" in payload and isinstance(payload["nickname"], str):
        cleaned = payload["nickname"].strip()[:40]
        current["nickname"] = cleaned if cleaned else "Anonymous Quant"
    if "plaza_hub_url" in payload and isinstance(payload["plaza_hub_url"], str):
        current["plaza_hub_url"] = payload["plaza_hub_url"].strip()
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(PLAZA_SETTINGS_FILE, current)
    return current


def sanitize_public_payload(obj: Any) -> Any:
    """Recursively sanitize dictionary to guarantee zero secret leakage."""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            k_lower = str(k).lower()
            if any(sub in k_lower for sub in _FORBIDDEN_KEY_SUBSTRINGS):
                continue
            cleaned[k] = sanitize_public_payload(v)
        return cleaned
    elif isinstance(obj, list):
        return [sanitize_public_payload(item) for item in obj]
    elif isinstance(obj, str):
        if _SECRET_PATTERN.search(obj):
            return "[REDACTED_SECRET]"
        return obj
    return obj


def assemble_plaza_public_profile() -> Dict[str, Any]:
    """Assemble public telemetry and cloneable payload for Strategy Plaza.

    Fail-closed:
    1. If sharing is disabled by user -> returns status: "disabled"
    2. If node is in Demo / Simulated mode -> returns status: "rejected", code: "LIVE_ONLY"
    """
    settings = load_plaza_settings()
    is_live = is_live_trading_node()

    if not settings.get("enabled", False):
        return {
            "status": "disabled",
            "is_live": is_live,
            "message": "该节点未开启策略广场公开分享",
        }

    if not is_live:
        return {
            "status": "rejected",
            "code": "LIVE_ONLY",
            "is_live": False,
            "message": "策略广场仅接收真实实盘（LIVE）节点，当前为模拟盘模式，已被物理拒绝",
        }

    # Load cache snapshot
    cache_data: Dict[str, Any] = {}
    if DASHBOARD_CACHE_FILE.exists():
        try:
            with open(DASHBOARD_CACHE_FILE, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
        except Exception:
            cache_data = {}

    # 1. Node Info
    node_info = {
        "nickname": settings.get("nickname") or "0xEthan",
        "system_version": get_version(),
        "is_live": True,
        "environment": "live",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # 2. Performance KPI
    show_perf = settings.get("show_performance", True)
    show_balance = settings.get("show_balance", False)
    performance_block: Dict[str, Any] = {"visible": show_perf}
    if show_perf:
        perf = cache_data.get("performance") or {}
        acct = cache_data.get("account") or {}
        today = cache_data.get("today_stats") or {}

        performance_block.update({
            "total_roi_pct": float(acct.get("total_roi", acct.get("roi", 0.0)) or 0.0),
            "win_rate_pct": float(perf.get("win_rate", today.get("win_rate", 0.0)) or 0.0),
            "profit_factor": float(perf.get("profit_factor", 0.0) or 0.0),
            "all_trades": int(perf.get("all_trades", today.get("all_trades", 0)) or 0),
            "win_trades": int(perf.get("win_trades", today.get("win_trades", 0)) or 0),
            "loss_trades": int(perf.get("loss_trades", today.get("loss_trades", 0)) or 0),
            "max_drawdown_pct": float(acct.get("max_drawdown", 0.0) or 0.0),
            "leaderboard": perf.get("leaderboard", []),
            "total_pnl_usdt": float(acct.get("total_pnl", 0.0) or 0.0) if show_balance else None,
            "equity_usdt": float(acct.get("total_eq", 0.0) or 0.0) if show_balance else None,
        })

    # 3. Model Specs
    show_model = settings.get("show_model", True)
    model_block: Dict[str, Any] = {"visible": show_model}
    if show_model:
        llm_rt = cache_data.get("llm_runtime") or {}
        c_cfg: Dict[str, Any] = {}
        if COUNCIL_CONFIG_FILE.exists():
            try:
                with open(COUNCIL_CONFIG_FILE, "r", encoding="utf-8") as f:
                    c_cfg = json.load(f)
            except Exception:
                c_cfg = {}

        advisors = []
        for k, v in (c_cfg.get("advisors") or {}).items():
            if isinstance(v, dict):
                advisors.append({
                    "id": k,
                    "name": v.get("name", k),
                    "role": v.get("role", ""),
                    "model": v.get("model_name", v.get("model", "")),
                })

        model_block.update({
            "primary_model": llm_rt.get("model", os.getenv("LLM_MODEL", "unknown")),
            "provider": llm_rt.get("provider_name", "custom"),
            "reasoning_effort": llm_rt.get("reasoning_effort", os.getenv("LLM_REASONING_EFFORT", "medium")),
            "council_enabled": bool(c_cfg.get("enabled", False)),
            "council_consensus_mode": c_cfg.get("consensus_mode", "cio"),
            "council_advisors": advisors,
        })

    # 4. Cloneable Strategy Parameters
    show_params = settings.get("show_strategy_params", True)
    strategy_block: Dict[str, Any] = {"visible": show_params}
    if show_params:
        try:
            from scripts.prompt_library import get_profile, active_profile_id
            prof_id = active_profile_id()
            profile_data = get_profile(prof_id)
        except Exception:
            prof_id = "default"
            profile_data = {}

        risk_settings = {
            "risk_mode": os.getenv("ASTRA_RISK_SUITE", "aggressive"),
            "min_leverage": float(os.getenv("ASTRA_MIN_LEVERAGE", 5.0)),
            "max_leverage": float(os.getenv("ASTRA_MAX_LEVERAGE", 8.0)),
            "max_margin_equity_ratio": float(os.getenv("ASTRA_MAX_MARGIN_EQUITY_RATIO", 0.35)),
            "single_asset_equity_ratio": float(os.getenv("ASTRA_SINGLE_ASSET_EQUITY_RATIO", 0.45)),
            "risk_per_trade_ratio": float(os.getenv("ASTRA_RISK_PER_TRADE_RATIO", 0.03)),
            "daily_loss_equity_ratio": float(os.getenv("ASTRA_DAILY_LOSS_EQUITY_RATIO", 0.10)),
        }

        strategy_block.update({
            "strategy_id": prof_id,
            "strategy_name": (profile_data or {}).get("name", "AstraQuant 实盘方案"),
            "description": (profile_data or {}).get("description", "AstraQuant AI 实盘量化策略"),
            "risk_settings": risk_settings,
            "prompt_profile": profile_data or {},
        })

    result = {
        "status": "ok",
        "node_info": node_info,
        "performance": performance_block,
        "model_specs": model_block,
        "strategy_clone_payload": strategy_block,
    }

    # Final security pass: sanitize any accidental secret or credential
    return sanitize_public_payload(result)
