"""持仓中调整止盈的**腿感知**下发通道（2026-09-29 UPDATE_TP）。

## 为什么需要它

`okx_rest.amend_algo_sl` 从一开始就支持 `newTpTriggerPx`，但**全仓没有任何调用点**：
模型的动作词表只有 `HOLD/CLOSE_MARKET/UPDATE_SL`，tracker 的 `takeProfitPx` 建仓后
再无写入点。于是"模型按行情调整止盈"这件事三个环节全缺（词表 / 通道 / 真源）。

本模块补的是**通道 + 真源**：

- **认腿**靠建仓时登记的 `leg_algo_ids`（`{tp1: algoId, tp2: algoId}`），
  不靠"比价猜哪条是 TP1" —— 价格一旦被改，比价就会改错腿（把 TP1 当 TP2 改，
  半个仓位在错误价位成交）；
- **一次 amend 同时带 SL 与 TP**（OKX `amend-algos` 支持），避免两腿 SL/TP 不一致；
- **amend 失败不回写 tracker**：真源必须等于交易所上的真实挂单，
  否则下一轮 `ensure_cloud_position_protection` 会拿假价重建保护；
- 分批已发生（`phase=1`）⇒ 只剩余仓腿，只改它。

## 方向纪律（防鞭打）

默认只允许**向有利方向**移动（多单上移、空单下移）且最小步长
`ASTRA_TP_AMEND_MIN_STEP_ATR × ATR`（默认 0.25×ATR，且不低于现价的 0.1%）——
模型每 15 分钟改一次、来回改单既会被 OKX 限速，也会让保护层反复重建。

`ASTRA_TP_ALLOW_ADVERSE=1` 时允许**下调**止盈（行情转弱时主动收小目标），
但**仅限未分批（phase<1）**，并且调用方必须把方向记进台账/通知（标红）。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

ALLOW_ADVERSE_ENV = "ASTRA_TP_ALLOW_ADVERSE"
MIN_STEP_ATR_ENV = "ASTRA_TP_AMEND_MIN_STEP_ATR"
DEFAULT_MIN_STEP_ATR = 0.25
MIN_STEP_PRICE_RATIO = 0.001


def _round_px(value: Any, px_prec: Any) -> float:
    """按价格精度取整（半进一，非银行家舍入）：0.22355 @4 → 0.2236。"""
    try:
        v = float(value)
        p = int(px_prec if px_prec is not None else 2)
    except (TypeError, ValueError):
        return float(value)
    if p < 0:
        return v
    from decimal import ROUND_HALF_UP, Decimal
    q = Decimal(1).scaleb(-p)
    return float(Decimal(repr(v)).quantize(q, rounding=ROUND_HALF_UP))


def allow_adverse() -> bool:
    """是否允许把止盈往不利方向改（默认否 —— 行为变更必须显式开关）。"""
    return str(os.getenv(ALLOW_ADVERSE_ENV, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def min_step(atr: Any, cur_px: Any) -> float:
    """最小变动步长 = max(MIN_STEP_ATR×ATR, 现价×0.1%)。"""
    try:
        atr_v = float(atr or 0.0)
    except (TypeError, ValueError):
        atr_v = 0.0
    try:
        px = float(cur_px or 0.0)
    except (TypeError, ValueError):
        px = 0.0
    try:
        mult = float(os.getenv(MIN_STEP_ATR_ENV, "") or DEFAULT_MIN_STEP_ATR)
    except (TypeError, ValueError):
        mult = DEFAULT_MIN_STEP_ATR
    return max(abs(mult) * atr_v, abs(px) * MIN_STEP_PRICE_RATIO)


def _close_to(a: Any, b: Any, *, tolerance_ratio: float = 0.0005) -> bool:
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if x <= 0 or y <= 0:
        return False
    return abs(x - y) <= max(1e-12, abs(y) * tolerance_ratio)


def leg_direction_ok(*, is_long: bool, old_px: float, new_px: float, step: float,
                     allow_adverse_move: bool) -> Tuple[bool, str]:
    """单价的**方向 + 步长**校验（三态：有利 / 不利 / 无变化）。"""
    if new_px <= 0:
        return False, "目标价无效"
    delta = (new_px - old_px) if is_long else (old_px - new_px)   # >0 = 向有利方向
    if abs(delta) < step - 1e-12:
        return False, f"变动小于最小步长 {step:.6g}（防鞭打）"
    if delta < 0 and not allow_adverse_move:
        return False, "只允许向有利方向调整止盈（需要 ASTRA_TP_ALLOW_ADVERSE=1 才可下调）"
    return True, "向上" if delta > 0 else "下调"


def select_leg(rows: Sequence[Dict[str, Any]], pos_side: str, role: str,
               leg_algo_ids: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """按**登记的角色 → algoId** 选出要走的那条腿。

    登记优先（唯一可靠）；登记缺失时退回"最接近该角色目标价"的腿，
    并在调用方留痕（属于降级认腿）。
    """
    close_side = "sell" if pos_side == "long" else "buy"
    live = [row for row in rows or []
            if str(row.get("state", "live")).lower() in {"live", "effective"}
            and str(row.get("posSide", "net")).lower() in {pos_side, "net"}
            and str(row.get("side", close_side)).lower() == close_side
            and row.get("tpTriggerPx")]
    if not live:
        return None
    registered = str((leg_algo_ids or {}).get(role) or "")
    if registered:
        hit = next((row for row in live if str(row.get("algoId") or "") == registered), None)
        if hit is not None:
            return hit
    return None


def sync_cloud_algo_tp(inst_id: str, pos_side: str, *, is_long: bool,
                       tp1_px: Any = None, tp2_px: Any = None, sl_px: Any = None,
                       phase: int = 0, leg_algo_ids: Optional[Dict[str, Any]] = None,
                       tracker: Optional[Dict[str, Any]] = None,
                       okx_rest, atr: Any = 0.0, cur_px: Any = 0.0,
                       px_prec: int = 2) -> Tuple[bool, str, Dict[str, float]]:
    """把新的 TP1/TP2 下发到对应腿；返回 `(是否成功, 说明, 已生效的价格)`。

    ⚠️ `px_prec` 是**价格**精度（不是张数精度）。2026-09-29 真机实测踩到：调用方传了
    张数精度（ARB = 0/2 位小数）⇒ 0.2236 被下发成 `0.22`（差 1.6%！），而 tracker 记的
    却是未取整的 0.2236 ⇒ 真源与交易所**分叉**。故参数直接改名为 `px_prec` 以免再混。

    `已生效的价格` 只包含**真的改成功**的那些价位，且以**交易所回读值**为准
    （OKX 会按合约 `tickSz` 回显触发价，与下发值可能差一个 tick）—— 调用方据此更新
    tracker，真源恒等于交易所。任何一条腿改失败都返回 False，且**不**更新该价位。
    """
    applied: Dict[str, float] = {}
    try:
        rows = okx_rest.pending_algo_orders(inst_id)
    except Exception as exc:
        return False, f"无法读取保护腿: {exc}", applied

    step = min_step(atr, cur_px)
    adverse_ok = allow_adverse()
    # 分批已发生 ⇒ TP1 那一半已经落袋，只剩余仓腿承载 TP2。
    targets: List[Tuple[str, float]] = []
    if tp2_px:
        targets.append(("tp2", float(tp2_px)))
    if tp1_px and int(phase or 0) < 1:
        targets.append(("tp1", float(tp1_px)))
    elif tp1_px and int(phase or 0) >= 1:
        return False, "分批已发生：TP1 腿已成交，只允许调整 tp2", applied

    if not targets:
        return False, "没有需要调整的止盈价", applied

    notes: List[str] = []
    directions: Dict[str, str] = {}
    for role, new_px in targets:
        leg = select_leg(rows, pos_side, role, leg_algo_ids)
        if leg is None:
            notes.append(f"{role} 腿未找到（algoId 登记可能已失效）")
            return False, "；".join(notes), applied
        old_px = float(leg.get("tpTriggerPx") or 0.0)
        if _close_to(old_px, new_px):
            applied[role] = old_px
            notes.append(f"{role} 已是 {new_px:g}（幂等跳过）")
            continue
        ok_dir, why = leg_direction_ok(is_long=is_long, old_px=old_px, new_px=new_px,
                                      step=step, allow_adverse_move=adverse_ok)
        if not ok_dir:
            notes.append(f"{role} {old_px:g}→{new_px:g} 被拒: {why}")
            return False, "；".join(notes), applied
        # ⚠️ `amend_algo_sl` 的第二个位置参数是 **new_sl_trigger_px**：不打算改止损时
        # 必须传该腿**当前**的止损价 —— 传别的值等于把止损挪到那里（钱路事故）。
        try:
            current_sl = float(leg.get("slTriggerPx") or 0.0)
            target_sl = float(sl_px) if sl_px and float(sl_px) > 0 else current_sl
            if target_sl <= 0:
                notes.append(f"{role} 缺当前止损价，拒绝 amend（避免误移止损）")
                return False, "；".join(notes), applied
            okx_rest.amend_algo_sl(
                leg["algoId"], target_sl, inst_id=inst_id,
                new_tp_trigger_px=_round_px(new_px, px_prec),
                new_tp_ord_px="-1",
            )
        except Exception as exc:
            notes.append(f"{role} amend 失败（真源保持不变）: {exc}")
            return False, "；".join(notes), applied
        applied[role] = _round_px(new_px, px_prec)
        directions[role] = why
        notes.append(f"{role} {old_px:g}→{new_px:g} {why}")

    # 回读一次：OKX 按 tickSz 回显触发价，tracker 必须记**交易所实际值**（真源）。
    if applied:
        try:
            echo = {str(row.get("algoId")): row.get("tpTriggerPx")
                    for row in okx_rest.pending_algo_orders(inst_id)}
            for role in list(applied):
                _aid = str((leg_algo_ids or {}).get(role) or "")
                if _aid and _aid in echo and echo[_aid] not in (None, ""):
                    applied[role] = float(echo[_aid])
        except Exception as exc:
            notes.append(f"回读交易所触发价失败（以下发值为准）: {exc}")

    if tracker is not None:
        if "tp2" in applied:
            tracker["takeProfitPx"] = applied["tp2"]
        if "tp1" in applied:
            tracker["scale_out_tp"] = applied["tp1"]
        tracker["last_tp_amend"] = {
            "applied": dict(applied),
            "directions": dict(directions),
            "adverse": any(v == "下调" for v in directions.values()),
            "allow_adverse": adverse_ok,
        }
    return True, "；".join(notes), applied
