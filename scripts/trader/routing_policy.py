"""选所路由与组合预算政策（B3 抽取·trader 瘦身第八刀，第八十七刀）。

从 `scripts/ai_factor_trader.py` **纯搬家**八函数（219 行）：

| 函数 | 行数 | 职责 |
|---|---|---|
| `load_routing_mode` | 7 | 路由模式（auto/锁定所）读取 |
| `load_preferred_venue` | 7 | 手选锁定所读取 |
| `portfolio_risk_budget_usdt` | 5 | 组合风险预算（env `ASTRA_PORTFOLIO_RISK_BUDGET_USDT`，0=不限） |
| `estimate_margin_usdt` | 6 | 名义额 → 保证金估算 |
| `portfolio_budget_guard` | 17 | 跨所合算总闸（纯函数，0=不限，fail-closed） |
| `route_and_reserve_signal` | — | 信号路由 + 预留落账主流程 |

⚠️ **OKX 专用化（多所执行面拆除）**：评分选所（候选装配 / 场所路由 / 选所证据
落盘）随 `astra_backend` 的多所路由模块与 `scripts/trader/venue_evidence` 的删除
一并移除 —— 全系统只剩 OKX 一个已登记且已接单的场所，选所退化为「锁定 OKX +
手选合法性校验」，预算预留与审计③的跨所合算总闸逐位保留。

## 注入（本刀最宽，全部调用期）

`estimate_margin_usdt` / `load_preferred_venue` / `portfolio_budget_guard` /
`portfolio_risk_budget_usdt` / `reservation_manager` / `VENUE_SUBMITTERS` /
`current_environment` / `risk_reservation`。

⚠️ **源码锚点已同步**：`tests/audit/test_audit_batch2_risk_gates_live.py::
test_route_and_reserve_wires_guard` 用 `inspect.getsource(门面函数)` 断言
"路由必须调用 `portfolio_budget_guard(`"（活线化防漂移锚）。搬壳后门面只剩转发，
该锚改用 `tests/source_scan.find_function_node`（**优先实现体**）并加反证
（门面壳文本不得出现该调用）—— 意图不变、防虚 Hits（§97.2 家族）。
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple


def load_routing_mode(
                              *,
                              routing_policy) -> str:
    """选所路由模式（auto=最优执行B | balanced=均衡轮换A | split=资金拆分C）。

    模块绑定转发（同 load_preferred_venue 钉法）：测试 patch 本函数即可完全
    封闭，绝不在用读真实 data/venue_routing.json 的情况下跑路由断言。
    """
    return routing_policy.load_routing_mode()



def load_preferred_venue(
                              *,
                              routing_policy) -> str:
    """手动选所优先项（data/venue_routing.json 顶层 preferred_venue）。

    单一事实源在 astra_backend.exchanges.routing_policy：缺字段/非法值由其回退
    'auto' 并打 warn。此处只做模块绑定转发，方便接线级测试一键切档。
    """
    return routing_policy.load_preferred_venue()



def portfolio_risk_budget_usdt(
                              *,
                              PORTFOLIO_RISK_BUDGET_ENV) -> float:
    try:
        return max(0.0, float(os.getenv(PORTFOLIO_RISK_BUDGET_ENV, "") or 0.0))
    except (TypeError, ValueError):
        return 0.0



def estimate_margin_usdt(notional_usdt: float, margin_usdt: float = 0.0) -> float:
    """保证金估算：优先执行层算好的真实保证金，缺失时按 3x 保守折算。"""
    if margin_usdt and float(margin_usdt) > 0:
        return round(float(margin_usdt), 4)
    notional = max(0.0, float(notional_usdt or 0.0))
    return round(notional / 3.0, 4)



def portfolio_budget_guard(budget_total: float, budget_used: float, margin_est: float,
                           environment: str = "") -> Optional[str]:
    """审计③：跨所合算总闸的可测纯函数。返回 None=放行；返回 str=拒绝理由。
    语义：budget_total<=0 → 不封顶（保持既有 0=无顶默认）；>0 时按 gross_exposure
    已占用 + 本笔保证金估算 与总预算比较（1e-9 浮点容差）。"""
    try:
        bt = float(budget_total or 0.0)
        bu = float(budget_used or 0.0)
        me = float(margin_est or 0.0)
    except (TypeError, ValueError):
        return "预算数值不可解析，fail-closed 拒绝下单"
    if bt <= 0:
        return None
    if me > 0 and bu + me > bt + 1e-9:
        return (f"组合预算（跨所合算）用尽：已占 {bu:.2f}U + 本笔 {me:.2f}U "
                f"> 总预算 {bt:.2f}U（环境 {environment}）")
    return None



def route_and_reserve_signal(inst_id: str, side: str, price: float,
                             notional_usdt: float = 0.0, margin_usdt: float = 0.0,
                             intent_id: str = "", leverage: float = 0.0,
                              *,
                              estimate_margin_usdt,
                              load_preferred_venue,
                              portfolio_budget_guard,
                              portfolio_risk_budget_usdt,
                              reservation_manager,
                              VENUE_SUBMITTERS,
                              current_environment,
                              risk_reservation) -> Dict[str, Any]:
    """路由 → 执行面接线校验 → 预算原子预留（US-003 决策面前置闸）。

    返回 {"ok": bool, "error": str|None, "venue": str|None, "decision": dict,
          "reservation": dict|None}；任何一步不过 → ok=False，调用方本轮不下单。

    ## OKX 专用化后的"路由"

    系统只剩 OKX 一个已登记**且已接单**的场所（`registered_venues()` 恒为 `["okx"]`），
    评分选所（候选装配 / 拆单 / 选所证据）已随多所执行面移除 ⇒ 目标场所恒为 OKX。
    唯一保留的抉择是**手选锁定**：`preferred_venue` 若被锁到一个不再登记的场所，
    这里 **fail-closed 拒单**，绝不"猜所"改派 OKX —— 与配置面 fail-safe 同族
    （非法值在 `load_preferred_venue` 就回退 auto 并 warn）。
    """
    env = current_environment()
    environment = str(env.mode)
    preferred = load_preferred_venue()
    # 名义额（**钱**口径，与场所无关）：优先执行层算好的 `notional_usdt`；缺失时按
    # `margin × leverage` 反推 —— 这两者都是钱，任何场所都成立。
    #
    # ⚠️ 2026-09-28：本函数**已不再接收张数**。旧兜底是 `max(0.0, size * price)`，
    # 漏乘合约面值（`size` 是 OKX 张数，XRP 的 `ctVal=100` ⇒ 差 100 倍），它会流进
    # `signal["size_usdt"]`，被选所层的 `min_notional` 闸门当成"最小名义额不足"
    # **误杀合格单**。现在路由层只看钱：原生数量只在场所边界出现一次。
    notional = float(notional_usdt or 0.0)
    if notional <= 0 and float(margin_usdt or 0.0) > 0 and float(leverage or 0.0) > 0:
        notional = float(margin_usdt) * float(leverage)
    if notional <= 0:
        print(f"[选所路由] warn {inst_id} 既无 notional_usdt 也无 margin×leverage，"
              f"名义额按不可判定处理（不再用 张数×价格 臆造）")
    margin_est = estimate_margin_usdt(notional, margin_usdt)

    venue = "okx"
    payload: Dict[str, Any] = {
        "preferred_venue": preferred,
        "venue": venue,
        "reason_code": "SINGLE_REGISTERED_VENUE",
        "reasons": [f"registered={sorted(VENUE_SUBMITTERS)}"],
        "rejected": [],
        "hysteresis_applied": False,
        "allocation": None,
        "decided_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    if preferred != "auto" and preferred != venue:
        # 手选锁定到一个不再登记/不再接单的场所：fail-closed，不偷偷改派 OKX
        reason = (f"手选场所 {preferred} 未登记下单实现"
                  f"（VENUE_SUBMITTERS 只有 {sorted(VENUE_SUBMITTERS)}）")
        payload["outcome"] = "rejected"
        payload["skip_reason"] = reason
        print(f"[选所路由] 本轮不下单 {inst_id}: {reason}")
        return {"ok": False, "error": f"路由拒绝: {reason}",
                "venue": None, "decision": payload, "reservation": None}

    payload["outcome"] = "selected"
    if venue not in VENUE_SUBMITTERS:
        # 登记表与下单实现不一致：fail-closed 不硬打端点
        reason = f"{venue} 未登记下单实现（VENUE_SUBMITTERS 只有 {sorted(VENUE_SUBMITTERS)}）"
        payload["executed_venue"] = None
        payload["skip_reason"] = reason
        print(f"[选所路由] 本轮不下单 {inst_id}: {reason}")
        return {"ok": False, "error": f"路由拒绝: {reason}",
                "venue": venue, "decision": payload, "reservation": None}

    budget_total = portfolio_risk_budget_usdt()
    try:
        mgr = reservation_manager()
        budget_used = mgr.gross_exposure(environment) if budget_total > 0 else 0.0
    except Exception as exc:
        mgr = None
        budget_used = 0.0
        print(f"[预算预留] warn 预留层不可用，本轮不下单（fail-closed）: {exc}")

    if mgr is None:
        return {"ok": False, "error": "预算预留拒绝: 预留层不可用（fail-closed 不下单）",
                "venue": venue, "decision": payload, "reservation": None}

    # 审计③(2026-09-13)：「组合风险总预算」此前名不副实——reserve 的 sqlite 上限按
    # (venue, env, fingerprint) 逐所求和，gross_exposure(environment) 跨所聚合只进证据
    # payload 不参与裁决，多所全开闸时 1000U 预算实际可占用 3000U。现把跨所合算补成
    # 真实总闸（各所子闸保留）。仅显式配置 budget>0 时生效（0=无顶语义不变）。
    # 幂等豁免：同 (account_key, intent) 重提不是新增占用（reserve 底层本就幂等），
    # 需从 gross_exposure 扣回该 intent 已占额，否则重试会被总闸误杀。
    intent = str(intent_id or f"{inst_id}:{side}:{int(time.time())}")
    account_key = (venue, environment, str(env.fingerprint))
    _prior_same_intent = 0.0
    if budget_total > 0:
        try:
            for _r in mgr.reservations(account_key):
                if str(_r.get("intent_id") or "") == intent:
                    _prior_same_intent = float(_r.get("amount_usdt") or 0.0)
                    break
        except Exception:
            pass
    _pb_err = portfolio_budget_guard(budget_total, budget_used - _prior_same_intent,
                                     margin_est, environment)
    if _pb_err:
        payload["budget"] = {"limit_usdt": budget_total,
                             "reserved_before_usdt": budget_used,
                             "gross_exposure_before_usdt": budget_used,
                             "margin_usdt": margin_est, "error": _pb_err}
        payload["outcome"] = "portfolio_budget_exceeded"
        payload["skip_reason"] = _pb_err
        print(f"[预算预留] 本轮不下单 {inst_id}: {_pb_err}")
        return {"ok": False, "error": _pb_err, "venue": venue,
                "decision": payload, "reservation": None}

    try:
        record = mgr.reserve(account_key, intent, margin_est, state="pending")
    except risk_reservation.ReservationExceeded as exc:
        payload["budget"] = {"limit_usdt": budget_total, "reserved_before_usdt": budget_used,
                             "margin_usdt": margin_est, "error": str(exc)}
        payload["outcome"] = "budget_rejected"
        payload["skip_reason"] = f"预算预留拒绝: {exc}"
        print(f"[预算预留] 本轮不下单 {inst_id}: {exc}")
        return {"ok": False, "error": f"预算预留拒绝: {exc}",
                "venue": venue, "decision": payload, "reservation": None}
    except Exception as exc:
        payload["budget"] = {"limit_usdt": budget_total, "margin_usdt": margin_est,
                             "error": str(exc)}
        payload["outcome"] = "budget_error"
        payload["skip_reason"] = f"预算预留拒绝: {exc}"
        print(f"[预算预留] 本轮不下单 {inst_id}: 预留层异常 {exc}")
        return {"ok": False, "error": f"预算预留拒绝: {exc}",
                "venue": venue, "decision": payload, "reservation": None}

    payload["budget"] = {"limit_usdt": budget_total, "account_key": list(account_key),
                         "intent_id": intent, "amount_usdt": margin_est,
                         "reserved_before_usdt": budget_used,
                         "state": record.get("state") if isinstance(record, dict) else None}
    print(f"[选所路由] {inst_id} → {venue}（{payload['reason_code']}"
          + (f"，手选优先 {preferred}" if preferred != "auto" else "")
          + f"；预留保证金估算 {margin_est}U）")
    return {"ok": True, "error": None, "venue": venue, "decision": payload,
            "reservation": {"manager": mgr, "account_key": account_key,
                            "intent_id": intent, "amount_usdt": margin_est}}

