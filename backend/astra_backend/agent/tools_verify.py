"""只读验证与演练工具（实景快照决策预演 + 历史 K 线风控回测对比），绝不写盘或下单。"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict
from typing import Any, Dict, List

from astra_backend.agent.tools_read import _read_data_json


def _build_live_snapshot_market_context() -> tuple[str, Dict[str, Any]]:
    """从真实缓存构建市场上下文（与 routers/strategy/council.py 同口径，缺什么标什么，绝不臆造）。"""
    meta: Dict[str, Any] = {"source": "live", "missing": []}
    lines = ["======================= 【推演基准与资金持仓（真实快照）】 ======================="]

    factor_snap = _read_data_json("factor_library_snapshot.json", {})
    snap_ts = ""
    instruments: List[Dict[str, Any]] = []
    if isinstance(factor_snap, dict):
        snap_ts = str(factor_snap.get("time_str") or factor_snap.get("timestamp") or "")
        instruments = [i for i in (factor_snap.get("instruments") or []) if isinstance(i, dict)]
    lines.append(f"【推演基准时间】: {snap_ts or '—（因子快照不可用）'}")

    account = positions = pending = None
    try:
        import astra_backend.dashboard_cache as dash_cache
        cache = getattr(dash_cache, "CACHE_DATA", None)
        if isinstance(cache, dict):
            account = cache.get("account") if isinstance(cache.get("account"), dict) else None
            positions = cache.get("positions") if isinstance(cache.get("positions"), list) else None
            pending = cache.get("pending_orders") if isinstance(cache.get("pending_orders"), list) else None
        else:
            meta["missing"].append("dashboard 缓存不可用")
    except Exception as exc:
        meta["missing"].append(f"dashboard 缓存读取失败: {str(exc)[:80]}")

    if account:
        lines.append(
            f"【当前账户可用资金】: {account.get('avail_eq', '—')} USDT"
            f"（总权益 {account.get('total_eq', '—')} USDT）"
        )
    else:
        meta["missing"].append("账户快照")
        lines.append("【当前账户可用资金】: —（账户快照不可用）")

    if positions is None:
        meta["missing"].append("持仓快照")
        lines.append("【当前活动在途持仓明细】: —（持仓快照不可用）")
    else:
        lines.append(f"【当前活动在途持仓明细】(共 {len(positions)} 笔):")
        for pos in positions[:8]:
            if isinstance(pos, dict):
                lines.append(
                    f"- 标的: {pos.get('instId', '—')} | 方向: {pos.get('posSide', '—')}"
                    f" | 持仓量: {pos.get('pos', '—')} | 未结浮盈: {pos.get('upl', '—')}"
                )
        if not positions:
            lines.append("- （当前无持仓）")

    if pending is None:
        meta["missing"].append("挂单快照")
        lines.append("【当前在途挂单列表】: —（挂单快照不可用）")
    else:
        lines.append(f"【当前在途挂单列表】(共 {len(pending)} 笔):")
        for od in pending[:8]:
            if isinstance(od, dict):
                lines.append(
                    f"- [挂单ID: {od.get('ordId') or od.get('id') or '—'}] {od.get('instId', '—')}"
                    f" | 价格: {od.get('px', '—')} | 数量: {od.get('sz', '—')}"
                )
        if not pending:
            lines.append("- （当前无挂单）")

    lines.append("")
    lines.append(f"======================= 【市场全要素动力学与微结构实时快照 ({len(instruments)} 大主力标的)】 =======================")
    if not instruments:
        meta["missing"].append("因子快照")
        lines.append("- —（因子快照不可用，禁止臆造行情）")
    for item in instruments:
        momentum = item.get("trend_momentum") if isinstance(item.get("trend_momentum"), dict) else {}
        vol = item.get("volatility_channel") if isinstance(item.get("volatility_channel"), dict) else {}
        flow = item.get("volume_money_flow") if isinstance(item.get("volume_money_flow"), dict) else {}
        smart = item.get("smart_money_derivatives") if isinstance(item.get("smart_money_derivatives"), dict) else {}
        lines.append(
            f"- {item.get('instId', '—')}: 现价 ${item.get('price', '—')} ({item.get('chg24h', '—')}%), "
            f"ADX={momentum.get('adx_1h', '—')}, RSI={momentum.get('rsi_14', '—')}, 趋势={momentum.get('trend_regime', '—')}, "
            f"1H ATR={vol.get('atr_1h', '—')}, CMF={flow.get('cmf_1h', '—')}, "
            f"聪明钱多头={smart.get('weighted_long_pct', '—')}%"
        )

    meta["factor_time"] = snap_ts or None
    meta["instruments"] = len(instruments)
    return "\n".join(lines), meta


def _apply_candidate_prompt_overrides(profile: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    from scripts.prompt_library import (
        TEMPLATE_KEYS,
        _clean_profile,
        demote_edited_base_modules,
        get_profile,
        pipeline_view,
        validate_profile,
    )
    from astra_backend.prompt_views import EVOLUTION_USER_TEMPLATE, TRADING_USER_TEMPLATE
    from scripts.ai_brain_trader import SYSTEM_PROMPT
    from scripts.self_improvement_engine import EVOLUTION_SYSTEM_PROMPT

    base_map = {
        "trading_system": SYSTEM_PROMPT,
        "trading_user": TRADING_USER_TEMPLATE,
        "evolution_system": EVOLUTION_SYSTEM_PROMPT,
        "evolution_user": EVOLUTION_USER_TEMPLATE,
    }
    target_pid = str(overrides.get("profile_id") or profile.get("id") or "")
    cand = get_profile(target_pid) if target_pid and target_pid != profile.get("id") else copy.deepcopy(profile)
    pipe = str(overrides.get("pipeline") or "trading_system")
    if pipe not in TEMPLATE_KEYS:
        raise ValueError(f"无效提示词管线：{pipe}")

    modules = copy.deepcopy(pipeline_view(base_map[pipe], cand, pipe))
    mod_id = str(overrides.get("module_id") or "").strip()
    mod_title = str(overrides.get("module_title") or "").strip()

    matched_idx = None
    for idx, m in enumerate(modules):
        if (mod_id and m.get("id") == mod_id) or (mod_title and m.get("title") == mod_title):
            matched_idx = idx
            break
    if matched_idx is None:
        if mod_title and overrides.get("content"):
            modules.append({
                "title": mod_title,
                "content": str(overrides["content"]),
                "enabled": bool(overrides.get("enabled", True)),
                "source": "custom",
            })
        else:
            raise ValueError(f"在 {pipe} 中未找到目标模块（module_id={mod_id!r}, module_title={mod_title!r}）")
    else:
        if "content" in overrides and overrides["content"] is not None:
            modules[matched_idx]["content"] = str(overrides["content"])
        if "enabled" in overrides and overrides["enabled"] is not None:
            modules[matched_idx]["enabled"] = bool(overrides["enabled"])

    pipelines = copy.deepcopy(cand.get("pipelines") or {})
    pipelines[pipe] = demote_edited_base_modules(modules, base_map[pipe], pipe)
    cand = _clean_profile({**cand, "pipelines": pipelines}, str(cand.get("id") or "preview"))
    check = validate_profile(cand)
    if not check["valid"]:
        raise ValueError("；".join(check["errors"]))
    return cand


def _tool_dry_run_decision_preview(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.council.debate import execute_council_debate as core_council_debate
    from astra_backend.council_manager import (
        _call_single_trader,
        _call_single_trader_critique,
        load_council_config,
        resolve_seat_model,
    )
    from astra_backend.llm_manager import execute_llm_request
    from scripts.ai_brain_trader import SYSTEM_PROMPT
    from scripts.prompt_library import active_profile, apply_module_layout, compile_modules

    mode = str(args.get("mode") or "single").strip().lower()
    custom_market = str(args.get("custom_market_prompt") or "").strip()
    if custom_market:
        test_market = custom_market
        context_meta: Dict[str, Any] = {"source": "manual_mock", "missing": []}
    else:
        test_market, context_meta = _build_live_snapshot_market_context()

    prof = active_profile()
    prompt_overrides = args.get("prompt_overrides")
    if isinstance(prompt_overrides, dict) and prompt_overrides:
        prof = _apply_candidate_prompt_overrides(prof, prompt_overrides)

    sys_mods = (prof.get("pipelines") or {}).get("trading_system") or []
    compiled_sys = compile_modules(sys_mods) if sys_mods else SYSTEM_PROMPT
    test_sys = apply_module_layout(
        compiled_sys,
        prof,
        "trading_system",
        "Agent演练",
        context={"market_matrix": test_market, "profile_name": prof.get("name", "")},
    )

    live_decisions = _read_data_json("ai_brain_decisions.json", {})
    live_summary = {
        k: {
            "action": ((v.get("decision") or {}).get("action") if isinstance(v, dict) else None),
            "confidence": ((v.get("decision") or {}).get("confidence") if isinstance(v, dict) else None),
        }
        for k, v in (live_decisions.items() if isinstance(live_decisions, dict) else [])
    }

    if mode == "council":
        c_cfg = copy.deepcopy(load_council_config())
        c_over = args.get("council_overrides")
        if isinstance(c_over, dict):
            if "consensus_mode" in c_over and c_over["consensus_mode"]:
                c_cfg["consensus_mode"] = str(c_over["consensus_mode"])
            if "timeout_seconds" in c_over and c_over["timeout_seconds"] is not None:
                c_cfg["timeout_seconds"] = float(c_over["timeout_seconds"])
            role_over = c_over.get("roles")
            if isinstance(role_over, dict):
                roles = c_cfg.setdefault("roles", {})
                for rid, patch_data in role_over.items():
                    if isinstance(patch_data, dict) and rid in roles and isinstance(roles[rid], dict):
                        roles[rid].update(patch_data)

        brain_output, transcript = core_council_debate(
            lambda: c_cfg,
            resolve_seat_model,
            _call_single_trader,
            _call_single_trader_critique,
            market_prompt=test_market,
            original_system_prompt=test_sys,
            timeout=float(c_cfg.get("timeout_seconds") or 120.0),
            runtime_context={"market_matrix": test_market, "profile_name": prof.get("name", ""), "trading_memory": ""},
        )
        return {
            "ok": True,
            "mode": "council",
            "market_context": context_meta,
            "candidate_output": brain_output,
            "transcript": transcript,
            "current_live_decisions": live_summary,
        }

    content, reasoning, usage, latency = execute_llm_request(
        messages=[
            {"role": "system", "content": test_sys},
            {"role": "user", "content": f"【预演市场快照】\n{test_market}\n\n请按系统提示词契约输出 JSON 决策（仅演练，不实际下单）。"},
        ],
        response_format={"type": "json_object"},
        allow_fallback=True,
    )
    cleaned = content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    try:
        parsed_out = json.loads(cleaned.strip())
    except json.JSONDecodeError:
        parsed_out = {"raw_text": content[:2000]}

    return {
        "ok": True,
        "mode": "single",
        "market_context": context_meta,
        "latency_ms": latency,
        "usage": usage,
        "reasoning_excerpt": (reasoning or "")[:800],
        "candidate_output": parsed_out,
        "current_live_decisions": live_summary,
    }


def _run_portfolio_variant(
    candles_by_symbol: Dict[str, List[Dict[str, Any]]],
    risk_values: Dict[str, Any],
    capital_per_asset: float = 10000.0,
) -> Dict[str, Any]:
    from scripts.backtest.metrics import aggregate_portfolio
    from scripts.backtest_engine import BacktestEngine

    risk_pct = float(risk_values.get("ASTRA_RISK_PER_TRADE_RATIO", 0.02))
    min_conf = float(risk_values.get("ASTRA_MIN_ENTRY_CONFIDENCE", 75.0)) / 100.0
    min_rr = float(risk_values.get("ASTRA_MIN_RISK_REWARD", 2.0))

    asset_results: Dict[str, Any] = {}
    combined_trades: List[Dict[str, Any]] = []
    total_final = 0.0
    total_filtered = 0
    symbols = list(candles_by_symbol.keys())

    for sym, candles in candles_by_symbol.items():
        engine = BacktestEngine(
            initial_capital=capital_per_asset,
            risk_per_trade_pct=risk_pct,
            min_confidence_gate=min_conf,
            min_rr_gate=min_rr,
        )
        summary = engine.run(candles)
        asset_results[sym] = asdict(summary)
        total_final += summary.final_equity
        total_filtered += summary.gatekeeper_filtered_count
        combined_trades.extend(summary.recent_trades)

    portfolio = aggregate_portfolio(
        asset_results=asset_results,
        symbols=symbols,
        total_initial=capital_per_asset * len(symbols),
        total_final=total_final,
        total_gatekeeper_filtered=total_filtered,
        combined_trades=combined_trades,
    )
    return {"portfolio": portfolio, "by_symbol": asset_results}


def _tool_backtest_risk_comparison(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend import risk_config
    from scripts.backtest_engine import fetch_okx_candles
    from scripts.instrument_pool import load_instruments

    raw_symbols = args.get("symbols")
    if isinstance(raw_symbols, list) and raw_symbols:
        symbols = [str(s).strip().upper() for s in raw_symbols if str(s).strip()][:4]
    else:
        symbols = [str(i.get("instId")) for i in load_instruments()[:3] if i.get("instId")]
    if not symbols:
        symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]

    bar = str(args.get("bar") or "1H").strip()
    try:
        limit = max(30, min(int(args.get("limit") or 120), 300))
    except (TypeError, ValueError):
        limit = 120

    candidate_raw = args.get("candidate_risk_values") or {}
    if not isinstance(candidate_raw, dict) or not candidate_raw:
        return {"ok": False, "error": "请提供 candidate_risk_values 用于回测对比"}
    # 通过同一校验口径先验证候选参数合法性
    normalized = risk_config.normalize(candidate_raw)
    cur_vals = risk_config.current_values()
    cand_vals = {**cur_vals}
    for k, v in normalized.items():
        cand_vals[k] = float(v)

    candles_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    failed_symbols: List[str] = []
    for sym in symbols:
        candles = fetch_okx_candles(sym, bar=bar, limit=limit)
        if candles and len(candles) >= 20:
            candles_by_symbol[sym] = candles
        else:
            failed_symbols.append(sym)

    if not candles_by_symbol:
        return {
            "ok": False,
            "error": "无法获取 OKX 实时历史 K 线数据（离线或上游限流），已按红线拒绝对合成 K 线跑假回测。",
            "failed_symbols": failed_symbols,
        }

    baseline_res = _run_portfolio_variant(candles_by_symbol, cur_vals)
    candidate_res = _run_portfolio_variant(candles_by_symbol, cand_vals)

    b_port = baseline_res["portfolio"]
    c_port = candidate_res["portfolio"]
    delta = {}
    for metric in (
        "total_return_pct",
        "win_rate_pct",
        "profit_factor",
        "max_drawdown_pct",
        "sharpe_ratio",
        "avg_r_multiple",
        "gatekeeper_filtered_count",
        "total_trades",
    ):
        if metric in b_port and metric in c_port:
            delta[metric] = round(float(c_port[metric]) - float(b_port[metric]), 3)

    return {
        "ok": True,
        "symbols_tested": list(candles_by_symbol.keys()),
        "failed_symbols": failed_symbols,
        "bar": bar,
        "candles_per_symbol": limit,
        "note": "基于当前回测引擎可用门禁（单笔1R风险/最小置信度/最小盈亏比）的历史 K 线对照实验，仅作决策参考。",
        "baseline": b_port,
        "candidate": c_port,
        "delta": delta,
    }


VERIFY_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "dry_run_decision_preview",
        "description": "只读预演：使用当前真实行情与持仓快照，试跑候选提示词修改或投委会调整，并与当前现网决策对比（绝不下单或落盘）。",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["single", "council"], "description": "single=主脑单模型预演；council=投委会辩论预演"},
                "prompt_overrides": {
                    "type": "object",
                    "description": "可选：内存级临时覆盖的提示词模块 {profile_id, pipeline, module_id, module_title, content, enabled}",
                },
                "council_overrides": {
                    "type": "object",
                    "description": "可选：内存级临时覆盖的投委会配置 {consensus_mode, timeout_seconds, roles}",
                },
                "custom_market_prompt": {"type": "string", "description": "可选：手动指定演练文本；留空则使用真实快照"},
            },
        },
    },
    {
        "name": "backtest_risk_comparison",
        "description": "只读回测对比：拉取真实 OKX 历史 K 线，对比当前风控参数与候选风控参数（1R风险/最小置信度/最小盈亏比）的收益率、胜率、最大回撤与 Sharpe 差异。",
        "parameters": {
            "type": "object",
            "required": ["candidate_risk_values"],
            "properties": {
                "candidate_risk_values": {"type": "object", "description": "候选风控参数键值对，如 {\"ASTRA_MIN_ENTRY_CONFIDENCE\": 80}"},
                "symbols": {"type": "array", "items": {"type": "string"}, "description": "可选币种列表（最多4个，默认取标的池前3个）"},
                "bar": {"type": "string", "description": "K线周期，默认 1H"},
                "limit": {"type": "integer", "description": "K线数量（30~300，默认120）"},
            },
        },
    },
]

_VERIFY_HANDLERS = {
    "dry_run_decision_preview": _tool_dry_run_decision_preview,
    "backtest_risk_comparison": _tool_backtest_risk_comparison,
}


def execute_verify_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    handler = _VERIFY_HANDLERS.get(name)
    if not handler:
        raise ValueError(f"未知验证工具：{name}")
    return handler(args or {})
