"""选所路由与组合预算政策（B3 抽取·trader 瘦身第八刀，第八十七刀）。

从 `scripts/ai_factor_trader.py` **纯搬家**八函数（219 行）：

| 函数 | 行数 | 职责 |
|---|---|---|
| `load_routing_mode` | 7 | 路由模式（auto/锁定所）读取 |
| `load_preferred_venue` | 7 | 手选锁定所读取 |
| `portfolio_risk_budget_usdt` | 5 | 组合风险预算（env `ASTRA_PORTFOLIO_RISK_BUDGET_USDT`，0=不限） |
| `estimate_margin_usdt` | 6 | 名义额 → 保证金估算 |
| `_decision_payload` | 12 | 决策载荷取值（含缺省合并） |
| `_rejection_focus_reason` | 19 | 拒单焦点原因提取（日志/通知用） |
| `portfolio_budget_guard` | 17 | 跨所合算总闸（纯函数，0=不限，fail-closed） |
| `route_and_reserve_signal` | 146 | 信号路由 + 预留落账主流程 |

## 同名注入（沿第八十二～八十六刀，本刀最宽：14 项）

⇒ 函数体 AST **零例外全等**。三个模块对象（`risk_reservation` / `venue_router` /
`routing_policy`）按**同一对象**注入；`VENUE_SUBMITTERS` 只读（成员判定）。

⚠️ **源码锚点已同步**：`tests/audit/test_audit_batch2_risk_gates_live.py::
test_route_and_reserve_wires_guard` 用 `inspect.getsource(门面函数)` 断言
"路由必须调用 `portfolio_budget_guard(`"（活线化防漂移锚）。搬壳后门面只剩转发，
该锚改用 `tests/source_scan.find_function_node`（**优先实现体**）并加反证
（门面壳文本不得出现该调用）—— 意图不变、防虚 Hits（§97.2 家族）。
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple


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



def _decision_payload(decision, preferred: str) -> Dict[str, Any]:
    """RouteDecision → 决策 JSON 的 venue_decision 段（纯附加字段）。"""
    return {
        "preferred_venue": preferred,
        "venue": decision.venue,
        "reason_code": decision.reason_code,
        "reasons": list(decision.reasons or []),
        "rejected": [dict(r) for r in (decision.rejected or [])],
        "hysteresis_applied": bool(decision.hysteresis_applied),
        "allocation": decision.allocation,
        "decided_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }



def _rejection_focus_reason(decision, candidates: List[Dict[str, Any]],
                            preferred: str) -> str:
    """ALL_REJECTED 时挑「最该解释本次跳过」的那条淘汰理由。

    优先级：手选场所 > 现任所（本链路直签所）> 首个候选 > 第一条记录；同一场所若
    有多阶段淘汰，取非 executable 的第一条（listing/precision/freshness 才是真因，
    未开闸只是结构性事实）。
    """
    wanted = [preferred] if preferred != "auto" else []
    wanted += [str(c.get("venue")) for c in candidates if c.get("current_venue")]
    wanted += [str(c.get("venue")) for c in candidates]
    rows = list(decision.rejected or [])
    for venue in wanted:
        same = [r for r in rows if str(r.get("venue")) == venue]
        if not same:
            continue
        substantive = [r for r in same if r.get("stage") != "executable"]
        return str((substantive or same)[0].get("reason") or "")
    return str((rows[0] if rows else {}).get("reason") or "无候选所")



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
                              _decision_payload,
                              _rejection_focus_reason,
                              build_venue_candidates,
                              estimate_margin_usdt,
                              load_preferred_venue,
                              load_routing_mode,
                              persist_venue_decision,
                              portfolio_budget_guard,
                              portfolio_risk_budget_usdt,
                              reservation_manager,
                              VENUE_SUBMITTERS,
                              current_environment,
                              risk_reservation,
                              venue_router) -> Dict[str, Any]:
    """选所路由 → 执行面接线校验 → 预算原子预留（US-003 决策面前置闸）。

    返回 {"ok": bool, "error": str|None, "venue": str|None, "decision": dict,
          "reservation": dict|None}；任何一步不过 → ok=False，调用方本轮不下单。
    """
    env = current_environment()
    environment = str(env.mode)
    preferred = load_preferred_venue()
    # 名义额（**钱**口径，与场所无关）：优先执行层算好的 `notional_usdt`；缺失时按
    # `margin × leverage` 反推 —— 这两者都是钱，任何场所都成立。
    #
    # ⚠️ 2026-09-28：本函数**已不再接收张数**。旧兜底是 `max(0.0, size * price)`，
    # 漏乘合约面值（`size` 是 OKX 张数，XRP 的 `ctVal=100` ⇒ 差 100 倍），它会流进
    # `signal["size_usdt"]`，被 `venue_routing/selection.py` 的 `min_notional` 闸门
    # 当成"最小名义额不足"**误杀合格单**。现在路由层只看钱：
    # 原生数量只在场所边界（`execution_router` / `okx_rest.place_order`）出现一次。
    notional = float(notional_usdt or 0.0)
    if notional <= 0 and float(margin_usdt or 0.0) > 0 and float(leverage or 0.0) > 0:
        notional = float(margin_usdt) * float(leverage)
    if notional <= 0:
        print(f"[选所路由] warn {inst_id} 既无 notional_usdt 也无 margin×leverage，"
              f"名义额按不可判定处理（不再用 张数×价格 臆造）")
    margin_est = estimate_margin_usdt(notional, margin_usdt)
    signal = {
        "inst_id": inst_id,
        "symbol_canonical": str(inst_id).split("-")[0].upper(),
        "side": "long" if str(side).lower() in ("buy", "long") else "short",
        "size_usdt": notional,
        "price": float(price or 0.0),
    }
    candidates = build_venue_candidates(inst_id, environment)

    if preferred != "auto":
        # 手动选所优先：只让该所参与评估（直取该所），但**仍过 route_signal**，
        # 以便 executable/listing 的 rejected 证据照常落盘（可解释不因为手选而失效）。
        candidates = [c for c in candidates if str(c.get("venue")) == preferred]
        if not candidates:
            print(f"[选所路由] warn 手选场所 {preferred} 未在 registry 登记，按不可执行候选处理")
            candidates = [{
                "venue": preferred,
                "environment": environment,
                "executable": False,
                "health_updated_utc": None,
                "current_venue": False,
            }]

    budget_total = portfolio_risk_budget_usdt()
    try:
        mgr = reservation_manager()
        budget_used = mgr.gross_exposure(environment) if budget_total > 0 else 0.0
    except Exception as exc:
        mgr = None
        budget_used = 0.0
        print(f"[预算预留] warn 预留层不可用，本轮不下单（fail-closed）: {exc}")

    # 预算硬筛**不在路由层重复执行**：路由只负责选所，预算占用由 risk_reservation
    # 的原子 reserve 单点裁决（口径=保证金，与 notional 混用会双重误杀）。路由层的
    # budget_view 预筛等 US-004 名义额口径统一后再启用，这里显式传 None。
    r_mode = load_routing_mode()
    cfg = venue_router.RouterConfig(
        routing_mode=r_mode,
        # 模式 C：生成跨所拆单方案进决策证据；执行面按现任中选所单笔落地，
        # 逐片真实分发等 US-004 名义额口径统一（allocation 已随证据落盘）
        split_enabled=(r_mode == "split"))
    decision = venue_router.route_signal(signal, candidates, budget_view=None, config=cfg)
    payload = _decision_payload(decision, preferred)

    if decision.venue is None or decision.reason_code in ("ALL_REJECTED", "NO_CANDIDATES"):
        reason = _rejection_focus_reason(decision, candidates, preferred)
        payload["outcome"] = "rejected"
        payload["skip_reason"] = f"{decision.reason_code}: {reason}"
        persist_venue_decision(inst_id, payload)
        print(f"[选所路由] 本轮不下单 {inst_id}: {decision.reason_code} → {reason}")
        return {"ok": False, "error": f"路由拒绝: {reason}",
                "venue": None, "decision": payload, "reservation": None}

    venue = str(decision.venue)
    payload["outcome"] = "selected"
    if venue not in VENUE_SUBMITTERS:
        # 路由可选中未来所，但下单实现只在登记后存在——fail-closed 不硬打 OKX 端点
        reason = f"{venue} 未登记下单实现（VENUE_SUBMITTERS 只有 {sorted(VENUE_SUBMITTERS)}）"
        payload["executed_venue"] = None
        payload["skip_reason"] = reason
        persist_venue_decision(inst_id, payload)
        print(f"[选所路由] 本轮不下单 {inst_id}: {reason}")
        return {"ok": False, "error": f"路由拒绝: {reason}",
                "venue": venue, "decision": payload, "reservation": None}

    if mgr is None:
        persist_venue_decision(inst_id, payload)
        return {"ok": False, "error": "预算预留拒绝: 预留层不可用（fail-closed 不下单）",
                "venue": venue, "decision": payload, "reservation": None}

    # 审计③(2026-09-13)：「组合风险总预算」此前名不副实——reserve 的 sqlite 上限按
    # (venue, env, fingerprint) 逐所求和，gross_exposure(environment) 跨所聚合只进证据
    # payload 不参与裁决，三所全开闸时 1000U 预算实际可占用 3000U。现把跨所合算补成
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
        persist_venue_decision(inst_id, payload)
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
        persist_venue_decision(inst_id, payload)
        print(f"[预算预留] 本轮不下单 {inst_id}: {exc}")
        return {"ok": False, "error": f"预算预留拒绝: {exc}",
                "venue": venue, "decision": payload, "reservation": None}
    except Exception as exc:
        payload["budget"] = {"limit_usdt": budget_total, "margin_usdt": margin_est,
                             "error": str(exc)}
        payload["outcome"] = "budget_error"
        payload["skip_reason"] = f"预算预留拒绝: {exc}"
        persist_venue_decision(inst_id, payload)
        print(f"[预算预留] 本轮不下单 {inst_id}: 预留层异常 {exc}")
        return {"ok": False, "error": f"预算预留拒绝: {exc}",
                "venue": venue, "decision": payload, "reservation": None}

    payload["budget"] = {"limit_usdt": budget_total, "account_key": list(account_key),
                         "intent_id": intent, "amount_usdt": margin_est,
                         "reserved_before_usdt": budget_used,
                         "state": record.get("state") if isinstance(record, dict) else None}
    persist_venue_decision(inst_id, payload)
    print(f"[选所路由] {inst_id} → {venue}（{decision.reason_code}"
          + (f"，手选优先 {preferred}" if preferred != "auto" else "")
          + f"；预留保证金估算 {margin_est}U）")
    return {"ok": True, "error": None, "venue": venue, "decision": payload,
            "reservation": {"manager": mgr, "account_key": account_key,
                            "intent_id": intent, "amount_usdt": margin_est}}

