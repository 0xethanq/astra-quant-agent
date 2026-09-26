"""决策校验与决策缓存装配（B3 抽取第三块）。

从 `scripts/ai_brain_trader.py` 原 L915-L1062（148 行）搬出：

| 函数 | 作用 |
|---|---|
| `validate_and_filter_decision` | 单条决策的置信度/RR 校验，返回 (action, reason, rr) |
| `assemble_decision_cache` | 把 LLM 原始决策装配成落盘缓存（含杠杆夹取、策略快照绑定） |

## 为什么这两块一起搬

`assemble_decision_cache` 内部会调用 `validate_and_filter_decision`（同一份语义域），
一起搬可以避免"跨文件互调"这种最脆的耦合；两者搬走后门面只留薄壳。

## 注入面（都是**既有测试缝**，不是设计洁癖）

| 依赖 | 缝在哪 |
|---|---|
| `data_dir`（门面 `DATA_DIR`） | `tests/ops/test_ai_health_sidecar.py:20` `patch.object(abt, "DATA_DIR", …)`；本函数要读 `asset_multipliers.json` |
| `max_leverage` / `min_leverage` | `tests/llm/test_leverage_range_and_council.py:212` 同时 patch 两个门面名，并断言"模型给 3 被下限抬到 5"—— 夹取必须读到补丁后的值 |
| `safe_float` | 定义在门面自身（非共享叶子函数），且门面会被 `pin_baseline_risk_env()` 原地重载 |
| `get_system_version_tag` | 门面私有函数，保持单一实现 |
| `validate` | 把 `validate_and_filter_decision` 作为参数传入，使两块可独立测试。**契约：4 个位置参数** `(p, d_item, active_inst_ids, active_position_sides)`；门面负责把 `safe_float` curry 进去（保持该函数对外的 4 参签名不变） |

标准库（`json` / `os` / `time`）与 typing 名直接 import —— 它们是稳定叶子，
不在这批门面 patch 名单里。
"""
import json
import os
import time
from typing import Any, Dict, List, Optional


def validate_and_filter_decision(p: Dict[str, Any], d_item: Dict[str, Any], active_inst_ids: set,
                                 active_position_sides: Dict[str, str], *,
                                 safe_float) -> tuple[str, str, float]:
    """
    Fail-closed execution layer gatekeeper powered by pluggable interceptors.
    1. Base pre-checks: data completeness & opposing position collision
    2. Dynamic interceptor pipeline: runs all enabled Python interceptor plugins
    """
    context = {
        "active_inst_ids": active_inst_ids,
        "active_position_sides": active_position_sides,
    }
    try:
        from astra_backend.interceptor_manager import run_interceptor_pipeline
        return run_interceptor_pipeline(p, d_item, context)
    except Exception as exc:
        # Fail-closed fallback in case interceptor manager cannot be reached
        raw_action = str((d_item or {}).get("action", "WAIT")).upper()
        if raw_action not in {"BUY_LONG", "SELL_SHORT", "WAIT"}:
            raw_action = "WAIT"
        entry = safe_float((d_item or {}).get("entry_price"))
        take_profit = safe_float((d_item or {}).get("take_profit_price"))
        stop_loss = safe_float((d_item or {}).get("stop_loss_price"))
        rr = 0.0
        if raw_action == "BUY_LONG" and entry > stop_loss > 0 and take_profit > entry:
            rr = (take_profit - entry) / (entry - stop_loss)
        elif raw_action == "SELL_SHORT" and stop_loss > entry > take_profit > 0:
            rr = (entry - take_profit) / (stop_loss - entry)
        return "WAIT", f"拦截插件管线调用异常: {exc}，安全降级为 WAIT", rr


