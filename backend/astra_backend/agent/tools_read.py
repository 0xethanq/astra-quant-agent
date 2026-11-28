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
}


def execute_read_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    handler = _READ_HANDLERS.get(name)
    if not handler:
        raise ValueError(f"未知只读工具：{name}")
    return handler(args or {})
