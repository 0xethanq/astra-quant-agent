"""Agent 只读诊断与策略透视工具集（全工具只读、绝不编造缺失值、绝不泄露密钥）。"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List

from astra_backend import dependencies as deps
from astra_backend.audit import recent as audit_recent
from astra_backend.config import settings
from astra_backend.evolution_config import load_evolution_config
from astra_backend.redact import mask
from astra_backend.version import __version__

_SECRET_LINE_RE = re.compile(
    r"(?i)(authorization\s*[:=]\s*bearer\s+|sk-[A-Za-z0-9_-]{8,}|(?:api[_-]?key|secret[_-]?key|passphrase|token|webhook)\s*[:=]\s*['\"]?)([^\s'\",;}{]{6,})"
)


def _redact_text(text: str) -> str:
    def _repl(match: re.Match) -> str:
        prefix = match.group(1)
        val = match.group(2)
        if prefix.lower().startswith("sk-"):
            return mask("sk-" + val, visible=3)
        return prefix + mask(val, visible=3)

    return _SECRET_LINE_RE.sub(_repl, text or "")


def _read_data_json(filename: str, default: Any) -> Any:
    override_dir = os.environ.get("ASTRA_DATA_DIR", "").strip()
    if override_dir and deps.DATA_DIR == deps.ROOT / "data":
        path = Path(override_dir) / filename
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
    return deps.read_json(filename, default)


def _logs_root() -> Path:
    return deps.ROOT / "logs"


def _file_age_health(filename: str, expected_interval_s: int) -> Dict[str, Any]:
    override_dir = os.environ.get("ASTRA_DATA_DIR", "").strip()
    base = Path(override_dir) if (override_dir and deps.DATA_DIR == deps.ROOT / "data") else deps.DATA_DIR
    path = base / filename
    if not path.exists():
        return {"name": filename, "exists": False, "age_seconds": None, "fresh": False}
    age = max(0, int(time.time() - path.stat().st_mtime))
    return {"name": filename, "exists": True, "age_seconds": age, "fresh": age <= expected_interval_s * 2}


def build_state_summary() -> Dict[str, Any]:
    """构建当前系统策略、风控、账户与运行健康的权威摘要（指挥台右侧状态栏与工具共用）。"""
    from astra_backend import risk_config
    from astra_backend.council.roster import seat_model_health
    from astra_backend.council_manager import load_council_config
    from astra_backend.llm_manager import load_llm_config
    from astra_backend.policy_snapshot import capture_full_strategy_package, generate_policy_snapshot, load_archive_index, package_identity
    from astra_backend.trading_session_store import load_trading_session
    from scripts.instrument_pool import load_instruments
    from scripts.prompt_library import active_profile, load_library
    from scripts.trader.session import coverage_estimate, normalize_session, resolve_session

    # 1. 运行态与账户缓存
    try:
        import astra_backend.dashboard_cache as dash_cache
        cache = getattr(dash_cache, "CACHE_DATA", None)
    except Exception:
        cache = None
    cache_dict = cache if isinstance(cache, dict) else {}
    account = cache_dict.get("account") if isinstance(cache_dict.get("account"), dict) else {}
    positions = cache_dict.get("positions") if isinstance(cache_dict.get("positions"), list) else []
    pending_orders = cache_dict.get("pending_orders") if isinstance(cache_dict.get("pending_orders"), list) else []
    data_health = cache_dict.get("data_health") if isinstance(cache_dict.get("data_health"), dict) else {}

    health_files = [
        _file_age_health("ai_brain_decisions.json", 15 * 60),
        _file_age_health("factor_library_snapshot.json", 60),
        _file_age_health("news_sentiment.json", 10 * 60),
        _file_age_health("trading_ledger.json", 15 * 60),
    ]
    all_fresh = all(h.get("fresh", False) for h in health_files)

    # 2. LLM 摘要（无密钥）
    try:
        llm_cfg = load_llm_config(mask_keys=True)
    except Exception:
        llm_cfg = {}
    active_mid = str(llm_cfg.get("active_model_id") or settings.llm_model or "")
    active_model_meta = next((m for m in (llm_cfg.get("models") or []) if m.get("id") == active_mid), {})

    # 3. 风控参数与套件匹配
    r_values = risk_config.current_values()
    matched_suite = "custom"
    for suite in risk_config.SUITES:
        vals = suite.get("values") or {}
        if all(abs(float(r_values.get(k, -999999)) - float(v)) < 1e-9 for k, v in vals.items()):
            matched_suite = str(suite["id"])
            break
    drift = risk_config.file_vs_process_diff()

    # 4. 提示词方案摘要
    try:
        lib = load_library()
        prof = active_profile()
    except Exception:
        lib = {"active_profile_id": "unknown"}
        prof = {"id": "unknown", "name": "未知", "editor_mode": "modules", "pipelines": {}}
    pipe_summary: Dict[str, Any] = {}
    for pk in ("trading_system", "trading_user", "evolution_system", "evolution_user"):
        mods = (prof.get("pipelines") or {}).get(pk) or []
        pipe_summary[pk] = {
            "total": len(mods),
            "enabled": sum(1 for m in mods if isinstance(m, dict) and m.get("enabled", True)),
        }

    # 5. 投委会摘要
    try:
        c_cfg = load_council_config()
    except Exception:
        c_cfg = {"enabled": False, "consensus_mode": "standard", "timeout_seconds": 240.0, "roles": {}}
    health_by_role = {row["role_id"]: row for row in seat_model_health(c_cfg.get("roles"))}
    role_rows = []
    for rid, role in (c_cfg.get("roles") or {}).items():
        if not isinstance(role, dict):
            continue
        hr = health_by_role.get(rid, {})
        role_rows.append({
            "id": rid,
            "name": str(role.get("name") or rid),
            "enabled": bool(role.get("enabled", True)),
            "is_arbitrator": bool(role.get("is_arbitrator", False)) or rid.lower() in {"cio", "arbitrator"},
            "weight": role.get("weight", 0.3),
            "model_id": str(role.get("model_id") or ""),
            "reasoning_effort": str(role.get("reasoning_effort") or "medium"),
            "registered": bool(hr.get("registered", True)),
        })

    # 6. 标的池与交易时段
    try:
        pool = load_instruments()
    except Exception:
        pool = []

    raw_sess = load_trading_session()
    norm_sess, _ = normalize_session(raw_sess)
    sess_state = resolve_session(norm_sess)
    sess_cov = coverage_estimate(norm_sess)

    # 7. 自进化与心法摘要
    evo_cfg = load_evolution_config()
    try:
        from scripts import evolution_shield
        mem_view = evolution_shield.admin_memory_view()
        lessons = mem_view.get("structured_lessons") or []
    except Exception:
        lessons = []

    # 8. 策略快照
    try:
        snap = generate_policy_snapshot()
        pkg_hash = package_identity(capture_full_strategy_package().get("package") or {})
        archives = load_archive_index()
        latest_arch = archives[0] if archives else None
    except Exception:
        snap = {}
        pkg_hash = ""
        latest_arch = None

    return {
        "environment": "demo" if settings.okx_simulated else "live",
        "version": __version__,
        "uptime_seconds": int(max(0.0, time.time() - deps.STARTED_AT)),
        "data_health": {
            "overall": "LIVE" if all_fresh else "STALE",
            "cache_age_seconds": data_health.get("cache_age_seconds"),
            "files": health_files,
        },
        "account": {
            "avail_eq": account.get("avail_eq"),
            "total_eq": account.get("total_eq"),
            "positions_count": len(positions),
            "pending_orders_count": len(pending_orders),
        },
        "llm": {
            "active_model_id": active_mid,
            "active_model_name": active_model_meta.get("name") or active_mid,
            "provider_name": active_model_meta.get("provider_name") or "",
            "reasoning_effort": str(llm_cfg.get("active_reasoning_effort") or settings.llm_reasoning_effort or "high"),
            "thinking_timeout": llm_cfg.get("thinking_timeout", 120.0),
            "request_attempts": llm_cfg.get("request_attempts", 3),
            "fallback_model_ids": list(llm_cfg.get("fallback_model_ids") or []),
        },
        "risk": {
            "active_suite_id": matched_suite,
            "order_mode": (os.getenv("ASTRA_ORDER_MODE") or getattr(settings, "order_mode", "limit") or "limit").strip().lower(),
            "risk_audit": risk_config.audit_risk_consistency(r_values),
            "drift_count": int(drift.get("count", 0)),
            "max_positions": r_values.get("ASTRA_MAX_CONCURRENT_POSITIONS"),
            "max_same_direction": r_values.get("ASTRA_MAX_SAME_DIRECTION_POSITIONS"),
            "min_leverage": r_values.get("ASTRA_MIN_LEVERAGE"),
            "max_leverage": r_values.get("ASTRA_MAX_LEVERAGE"),
            "max_margin_equity_ratio": r_values.get("ASTRA_MAX_MARGIN_EQUITY_RATIO"),
            "single_asset_equity_ratio": r_values.get("ASTRA_SINGLE_ASSET_EQUITY_RATIO"),
            "daily_loss_equity_ratio": r_values.get("ASTRA_DAILY_LOSS_EQUITY_RATIO"),
            "min_risk_reward": r_values.get("ASTRA_MIN_RISK_REWARD"),
            "max_risk_reward": r_values.get("ASTRA_MAX_RISK_REWARD"),
            "min_entry_confidence": r_values.get("ASTRA_MIN_ENTRY_CONFIDENCE"),
            "time_stop_hours": r_values.get("ASTRA_TIME_STOP_HOURS"),
            "scale_out_enabled": bool(r_values.get("ASTRA_SCALE_OUT_ENABLED")),
            "max_scale_in_count": r_values.get("ASTRA_MAX_SCALE_IN_COUNT"),
        },
        "prompt": {
            "active_profile_id": str(lib.get("active_profile_id") or prof.get("id") or ""),
            "active_profile_name": str(prof.get("name") or ""),
            "editor_mode": str(prof.get("editor_mode") or "modules"),
            "updated_at": str(prof.get("updated_at") or ""),
            "pipelines": pipe_summary,
        },
        "council": {
            "enabled": bool(c_cfg.get("enabled", False)),
            "consensus_mode": str(c_cfg.get("consensus_mode") or "standard"),
            "timeout_seconds": c_cfg.get("timeout_seconds", 240.0),
            "roles": role_rows,
        },
        "instruments": {
            "count": len(pool),
            "max_pool_size": deps.MAX_POOL_SIZE,
            "items": [
                {
                    "instId": str(i.get("instId") or ""),
                    "name": str(i.get("name") or ""),
                    "tier": str(i.get("tier") or ""),
                    "max_leverage": i.get("max_leverage"),
                    "sl_atr_mult": i.get("sl_atr_mult"),
                }
                for i in pool
            ],
        },
        "trading_session": {
            **norm_sess,
            "state": sess_state,
            "coverage": sess_cov,
        },
        "evolution": {
            "model_id": evo_cfg.get("model_id"),
            "effective_model_id": evo_cfg.get("effective_model_id"),
            "reasoning_effort": evo_cfg.get("reasoning_effort"),
            "analysis_depth": evo_cfg.get("analysis_depth"),
            "enabled_lessons": sum(1 for item in lessons if isinstance(item, dict) and item.get("enabled", True)),
            "total_lessons": len(lessons),
        },
        "policy": {
            "policy_hash": snap.get("policy_hash", ""),
            "policy_version": snap.get("policy_version", ""),
            "package_hash": pkg_hash,
            "latest_archive": latest_arch,
        },
    }


def _tool_get_system_overview(_args: Dict[str, Any]) -> Dict[str, Any]:
    return build_state_summary()


def _tool_get_live_account_and_positions(_args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import astra_backend.dashboard_cache as dash_cache
        cache = getattr(dash_cache, "CACHE_DATA", None)
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    if not isinstance(cache, dict) or not cache:
        trackers = _read_data_json("position_trackers.json", {})
        return {
            "available": False,
            "note": "实时看板缓存尚未预热，仅返回本地追踪记录",
            "trackers": trackers if isinstance(trackers, dict) else {},
        }
    return {
        "available": True,
        "environment": cache.get("environment"),
        "account": cache.get("account"),
        "positions": cache.get("positions") or [],
        "pending_orders": cache.get("pending_orders") or [],
        "algo_protection": cache.get("algo_protection"),
        "data_health": cache.get("data_health"),
    }


def _tool_get_trade_performance_and_ledger(args: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(args.get("symbol") or "").strip().upper()
    try:
        limit = max(1, min(int(args.get("limit") or 25), 100))
    except (TypeError, ValueError):
        limit = 25

    ledger = _read_data_json("trading_ledger.json", [])
    rows = ledger if isinstance(ledger, list) else (ledger.get("trades") or ledger.get("records") or [] if isinstance(ledger, dict) else [])
    closed: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        inst = str(row.get("inst") or row.get("instId") or row.get("name") or "").upper()
        if symbol and symbol not in inst:
            continue
        if str(row.get("status") or "").lower() == "closed":
            closed.append(row)

    wins = 0
    losses = 0
    total_pnl = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for row in closed:
        inst = str(row.get("inst") or row.get("instId") or row.get("name") or "UNKNOWN")
        pnl_raw = row.get("net_pnl") if row.get("net_pnl") is not None else row.get("pnl")
        try:
            pnl = float(pnl_raw or 0.0)
        except (TypeError, ValueError):
            pnl = 0.0
        total_pnl += pnl
        bucket = by_symbol.setdefault(inst, {"trades": 0, "wins": 0, "pnl": 0.0})
        bucket["trades"] += 1
        bucket["pnl"] = round(bucket["pnl"] + pnl, 2)
        if pnl > 0:
            wins += 1
            gross_profit += pnl
            bucket["wins"] += 1
        elif pnl < 0:
            losses += 1
            gross_loss += abs(pnl)

    total = len(closed)
    recent_slice = [
        {
            "inst": r.get("inst") or r.get("instId"),
            "side": r.get("side") or r.get("posSide"),
            "open_time": r.get("open_time"),
            "close_time": r.get("close_time"),
            "net_pnl": r.get("net_pnl") if r.get("net_pnl") is not None else r.get("pnl"),
            "roi_pct": r.get("roi_pct"),
            "exit_reason": r.get("exit_reason"),
            "adopted_role": r.get("adopted_role") or (r.get("council") or {}).get("adopted_role"),
        }
        for r in reversed(closed[-limit:])
    ]
    return {
        "filter_symbol": symbol or None,
        "total_closed_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round((wins / total) * 100.0, 2) if total else None,
        "total_net_pnl_usdt": round(total_pnl, 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else None),
        "by_symbol": by_symbol,
        "recent_closed_trades": recent_slice,
    }


def _tool_get_market_factors_and_decisions(args: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(args.get("symbol") or "").strip().upper()
    include_history = bool(args.get("include_history", False))
    try:
        hist_lim = max(1, min(int(args.get("history_limit") or 5), 20))
    except (TypeError, ValueError):
        hist_lim = 5

    factors_raw = _read_data_json("factor_library_snapshot.json", {})
    decisions_raw = _read_data_json("ai_brain_decisions.json", {})

    instruments = factors_raw.get("instruments") if isinstance(factors_raw, dict) else []
    if not isinstance(instruments, list):
        instruments = []
    if symbol:
        instruments = [i for i in instruments if isinstance(i, dict) and symbol in str(i.get("instId") or "").upper()]

    decisions = decisions_raw if isinstance(decisions_raw, dict) else {}
    if symbol:
        decisions = {k: v for k, v in decisions.items() if symbol in str(k).upper()}

    out: Dict[str, Any] = {
        "factor_timestamp": factors_raw.get("time_str") if isinstance(factors_raw, dict) else None,
        "instruments": instruments,
        "latest_decisions": decisions,
    }
    if include_history:
        hist = _read_data_json("ai_brain_history.json", [])
        if isinstance(hist, list):
            out["recent_history"] = hist[-hist_lim:]
    return out


def _tool_get_logs_and_audit(args: Dict[str, Any]) -> Dict[str, Any]:
    source = str(args.get("source") or "trader").strip().lower()
    source_map = {
        "trader": "ai_factor_trader.log",
        "backend": "uvicorn.log",
        "scheduler": "astra_gateway.log",
        "gateway": "astra_gateway.log",
    }
    filename = source_map.get(source, "ai_factor_trader.log")
    try:
        lines_n = max(10, min(int(args.get("lines") or 60), 200))
    except (TypeError, ValueError):
        lines_n = 60
    level = str(args.get("level") or "").strip().upper()
    keyword = str(args.get("keyword") or "").strip().lower()
    include_audit = bool(args.get("include_audit", True))
    try:
        audit_lim = max(1, min(int(args.get("audit_limit") or 25), 100))
    except (TypeError, ValueError):
        audit_lim = 25

    log_path = _logs_root() / filename
    log_lines: List[str] = []
    if log_path.is_file():
        raw_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
        for ln in raw_lines:
            if level and level not in ln.upper():
                continue
            if keyword and keyword not in ln.lower():
                continue
            log_lines.append(_redact_text(ln))
        log_lines = log_lines[-lines_n:]

    res: Dict[str, Any] = {
        "source": source,
        "filename": filename,
        "exists": log_path.is_file(),
        "lines": log_lines,
    }
    if include_audit:
        res["audit_records"] = audit_recent(audit_lim)
    return res


def _tool_get_risk_config(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend import risk_config

    group = str(args.get("group") or "").strip()
    sc = risk_config.schema()
    params = sc.get("params") or []
    if group:
        params = [p for p in params if p.get("group") == group]
    return {
        "groups": sc.get("groups"),
        "params": params,
        "suites": [
            {"id": s["id"], "name": s["name"], "tagline": s.get("tagline"), "values": s.get("values")}
            for s in risk_config.SUITES
        ],
        "current_values": risk_config.current_values(),
        "file_vs_process": risk_config.file_vs_process_diff(),
        "effective_engine_values": risk_config.effective_engine_values(None),
        "high_risk_phrase": risk_config.HIGH_RISK_PHRASE,
    }


def _tool_get_prompt_library(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.prompt_views import EVOLUTION_USER_TEMPLATE, TRADING_USER_TEMPLATE
    from scripts.ai_brain_trader import SYSTEM_PROMPT
    from scripts.prompt_library import (
        ALLOWED_VARIABLES,
        TEMPLATE_VARIABLES_METADATA,
        all_profiles,
        get_profile,
        load_library,
        pipeline_view,
    )
    from scripts.self_improvement_engine import EVOLUTION_SYSTEM_PROMPT

    base_map = {
        "trading_system": SYSTEM_PROMPT,
        "trading_user": TRADING_USER_TEMPLATE,
        "evolution_system": EVOLUTION_SYSTEM_PROMPT,
        "evolution_user": EVOLUTION_USER_TEMPLATE,
    }
    lib = load_library()
    active_id = str(lib.get("active_profile_id") or "")
    target_pid = str(args.get("profile_id") or "").strip() or active_id
    pipeline = str(args.get("pipeline") or "").strip()
    include_content = bool(args.get("include_content", False))

    profiles_brief = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "description": p.get("description"),
            "enabled": p.get("enabled", True),
            "editor_mode": p.get("editor_mode", "modules"),
            "updated_at": p.get("updated_at"),
        }
        for p in all_profiles()
    ]

    prof = get_profile(target_pid)
    keys = [pipeline] if pipeline in base_map else list(base_map.keys())
    pipelines_out: Dict[str, List[Dict[str, Any]]] = {}
    for pk in keys:
        mods = pipeline_view(base_map[pk], prof, pk)
        out_mods = []
        for m in mods:
            entry: Dict[str, Any] = {
                "id": m.get("id"),
                "title": m.get("title"),
                "enabled": m.get("enabled", True),
                "source": m.get("source"),
                "locked": bool(m.get("locked", False)),
                "char_count": len(str(m.get("content") or "")),
            }
            if include_content:
                entry["content"] = str(m.get("content") or "")
            out_mods.append(entry)
        pipelines_out[pk] = out_mods

    return {
        "active_profile_id": active_id,
        "inspected_profile_id": target_pid,
        "inspected_profile_name": prof.get("name"),
        "profiles": profiles_brief,
        "pipelines": pipelines_out,
        "allowed_variables": sorted(ALLOWED_VARIABLES),
        "template_variables": TEMPLATE_VARIABLES_METADATA,
    }


def _tool_get_council_config(_args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.council.attribution import compute_council_seat_performance
    from astra_backend.council_manager import get_preset_suites, load_council_config, seat_model_health

    cfg = load_council_config()
    override_dir = os.environ.get("ASTRA_DATA_DIR", "").strip()
    perf_dir = Path(override_dir) if (override_dir and deps.DATA_DIR == deps.ROOT / "data") else deps.DATA_DIR
    return {
        "config": cfg,
        "model_health": seat_model_health(cfg.get("roles")),
        "seat_performance": compute_council_seat_performance(data_dir=perf_dir),
        "available_suites": get_preset_suites(),
    }


def _tool_get_strategy_extras(_args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.llm.model_health import audit_llm_config
    from astra_backend.llm.policy import SUPPORTED_API_FORMATS
    from astra_backend.llm_manager import load_llm_config
    from astra_backend.trading_session_store import load_trading_session
    from scripts import evolution_shield
    from scripts.instrument_pool import load_instruments
    from scripts.trader.session import coverage_estimate, normalize_session, resolve_session

    llm_cfg = load_llm_config(mask_keys=True)
    formats = tuple(f["id"] for f in SUPPORTED_API_FORMATS)
    norm_sess, errors = normalize_session(load_trading_session())
    sess_state = resolve_session(norm_sess)
    sess_state["errors"] = [*errors, *sess_state.get("errors", [])]
    mem_view = evolution_shield.admin_memory_view()
    mem_view["injection"] = evolution_shield.injection_report(mem_view.get("structured_lessons") or [])

    return {
        "instruments": load_instruments(),
        "pool_limits": {"min": deps.MIN_POOL_SIZE, "max": deps.MAX_POOL_SIZE, "btc_required": True},
        "trading_session": {**norm_sess, "state": sess_state, "coverage": coverage_estimate(norm_sess)},
        "llm_settings": {
            "active_model_id": llm_cfg.get("active_model_id"),
            "active_reasoning_effort": llm_cfg.get("active_reasoning_effort"),
            "thinking_timeout": llm_cfg.get("thinking_timeout"),
            "request_attempts": llm_cfg.get("request_attempts"),
            "fallback_model_ids": llm_cfg.get("fallback_model_ids") or [],
            "models": [
                {
                    "id": m.get("id"),
                    "name": m.get("name"),
                    "provider_name": m.get("provider_name"),
                    "api_format": m.get("api_format"),
                    "reasoning_effort": m.get("reasoning_effort"),
                }
                for m in (llm_cfg.get("models") or [])
                if isinstance(m, dict)
            ],
            "model_health": audit_llm_config(llm_cfg, formats),
        },
        "evolution_config": load_evolution_config(),
        "evolution_memory": mem_view,
    }


def _tool_list_policy_snapshots(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.policy_snapshot import capture_full_strategy_package, generate_policy_snapshot, load_archive_index, package_identity

    try:
        lim = max(1, min(int(args.get("limit") or 15), 50))
    except (TypeError, ValueError):
        lim = 15
    snap = generate_policy_snapshot()
    pkg_hash = package_identity(capture_full_strategy_package().get("package") or {})
    archives = load_archive_index()[:lim]
    return {
        "current": {
            "policy_version": snap.get("policy_version"),
            "policy_hash": snap.get("policy_hash"),
            "package_hash": pkg_hash,
            "summary": snap.get("summary"),
        },
        "archives": archives,
    }


def _tool_diff_policy_snapshot(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.policy_snapshot import ARCHIVE_DIR, _resolve_archive_file, capture_full_strategy_package

    target_hash = str(args.get("target_hash") or "").strip()
    if not target_hash:
        return {"error": "请提供 target_hash（policy_hash 或 package_hash）"}
    arch_file = _resolve_archive_file(ARCHIVE_DIR, target_hash)
    if not arch_file.is_file():
        return {"error": f"未找到策略快照：{target_hash}"}
    archived_doc = json.loads(arch_file.read_text(encoding="utf-8"))
    arch_pkg = archived_doc.get("package") or {}
    cur_pkg = capture_full_strategy_package().get("package") or {}

    risk_diffs: List[Dict[str, Any]] = []
    arch_risk = arch_pkg.get("risk_config") or {}
    cur_risk = cur_pkg.get("risk_config") or {}
    for k in sorted(set(arch_risk.keys()) | set(cur_risk.keys())):
        if arch_risk.get(k) != cur_risk.get(k):
            risk_diffs.append({"key": k, "current": cur_risk.get(k), "snapshot": arch_risk.get(k)})

    arch_prompt = arch_pkg.get("prompt_config") or {}
    cur_prompt = cur_pkg.get("prompt_config") or {}
    arch_council = arch_pkg.get("council_config") or {}
    cur_council = cur_pkg.get("council_config") or {}
    arch_mem = (arch_pkg.get("evolution_memory") or {}).get("lessons") if isinstance(arch_pkg.get("evolution_memory"), dict) else (arch_pkg.get("evolution_memory") or [])
    cur_mem = (cur_pkg.get("evolution_memory") or {}).get("lessons") if isinstance(cur_pkg.get("evolution_memory"), dict) else (cur_pkg.get("evolution_memory") or [])

    return {
        "target_hash": target_hash,
        "snapshot_meta": archived_doc.get("metadata") or {},
        "risk_diffs": risk_diffs,
        "prompt_diff": {
            "current_active_profile": cur_prompt.get("active_profile_id"),
            "snapshot_active_profile": arch_prompt.get("active_profile_id"),
        },
        "council_diff": {
            "current": {"enabled": cur_council.get("enabled"), "consensus_mode": cur_council.get("consensus_mode")},
            "snapshot": {"enabled": arch_council.get("enabled"), "consensus_mode": arch_council.get("consensus_mode")},
        },
        "memory_diff": {
            "current_count": len(cur_mem) if isinstance(cur_mem, list) else 0,
            "snapshot_count": len(arch_mem) if isinstance(arch_mem, list) else 0,
        },
    }


def _parse_cycles_arg(args: Dict[str, Any], default: int = 48, upper: int = 200) -> int:
    try:
        return max(1, min(int(args.get("cycles") or default), upper))
    except (TypeError, ValueError):
        return default


def _extract_history_entries() -> List[Dict[str, Any]]:
    raw = _read_data_json("ai_brain_history.json", [])
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        items = raw.get("history") or raw.get("records") or raw.get("items") or []
        if isinstance(items, list):
            return [r for r in items if isinstance(r, dict)]
    return []


def _tool_diagnose_order_funnel(args: Dict[str, Any]) -> Dict[str, Any]:
    from collections import Counter
    from datetime import datetime

    cycles = _parse_cycles_arg(args, default=48, upper=200)
    history = _extract_history_entries()[-cycles:]

    action_counts: Counter[str] = Counter()
    adopted_role_counts: Counter[str] = Counter()
    advisor_quote_counts: Counter[str] = Counter()
    rejection_reasons: Counter[str] = Counter()
    omitted_count = 0
    total_slots = 0

    for cyc in history:
        decs = cyc.get("decisions")
        dec_list: List[Dict[str, Any]] = []
        if isinstance(decs, dict):
            dec_list = [v for v in decs.values() if isinstance(v, dict)]
        elif isinstance(decs, list):
            dec_list = [v for v in decs if isinstance(v, dict)]

        for item in dec_list:
            total_slots += 1
            act = str(item.get("action") or "WAIT").upper()
            action_counts[act] += 1
            role = str(item.get("adopted_role") or "NONE")
            adopted_role_counts[role] += 1
            reason_txt = str(item.get("reasoning") or item.get("summary_reason") or item.get("reason") or "")
            if item.get("decision_source") == "omitted" or "全市场矩阵综合评估中" in reason_txt:
                omitted_count += 1
            elif act == "WAIT" and reason_txt:
                rejection_reasons[reason_txt[:60]] += 1

        ct = cyc.get("council_transcript") if isinstance(cyc.get("council_transcript"), dict) else {}
        cm = ct.get("consensus_metrics") if isinstance(ct.get("consensus_metrics"), dict) else {}
        by_sym = cm.get("by_symbol") if isinstance(cm.get("by_symbol"), dict) else {}
        for sym_data in by_sym.values():
            if not isinstance(sym_data, dict):
                continue
            for detail in sym_data.get("seat_details") or []:
                if isinstance(detail, dict):
                    advisor_quote_counts[str(detail.get("action") or "WAIT").upper()] += 1

    ledger = _read_data_json("trading_ledger.json", [])
    rows = ledger if isinstance(ledger, list) else (ledger.get("trades") or ledger.get("records") or [] if isinstance(ledger, dict) else [])
    closed_rows = [r for r in rows if isinstance(r, dict) and str(r.get("status") or "").lower() == "closed"]
    latest_trade_ts = ""
    hours_since_last_trade = None
    if closed_rows:
        last = closed_rows[-1]
        latest_trade_ts = str(last.get("exit_time") or last.get("closed_at") or last.get("entry_time") or last.get("timestamp") or "")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
            if not latest_trade_ts:
                break
            try:
                dt = datetime.strptime(latest_trade_ts[:19], fmt)
                hours_since_last_trade = round(max(0.0, (datetime.now() - dt).total_seconds() / 3600.0), 2)
                break
            except ValueError:
                continue

    intents_raw = _read_data_json("open_order_intents.json", [])
    intents = intents_raw if isinstance(intents_raw, list) else []

    log_path = _logs_root() / "ai_factor_trader.log"
    cancel_samples: List[str] = []
    gate_blocks = {"ttl_cancel": 0, "drift_cancel": 0, "rr_block": 0, "conf_block": 0, "other_reject": 0}
    if log_path.is_file():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-600:]
        for ln in lines:
            low = ln.lower()
            if any(k in low for k in ("ttl", "过期", "超期")) and any(k in low for k in ("cancel", "撤")):
                gate_blocks["ttl_cancel"] += 1
                cancel_samples.append(_redact_text(ln))
            elif any(k in low for k in ("drift", "偏离")) and any(k in low for k in ("cancel", "撤")):
                gate_blocks["drift_cancel"] += 1
                cancel_samples.append(_redact_text(ln))
            elif "r:r" in low or "盈亏比" in low:
                gate_blocks["rr_block"] += 1
                if any(k in low for k in ("拒绝", "拦截", "reject", "skip")):
                    cancel_samples.append(_redact_text(ln))
            elif ("置信度" in low or "confidence" in low) and any(k in low for k in ("拒绝", "拦截", "低于", "skip")):
                gate_blocks["conf_block"] += 1
                cancel_samples.append(_redact_text(ln))
            elif any(k in low for k in ("cancel", "撤单", "风控拦截", "下单失败")):
                gate_blocks["other_reject"] += 1
                cancel_samples.append(_redact_text(ln))

    omitted_rate = round((omitted_count / total_slots) * 100.0, 2) if total_slots > 0 else 0.0
    return {
        "cycles_analyzed": len(history),
        "total_decision_slots": total_slots,
        "action_counts": dict(action_counts),
        "adopted_role_counts": dict(adopted_role_counts),
        "advisor_quote_counts": dict(advisor_quote_counts),
        "omitted_decisions_count": omitted_count,
        "omitted_rate_pct": omitted_rate,
        "top_wait_reasons": [{"reason": k, "count": v} for k, v in rejection_reasons.most_common(6)],
        "closed_trades_total": len(closed_rows),
        "latest_trade_time": latest_trade_ts,
        "hours_since_last_trade": hours_since_last_trade,
        "open_intents_count": len(intents),
        "gate_and_cancel_counts": gate_blocks,
        "recent_cancel_or_block_logs": cancel_samples[-12:],
    }


def _tool_audit_strategy_conflicts(_args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend import risk_config
    from astra_backend.council.roster import seat_model_health
    from astra_backend.council_manager import load_council_config
    from scripts.prompt_library import active_profile

    r_values = risk_config.current_values()
    risk_audit = risk_config.audit_risk_consistency(r_values)
    conflicts: List[Dict[str, Any]] = [
        {
            "category": "risk",
            "code": item["code"],
            "severity": item["severity"],
            "title": item["title"],
            "detail": item["detail"],
            "recommendation": item["recommendation"],
        }
        for item in (risk_audit.get("issues") or [])
    ]

    order_mode = (os.getenv("ASTRA_ORDER_MODE") or getattr(settings, "order_mode", "limit") or "limit").strip().lower()
    ttl = float(r_values.get("ASTRA_LIMIT_ORDER_TTL_MINUTES", 90))
    drift = float(r_values.get("ASTRA_LIMIT_ORDER_DRIFT_ATR", 1.2))
    if order_mode == "limit" and (ttl <= 60 or drift <= 0.8):
        conflicts.append({
            "category": "execution",
            "code": "PURE_LIMIT_HIGH_CANCEL_RISK",
            "severity": "warning",
            "title": "纯限价模式与严格超时阈值易导致踏空撤单",
            "detail": f"当前订单模式为 limit 且 TTL={ttl:g}m / 漂移阈值={drift:g}x ATR，顺势启动时挂单难以成交。",
            "recommendation": "建议切换为 smart（智能自适应）订单模式，近盘抓机遇、深回踩挂限价。",
        })

    try:
        prof = active_profile()
        sys_txt = str(prof.get("trading_system") or "")
        min_conf = float(r_values.get("ASTRA_MIN_ENTRY_CONFIDENCE", 72.0))
        if min_conf < 72.0 and "confidence < 72" in sys_txt:
            conflicts.append({
                "category": "prompt",
                "code": "PROMPT_CONFIDENCE_STALE",
                "severity": "warning",
                "title": "提示词内残留硬编码 72% 置信度门槛",
                "detail": f"当前风控开仓门禁已设为核心 {min_conf:g}%，但提示词正文仍要求 confidence < 72 直接 WAIT。",
                "recommendation": "同步激活提示词方案以引用【本周期风险预算】动态门禁。",
            })
        if "不接受 BEAR_EXHAUSTING" in sys_txt or "BULL_EXHAUSTING ＋ alpha ≤ 0 ⇒ WAIT" in sys_txt:
            conflicts.append({
                "category": "prompt",
                "code": "PROMPT_BAN_A_OVERCONSTRAINED",
                "severity": "info",
                "title": "提示词包含较严格的动能衰竭一刀切禁令",
                "detail": "当行情处于趋势中继小幅减速回踩（EXHAUSTING）时，旧版禁令 A 与做空规则会全量拦截潜在回踩/反弹结构单。",
                "recommendation": "若目标为高频活跃风格，可升级为结构位豁免版提示词模块。",
            })
    except Exception:
        pass

    try:
        c_cfg = load_council_config()
        if c_cfg.get("enabled", False):
            roles = c_cfg.get("roles") or {}
            health_rows = seat_model_health(roles)
            unbound = [r["role_id"] for r in health_rows if r.get("enabled", True) and not r.get("registered", True)]
            if unbound:
                conflicts.append({
                    "category": "council",
                    "code": "COUNCIL_UNREGISTERED_MODEL",
                    "severity": "warning",
                    "title": "投委会部分启用席位未绑定有效模型",
                    "detail": f"席位 {', '.join(unbound)} 当前绑定模型未在 LLM 管理中登记，运行时将被主脑代答或降质。",
                    "recommendation": "为对应席位分配已验证模型或暂禁非必要席位。",
                })
            if str(c_cfg.get("consensus_mode") or "standard") != "standard" and float(c_cfg.get("timeout_seconds") or 240) < 120:
                conflicts.append({
                    "category": "council",
                    "code": "COUNCIL_TIMEOUT_TIGHT",
                    "severity": "warning",
                    "title": "多轮投委会超时预算过紧",
                    "detail": "开启交叉质询/红蓝对抗模式下，总超时 < 120s 易导致 CIO 裁决阶段超时降级。",
                    "recommendation": "建议将 timeout_seconds 提升至 ≥ 240s 或切回 standard 单轮合议。",
                })
    except Exception:
        pass

    critical = sum(1 for c in conflicts if c["severity"] == "critical")
    warnings = sum(1 for c in conflicts if c["severity"] == "warning")
    return {
        "ok": critical == 0,
        "status": "critical" if critical else ("warning" if warnings else "healthy"),
        "critical_count": critical,
        "warning_count": warnings,
        "order_mode": order_mode,
        "risk_audit": risk_audit,
        "conflicts": conflicts,
    }


def _tool_inspect_council_debates(args: Dict[str, Any]) -> Dict[str, Any]:
    cycles = _parse_cycles_arg(args, default=12, upper=50)
    history = _extract_history_entries()[-cycles:]
    rounds: List[Dict[str, Any]] = []
    for cyc in reversed(history):
        ct = cyc.get("council_transcript") if isinstance(cyc.get("council_transcript"), dict) else {}
        if not ct:
            continue
        arb = ct.get("arbitrator") if isinstance(ct.get("arbitrator"), dict) else {}
        advisors = ct.get("advisors") if isinstance(ct.get("advisors"), dict) else {}
        advisor_brief = []
        for rk, rv in advisors.items():
            if isinstance(rv, dict):
                advisor_brief.append({
                    "role_id": rk,
                    "role_name": rv.get("role_name") or rk,
                    "status": rv.get("status"),
                    "model_used": rv.get("model_used"),
                    "latency_ms": rv.get("latency_ms"),
                    "weight": rv.get("weight"),
                })
        cm = ct.get("consensus_metrics") if isinstance(ct.get("consensus_metrics"), dict) else {}
        decs = cyc.get("decisions") if isinstance(cyc.get("decisions"), dict) else {}
        adopted_summary: Dict[str, Any] = {}
        for sym, d in (decs.items() if isinstance(decs, dict) else []):
            if isinstance(d, dict):
                adopted_summary[sym] = {
                    "action": d.get("action"),
                    "adopted_role": d.get("adopted_role"),
                    "confidence": d.get("confidence"),
                }
        rounds.append({
            "timestamp": cyc.get("timestamp") or cyc.get("time_str") or "",
            "consensus_mode": ct.get("consensus_mode"),
            "total_duration_ms": ct.get("total_duration_ms"),
            "arbitrator_model": arb.get("model_used"),
            "arbitrator_latency_ms": arb.get("latency_ms"),
            "advisors": advisor_brief,
            "strong_consensus_symbols": cm.get("strong_consensus_symbols") or [],
            "disputed_symbols": cm.get("disputed_symbols") or [],
            "decisions_summary": adopted_summary,
        })
    return {
        "cycles_scanned": len(history),
        "council_rounds": rounds,
    }


def _tool_inspect_order_execution_and_cancels(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        lines_n = max(10, min(int(args.get("lines") or 50), 120))
    except (TypeError, ValueError):
        lines_n = 50
    intents = _read_data_json("open_order_intents.json", [])
    trackers = _read_data_json("position_trackers.json", {})
    pending_orders: List[Dict[str, Any]] = []
    try:
        import astra_backend.dashboard_cache as dash_cache
        cache = getattr(dash_cache, "CACHE_DATA", None)
        if isinstance(cache, dict) and isinstance(cache.get("pending_orders"), list):
            pending_orders = list(cache["pending_orders"])
    except Exception:
        pass

    log_path = _logs_root() / "ai_factor_trader.log"
    events: List[str] = []
    if log_path.is_file():
        raw = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
        for ln in raw:
            low = ln.lower()
            if any(k in low for k in ("order", "下单", "挂单", "撤单", "cancel", "市价", "智能", "limit", "oco", "拦截")):
                events.append(_redact_text(ln))

    return {
        "order_mode": (os.getenv("ASTRA_ORDER_MODE") or getattr(settings, "order_mode", "limit") or "limit").strip().lower(),
        "open_order_intents": intents if isinstance(intents, list) else [],
        "active_trackers": trackers if isinstance(trackers, dict) else {},
        "pending_orders_live": pending_orders,
        "execution_log_events": events[-lines_n:],
    }


def build_proactive_insights() -> Dict[str, Any]:
    """生成后台指挥台主动诊断洞见卡与策略健康分。"""
    from datetime import datetime, timedelta, timezone

    conflicts_res = _tool_audit_strategy_conflicts({})
    funnel_res = _tool_diagnose_order_funnel({"cycles": 48})
    summary = build_state_summary()

    insights: List[Dict[str, Any]] = []
    for idx, c in enumerate(conflicts_res.get("conflicts") or []):
        cat = c.get("category") or "risk"
        prompt = "请帮我检查当前风控与策略冲突并给出最稳妥的修复方案" if cat == "risk" else (
            "请检查当前委托订单模式与提示词/投委会配置冲突并生成调整提案"
        )
        insights.append({
            "id": f"conflict_{c.get('code', idx)}",
            "severity": c.get("severity") or "warning",
            "category": cat,
            "title": c.get("title") or "策略参数冲突",
            "detail": f"{c.get('detail', '')} 建议：{c.get('recommendation', '')}".strip(),
            "metric": f"{conflicts_res.get('order_mode', 'limit')} · {summary.get('risk', {}).get('active_suite_id', 'custom')}",
            "suggested_prompt": prompt,
        })

    total_slots = int(funnel_res.get("total_decision_slots") or 0)
    action_counts = funnel_res.get("action_counts") or {}
    opened_signals = int(action_counts.get("BUY_LONG") or 0) + int(action_counts.get("SELL_SHORT") or 0)
    omitted_pct = float(funnel_res.get("omitted_rate_pct") or 0.0)

    if omitted_pct >= 10.0 and total_slots > 0:
        insights.append({
            "id": "funnel_omitted_degradation",
            "severity": "warning",
            "category": "council",
            "title": f"决策遗漏降级偏高（{omitted_pct:g}%）",
            "detail": f"最近 {funnel_res.get('cycles_analyzed', 0)} 个周期中 {funnel_res.get('omitted_decisions_count', 0)} 个标的槽位被降级为占位 WAIT，建议检查 CIO 输出与超时预算。",
            "metric": f"{omitted_pct:g}% omitted",
            "suggested_prompt": "请调用 inspect_council_debates 与 diagnose_order_funnel 排查为何 CIO 漏答部分标的",
        })

    if total_slots >= 12 and opened_signals == 0:
        hrs = funnel_res.get("hours_since_last_trade")
        hrs_txt = f"距上一笔已平仓交易约 {hrs} 小时，" if hrs is not None else ""
        insights.append({
            "id": "funnel_zero_entry_drought",
            "severity": "warning",
            "category": "funnel",
            "title": "近期决策漏斗零开仓信号",
            "detail": f"{hrs_txt}最近 {funnel_res.get('cycles_analyzed', 0)} 轮共 {total_slots} 个决策槽位全部输出 WAIT。",
            "metric": f"0/{total_slots} entries",
            "suggested_prompt": "系统近期很难开单，请诊断开单漏斗与取消原因，并帮我优化为高频活跃策略配置",
        })

    if summary.get("data_health", {}).get("overall") != "LIVE":
        insights.append({
            "id": "data_health_stale",
            "severity": "info",
            "category": "health",
            "title": "部分本地缓存或行情快照非最新",
            "detail": "后台缓存或因子文件时间戳偏旧，确认交易守护进程与调度器正常运转。",
            "metric": str(summary.get("data_health", {}).get("overall") or "STALE"),
            "suggested_prompt": "请检查系统运行健康与最新 trader/gateway 日志",
        })

    crit_n = sum(1 for i in insights if i["severity"] == "critical")
    warn_n = sum(1 for i in insights if i["severity"] == "warning")
    health_score = max(0, min(100, 100 - min(60, crit_n * 25) - min(35, warn_n * 10)))
    bj_now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "health_score": health_score,
        "critical_count": crit_n,
        "warning_count": warn_n,
        "insights": insights,
        "funnel_snapshot": {
            "cycles_analyzed": funnel_res.get("cycles_analyzed", 0),
            "opened_signals": opened_signals,
            "total_slots": total_slots,
            "omitted_rate_pct": omitted_pct,
            "hours_since_last_trade": funnel_res.get("hours_since_last_trade"),
        },
        "generated_at": bj_now,
    }


def build_inspector_payload() -> Dict[str, Any]:
    """返回右侧 5-Tab 策略透视面板所需的全量只读结构化数据。"""
    overview = build_state_summary()
    risk_data = _tool_get_risk_config({})
    risk_data["order_mode"] = overview.get("risk", {}).get("order_mode", "limit")
    risk_data["risk_audit"] = overview.get("risk", {}).get("risk_audit", {})

    prompt_raw = _tool_get_prompt_library({"include_content": True})
    compact_pipes: Dict[str, List[Dict[str, Any]]] = {}
    for pk, mods in (prompt_raw.get("pipelines") or {}).items():
        compact_pipes[pk] = [
            {
                "id": m.get("id"),
                "title": m.get("title"),
                "enabled": m.get("enabled", True),
                "locked": m.get("locked", False),
                "char_count": m.get("char_count", 0),
                "preview": str(m.get("content") or "")[:240],
            }
            for m in (mods or [])
            if isinstance(m, dict)
        ]
    prompt_data = {
        "active_profile_id": prompt_raw.get("active_profile_id"),
        "inspected_profile_id": prompt_raw.get("inspected_profile_id"),
        "inspected_profile_name": prompt_raw.get("inspected_profile_name"),
        "profiles": prompt_raw.get("profiles") or [],
        "pipelines": compact_pipes,
    }

    council_data = _tool_get_council_config({})
    snapshots_data = _tool_list_policy_snapshots({"limit": 12})
    return {
        "overview": overview,
        "risk": risk_data,
        "prompt": prompt_data,
        "council": council_data,
        "snapshots": snapshots_data,
    }


READ_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "get_system_overview",
        "description": "获取系统运行总览（模拟/实盘环境、持仓挂单数、数据健康、激活模型、风控红线、投委会、标的池、交易时段与当前策略快照）。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_live_account_and_positions",
        "description": "查询实时账户权益、可用保证金、当前持仓明细（含浮盈、杠杆与保护单状态）和在途挂单。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_trade_performance_and_ledger",
        "description": "查询历史平仓台账统计：总胜率、盈亏比、净盈亏、分币种战绩及最近平仓明细（可按币种过滤，用于亏损复盘与归因）。",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "可选币种过滤（如 BTC 或 BTC-USDT-SWAP）"},
                "limit": {"type": "integer", "description": "返回最近多少笔已平仓记录（1~100，默认25）"},
            },
        },
    },
    {
        "name": "get_market_factors_and_decisions",
        "description": "查询最新7梯队量化因子快照、AI 主脑最新决策与思维链摘要（可选附带最近决策历史）。",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "可选标的过滤，如 BTC-USDT-SWAP"},
                "include_history": {"type": "boolean", "description": "是否返回最近决策历史"},
                "history_limit": {"type": "integer", "description": "决策历史条数（1~20，默认5）"},
            },
        },
    },
    {
        "name": "get_logs_and_audit",
        "description": "查看系统运行日志（trader/backend/scheduler）及后台操作审计记录，支持按级别或关键字过滤。",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "enum": ["trader", "backend", "scheduler", "gateway"], "description": "日志源"},
                "lines": {"type": "integer", "description": "返回日志行数（10~200，默认60）"},
                "level": {"type": "string", "description": "可选日志级别过滤（INFO/WARNING/ERROR/CRITICAL）"},
                "keyword": {"type": "string", "description": "可选关键词过滤"},
                "include_audit": {"type": "boolean", "description": "是否同时返回最近管理员审计记录"},
                "audit_limit": {"type": "integer", "description": "审计记录条数（默认25）"},
            },
        },
    },
    {
        "name": "get_risk_config",
        "description": "查询当前 32 项物理风控参数 schema、预设套件（保守/平衡/激进）、当前值、进程漂移及高危阈值。",
        "parameters": {
            "type": "object",
            "properties": {
                "group": {"type": "string", "description": "可选分组过滤：exposure/exit_strategy/per_trade/stop_loss/pyramiding"},
            },
        },
    },
    {
        "name": "get_prompt_library",
        "description": "查询提示词方案库、当前激活方案、各管线模块清单及完整正文（修改提示词前务必先调用本工具查看精确 module_id 与内容）。",
        "parameters": {
            "type": "object",
            "properties": {
                "profile_id": {"type": "string", "description": "留空则查看当前激活方案"},
                "pipeline": {"type": "string", "enum": ["trading_system", "trading_user", "evolution_system", "evolution_user"], "description": "可选管线过滤"},
                "include_content": {"type": "boolean", "description": "是否返回模块正文（编辑前请传 true）"},
            },
        },
    },
    {
        "name": "get_council_config",
        "description": "查询多模型投委会开关、仲裁模式、超时预算、各席位角色提示词/权重/绑定模型健康度及历史带单归因战绩。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_strategy_extras",
        "description": "查询交易标的池、交易时段闸门、LLM 全局设置（主脑/思考强度/回退链，不含密钥）、自进化模型配置与心法库条目。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_policy_snapshots",
        "description": "列出当前策略指纹与历史归档策略快照列表（用于版本对比与回滚）。",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "返回数量（默认15）"}},
        },
    },
    {
        "name": "diff_policy_snapshot",
        "description": "对比指定历史策略快照（policy_hash 或 package_hash）与当前运行态的详细差异。",
        "parameters": {
            "type": "object",
            "required": ["target_hash"],
            "properties": {"target_hash": {"type": "string", "description": "目标快照的 policy_hash 或 package_hash"}},
        },
    },
    {
        "name": "diagnose_order_funnel",
        "description": "深度诊断近期开单漏斗（决策动作分布、CIO采纳归属、遗漏降级率、距上次成交小时数、TTL/偏离撤单与R:R拦截统计）。",
        "parameters": {
            "type": "object",
            "properties": {
                "cycles": {"type": "integer", "description": "统计最近多少轮决策历史（1~200，默认48）"},
            },
        },
    },
    {
        "name": "audit_strategy_conflicts",
        "description": "全面体检风控参数数学死锁（SL/TP/RR）、委托订单模式与超时配置兼容性、提示词正文与投委会席位冲突。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "inspect_council_debates",
        "description": "透视最近 N 轮多模型投委会辩论详情（模式、总耗时、CIO与各参谋席位响应/耗时/权重、共识矩阵与裁决归属）。",
        "parameters": {
            "type": "object",
            "properties": {
                "cycles": {"type": "integer", "description": "查看最近几轮委员会裁决（1~50，默认12）"},
            },
        },
    },
    {
        "name": "inspect_order_execution_and_cancels",
        "description": "查看委托订单模式、本地开仓意图队列、在途活动挂单以及近期撮合下单/撤单/拦截日志（自动脱敏）。",
        "parameters": {
            "type": "object",
            "properties": {
                "lines": {"type": "integer", "description": "返回日志行数（10~120，默认50）"},
            },
        },
    },
]

_READ_HANDLERS = {
    "get_system_overview": _tool_get_system_overview,
    "get_live_account_and_positions": _tool_get_live_account_and_positions,
    "get_trade_performance_and_ledger": _tool_get_trade_performance_and_ledger,
    "get_market_factors_and_decisions": _tool_get_market_factors_and_decisions,
    "get_logs_and_audit": _tool_get_logs_and_audit,
    "get_risk_config": _tool_get_risk_config,
    "get_prompt_library": _tool_get_prompt_library,
    "get_council_config": _tool_get_council_config,
    "get_strategy_extras": _tool_get_strategy_extras,
    "list_policy_snapshots": _tool_list_policy_snapshots,
    "diff_policy_snapshot": _tool_diff_policy_snapshot,
    "diagnose_order_funnel": _tool_diagnose_order_funnel,
    "audit_strategy_conflicts": _tool_audit_strategy_conflicts,
    "inspect_council_debates": _tool_inspect_council_debates,
    "inspect_order_execution_and_cancels": _tool_inspect_order_execution_and_cancels,
}


def execute_read_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    handler = _READ_HANDLERS.get(name)
    if not handler:
        raise ValueError(f"未知只读工具：{name}")
    return handler(args or {})
