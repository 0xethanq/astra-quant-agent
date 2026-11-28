"""TP1/TP2 单一真源与几何守卫（2026-09-29 分批止盈实盘化）。

## 为什么需要这个模块

旧实现里 TP1 由 `scale_out.py` **每轮用当轮 ATR 重算**：

    trigger_threshold = SCALE_OUT_TRIGGER_ATR * max(f["atr"], cur_px * 0.005)

而云端挂单是一个**一次性价格**。实盘双腿方案（把首批 50% 作为独立算法腿挂在
TP1）要求"软件判定的 TP1"与"交易所挂着的 TP1"**逐位相同** —— 否则会出现
两种坏结局：软件在腿之前市价平掉一半（腿随后触发，多平一次），或腿在软件阈值
之前成交而软件不认账。故 TP1 在建仓时**冻结**进 tracker（`scale_out_tp`），
此后所有路径只读不算。

## 几何守卫

双腿必须满足 `现价 < TP1 < TP2`（多单）/ `现价 > TP1 > TP2`（空单）。
不满足时**必须放弃挂腿**：腿挂到错误一侧要么被 OKX 直接拒（51000 族），
要么立刻触发变成"开盘即平一半"。守卫生效时软件路径**仍然可跑** ——
它按浮盈判定，不依赖云端腿。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

try:
    from scripts.risk_constants import SCALE_OUT_TRIGGER_ATR
except Exception:                                          # pragma: no cover - 独立运行兜底
    SCALE_OUT_TRIGGER_ATR = 1.20

#: ATR 下限：低于现价的 0.5% 视为无效 ATR（与 scale_out 旧口径逐位一致）。
MIN_ATR_PRICE_RATIO = 0.005


def effective_atr(atr: Any, cur_px: Any) -> float:
    """`max(atr, 现价×0.5%)` —— 与旧 `scale_out` 的口径保持逐位相同。"""
    try:
        base = float(atr or 0.0)
    except (TypeError, ValueError):
        base = 0.0
    try:
        px = float(cur_px or 0.0)
    except (TypeError, ValueError):
        px = 0.0
    return max(base, px * MIN_ATR_PRICE_RATIO)


def compute_tp1(entry_px: Any, atr: Any, is_long: bool, prec: int = 2,
                cur_px: Any = None, multiple: Optional[float] = None,
                initial_stop_px: Any = None, tp2_px: Any = None) -> Optional[float]:
    """首批止盈价（TP1）= 入场价 ± max(SCALE_OUT_TRIGGER_ATR × ATR, 1.0 × 初始止损距离 1R)。

    当传入 `tp2_px` 时强制保证严格几何顺序：多单 `entry < TP1 < TP2`、空单 `entry > TP1 > TP2`。
    若 TP2 空间不足 1.45R（或钳位后 TP1 退化至不足 0.9R / 与 TP2 重合），返回 None 以退回全仓止盈。
    `cur_px` 只在 ATR 无效时用来兜底（旧口径），冻结场景传 None 即可。
    """
    entry = float(entry_px or 0.0)
    mult = float(SCALE_OUT_TRIGGER_ATR if multiple is None else multiple)
    atr_eff = effective_atr(atr, cur_px if cur_px is not None else entry)
    threshold = mult * atr_eff
    r_dist = 0.0
    if initial_stop_px is not None:
        try:
            sl = float(initial_stop_px)
            r_val = (entry - sl) if is_long else (sl - entry)
            if sl > 0 and r_val > 0:
                r_dist = r_val
                threshold = max(threshold, r_dist)
        except (TypeError, ValueError):
            pass

    p = int(prec or 2)
    if tp2_px is not None:
        try:
            tp2 = float(tp2_px or 0.0)
        except (TypeError, ValueError):
            tp2 = 0.0
        if tp2 <= 0 or entry <= 0:
            return None
        tp2_dist = (tp2 - entry) if is_long else (entry - tp2)
        if tp2_dist <= 0:
            return None
        min_headroom = max(1.45 * r_dist, 1.35 * max(0.9 * atr_eff, entry * 0.004)) if r_dist > 0 else (1.35 * max(0.9 * atr_eff, entry * 0.004))
        if tp2_dist < min_headroom:
            return None
        # 为 TP2 腿留出至少 20% 或 0.2% 价格空间，防止 TP1 >= TP2
        max_tp1_dist = max(0.0, min(tp2_dist * 0.80, tp2_dist - entry * 0.002))
        threshold = min(threshold, max_tp1_dist)
        min_tp1_floor = max(0.9 * r_dist, entry * 0.003) if r_dist > 0 else max(0.9 * atr_eff, entry * 0.003)
        if threshold < min_tp1_floor:
            return None
        cand = round(entry + threshold if is_long else entry - threshold, p)
        tp2_round = round(tp2, p)
        if (is_long and cand >= tp2_round) or ((not is_long) and cand <= tp2_round):
            return None
        return cand

    return round(entry + threshold if is_long else entry - threshold, p)


def freeze_tp1(tracker: Dict[str, Any], *, entry_px: Any, atr: Any, is_long: bool,
               prec: int = 2, multiple: Optional[float] = None,
               initial_stop_px: Any = None, tp2_px: Any = None) -> float:
    """把 TP1 冻结进 tracker（幂等：已有值就用已有值，绝不重算覆盖）。

    ⚠️ 只在**没有值**时计算：一旦挂腿，TP1 就是交易所上的一个真实价格，
    重算等于偷偷改单（这正是旧实现每轮覆盖 `scale_out_tp` 的问题）。
    """
    existing = tracker.get("scale_out_tp")
    if existing is not None:
        try:
            value = float(existing)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    value = compute_tp1(
        entry_px, atr, is_long, prec,
        multiple=multiple, initial_stop_px=initial_stop_px, tp2_px=tp2_px,
    )
    if value is None or value <= 0:
        tracker["scale_out_tp"] = None
        return 0.0
    tracker["scale_out_tp"] = value
    return value


def tp1_geometry_ok(tp1_px: Any, tp2_px: Any, cur_px: Any, is_long: bool) -> bool:
    """`现价 < TP1 < TP2`（多）/ `现价 > TP1 > TP2`（空）—— 挂腿前必须成立。"""
    try:
        tp1 = float(tp1_px or 0.0)
        tp2 = float(tp2_px or 0.0)
        px = float(cur_px or 0.0)
    except (TypeError, ValueError):
        return False
    if tp1 <= 0 or tp2 <= 0 or px <= 0:
        return False
    if is_long:
        return px < tp1 < tp2
    return px > tp1 > tp2


def format_trigger_text(threshold: Any, entry_px: Any) -> str:
    """把触发门槛写成**可读的百分比**（旧文案对 ARB 这类低价标的一直显示 `+0.00`）。

    返回形如 `+1.2% (≈+0.0024)`；入场价无效时退化为纯百分比或纯价格。
    """
    try:
        thr = abs(float(threshold or 0.0))
    except (TypeError, ValueError):
        thr = 0.0
    try:
        entry = abs(float(entry_px or 0.0))
    except (TypeError, ValueError):
        entry = 0.0
    if entry > 0:
        pct = thr / entry * 100
        if thr >= 1.0:
            return f"+{pct:.1f}% (≈+{thr:.2f})"
        return f"+{pct:.1f}% (≈+{thr:.4f})"
    return f"+{thr:.4f}"