def assemble_decision_cache(
    packages: List[Dict[str, Any]],
    decisions_dict: Dict[str, Any],
    active_inst_ids: set,
    active_position_sides: Dict[str, str],
    time_str: str,
    macro_summary: str,
    policy_snapshot: Optional[Dict[str, Any]] = None,
    council_status: Optional[Dict[str, Any]] = None,
    *,
    data_dir,
    max_leverage,
    min_leverage,
    safe_float,
    get_system_version_tag,
    validate,
) -> Dict[str, Any]:
    """Pure assembly of validated decisions into the standard cache contract, bound to policy snapshot."""
    policy_snapshot = policy_snapshot or {}
    p_ver = policy_snapshot.get("policy_version", f"{get_system_version_tag()}@unknown")
    p_hash = policy_snapshot.get("policy_hash", "unknown")
    p_summary = policy_snapshot.get("summary", "")

    standard_cache = {}
    # Load dynamic asset multipliers from self-improvement review if present
    asset_multipliers = {}
    try:
        mult_file = os.path.join(data_dir, "asset_multipliers.json")
        if os.path.isfile(mult_file):
            with open(mult_file, "r", encoding="utf-8") as f:
                mult_data = json.load(f)
            asset_multipliers = mult_data.get("multipliers") or {}
    except Exception:
        pass

    for p in packages:
        inst_id = p["instId"]
        d_item = decisions_dict.get(inst_id, {})
        if not isinstance(d_item, dict):
            d_item = {}
        # Smooth field alias normalization (support both standard contract and council desk outputs)
        entry = safe_float(d_item.get("entry_price") or d_item.get("limit_price"))
        take_profit = safe_float(d_item.get("take_profit_price") or d_item.get("take_profit"))
        stop_loss = safe_float(d_item.get("stop_loss_price") or d_item.get("stop_loss"))
        confidence = max(0.0, min(100.0, safe_float(d_item.get("confidence"))))
        # 杠杆钳制与后台风控页杠杆区间 [MIN, MAX] 联动（2026-09-10：
        # 旧版下限钉死 2 且提示词示例 min(3,MAX) 锚定，导致上限配 7 仍单单一律 3x）
        lev_hi = max(1, int(round(max_leverage)))
        lev_lo = max(1, min(int(round(min_leverage)), lev_hi))
        ai_leverage = int(max(lev_lo, min(lev_hi, round(safe_float(d_item.get("leverage", lev_lo))))))
        raw_margin = safe_float(d_item.get("margin_usdt") or d_item.get("margin_usd", 0.0))

        # Dynamically apply self-improvement asset multiplier (e.g. BTC 1.2x, DOGE 0.8x)
        sym_key = inst_id.split("-")[0] if "-" in inst_id else inst_id
        mult = float(asset_multipliers.get(sym_key, asset_multipliers.get(inst_id, 1.0)))
        mult = max(0.5, min(1.5, mult))
        ai_margin = round(raw_margin * mult, 2) if raw_margin > 0 else 0.0

        # Ensure normalized keys exist for downstream interceptors
        normalized_d_item = dict(d_item)
        normalized_d_item["entry_price"] = entry
        normalized_d_item["take_profit_price"] = take_profit
        normalized_d_item["stop_loss_price"] = stop_loss
        normalized_d_item["margin_usdt"] = ai_margin
        normalized_d_item["leverage"] = ai_leverage

        # `validate` 的契约固定为 4 个位置参数（与本模块的同名函数一致）——
        # 调用方（门面）负责把 `safe_float` curry 进去。这样既保持了
        # `validate_and_filter_decision` 的公开签名不变，也让本函数无需知道
        # 校验内部怎么取数。
        final_action, rejection_reason, rr = validate(
            p, normalized_d_item, active_inst_ids, active_position_sides,
        )

        standard_cache[inst_id] = {
            "instId": inst_id,
            "name": p["name"],
            "timestamp": int(time.time()),
            "time_str": time_str,
            "policy_version": p_ver,
            "policy_hash": p_hash,
            "policy_snapshot": {
                "policy_version": p_ver,
                "policy_hash": p_hash,
                "summary": p_summary,
            },
            "macro_assessment": macro_summary,
            # 投委会溯源（2026-09-10 前台适配数据契约）：ran/reason + CIO 采纳席位
            "council": {
                **(council_status or {"ran": False}),
                "adopted_role": (d_item or {}).get("adopted_role"),
            },
            "thought_process": {
                "market_structure": d_item.get("market_structure", "多周期结构中性"),
                "calculus_dynamics": d_item.get("calculus_dynamics", "模型未提供具体微积分证据"),
                "math_prob_rationale": d_item.get("math_prob_rationale", "模型未提供具体定积分与概率证据"),
                "volume_and_oi": d_item.get("volume_and_oi", f"OI: {p.get('oiUsd', '--')}, Taker: {p.get('takerNetUsd', '--')}"),
                "risk_reward_evaluation": "目标盈亏比与硬底线以【本周期风险预算】为准"
            },
            "smart_money": p.get("smart_money", {}),
            "adx_1h": p.get("adx_1h", "--"),
            "decision": {
                "action": final_action,
                "confidence": confidence,
                "leverage": ai_leverage,
                "margin_usdt": ai_margin,
                "entry_price": entry,
                "take_profit_price": take_profit,
                "stop_loss_price": stop_loss,
                "risk_reward_ratio": f"{rr:.2f} : 1" if rr > 0 else "--",
                "summary_reason": rejection_reason or str(d_item.get("summary_reason", "全市场矩阵综合评估中"))[:120]
            },
            "data_quality": p.get("data_quality", "invalid"),
            "raw_ticker": {
                "last": p.get("price"),
                "bidPx": p.get("bidPx"),
                "askPx": p.get("askPx"),
                "chg24h": p.get("chg24h"),
                "vol24h": p.get("vol24h", 0.0)
            },
            "raw_funding_rate": f"{p['fundingRate']}%" if p.get('fundingRate') else "--",
            "raw_oi": p.get('oiUsd') or "--",
            "raw_taker_vol": p.get('takerNetUsd') or "--",
            "raw_ls_ratio": str(p.get('lsRatio')) if p.get('lsRatio') is not None else "--",
            # US-007 数据通路：把跨所比对矩阵随决策缓存持久化，供 /api/all 透传前台；
            # 纯附加键，既有消费方忽略未知键，缺数据时为空 dict
            "xvenue": p.get("xvenue") or {}
        }

    return standard_cache
