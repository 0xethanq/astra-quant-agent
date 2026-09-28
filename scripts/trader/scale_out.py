"""持仓分批平仓止盈执行引擎（Scale-Out Engine）。

职责：
当持仓浮盈达到设定的门槛（如 1.2x ATR）时，自动市价平仓指定比例（如 50%）锁定现金利润，
同时原子级撤销旧的全量云端 OCO 保护单，换挂剩余仓位的新 OCO 保护单，并将止损价推进至
开仓成本保本位（entry_px + 0.25%），且对当前持仓生命周期加锁互斥金字塔加仓。

防御机制：
1. 最小合约张数与精度防御（pos_sz < 2*minSz 时优雅降级为整仓追踪止盈）；
2. 原生 reduceOnly 市价平仓委托（交易所底层物理杜绝反向开仓）；
3. 云端 OCO 覆盖单超额撤销重置（彻底消除原 100% 止损单残留导致的反向开仓）；
4. 金字塔顺势加仓单向锁（scale_count = 999，互斥锁定，防止边平边加）；
5. 幂等性守卫（scale_out_phase = 1，单次持仓生命周期内仅执行一次）。
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from scripts.risk_constants import (
        SCALE_OUT_ENABLED,
        SCALE_OUT_RATIO,
        SCALE_OUT_TRIGGER_ATR,
    )
except Exception:
    SCALE_OUT_ENABLED = True
    SCALE_OUT_RATIO = 0.50
    SCALE_OUT_TRIGGER_ATR = 1.20


def execute_scale_out_if_eligible(
    f: Dict[str, Any],
    curr_pos: Dict[str, Any],
    trackers: Dict[str, Any],
    timestamp_full: str,
    executed_actions: List[str],
    *,
    okx_rest=None,
    venue_registry=None,
    record_trade=None,
    notify_trade_close=None,
    close_fee=None,
    close_trade_payload=None,
    TAKER_FEE_RATE: float = 0.0005,
    ensure_cloud_position_protection=None,
) -> Tuple[bool, str]:
    """若当前持仓达到分批止盈条件，执行半仓市价平仓、保本移损与云端 OCO 重置。"""
    if not SCALE_OUT_ENABLED:
        return False, "分批止盈未启用"

    if not f or not curr_pos or not f.get("market_data_valid"):
        return False, "行情数据不完整"

    inst_id = str(f.get("instId", ""))
    name = str(f.get("name", inst_id.split("-")[0]))
    cur_px = float(f.get("price", 0.0) or 0.0)
    atr = max(float(f.get("atr", 0.0) or 0.0), cur_px * 0.005)
    # ⚠️ 单位纪律（三所持仓接管）：`ctVal`/`minSz`/尺寸精度对**外所在仓**必须取
    # 该所自己的值 —— `f[...]` 一律来自 OKX 合约池，而币安的 `pos` 是币数
    # （OKX 面值 100 会算错 100 倍）、Gate 是自家张数（面值 10，错 10 倍）。
    # 持仓记录上挂的值优先；缺失时回落 OKX 口径 ⇒ OKX 路径逐位不变。
    # 注意 `prec` 只用于**尺寸**取整（价格精度见下方 `px_prec`，仍取 `f`）。
    _pos_ct = curr_pos.get("ctVal")
    _pos_min = curr_pos.get("minSz")
    _pos_prec = curr_pos.get("precision")
    ct_val = float(_pos_ct if _pos_ct else (f.get("ctVal", 1.0) or 1.0))
    min_sz = float(_pos_min if _pos_min else (f.get("minSz", 0.01) or 0.01))
    prec = int(_pos_prec if _pos_prec is not None else (f.get("precision", 2) or 2))

    pos_sz = abs(float(curr_pos.get("pos", 0.0) or 0.0))
    if pos_sz <= 0:
        return False, "无持仓"

    # ── 展示口径：一切对外文案只说**钱**（保证金 / 名义额），不说张 ──────────
    # 用户 2026-09-28 拍板：三所的"张"单位不同（OKX 张 / 币安币数 / Gate 张），
    # 且**各币种的合约面值算法都不一样** ⇒ 张数既不能跨场所比也不能跨币种比，
    # 交易员无法从它判断"这笔占了我多少钱"。张数仍用于**切分计算**本身（必须），
    # 但绝不进入文案。
    _lever = float(curr_pos.get("lever", curr_pos.get("leverage", 0.0)) or 0.0) or 1.0

    def _margin_of(_sz):
        """把原生张数换成该仓的**保证金**（U）。"""
        return round(_sz * ct_val * cur_px / _lever, 2)

    def _notional_of(_sz):
        """把原生张数换成**名义额**（U）——各币种面值不同，这里才是可比的量。"""
        return round(_sz * ct_val * cur_px, 2)

    is_long = "long" in str(curr_pos.get("side", "")).lower()
    pos_side = "long" if is_long else "short"
    entry_px = float(curr_pos.get("avgPx", 0.0) or 0.0)
    if entry_px <= 0:
        return False, "持仓均价无效"

    pos_key = f"{inst_id}_{curr_pos.get('side', pos_side)}"
    if pos_key not in trackers:
        return False, "未找到持仓跟踪器"

    t = trackers[pos_key]

    # 1. 幂等性守卫：若已执行过分批止盈，跳过
    if int(t.get("scale_out_phase", 0) or 0) >= 1:
        return False, "已执行过分批平仓"

    # 2. 计算首批止盈目标价位（TP1）并持久化到跟踪器
    trigger_threshold = float(SCALE_OUT_TRIGGER_ATR or 1.20) * atr
    tp1_px = (entry_px + trigger_threshold) if is_long else (entry_px - trigger_threshold)
    px_prec = int(f.get("precision", 2) or 2)
    tp1_px = round(tp1_px, px_prec)
    t["scale_out_tp"] = tp1_px

    # 3. 浮盈判定
    cur_profit_px = (cur_px - entry_px) if is_long else (entry_px - cur_px)
    if cur_profit_px < trigger_threshold:
        current_desc = str(t.get("stage_desc") or "")
        if not current_desc or "监控中" in current_desc or "TP1" in current_desc:
            gain_pct = abs(tp1_px - entry_px) / entry_px * 100 if entry_px > 0 else 0.0
            t["stage_desc"] = f"持有中 (首批止盈目标 TP1: {tp1_px:g} · +{gain_pct:.1f}% · 达标平50%保本)"
        return False, "浮盈未达分批止盈门槛"

    # 4. 精度与最小下单量防御
    # 若总持仓不足 2 倍 minSz，无法安全切分为两半，优雅降级。
    # 文案用**最小下单名义**表述（`minSz × 面值 × 现价`）—— 那是跨币种可比的额。
    if pos_sz < (2.0 * min_sz - 1e-12):
        msg = (f"[{name}] 持仓名义 {_notional_of(pos_sz):.2f}U 低于分批下限"
               f"（最小下单名义 {_notional_of(min_sz):.2f}U 的 2 倍），自动降级为全仓追踪")
        executed_actions.append(msg)
        t["scale_out_phase"] = -1  # 标记为已评估但不可切分，防止每轮重复提示
        return False, "保证金不足以切分"

    ratio = max(0.1, min(0.9, float(SCALE_OUT_RATIO or 0.50)))
    raw_close_sz = pos_sz * ratio
    close_sz = round(raw_close_sz, prec)
    # 按 minSz 步长向下夹取对齐
    if min_sz > 0:
        close_sz = math.floor(close_sz / min_sz + 1e-9) * min_sz
        close_sz = round(close_sz, prec)

    remaining_sz = round(pos_sz - close_sz, prec)
    if close_sz < min_sz or remaining_sz < min_sz:
        msg = (f"[{name}] 计算平仓名义 {_notional_of(close_sz):.2f}U 或剩余名义 "
               f"{_notional_of(remaining_sz):.2f}U 低于最小下单名义 "
               f"{_notional_of(min_sz):.2f}U，降级全仓追踪")
        executed_actions.append(msg)
        t["scale_out_phase"] = -1
        return False, "切片名义不满足最小精度"

    # 4. 执行定向市价平仓（带有 reduceOnly=True）
    close_side = "sell" if is_long else "buy"
    pos_venue = str(curr_pos.get("venue") or curr_pos.get("exchange") or "okx").lower()
    
    order_success = False
    order_detail = ""

    if pos_venue == "okx":
        try:
            res = okx_rest.place_order(
                inst_id,
                close_side,
                f"{close_sz:g}",
                pos_side=pos_side,
                td_mode="cross",
                ord_type="market",
                reduce_only=True,
            )
            order_success = True
            order_detail = str(res)
        except Exception as exc:
            order_success = False
            order_detail = f"OKX分批平仓异常: {exc}"
    elif pos_venue == "binance":
        if venue_registry:
            try:
                ad = venue_registry.get_adapter(pos_venue)
                symbol_native = inst_id.split("-")[0]
                raw_pos = curr_pos.get("raw") if isinstance(curr_pos.get("raw"), dict) else {}
                ps = str(curr_pos.get("positionSide") or raw_pos.get("positionSide") or "").upper()
                if ps in ("LONG", "SHORT"):
                    res = ad.place_order(symbol_native, close_side, close_sz, position_side=ps)
                else:
                    res = ad.place_order(symbol_native, close_side, close_sz, reduce_only=True)
                order_success = True
                order_detail = str(res)
            except Exception as exc:
                order_success = False
                order_detail = f"BINANCE分批平仓异常: {exc}"
        else:
            order_success = False
            order_detail = "未提供 BINANCE 适配器注册表"
    elif pos_venue == "gate":
        if venue_registry:
            try:
                ad = venue_registry.get_adapter(pos_venue)
                symbol_native = inst_id.split("-")[0]
                res = ad.place_order(symbol_native, close_side, close_sz, reduce_only=True)
                order_success = True
                order_detail = str(res)
            except Exception as exc:
                order_success = False
                order_detail = f"GATE分批平仓异常: {exc}"
        else:
            order_success = False
            order_detail = "未提供 GATE 适配器注册表"
    else:
        # 多所适配器路径兜底
        if venue_registry:
            try:
                ad = venue_registry.get_adapter(pos_venue)
                symbol_native = inst_id.split("-")[0]
                res = ad.place_order(symbol_native, close_side, close_sz, reduce_only=True)
                order_success = True
                order_detail = str(res)
            except Exception as exc:
                order_success = False
                order_detail = f"{pos_venue.upper()}分批平仓异常: {exc}"
        else:
            order_success = False
            order_detail = f"未提供 {pos_venue.upper()} 适配器注册表"

    if not order_success:
        executed_actions.append(f"[{name}] ⚠️ 分批止盈市价平仓提交失败: {order_detail}")
        return False, "平仓提交失败"

    # 5. 原子级撤销旧 OCO / 保护单，避免超额单量穿仓反向开单与旧止损残留
    if pos_venue == "okx":
        try:
            pending_algos = okx_rest.pending_algo_orders(inst_id)
            old_algo_ids = [
                str(o.get("algoId") or "")
                for o in pending_algos
                if str(o.get("posSide", "net")).lower() in (pos_side, "net")
                and (o.get("algoId") or "")
            ]
            if old_algo_ids:
                okx_rest.cancel_algo_orders(old_algo_ids[:10], inst_id=inst_id)
        except Exception as cxl_exc:
            print(f"[Scale-Out] 清理 {inst_id} 旧OCO异常（由新保护单覆盖）: {cxl_exc}")
    elif pos_venue in ("binance", "gate") and venue_registry:
        try:
            adapter = venue_registry.get_adapter(pos_venue)
            if adapter and hasattr(adapter, "cancel_protective_orders"):
                adapter.cancel_protective_orders(name)
            elif adapter and hasattr(adapter, "cancel_all_algo_open_orders"):
                adapter.cancel_all_algo_open_orders(symbol=adapter.native_symbol(name))
        except Exception as cxl_exc:
            print(f"[Scale-Out] 清理 {pos_venue.upper()} {name} 旧保护单异常: {cxl_exc}")

    # 6. 计算保本止损线并为剩余仓位重建云端 OCO
    breakeven_cushion = 0.0025 * entry_px
    breakeven_sl = round((entry_px + breakeven_cushion) if is_long else (entry_px - breakeven_cushion), prec)
    take_profit_px = float(t.get("takeProfitPx", 0.0) or 0.0)

    if pos_venue == "okx" and ensure_cloud_position_protection and take_profit_px > 0:
        try:
            ensure_cloud_position_protection(
                inst_id, pos_side, remaining_sz, take_profit_px, breakeven_sl
            )
        except Exception as oco_exc:
            print(f"[Scale-Out] 剩余仓位云端保护更新异常: {oco_exc}")
    elif pos_venue in ("binance", "gate") and venue_registry:
        try:
            adapter = venue_registry.get_adapter(pos_venue)
            if adapter and hasattr(adapter, "attach_protective_orders"):
                adapter.attach_protective_orders(
                    name, pos_side, tp_px=take_profit_px if take_profit_px > 0 else None,
                    sl_px=breakeven_sl, contracts=remaining_sz
                )
        except Exception as oco_exc:
            print(f"[Scale-Out] 外所 {pos_venue.upper()} 剩余仓位云端保护更新异常: {oco_exc}")

    # 7. 更新本地状态机与账本
    t["scale_out_phase"] = 1
    t["scale_out_tp"] = None
    t["currentSz"] = remaining_sz
    t["trailingStopPx"] = breakeven_sl
    t["scale_count"] = 999  # 永久互斥锁定金字塔加仓
    t["stage_desc"] = (f"已分批止盈50% (余仓保证金 ~{_margin_of(remaining_sz):.2f}U"
                       f" · 保本止损 {breakeven_sl})")

    # 8. 记录平仓台账与通知
    realized_pnl = close_sz * ct_val * (cur_px - entry_px if is_long else entry_px - cur_px)
    fee_val = close_fee(close_sz, ct_val, cur_px, TAKER_FEE_RATE) if close_fee else (close_sz * ct_val * cur_px * TAKER_FEE_RATE)

    msg_action = (f"[{name}] 🎯 达到首批止盈门槛(+{trigger_threshold:.2f})，已市价平仓 "
                  f"{ratio*100:.0f}% (保证金 {_margin_of(close_sz):.2f}U)，锁定盈利 "
                  f"+{realized_pnl:.2f}U；余仓保证金 ~{_margin_of(remaining_sz):.2f}U "
                  f"推进至保本位 {breakeven_sl}")
    executed_actions.append(msg_action)

    if record_trade and close_trade_payload:
        record_trade(close_trade_payload(
            is_long=is_long,
            timestamp_full=timestamp_full,
            name=name,
            action_type="分批止盈",
            side_suffix="首批平仓50%",
            pos_sz=close_sz,
            cur_px=cur_px,
            fee=fee_val,
            pnl=realized_pnl,
            remark=f"浮盈达到 {trigger_threshold:.2f} 触发首批止盈，锁定现金利润，余仓移损保本",
        ))

    if notify_trade_close:
        try:
            notify_trade_close(
                inst=name,
                pnl=realized_pnl,
                stage="首批分批止盈50%",
                exit_px=cur_px,
                side="多" if is_long else "空",
                entry_px=entry_px,
                fee=fee_val,
                venue=pos_venue,
                is_partial=True,
            )
        except Exception:
            pass

    return True, "首批分批平仓成功"
