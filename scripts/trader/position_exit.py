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

## 同名注入（本仓最宽之一）

⇒ 函数体 AST **零例外全等**。`time` 由本模块自 import。
`_close_fee` / `_close_trade_payload` / `notify_trade_close` /
`protection_signals` / `ratcheted_trailing_stop` 是门面从其它子包 import 进来的
名字，同样按门面全局**同名注入**（保持 patch 面与调用期解析语义不变）。
多所路径的原生云端棘轮注入已随场所下线移除。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

try:                                    # 与 scale_out.py 同源；独立运行时兜底
    from scripts.risk_constants import SCALE_OUT_RATIO
except Exception:                       # pragma: no cover
    SCALE_OUT_RATIO = 0.50


def _freeze_tp1_from_entry(entry_px: float, atr: float, is_long: bool, prec: int) -> Optional[float]:
    """建仓瞬间冻结首批止盈价（双腿挂单与软件判定共用同一价格）。"""
    try:
        from scripts.trader.tp1 import compute_tp1
        return compute_tp1(entry_px, atr, is_long, prec)
    except Exception:
        return None


def _is_simulated() -> bool:
    """OKX 是否模拟盘 —— 腿模式 `live_only` 需要它。

    fail-safe 方向：判不出来就当**模拟盘**（于是 live_only 下不挂腿）。
    宁可"本轮不新增挂腿"，也不在没确认环境时往实盘发新形态的委托。
    """
    try:
        import scripts.okx_rest as _okx_rest
        return bool(getattr(_okx_rest.current_environment(), "simulated", False))
    except Exception:
        return True


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
    ASSET_CLASS_PROFILES,
    TAKER_FEE_RATE,
    TIME_STOP_ATR_BAND,
    TIME_STOP_HOURS,
    _close_fee,
    _close_trade_payload,
    notify_trade_close,
    protection_signals,
    ratcheted_trailing_stop):
    # ⚠️ 2026-09-30（通知单一事实源）：本模块**不再发布**任何 `trade.closed`。
    #     此前硬止损/保护失效/时间止损/阶梯锁利四处各发一张卡片，而台账同步路径
    #     （`scripts/sync_full_ledger.py` → `scripts/ledger/notify.py`）会对同一笔再发
    #     一张 —— 实测同一天同一笔出现两条互相矛盾的金额（XRP −30.73 对 −32.63、
    #     DOGE −35.73 对 −37.71、SUI +28.32 对 +18.11），用户据此认定"数据不对"。
    #     金额类通知一律由台账路径发布（唯一握有交易所真实成交价/手续费/ROI/时长）；
    #     本路径的即时信息由 `executed_actions` 动作行与追踪器承载。
    #     参数保留以维持注入面（门面同名注入 + 既有 patch 面），故显式消费一次。
    _ = notify_trade_close
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
    # ⚠️ 只读守卫：已移除场所的历史持仓可能仍留在台账里。它的
    # instId 与 OKX 同名，**绝不能**把它交给任何 OKX 直签接口 ——
    # `close_position_confirmed` 不传 venue 就默认 okx，会把同名标的在 OKX 的仓
    # 平掉（平的是别人的仓，2026-09-28 实盘事故）。故非 OKX 一律留痕跳过，
    # 不撤台账行、不下发任何交易所指令、更不抛异常。
    if pos_venue != "okx":
        executed_actions.append(
            f"[{f['name']}] 非 OKX 场所({pos_venue})历史持仓，只读跳过机械退出（不下发任何交易所指令）")
        return False, f"非 OKX 场所({pos_venue})，只读跳过"

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
            # 分批止盈的双基准（2026-09-29）：
            #   entry_sz  —— 建仓张数**冻结**，用于识别"交易所侧 TP1 腿已成交"
            #                （旧实现只有会被每轮刷新的 currentSz，无法分辨腿成交）；
            #   scale_out_tp —— 首批止盈价**冻结**，挂腿与软件判定共用同一价格，
            #                不再每轮按当轮 ATR 重算（详见 scripts/trader/tp1.py）。
            "entry_sz": pos_sz,
            "scale_out_tp": _freeze_tp1_from_entry(entry_px, atr, is_long, prec),
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
    # 价格精度**每轮刷新**（来自合约规格，不是冻结决策）：持仓中调止盈要按它取整，
    # 2026-09-29 真机实测混用张数精度把 0.2236 下发成 0.22（差 1.6%）。
    t["px_prec"] = int(f.get("precision", 2) or 2)
    if not t.get("entry_sz"):
        # 旧 tracker 没有建仓张数：本轮只补记（不触发"腿已成交"判定）。
        t["entry_sz"] = pos_sz
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
        trackers.pop(pos_key, None)
        return True, "已硬止损"

    default_tp_dist = max(atr * profile["tp_atr_mult"], entry_px * profile["min_profit_ratio"])
    if not _float_or_zero(t.get("takeProfitPx")):
        t["takeProfitPx"] = round(entry_px + default_tp_dist if is_long else entry_px - default_tp_dist, prec)
    _pos_side = "long" if is_long else "short"
    # ⚠️ 云 OCO 核验（`okx_rest.pending_algo_orders` / `place_algo_oco`）是
    # **OKX 直签链专属**，本模块只对 OKX 持仓调用（非 OKX 持仓已在上方只读守卫处
    # 留痕返回，永不把外所 instId 交给 OKX 接口）。
    # 危险点：`close_position_confirmed` **不传 venue 就默认 okx**，
    # 若把外所持仓的 instId 交给它，"保护失效退出"会把同名标的在 OKX 的仓平掉
    # —— 平的是别人的仓（2026-09-28 实盘事故）。
    # 分批参数：只有**尚未分批**且 TP1 与 TP2 几何合法时才要求拆双腿
    # （腿挂在错误一侧会被 OKX 拒或立刻触发，见 scripts/trader/tp1.py 的守卫）。
    _tp2_px = float(t.get("takeProfitPx") or 0.0)
    _tp1_px = float(t.get("scale_out_tp") or 0.0)
    _split_enabled = False
    if _tp1_px > 0 and int(t.get("scale_out_phase", 0) or 0) < 1:
        try:
            from scripts.trader.tp1 import tp1_geometry_ok
            _split_enabled = tp1_geometry_ok(_tp1_px, _tp2_px, cur_px, is_long)
        except Exception:
            _split_enabled = False
    _pos_min = curr_pos.get("minSz")
    _leg_min_sz = float(_pos_min if _pos_min else (f.get("minSz", 0.01) or 0.01))
    protected, protection_detail = ensure_cloud_position_protection(
        inst_id, _pos_side, pos_sz, _tp2_px or float(t["takeProfitPx"]), hard_stop_px,
        tp1_px=_tp1_px if _split_enabled else None,
        scale_out_ratio=SCALE_OUT_RATIO,
        leg_min_sz=_leg_min_sz,
        prec=2,
        px_prec=int(f.get("precision", 2) or 2),
        legs_state=t,
        simulated=pos_venue == "okx" and _is_simulated(),
        split_enabled=_split_enabled,
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
        trackers.pop(pos_key, None)
        return True, "保护失效安全退出"
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
            sync_cloud_algo_stop(inst_id, "long", dynamic_floor_sl, reason=t["stage_desc"])
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
            sync_cloud_algo_stop(inst_id, "short", dynamic_floor_sl, reason=t["stage_desc"])
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
            if pos_key in trackers: del trackers[pos_key]
            return True, "已移动止盈"

    return False, "持仓监控中"

