"""按 AI 决策推导下单张数（B3 抽取第十九块）。

从 `scripts/ai_factor_trader.py::execute_portfolio` 的 per-factor 循环里搬出。
原实现是约 13 行的内联计算（含 4 个独立钳制）。

## 这块在解决什么

"AI 说要多少保证金 + 多少倍杠杆"到"实际下多少张"，中间隔着**四道互相牵制的钳制**，
顺序不能换，换一道结果就偏：

| # | 钳制 | 作用 |
|---|---|---|
| 1 | `planned_notional = ai_margin * ai_lever` → `quantize_size` | 按保证金×杠杆折算张数 |
| 2 | 自适应基准仓位的 **0.5x 下限** | 防止 AI 给过小的额，导致仓位被手续费吃掉 |
| 3 | 自适应基准仓位的 **2.0x 上限** | 防止 AI 给过大的额 |
| 4 | **可用余额硬顶** `max_size_within_margin` | 付不起就砍到付得起，**且只砍不放** |
| 5 | 收尾再 `quantize_size` | 因为第 4 步的 `min()` 可能引入非整步长 |

这 5 步里任何一步的顺序变化都会改变结果：
- 若把第 5 步（收尾量化）挪到第 4 步之前，余额硬顶砍出来的非整步长就带上去了
  —— 交易所以整步长校验，会**下单被拒**。
- 若把第 2/3 步放到第 4 步之后，余额硬顶会被 0.5x 下限**重新抬回去**
  —— 变成"付不起也要开"，这是最危险的一种。
- 第 4 步只做 `min()`，**不做 `max()`** —— 原注释写明"付不起则直接归零跳过而非放大"。
  若有人"顺手对称"地补一个 `max(actual_sz, afford_sz)`，就变成**放大仓位**。

## 返回值的两种含义

- 返回 `> 0`：可直接用的张数（已满足交易所步长）。
- 返回 `0`：**不可交易** —— 可能因为推导出的张数低于交易所最小下单量，
  也可能因为可用余额付不起。调用点据此跳过该标的（并打 `[仓位跳过]` 日志）。

## 与 `calculated_sz <= 0` 的守卫

原实现把第 2~5 步包在 `if calculated_sz > 0:` 里。由于 `quantize_size` 对非正输入
一律返回 `0.0`，而 `planned_notional` 恒为正（调用点已保证 `ai_margin > 0`、
`ai_lever >= 1`、`price > 0`、`ct_val > 0`），该守卫实际不可达，故本函数不再重复它。
**语义等价，但这不是"顺手删守卫"** —— 依据是 `quantize_size` 的失败返回值为 0：
即使守卫真被触发，本函数返回的 `actual_sz` 与"跳过整个块"后门面持有的
`f["sz"]`，在 `f["sz"] <= 0` 时对下游 `if actual_sz <= 0: continue` 的判定一致；
而 `f["sz"] > 0` 时守卫不可达。测试里有专项对照。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def size_for_decision(*, ai_margin, ai_lever, price, ct_val, step_sz, base_sz,
                      usdt_available, actual_sz, quantize_size,
                      max_size_within_margin):
    """返回本笔应下的张数（`0` 表示不可交易）。

    参数全部入参：
    - `quantize_size` / `max_size_within_margin` 由调用点注入 —— 它们是
      `astra_backend.execution.sizing` 里的共享函数，测试会 `patch.object` 门面，
      import 期绑定会绕过这些接缝（`astra_backend/README.md` §5）。
    - `base_sz` 是自适应基准仓位（门面里的 `f["sz"]`）。
    - `actual_sz` 是当前值（门面里的 `actual_sz`）；块未生效时原样返回。
    """
    # If AI planned margin & leverage, calculate custom contract size
    if not (ai_margin > 0 and ai_lever >= 1.0 and price > 0 and ct_val > 0):
        return actual_sz

    planned_notional = ai_margin * ai_lever
    calculated_sz = quantize_size(planned_notional / (price * ct_val), step_sz)
    if calculated_sz > 0:
        # 风险钳制：围绕自适应基准仓位的 0.5x~2.0x（按交易所最小步长量化，不再强制整数）
        min_allowed_sz = max(step_sz, quantize_size(base_sz * 0.5, step_sz))
        max_allowed_sz = quantize_size(base_sz * 2.0, step_sz)
        actual_sz = max(min_allowed_sz, min(max_allowed_sz, calculated_sz))
        # 可用余额硬顶：单笔保证金不得超过风控页配置的余额占比，付不起则直接归零跳过而非放大
        afford_sz = max_size_within_margin(usdt_available, ai_lever, price, ct_val, step_sz)
        if afford_sz is not None and afford_sz < float("inf"):
            actual_sz = min(actual_sz, afford_sz)
        actual_sz = quantize_size(actual_sz, step_sz)

    return actual_sz


def size_for_stop_risk(
    *,
    equity_usdt: float,
    entry_px: float,
    stop_px: float,
    ct_val: float,
    leverage: float,
    step_sz: float,
    min_sz: float,
    max_margin_usdt: float,
    risk_per_trade_ratio: float,
    max_risk_per_trade_usdt: float,
    risk_scale: float = 1.0,
    ai_margin_cap: float = 0.0,
) -> Tuple[float, float, float]:
    """按真实止损距离（1R = equity × risk_ratio）反推等风险仓位张数。

    返回 `(final_sz, actual_risk_usdt, actual_margin_usdt)`；无法满足最小手数时全 0。
    """
    eq = float(equity_usdt or 0.0)
    entry = float(entry_px or 0.0)
    stop = float(stop_px or 0.0)
    cv = float(ct_val or 0.0)
    lev = float(leverage or 0.0)
    stop_dist = abs(entry - stop)
    if eq <= 0 or entry <= 0 or stop <= 0 or cv <= 0 or lev <= 0 or stop_dist <= 0:
        return 0.0, 0.0, 0.0

    ratio_r = eq * float(risk_per_trade_ratio or 0.0)
    cap_r = float(max_risk_per_trade_usdt or 0.0)
    one_r = min(ratio_r, cap_r) if cap_r > 0 else ratio_r
    if one_r <= 0:
        return 0.0, 0.0, 0.0
    scale = max(0.05, float(risk_scale if risk_scale is not None else 1.0))
    risk_budget_usdt = one_r * scale
    risk_based_sz = risk_budget_usdt / (stop_dist * cv)

    m_cap = float(max_margin_usdt or 0.0)
    if float(ai_margin_cap or 0.0) > 0:
        m_cap = min(m_cap, float(ai_margin_cap)) if m_cap > 0 else float(ai_margin_cap)
    margin_based_sz = (m_cap * lev) / (entry * cv) if m_cap > 0 else float("inf")
    raw_sz = min(risk_based_sz, margin_based_sz)

    step = float(step_sz or 0.0)
    if step > 0:
        final_sz = round(math.floor(raw_sz / step + 1e-9) * step, 8)
    else:
        final_sz = round(raw_sz, 8)

    if final_sz <= 0 or final_sz < float(min_sz or 0.0):
        return 0.0, 0.0, 0.0

    actual_risk_usdt = round(final_sz * stop_dist * cv, 4)
    actual_margin_usdt = round((final_sz * entry * cv) / lev, 4)
    return float(final_sz), actual_risk_usdt, actual_margin_usdt


def estimate_portfolio_open_risk_r(
    *,
    all_factors: Optional[List[Dict[str, Any]]],
    trackers: Optional[Dict[str, Any]],
    equity_usdt: float,
    risk_per_trade_ratio: float,
    max_risk_per_trade_usdt: float,
) -> float:
    """估算组合当前在途总下行风险（以 1R 为单位）；已保本/锁利仓位贡献 0R。"""
    eq = float(equity_usdt or 0.0)
    ratio_r = eq * float(risk_per_trade_ratio or 0.0)
    cap_r = float(max_risk_per_trade_usdt or 0.0)
    one_r = min(ratio_r, cap_r) if cap_r > 0 else ratio_r
    if eq <= 0 or one_r <= 0:
        return 0.0

    total_risk_usdt = 0.0
    trackers = trackers or {}
    for f in all_factors or []:
        if not isinstance(f, dict):
            continue
        pos = f.get("position")
        if not isinstance(pos, dict):
            continue
        pos_sz = abs(float(pos.get("pos") or 0.0))
        if pos_sz <= 0:
            continue
        side = str(pos.get("side") or pos.get("posSide", "net") or "").lower()
        if side not in ("long", "short"):
            continue
        inst_id = str(f.get("instId") or "")
        entry_px = float(pos.get("avgPx") or pos.get("entryPx") or f.get("price") or 0.0)
        ct_val = float(f.get("ctVal") or pos.get("ctVal") or 1.0)
        tr = trackers.get(f"{inst_id}_{side}")
        sl_px = 0.0
        if isinstance(tr, dict):
            sl_px = float(tr.get("trailingStopPx") or tr.get("initialStopPx") or 0.0)
        if sl_px <= 0:
            sl_px = float(pos.get("trailingStopPx") or 0.0)
        if sl_px <= 0 or entry_px <= 0:
            total_risk_usdt += one_r
            continue
        downside = max(0.0, entry_px - sl_px) if side == "long" else max(0.0, sl_px - entry_px)
        total_risk_usdt += downside * pos_sz * ct_val

    return round(total_risk_usdt / one_r, 3)
