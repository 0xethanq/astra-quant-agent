"""持仓退出管理：止盈 / 追踪止损棘轮 / 时间止损（B3 抽取·trader 瘦身第十刀，第八十九刀）。

从 `scripts/ai_factor_trader.py` **纯搬家** `manage_position_tp_and_trailing`（273 行）。

## 职责

持仓的生命周期退出判定（每个交易周期对每笔持仓调用一次）：
硬止盈/止损、三档追踪止损棘轮（保本/锁盈/加速）、时间止损（ATR 带 + 小时数）、
云端保护单同步（`ensure_cloud_position_protection` / `sync_cloud_algo_stop`）、
平仓确认（`close_position_confirmed`）与台账记录（`record_trade`）。

⚠️ 与 `scripts/trader/position_mgmt.py`（**主脑持仓指令执行器**，
`execute_ai_position_management`）是**两个不同关注点**：
- `position_mgmt.py`：消费 LLM 下发的持仓指令（收紧止损/主动平仓）；
- 本模块：**无 LLM 参与**的机械退出规则（TP/棘轮/时间止损）。
命名刻意避开 `position_*` 混淆：本模块叫 `position_exit`。

## 同名注入（18 项，本仓最宽之一）

⇒ 函数体 AST **零例外全等**。`time` 由本模块自 import。
`_close_fee` / `_close_trade_payload` / `notify_trade_close` /
`protection_signals` / `ratcheted_trailing_stop` 是门面从其它子包 import 进来的
名字，同样按门面全局**同名注入**（保持 patch 面与调用期解析语义不变）。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple


def manage_position_tp_and_trailing(f, curr_pos, trackers, timestamp_full, executed_actions,
    *,
    _float_or_zero,
    add_stop_cooldown,
    build_signal_snapshot,
    close_position_confirmed,
    ensure_cloud_position_protection,
    evaluate_asset_signal,
    record_signal_snapshot,
    record_trade,
    sync_cloud_algo_stop,
    venue_registry,
    amend_venue_stop_loss,
    ASSET_CLASS_PROFILES,
    TAKER_FEE_RATE,
    TIME_STOP_ATR_BAND,
    TIME_STOP_HOURS,
    _close_fee,
    _close_trade_payload,
    notify_trade_close,
    protection_signals,
    ratcheted_trailing_stop):
    if not f.get("market_data_valid"):
        executed_actions.append(f"[{f['name']}] 行情数据不完整，保留云端保护并跳过本地移动止盈")
        return False, "行情无效"
    inst_id = f["instId"]
    name = f["name"]
    cur_px = f["price"]
    asset_type = f.get("type", "crypto")
    profile = ASSET_CLASS_PROFILES.get(asset_type, ASSET_CLASS_PROFILES["crypto"])
    atr = max(f["atr"], cur_px * 0.005)
    prec = f["precision"]
    ct_val = float(curr_pos.get("ctVal") or f["ctVal"])
    
    pos_sz = float(curr_pos["pos"])
    is_long = "long" in curr_pos["side"].lower()
    entry_px = float(curr_pos["avgPx"])
    pos_key = f"{inst_id}_{curr_pos['side']}"
    pos_venue = str(curr_pos.get("venue") or curr_pos.get("exchange") or "okx").lower()

    now_ts = int(time.time())
    if pos_key not in trackers:
        score, action, reasons, strat_tag, strat_desc = evaluate_asset_signal(f)
        trackers[pos_key] = {
            "instId": inst_id,
            "name": name,
            "side": curr_pos["side"],
            "policy_version": f.get("policy_version", ""),
            "policy_hash": f.get("policy_hash", ""),
            "strategy_tag": strat_tag if strat_tag != "⚪ 观望" else ("🌊 顺势回踩" if is_long else "⚡ 阻力抛压"),
            "entryPx": entry_px,
            "entryTs": now_ts,
            "entryTime": timestamp_full,
            "initialSz": pos_sz,
            "currentSz": pos_sz,
            "highWaterMark": cur_px,
            "lowWaterMark": cur_px,
            "trailingStopPx": round((entry_px - atr * profile["sl_atr_mult"]) if is_long else (entry_px + atr * profile["sl_atr_mult"]), prec),
            "takeProfitPx": round((entry_px + max(atr * profile["tp_atr_mult"], entry_px * profile["min_profit_ratio"])) if is_long else (entry_px - max(atr * profile["tp_atr_mult"], entry_px * profile["min_profit_ratio"])), prec),
            "signal_snapshot": build_signal_snapshot(f),
            "stage_desc": "持有监控中"
        }
        record_signal_snapshot({
            "instId": inst_id,
            "name": name,
            "side": curr_pos["side"],
            "entryTs": now_ts,
            "entryTime": timestamp_full,
            "entryPx": entry_px,
            "sz": pos_sz,
            "policy_version": f.get("policy_version", ""),
            "snapshot": trackers[pos_key]["signal_snapshot"],
        })

    t = trackers[pos_key]
    if not t.get("policy_version") and f.get("policy_version"):
        t["policy_version"] = f.get("policy_version")
        t["policy_hash"] = f.get("policy_hash", "")
    t["currentSz"] = pos_sz
    if "entryTs" not in t:
        t["entryTs"] = now_ts

    # Peak Profit Tracking
    if is_long:
        t["highWaterMark"] = max(t.get("highWaterMark", cur_px), cur_px)
        cur_profit_px = cur_px - entry_px
        peak_profit_px = t["highWaterMark"] - entry_px
    else:
        t["lowWaterMark"] = min(t.get("lowWaterMark", cur_px), cur_px)
        cur_profit_px = entry_px - cur_px
        peak_profit_px = entry_px - t["lowWaterMark"]

    # 1. Hard Stop Loss (loss protection is independent of profit-lock activation).
    # The tracker stop is the exchange-protection source of truth; if a legacy or
    # partially migrated position has no live cloud OCO, the local 15-minute
    # fail-safe still closes it once the stop is breached.
    # 判定见 scripts/trader/protection.py（长空方向合一）。
    hard_stop_px = float(t.get("trailingStopPx", 0.0) or 0.0)
    hard_stop_hit = protection_signals(is_long=is_long, cur_px=cur_px, hard_stop_px=hard_stop_px)
    if hard_stop_hit:
        closed, close_detail = close_position_confirmed(inst_id, "long" if is_long else "short", pos_sz, venue=pos_venue)
        if not closed:
            executed_actions.append(f"[{name}] 硬止损平仓失败，仓位仍保留: {close_detail}")
            return False, "硬止损平仓失败"
        close_fee = _close_fee(pos_sz, ct_val, cur_px, TAKER_FEE_RATE)
        pnl_val = curr_pos["upl"]
        executed_actions.append(f"[{name}] 🛑 触发硬止损 {hard_stop_px} 并确认平仓 (净盈亏: {pnl_val:+.2f}U)")
        record_trade(_close_trade_payload(
            is_long=is_long, timestamp_full=timestamp_full, name=name,
            action_type="硬止损", side_suffix="硬止损",
            pos_sz=pos_sz, cur_px=cur_px, fee=close_fee, pnl=pnl_val,
            remark=f"价格 {cur_px} 触及保护止损 {hard_stop_px}，交易所确认平仓",
        ))
        add_stop_cooldown(inst_id, "long" if is_long else "short", "硬止损")
        if notify_trade_close:
            notify_trade_close(inst=name, pnl=pnl_val, stage="硬止损平仓", exit_px=cur_px, venue=pos_venue)
        trackers.pop(pos_key, None)
        return True, "已硬止损"

    default_tp_dist = max(atr * profile["tp_atr_mult"], entry_px * profile["min_profit_ratio"])
    if not _float_or_zero(t.get("takeProfitPx")):
        t["takeProfitPx"] = round(entry_px + default_tp_dist if is_long else entry_px - default_tp_dist, prec)
    _pos_side = "long" if is_long else "short"
    # ⚠️ 云 OCO 核验（`okx_rest.pending_algo_orders` / `place_algo_oco`）是
    # **OKX 直签链专属**。三所持仓接管（2026-09-28）后外所仓也会走到这里：
    # 对币安/Gate 调用它必然失败（实测日志 `OKX 51001: Instrument ID doesn't exist`
    # —— 它拿币安的标的去问 OKX），随后落进 fail-closed「安全退出」分支去平仓。
    # 而那一刀真正的危险在这里：`close_position_confirmed` **不传 venue 就默认 okx**，
    # 于是"保护失效退出"会把同名标的在 OKX 的仓平掉 —— 平的是别人的仓。
    # 外所的保护腿由 `venue_protection` 场所看门狗独立核验与补挂，这里不重复。
    if pos_venue == "okx":
        protected, protection_detail = ensure_cloud_position_protection(
            inst_id, _pos_side, pos_sz, float(t["takeProfitPx"]), hard_stop_px
        )
        if not protected:
            closed, close_detail = close_position_confirmed(
                inst_id, _pos_side, pos_sz, venue=pos_venue)
            if not closed:
                executed_actions.append(f"[{name}] 🚨 云端 OCO 缺失且安全退出失败: {protection_detail}; {close_detail}")
                return False, "保护与退出均失败"
            pnl_val = curr_pos["upl"]
            executed_actions.append(f"[{name}] 🧯 云端 OCO 无法确认，已安全平仓: {protection_detail}")
            record_trade(_close_trade_payload(
                is_long=is_long, timestamp_full=timestamp_full, name=name,
                action_type="保护失效退出", side_suffix="保护失效退出",
                pos_sz=pos_sz, cur_px=cur_px,
                fee=_close_fee(pos_sz, ct_val, cur_px, TAKER_FEE_RATE), pnl=pnl_val,
                remark=f"云端 OCO 无法达到全仓覆盖，交易所确认安全平仓：{protection_detail}",
            ))
            add_stop_cooldown(inst_id, _pos_side, "云端保护失效")
            if notify_trade_close:
                notify_trade_close(inst=name, pnl=pnl_val, stage="云端保护失效退出", exit_px=cur_px, venue=pos_venue)
            trackers.pop(pos_key, None)
            return True, "保护失效安全退出"
    else:
        protection_detail = f"{pos_venue.upper()} 保护腿由场所看门狗核验（云 OCO 核验为 OKX 直签链专属）"
    t["cloudProtection"] = {"verifiedAt": timestamp_full, "detail": protection_detail}

    # 2. Volatility Time-Stop Exit (持仓超最长持仓时间且缩量横盘 → 时间止损，参数见后台风控管理页)
    hold_duration_sec = now_ts - t["entryTs"]
    if hold_duration_sec > TIME_STOP_HOURS * 3600 and abs(cur_profit_px) < TIME_STOP_ATR_BAND * atr:
        closed, close_detail = close_position_confirmed(inst_id, "long" if is_long else "short", pos_sz, venue=pos_venue)
        if not closed:
            executed_actions.append(f"[{name}] 时间止损平仓失败，仓位仍保留: {close_detail}")
            return False, "平仓失败"
        close_fee = _close_fee(pos_sz, ct_val, cur_px, TAKER_FEE_RATE)
        executed_actions.append(f"[{name}] ⌛ 超过 {TIME_STOP_HOURS:g} 小时无波动横盘，时间止损平仓释放保证金")
        record_trade(_close_trade_payload(
            is_long=is_long, timestamp_full=timestamp_full, name=name,
            action_type="时间止损", side_suffix="无波动出场",
            pos_sz=pos_sz, cur_px=cur_px, fee=close_fee, pnl=curr_pos["upl"],
            remark=f"持仓超 {TIME_STOP_HOURS:g} 小时无突破，主动平仓释放配比",
        ))
        if notify_trade_close:
            notify_trade_close(inst=name, pnl=float(curr_pos.get("upl", 0.0) or 0.0), stage="时间止损平仓", exit_px=cur_px, venue=pos_venue)
        if pos_key in trackers: del trackers[pos_key]
        return True, "时间止损"

    # 3. Three-Tier Ratchet Profit-Locking & Momentum Take-Profit Engine
    # Tier 1: Breakeven Lock at +1.5x ATR (~1.0R profit, covers taker fee + 0.20% cushion)
    # Tier 2: Solid Wave Profit Lock at +2.2x ATR (~1.6R profit, lock in at least +1.0x ATR profit)
    # Tier 3: Kinetic Momentum Pullback Exit (Symmetric >= 2.0x ATR peak profit with 0.75x ATR pullback)
    
    tier1_breakeven_trigger = 1.5 * atr
    tier2_lock_trigger = 2.2 * atr
    momentum_tp_trigger = 2.0 * atr
    momentum_pullback_buffer = 0.75 * atr
    
    if is_long:
        # Dynamic Ratchet Stop Calculation for Long（数学见 scripts/trader/protection.py）
        old_sl = float(t.get("trailingStopPx", 0.0) or 0.0)
        dynamic_floor_sl, stage_desc = ratcheted_trailing_stop(
            is_long=True, entry_px=entry_px, atr=atr, prec=prec,
            peak_profit_px=peak_profit_px, old_sl=old_sl,
            tier1_breakeven_trigger=tier1_breakeven_trigger,
            tier2_lock_trigger=tier2_lock_trigger,
        )
        if stage_desc:
            t["stage_desc"] = stage_desc
        
        # If dynamic floor stop ratcheted up, commit and sync to cloud OCO
        if dynamic_floor_sl > old_sl and old_sl > 0:
            t["trailingStopPx"] = dynamic_floor_sl
            if pos_venue == "okx":
                sync_cloud_algo_stop(inst_id, "long", dynamic_floor_sl, reason=t["stage_desc"])
            else:
                # 外所：`sync_cloud_algo_stop` 走 OKX 直签链，对外所仓必然失败
                # ——而 tracker 的 `trailingStopPx` 已经改成"已上移"⇒ **账实不符**
                # （台账说止损抬了、交易所上其实没抬）。改用场所原生棘轮，与 AI
                # 移损路径共用同一条 `amend_venue_stop_loss`。
                try:
                    _oil_ad = venue_registry.get_adapter(pos_venue)
                    _oil_ok, _oil_note = amend_venue_stop_loss(
                        _oil_ad, name, "long", dynamic_floor_sl, pos_sz)
                    if not _oil_ok:
                        executed_actions.append(
                            f"[{name}] {pos_venue.upper()} 云端止损上移失败: {_oil_note}")
                except Exception as _oil_exc:
                    executed_actions.append(
                        f"[{name}] {pos_venue.upper()} 云端止损上移异常: {_oil_exc}")
        else:
            t["trailingStopPx"] = dynamic_floor_sl

        # A. Hit Ratchet Floor Stop (Locked Profit Trigger)
        if cur_px <= dynamic_floor_sl and peak_profit_px >= tier1_breakeven_trigger:
            closed, close_detail = close_position_confirmed(inst_id, "long", pos_sz, venue=pos_venue)
            if not closed:
                executed_actions.append(f"[{name}] 锁利平多失败，仓位仍保留: {close_detail}")
                return False, "平仓失败"
            close_fee = _close_fee(pos_sz, ct_val, cur_px, TAKER_FEE_RATE)
            pnl_val = curr_pos["upl"]
            executed_actions.append(f"[{name}] 🛡️ 触发阶梯动态锁利平仓 (净盈亏: {pnl_val:+.2f}U)")
            record_trade(_close_trade_payload(
                is_long=is_long, timestamp_full=timestamp_full, name=name,
                action_type="阶梯锁利", side_suffix="阶梯锁利平仓",
                pos_sz=pos_sz, cur_px=cur_px, fee=close_fee, pnl=pnl_val,
                remark=f"最高 {t['highWaterMark']} 触发阶梯利润锁定线 {dynamic_floor_sl}",
            ))
            if notify_trade_close:
                notify_trade_close(inst=name, pnl=pnl_val, stage="阶梯锁利平仓", exit_px=cur_px, venue=pos_venue)
            if pos_key in trackers: del trackers[pos_key]
            return True, "已阶梯锁利"

        # B. Kinetic Momentum Pullback Exit from Peak (Symmetric 2.0x ATR profit with 0.75x ATR pullback)
        if peak_profit_px >= momentum_tp_trigger and cur_px <= (t["highWaterMark"] - momentum_pullback_buffer):
            closed, close_detail = close_position_confirmed(inst_id, "long", pos_sz, venue=pos_venue)
            if not closed:
                executed_actions.append(f"[{name}] 动能见顶移动止盈失败，仓位仍保留: {close_detail}")
                return False, "平仓失败"
            close_fee = _close_fee(pos_sz, ct_val, cur_px, TAKER_FEE_RATE)
            pnl_val = curr_pos["upl"]
            executed_actions.append(f"[{name}] 🎯 触发高点回撤动能止盈 (净盈亏: {pnl_val:+.2f}U)")
            record_trade(_close_trade_payload(
                is_long=is_long, timestamp_full=timestamp_full, name=name,
                action_type="移动止盈", side_suffix="高点回撤止盈",
                pos_sz=pos_sz, cur_px=cur_px, fee=close_fee, pnl=pnl_val,
                remark=f"最高 {t['highWaterMark']} 动能回撤触及移动止盈线",
            ))
            if notify_trade_close:
                notify_trade_close(inst=name, pnl=pnl_val, stage="移动止盈", exit_px=cur_px, venue=pos_venue)
            if pos_key in trackers: del trackers[pos_key]
            return True, "已移动止盈"

    else:
        # Dynamic Ratchet Stop Calculation for Short（数学见 scripts/trader/protection.py）
        old_sl = float(t.get("trailingStopPx", 0.0) or 0.0)
        dynamic_floor_sl, stage_desc = ratcheted_trailing_stop(
            is_long=False, entry_px=entry_px, atr=atr, prec=prec,
            peak_profit_px=peak_profit_px, old_sl=old_sl,
            tier1_breakeven_trigger=tier1_breakeven_trigger,
            tier2_lock_trigger=tier2_lock_trigger,
        )
        if stage_desc:
            t["stage_desc"] = stage_desc
        
        # If dynamic floor stop ratcheted down (tightened for short), commit and sync to cloud OCO
        if dynamic_floor_sl < old_sl and old_sl > 0:
            t["trailingStopPx"] = dynamic_floor_sl
            if pos_venue == "okx":
                sync_cloud_algo_stop(inst_id, "short", dynamic_floor_sl, reason=t["stage_desc"])
            else:
                # 同多头分支：外所走场所原生棘轮，避免 tracker 谎报止损已上移。
                try:
                    _ois_ad = venue_registry.get_adapter(pos_venue)
                    _ois_ok, _ois_note = amend_venue_stop_loss(
                        _ois_ad, name, "short", dynamic_floor_sl, pos_sz)
                    if not _ois_ok:
                        executed_actions.append(
                            f"[{name}] {pos_venue.upper()} 云端止损上移失败: {_ois_note}")
                except Exception as _ois_exc:
                    executed_actions.append(
                        f"[{name}] {pos_venue.upper()} 云端止损上移异常: {_ois_exc}")
        else:
            t["trailingStopPx"] = dynamic_floor_sl

        # A. Hit Ratchet Floor Stop (Locked Profit Trigger)
        if cur_px >= dynamic_floor_sl and peak_profit_px >= tier1_breakeven_trigger:
            closed, close_detail = close_position_confirmed(inst_id, "short", pos_sz, venue=pos_venue)
            if not closed:
                executed_actions.append(f"[{name}] 锁利平空失败，仓位仍保留: {close_detail}")
                return False, "平仓失败"
            close_fee = _close_fee(pos_sz, ct_val, cur_px, TAKER_FEE_RATE)
            pnl_val = curr_pos["upl"]
            executed_actions.append(f"[{name}] 🛡️ 触发阶梯动态锁利平仓 (净盈亏: {pnl_val:+.2f}U)")
            record_trade(_close_trade_payload(
                is_long=is_long, timestamp_full=timestamp_full, name=name,
                action_type="阶梯锁利", side_suffix="阶梯锁利平仓",
                pos_sz=pos_sz, cur_px=cur_px, fee=close_fee, pnl=pnl_val,
                remark=f"最低 {t['lowWaterMark']} 触发阶梯利润锁定线 {dynamic_floor_sl}",
            ))
            if notify_trade_close:
                notify_trade_close(inst=name, pnl=pnl_val, stage="阶梯锁利平仓", exit_px=cur_px, venue=pos_venue)
            if pos_key in trackers: del trackers[pos_key]
            return True, "已阶梯锁利"

        # B. Kinetic Momentum Pullback Exit from Peak (Symmetric 2.0x ATR profit with 0.75x ATR pullback)
        if peak_profit_px >= momentum_tp_trigger and cur_px >= (t["lowWaterMark"] + momentum_pullback_buffer):
            closed, close_detail = close_position_confirmed(inst_id, "short", pos_sz, venue=pos_venue)
            if not closed:
                executed_actions.append(f"[{name}] 动能见底移动止盈失败，仓位仍保留: {close_detail}")
                return False, "平仓失败"
            close_fee = _close_fee(pos_sz, ct_val, cur_px, TAKER_FEE_RATE)
            pnl_val = curr_pos["upl"]
            executed_actions.append(f"[{name}] 🎯 触发低点反弹动能止盈 (净盈亏: {pnl_val:+.2f}U)")
            record_trade(_close_trade_payload(
                is_long=is_long, timestamp_full=timestamp_full, name=name,
                action_type="移动止盈", side_suffix="低点反弹止盈",
                pos_sz=pos_sz, cur_px=cur_px, fee=close_fee, pnl=pnl_val,
                remark=f"最低 {t['lowWaterMark']} 动能反弹触及移动止盈线",
            ))
            if notify_trade_close:
                notify_trade_close(inst=name, pnl=pnl_val, stage="移动止盈", exit_px=cur_px, venue=pos_venue)
            if pos_key in trackers: del trackers[pos_key]
            return True, "已移动止盈"

    return False, "持仓监控中"

