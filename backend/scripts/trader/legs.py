"""持仓保护**双腿**编排（2026-09-29 分批止盈实盘化）。

## 为什么是双腿而不是 OKX 原生 closeFraction

2026-09-29 真机探针（模拟盘，`POST /api/v5/trade/order-algo`）：

| 形态 | 结果 |
|---|---|
| `closeFraction=0.5`（原生分批止盈） | **HTTP 400 `51000 Parameter closeFraction error`** |
| `closeFraction=0.5 + reduceOnly` | 同样 400 |
| `sz=1 + reduceOnly + cxlOnClosePos`（对照） | **200 受理** |

即"原生分批止盈在模拟盘不可用"是**真的**；而"多挂一条**带尺寸**的 reduceOnly
算法腿"两个环境都受理。故本仓用双腿实现首批止盈（TP1 腿 = `ratio×size`，
余仓腿 = 其余），完全不依赖 closeFraction。

## 关键约束：两条腿都必须是 OCO（同时带 TP 与 SL）

覆盖率统计 `_live_oco_coverage` **只认同时带 `tpTriggerPx` 与 `slTriggerPx`** 的
reduceOnly 腿。若把 TP1 腿做成"只有 TP"，它会被整条排除 ⇒ 覆盖率看起来只有 50%
⇒ 保护层以为缺一半、再补一条 ⇒ **超额保护腿**（本仓历史事故形态）。
双腿各自带同一个 SL 时：SL 先触发 → 两条腿都成交 = 100% 平仓；TP1 先触发 →
OCO 自动撤掉该腿的 SL，剩余 50% 仍由余仓腿保护。故覆盖率恒为 100%。

## 编排纪律

1. **先挂后撤**：新腿挂上、再撤被替代的旧腿 ⇒ 任何瞬间都有保护（短暂超覆盖，
   且全部 reduceOnly，物理上不可能反向开仓）；
2. **幂等**：几何已匹配就什么都不做（每轮巡检都会调用本函数）；
3. **量化**：`leg1 + leg2` 必须逐位等于持仓张数（按 minSz 步长向下夹取），
   否则余腿会因 51121 lot size 被拒（本仓历史事故）。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: 分批腿模式：off（关）/ live_only（仅实盘）/ always（实盘与模拟盘都挂）。
LEG_MODE_ENV = "ASTRA_SCALE_OUT_LEG_MODE"
DEFAULT_LEG_MODE = "always"
VALID_LEG_MODES = ("off", "live_only", "always")

#: 腿归属判定容差（触发价的相对误差）。OKX 会按 tickSz 取整，
#: 用相对容差可以同时覆盖 BTC（tick 0.1）与 SUI（tick 0.0001）。
MATCH_TOLERANCE_RATIO = 0.0005

#: 触发价类型：mark（标记价）—— 与本仓入场附着腿、云端棘轮腿同口径。
TRIGGER_PX_TYPE = "mark"


def leg_mode() -> str:
    """当前腿模式（未知取值一律回落默认，绝不因拼错而静默关掉保护）。"""
    raw = str(os.getenv(LEG_MODE_ENV, "") or "").strip().lower()
    return raw if raw in VALID_LEG_MODES else DEFAULT_LEG_MODE


def legs_enabled(*, simulated: bool = False) -> bool:
    """本环境是否该挂双腿。"""
    mode = leg_mode()
    if mode == "off":
        return False
    if mode == "live_only":
        return not simulated
    return True


def _quantize_down(value: float, step: float) -> float:
    import math
    if step <= 0:
        return value
    return math.floor(value / step + 1e-9) * step


def _precision_of(step: float) -> int:
    try:
        s = f"{float(step or 0.0):.8f}".rstrip("0")
        if "." in s:
            return len(s.split(".")[1])
    except Exception:
        pass
    return 0


def plan_legs(size: Any, tp1_px: Any, tp2_px: Any, sl_px: Any, *,
              ratio: float = 0.5, min_sz: float = 0.0, prec: int = 2,
              px_prec: Optional[int] = None
              ) -> Optional[List[Dict[str, Any]]]:
    """把一份持仓拆成 [TP1 腿, 余仓腿]；不可安全切分时返回 None。

    量化纪律：`close_sz = floor(size × ratio / minSz) × minSz`，
    `rest = size − close_sz`（**先算余量再校验**，保证两腿之和逐位等于 size）。

    ⚠️ `prec` 是**张数**精度、`px_prec` 是**价格**精度，两者**必须分开**：
    SUI 这类合约张数是整数（prec=0）而价格是 4 位小数 —— 混用一个参数会把
    TP1 从 1.117 四舍五入成 1.0（把止盈挂到离谱价位）。
    """
    try:
        total = abs(float(size or 0.0))
        tp1 = float(tp1_px or 0.0)
        tp2 = float(tp2_px or 0.0)
        sl = float(sl_px or 0.0)
    except (TypeError, ValueError):
        return None
    if total <= 0 or min(tp1, tp2, sl) <= 0:
        return None
    if tp1 == tp2:
        return None
    ratio = max(0.1, min(0.9, float(ratio or 0.5)))
    step = float(min_sz or 0.0)
    if step <= 0:
        return None
    # 尺寸精度：至少要能容纳 step 本身的步长精度，防止调用方错传价格精度导致张数残片被截掉
    sz_prec = max(int(prec or 0), _precision_of(step))
    # 首批**向下取整**（绝不多平），余量取"总量减首批"**再按张数精度取整**：
    # 取整可能让两腿之和比持仓多不到 1 张 —— 这是**有意**的：reduceOnly 由交易所按
    # 实际持仓封顶，多覆盖无害；反之若把余量也向下取整，就会有单张残片**完全无保护**，
    # 且覆盖率统计会长期 < 100% 触发每轮"补保护"。
    close_sz = round(_quantize_down(total * ratio, step), sz_prec)
    rest_sz = round(total - close_sz, sz_prec)
    if round(close_sz + rest_sz, sz_prec) < round(total, sz_prec):
        rest_sz = round(total - close_sz + step, sz_prec)
    if close_sz < step - 1e-12 or rest_sz < step - 1e-12:
        return None                      # 不足以切成两半（旧逻辑的"优雅降级"）
    _px = int(prec or 2) if px_prec is None else int(px_prec or 0)
    return [
        {"role": "tp1", "sz": close_sz, "tp": round(tp1, _px), "sl": round(sl, _px)},
        {"role": "tp2", "sz": rest_sz, "tp": round(tp2, _px), "sl": round(sl, _px)},
    ]


def leg_payload(leg: Dict[str, Any]) -> Dict[str, Any]:
    """腿 → OKX `order-algo` 参数（OCO：TP 与 SL 必须同时给）。"""
    return {
        "sz": leg["sz"],
        "tpTriggerPx": leg["tp"],
        "tpOrdPx": "-1",
        "tpTriggerPxType": TRIGGER_PX_TYPE,
        "slTriggerPx": leg["sl"],
        "slOrdPx": "-1",
        "slTriggerPxType": TRIGGER_PX_TYPE,
    }


def _live_reduce_only_legs(rows: Sequence[Dict[str, Any]], pos_side: str) -> List[Dict[str, Any]]:
    """筛出该 posSide 的"活着的、reduceOnly、OCO"腿（与覆盖率统计同口径）。"""
    close_side = "sell" if pos_side == "long" else "buy"
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        if str(row.get("state", "live")).lower() not in {"live", "effective"}:
            continue
        if str(row.get("posSide", "net")).lower() not in {pos_side, "net"}:
            continue
        if str(row.get("side", close_side)).lower() != close_side:
            continue
        if not row.get("tpTriggerPx") or not row.get("slTriggerPx"):
            continue
        if str(row.get("reduceOnly", "true")).lower() not in {"true", "1", "yes"}:
            continue
        out.append(row)
    return out


def _close_to(a: Any, b: Any, *, tolerance_ratio: float = MATCH_TOLERANCE_RATIO) -> bool:
    try:
        x, y = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if x <= 0 or y <= 0:
        return False
    return abs(x - y) <= max(1e-12, abs(y) * tolerance_ratio)


def legs_already_match(rows: Sequence[Dict[str, Any]], plan: Sequence[Dict[str, Any]],
                       pos_side: str, *, size: Any = None, min_sz: float = 0.0) -> bool:
    """现有腿是否已经**就是**目标双腿 —— 幂等判据。

    ⚠️ 判据是"**TP 价位集合一致 + 张数覆盖当前持仓**"，不是"逐腿张数与计划逐位相等"。
    2026-09-29 实盘踩到：计划随**当前持仓张数**重算，而持仓张数会因费率/结算/部分平仓
    产生 ±1 张漂移 ⇒ 逐位比对永远不相等 ⇒ **每轮都重挂双腿**（先挂后撤 = 每 15 分钟
    给 OKX 打 4 笔单，撞限速且徒增风险窗口）。TP 是腿几何的本质，张数只需"覆盖住"。
    """
    live = _live_reduce_only_legs(rows, pos_side)
    if len(live) != len(plan):
        return False
    # TP 比对用**同一容差**（0.05% 相对）逐一配对，不用位相等：
    # OKX 回读的触发价是按合约 `tickSz` 回显的，与我们下发的 4 位小数可能差 1 个 tick
    # （实测 ARB：下发 0.2138、回读 0.2137）。位相等会让"其实已经就位"的腿每轮被判定
    # 不匹配 ⇒ 先挂后撤无限重挂（2026-09-29 线上实测到）。
    remaining = list(live)
    for leg in plan:
        hit = next((row for row in remaining
                    if _close_to(row.get("tpTriggerPx"), leg["tp"])), None)
        if hit is None:
            return False
        remaining.remove(hit)
    if min_sz and any(float(row.get("sz") or 0) < float(min_sz) - 1e-12 for row in live):
        return False
    total = sum(float(row.get("sz") or 0) for row in live)
    need = float(size) if size not in (None, "") else sum(float(leg["sz"]) for leg in plan)
    # 覆盖住当前持仓即可（允许多覆盖一张：reduceOnly 由交易所按实际持仓封顶，
    # 宁可多覆盖，也绝不留下没有保护的单张残片）。
    return total >= need * (1.0 - MATCH_TOLERANCE_RATIO) - 1e-12


def sync_position_legs(inst_id: str, pos_side: str, size: Any, *,
                       tp1_px: Any, tp2_px: Any, sl_px: Any,
                       ratio: float = 0.5, min_sz: float = 0.0, prec: int = 2,
                       px_prec: Optional[int] = None,
                       okx_rest, simulated: bool = False,
                       tolerance_ratio: float = MATCH_TOLERANCE_RATIO,
                       state: Optional[Dict[str, Any]] = None
                       ) -> Tuple[bool, str]:
    """确保该持仓挂着 [TP1 腿, 余仓腿]；返回 `(是否达成, 说明)`。

    幂等：几何已匹配 ⇒ 立即返回 True 且**不发任何请求**。
    先挂后撤：新腿提交成功后，才撤掉被替代的旧腿。
    `state`（tracker）用于**撤单失败断路器**：上一轮撤不掉的旧腿 id 记在
    `leg_stale_ids`，本轮先重试撤销；撤销仍失败就**不再挂新腿** ——
    否则每轮都会"挂 2 条、撤不掉 3 条"，腿数无界增长。
    """
    if not legs_enabled(simulated=simulated):
        return False, f"双腿未启用（{LEG_MODE_ENV}={leg_mode()}）"

    pending_stale = list((state or {}).get("leg_stale_ids") or [])
    if pending_stale:
        try:
            okx_rest.cancel_algo_orders(pending_stale[:10], inst_id=inst_id)
            if state is not None:
                state.pop("leg_stale_ids", None)
        except Exception as exc:
            return False, f"上一轮旧腿未撤销，本轮只重试撤销（不重复挂腿）: {exc}"

    plan = plan_legs(size, tp1_px, tp2_px, sl_px, ratio=ratio, min_sz=min_sz,
                     prec=prec, px_prec=px_prec)
    if not plan:
        return False, "持仓无法安全切成两半（低于最小下单量的 2 倍）"

    try:
        rows = okx_rest.pending_algo_orders(inst_id)
    except Exception as exc:
        return False, f"无法读取现有保护腿: {exc}"

    if legs_already_match(rows, plan, pos_side, size=size, min_sz=min_sz):
        return True, "双腿已就位（无需改动）"

    close_side = "sell" if pos_side == "long" else "buy"
    old_legs = _live_reduce_only_legs(rows, pos_side)
    placed: List[str] = []
    try:
        for leg in plan:
            res = okx_rest.place_algo_oco(
                inst_id, close_side, f"{leg['sz']:g}", pos_side=pos_side, td_mode="cross",
                tp_trigger_px=leg["tp"], tp_ord_px="-1",
                sl_trigger_px=leg["sl"], sl_ord_px="-1",
                trigger_px_type=TRIGGER_PX_TYPE,
                reduce_only=True, cxl_on_close_pos=True,
            )
            for row in res or []:
                if row.get("algoId"):
                    placed.append(str(row["algoId"]))
    except Exception as exc:
        # 挂腿失败：**保留**旧腿（先挂后撤的意义就在这里），如实返回失败。
        return False, f"双腿挂单失败（旧保护单保留）: {exc}"

    if len(placed) != len(plan):
        return False, f"双腿挂单回执不完整（{len(placed)}/{len(plan)}），旧保护单保留"

    # 登记"角色 → algoId"：这是 UPDATE_TP 认腿的**唯一可靠依据**
    # （靠比价猜腿，一旦模型改了价就会改错腿 —— 半个仓位在错误价位成交）。
    if state is not None:
        state["leg_algo_ids"] = {"tp1": placed[0], "tp2": placed[1]}

    # 新腿已确认，再撤被替代的旧腿；撤单失败不改变"已达成"的结论（覆盖可能超额，
    # 但全部 reduceOnly）—— 只在说明里如实标注，留给下一轮幂等收尾。
    stale = [str(row.get("algoId")) for row in old_legs if row.get("algoId")
             and str(row.get("algoId")) not in placed]
    cancel_note = ""
    if stale:
        try:
            okx_rest.cancel_algo_orders(stale[:10], inst_id=inst_id)
            if state is not None:
                state.pop("leg_stale_ids", None)
        except Exception as exc:
            cancel_note = f"；旧腿撤销失败（下一轮重试）: {exc}"
            if state is not None:
                state["leg_stale_ids"] = stale
    return True, f"双腿已重建（{plan[0]['sz']:g}+{plan[1]['sz']:g}）{cancel_note}"


def split_superseded_by_phase(tracker: Dict[str, Any]) -> bool:
    """分批已完成 ⇒ 不再拆腿（余仓只需一条保护腿）。"""
    try:
        return int((tracker or {}).get("scale_out_phase", 0) or 0) >= 1
    except (TypeError, ValueError):
        return False
