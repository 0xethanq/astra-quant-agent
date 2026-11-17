"""因子雷达装配（结构优化阶段 2·B2 第八刀）。

从 update_cache_cycle 第 6 段迁出；三个输入路径均由门面在调用时注入。
"""
from __future__ import annotations

import json
import os

from astra_backend.dashboard_payload.readers import read_json
from astra_backend.time_utils import beijing_text
from scripts.instrument_pool import load_instruments

__all__ = ["build_factors_list"]


def build_factors_list(decisions_file, state_file, factor_file, positions, timestamp_full):
    """由 ai_brain_decisions / trading_state / factor_library 三个本地文件装配因子雷达。

    原样搬自 update_cache_cycle 第 6 段（118 行）。三个路径由门面注入 —— 它们都会被
    测试 patch / 沙箱重定向。`load_instruments` 走纯导入，无需注入。
    """
    state_data = {}
    ai_decisions = read_json(decisions_file, {})

    factors_list = []
    pos_map = {p.get("instId"): p for p in positions} if isinstance(positions, list) else {}
    active_pool = load_instruments()
    inst_state_map = {}
    state_data = read_json(state_file, {})
    try:
        for ins in state_data.get("instruments", []):
            if isinstance(ins, dict) and ins.get("instId"):
                inst_state_map[ins["instId"]] = ins
    except Exception:
        pass

    factor_lib_map = {}
    lib_data = read_json(factor_file, {})
    try:
        for item in lib_data.get("instruments", []):
            if isinstance(item, dict) and item.get("instId"):
                factor_lib_map[item["instId"]] = item
    except Exception:
        pass

    for target in active_pool:
        inst_id = target.get("instId")
        ins = inst_state_map.get(inst_id) or {}
        lib_item = factor_lib_map.get(inst_id) or {}
        # 7 梯队因子块（2026-10 起替代原 calculus 块）：逐块取，缺失即空 dict，
        # 下游一律用 `.get(k)` 读 —— **不给中性默认值冒充真因子**。
        _tm = lib_item.get("trend_momentum") or {}
        _flow = lib_item.get("volume_money_flow") or {}
        _micro = lib_item.get("microstructure") or {}
        _vp = lib_item.get("volume_profile") or {}
        _smd = lib_item.get("smart_money_derivatives") or {}
        ai_info = ai_decisions.get(inst_id, {})
        ai_dec = ai_info.get("decision", {})
        ai_thought = ai_info.get("thought_process", {})

        action_val = ai_dec.get("action", ins.get("action", "WAIT"))
        confidence = ai_dec.get("confidence")
        reason = ai_dec.get("summary_reason", ins.get("desc", "新组合标的，雷达与量化特征已接入"))

        strategy_val = "🟢 建议做多" if action_val == "BUY_LONG" else ("🔴 建议做空" if action_val == "SELL_SHORT" else "⚪ AI观望")
        score_val = 2.5 if action_val == "BUY_LONG" else (-2.5 if action_val == "SELL_SHORT" else 0.0)
        vwap_b = float(ins.get("vwap_bias", 0.0) or 0.0)

        # ★「不许假数据」：没有 AI 论述时**不再编**"CHOP (震荡)"这种结构结论
        _mr, _t1 = ins.get("market_regime"), ins.get("trend_1h")
        m_struct = ai_thought.get("market_structure") or (
            f"{_mr} ({_t1})" if (_mr or _t1) else "--")
        v_oi = ai_thought.get("volume_and_oi") or "--"
        rr_ratio = ai_thought.get("risk_reward_evaluation", "盈亏比评估中")

        raw_t = ai_info.get("raw_ticker", {})
        funding_r = ai_info.get("raw_funding_rate") or (f"{lib_item.get('smart_money_derivatives', {}).get('funding_rate_pct', 0.0):.4f}%" if "funding_rate_pct" in lib_item.get("smart_money_derivatives", {}) else "--")
        oi_str = ai_info.get("raw_oi") or lib_item.get("smart_money_derivatives", {}).get("oi_usd", "--")
        taker_str = ai_info.get("raw_taker_vol") or lib_item.get("volume_money_flow", {}).get("taker_net_usd", "--")
        ls_str = ai_info.get("raw_ls_ratio") or lib_item.get("smart_money_derivatives", {}).get("long_short_ratio", "--")

        chg_val = raw_t.get("chg24h") if raw_t.get("chg24h") is not None else lib_item.get("chg24h")
        raw_ticker_vol = raw_t.get("vol24h")
        price_val = ins.get("price") if ins.get("price") not in (None, "--") else lib_item.get("price", "--")
        # ★「不许假数据」：缺 `rsi_14` 不给 50.0 兜底（那是"中性"这个结论），前端渲染 `--`
        rsi_val = ins.get("rsi") if ins.get("rsi") is not None else lib_item.get("trend_momentum", {}).get("rsi_14")
        adx_val = ai_info.get("adx_1h") if ai_info.get("adx_1h") not in (None, "--") else lib_item.get("trend_momentum", {}).get("adx_1h", "--")
        sm_val = ai_info.get("smart_money") or lib_item.get("smart_money_derivatives", {})

        factors_list.append({
            "name": target.get("name") or ins.get("name"),
            "instId": inst_id,
            "position": pos_map.get(inst_id),
            "type": target.get("type", "crypto"),
            "price": price_val,
            "score": score_val,
            "change24h": chg_val,
            "chg24h": chg_val,
            "vol24h": raw_ticker_vol,
            "bidPx": raw_t.get("bidPx", ins.get("price", lib_item.get("microstructure", {}).get("bid_px", "--"))),
            "askPx": raw_t.get("askPx", ins.get("price", lib_item.get("microstructure", {}).get("ask_px", "--"))),
            "fundingRate": funding_r,
            "oiUsd": oi_str,
            "takerNetUsd": taker_str,
            "lsRatio": ls_str,
            "rsi": rsi_val,
            "rsi_7": ins.get("rsi_7"),
            "vwap_bias": vwap_b,
            "macd_hist": ins.get("macd_hist", 0.0),
            "macd_accel": ins.get("macd_accel", 0.0),
            "obv_flow": ins.get("obv_flow", lib_item.get("volume_money_flow", {}).get("obv_flow")),
            "bb_bandwidth": ins.get("bb_bandwidth", lib_item.get("volatility_channel", {}).get("bb_width_1h", 0.0)),
            "vol_ratio": ins.get("vol_ratio", lib_item.get("volume_money_flow", {}).get("vol_ratio_15m")),
            "trend_1h": ins.get("trend_1h"),
            "trend_4h": ins.get("trend_4h"),
            "market_regime": ins.get("market_regime"),
            "strategy_tag": strategy_val,
            "action": action_val,
            "confidence": confidence,
            "smart_money": sm_val,
            "adx_1h": adx_val,
            "atr_1h": lib_item.get("volatility_channel", {}).get("atr_1h", 0.0),
            "atr_pct": lib_item.get("volatility_channel", {}).get("atr_1h_pct", lib_item.get("volatility_channel", {}).get("atr_pct", 0.0)),
            # ★ 2026-10：原 `calculus` 块（velocity/accel/jerk/impulse）随数理系统退场，
            # 换成 7 梯队里**前端真正会看**的那几个因子（列在 FactorMatrix/FactorDrawer）。
            "momentum": {
                "macd_hist_1h": _tm.get("macd_hist"),
                "macd_accel_1h": _tm.get("macd_accel"),
                # 归一化口径（占现价 %）：跨标可比、且低价币不会被两位小数抹成 0.00
                "macd_hist_pct_1h": _tm.get("macd_hist_pct"),
                "macd_accel_pct_1h": _tm.get("macd_accel_pct"),
                "macd_momentum_state": _tm.get("macd_momentum_state", "--"),
                "macd_divergence": _tm.get("macd_divergence", "--"),
                "rsi_1h": _tm.get("rsi_1h"),
                "rsi_15m": _tm.get("rsi_15m"),
                "rsi_zone": _tm.get("rsi_zone", "NEUTRAL"),
            },
            "orderflow": {
                "cvd_5m_usd": _flow.get("cvd_5m_usd"),
                "cvd_1h_usd": _flow.get("cvd_1h_usd"),
                "taker_buy_sell_ratio": _flow.get("taker_buy_sell_ratio"),
                "cvd_divergence": _flow.get("cvd_divergence", "--"),
            },
            "microstructure": {
                "obi_pct": _micro.get("obi_pct"),
                # ★ 2026-10：多笔档口径 + 可信度标记。前端据此提示"盘口不可信"，
                #   避免把被单笔可撤挂单支配的 OBI 当成方向证据（见因子引擎文档）。
                "obi_robust_pct": _micro.get("obi_robust_pct"),
                "depth_reliable": _micro.get("depth_reliable"),
                "depth_bias": _micro.get("depth_bias", "NEUTRAL"),
                "bid_ask_depth_ratio": _micro.get("bid_ask_depth_ratio"),
                "spread_bps": _micro.get("spread_bps"),
            },
            "value_area": {
                "vwap_24h": _vp.get("vwap_24h"),
                "vwap_bias_pct": _tm.get("vwap_bias_pct"),
                "vah": _vp.get("vah"),
                "val": _vp.get("val"),
                "vpvr_poc": _vp.get("vpvr_poc"),
                "value_area_position": _vp.get("value_area_position", "--"),
                "vwap_extreme_band": _vp.get("vwap_extreme_band", "--"),
            },
                        "derivatives": {
                "funding_rate_pct": _smd.get("funding_rate_pct"),
                "next_funding_rate_pct": _smd.get("next_funding_rate_pct"),
                "funding_crowding": _smd.get("funding_crowding", "--"),
                "oi_chg_1h_pct": _smd.get("oi_chg_1h_pct"),
                "oi_price_quadrant": _smd.get("oi_price_quadrant", "--"),
                "elite_divergence": _smd.get("elite_divergence", "--"),
                "liquidation_bias": _smd.get("liquidation_bias", "--"),
                "basis_annualized_pct": _smd.get("basis_annualized_pct"),
            },
            "leverage": ai_dec.get("leverage"),
            "margin_usdt": ai_dec.get("margin_usdt", 0.0),
            "entry_price": ai_dec.get("entry_price", 0.0),
            "take_profit_price": ai_dec.get("take_profit_price", 0.0),
            "stop_loss_price": ai_dec.get("stop_loss_price", 0.0),
            "risk_reward_ratio": ai_dec.get("risk_reward_ratio", "--"),
            "reason": reason,
            # 三态可观测性（2026-10）：与 `scripts/brain/decisions.py` 同源，
            # 前端据此把「模型主动观望 / 物理层拦单 / 模型漏答」分开显示。
            "decision_source": ai_dec.get("decision_source", "model"),
            "gate_blocked": bool(ai_dec.get("gate_blocked", False)),
            "gate_reason": ai_dec.get("gate_reason", ""),
            "model_reason": ai_dec.get("model_reason", reason),
            "market_structure": m_struct,
            "volume_and_oi": v_oi,
            "rr_ratio": rr_ratio,
            "thought_process": ai_thought,
            "venue_decision": ai_info.get("venue_decision") or ai_dec.get("venue_decision"),
            "confluence_15m": m_struct,
            "confluence_1h": v_oi,
            "desc": reason,
            "ai_last_prompt": ai_info.get("ai_last_prompt", ""),
            "time_str": ai_info.get("time_str") or state_data.get("timestamp") or timestamp_full,
            "timestamp": ai_info.get("timestamp"),
        })

    # 7. Read Ledger Lifecycle Trades for Table (Directly sync fresh ledger if stale > 60s)
    return factors_list, state_data
