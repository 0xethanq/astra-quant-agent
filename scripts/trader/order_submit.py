"""受保护限价单提交（下单主路径）（B3 抽取·trader 瘦身第九刀，第八十八刀）。

从 `scripts/ai_factor_trader.py` **纯搬家** `submit_protected_limit_order`（198 行）。

## 这一刀为什么最敏感

它是唯一真正**落单**的函数：决策面前置闸（预算原子预留）→
US-007 环境维合约存在性对账 → 价格锚定 → **入场价穿价幻觉闸** → demo rescale
→ OKX 直签落地。审计④ 的"穿价幻觉拒单/回踩远挂放行"锚点全在本函数体内。

## 同名注入（11 项）

`route_and_reserve_signal` / `confirm_signal_reservation` /
`release_signal_reservation` / `record_open_intent` / `okx_rest` / `fetch_ticker` /
`venue_registry` / `canonical_base` / `current_environment` / `MAX_LEVERAGE` /
`MIN_LEVERAGE` 同名注入 ⇒ 函数体 AST **零例外全等**（`os` 由本模块自 import）。

⚠️ **源码锚点已同步**：`tests/audit/test_audit_batch2_risk_gates_live.py::
TestPriceSanityAnchor::test_guard_code_landed_in_submit_path` 原用
`inspect.getsource(aft)`（整门面）扫三段文本并检查**先后顺序**
（几何复验 < 穿价闸 < 入场闸门）——搬壳后门面里这三段一个都不在，
锚改为扫**该域**（`tests/source_scan.combined(..., pkg_name="trader")`），
并先断言实现确实住在 `order_submit.py`，顺序判据原样保留。
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple


def _shared_venue_entry_gate(*, venue: str, asset: str, action: str,
                             margin_unclamped: float, leverage: float,
                             confidence: float, current_environment) -> Tuple[bool, str]:
    """跑一遍**入场闸门**（同向敞口 / 持仓模式体检）。

    ## 这个函数在解决什么（2026-09-28 三所平权审计）

    入场闸门（跨所同向敞口 / 持仓模式体检）此前**只长在已移除的统一执行路由里**，
    而 OKX 直签路径（`okx_rest.place_order`，不经 router）**一个都没有**。于是出现
    最坏的一种不对称：

        **OKX 的仓占着跨所敞口上限，OKX 的下单却不查上限。**

    加重情节：提示词对主脑写「跨所同向敞口上限 … 超出执行层拒开」
    （`scripts/ai_brain_trader.build_risk_budget_lines`）—— 走到 OKX 时是**空头支票**。

    ## 判据单源，IO 在此

    判据全部在 `astra_backend/execution/venue_gate.py::venue_entry_gate`。

    ## 失败语义

    取不到闸门本身（import 失败、敞口核算异常）⇒ **拒单**（fail-closed）。
    "闸门没上线时放行"等于不设防，与本仓 P0 纪律相反。
    """
    target = str(venue or "").strip().lower()
    try:
        from astra_backend.execution import check_total_exposure as _check_exposure
        from astra_backend.execution.venue_gate import venue_entry_gate
        from astra_backend.exchanges.registry import get_adapter
    except Exception as exc:                                    # pragma: no cover
        return False, f"入场闸门不可用（fail-closed 拒单）: {exc}"

    env_name = str(getattr(current_environment(), "mode", "") or "") or None
    ad = None
    try:
        ad = get_adapter(target, environment=env_name)
    except Exception as exc:
        print(f"[入场闸门] warn {target.upper()} 适配器不可用，跳过持仓/模式探针: {exc}")

    caps = getattr(ad, "capabilities", None)
    declared = tuple(getattr(caps, "position_modes", ()) or ())
    ready = tuple(getattr(caps, "entry_ready_position_modes", ()) or ())
    probe = getattr(ad, "detect_position_mode", None)
    # 只在**真的实现了只读探测**时才体检：没探测器的适配器上
    # "声明了就体检、探测不到就拒"会把该所新开仓全部停掉。
    mode_checked = bool(declared and callable(probe))

    _cache: dict = {}

    def _position_mode() -> str:
        if "m" not in _cache:
            _cache["m"] = str(probe() or "unknown").strip().lower()
        return _cache["m"]

    # 同向敞口：上限为 0 ⇒ 闸门自身短路，**不产生任何网络调用**（既有契约）。
    cap = 0.0
    try:
        try:
            from scripts.risk_constants import MAX_TOTAL_EXPOSURE_USDT as _CAP
        except ImportError:                     # scripts/ 在 sys.path 上（双拼写铁律）
            from risk_constants import MAX_TOTAL_EXPOSURE_USDT as _CAP
        cap = float(_CAP or 0.0)
    except Exception:
        cap = 0.0

    exposure_fail = None
    if cap > 0:

        def _positions_reader():
            # 敞口核算只需**本所**（OKX）持仓：登记场所集已经收敛为 `{"okx"}`，
            # 逐腿照旧打 `venue` 标签供 `check_total_exposure` 归因。
            if ad is None:
                raise RuntimeError("OKX 适配器不可用，无法读取持仓核算敞口")
            return [dict(p, venue=target) for p in (ad.positions() or [])]

        def _fail_factory(stage, detail, **extra):
            return {"stage": stage, "detail": detail,
                    "venue": str(extra.pop("venue", target) or target), **extra}

        try:
            exposure_fail = _check_exposure(
                venue=target, asset=asset, action=action, margin=margin_unclamped,
                leverage=leverage, total_exposure_cap=cap, all_positions=None,
                positions_reader=_positions_reader, fail_factory=_fail_factory)
        except Exception as exc:
            return False, f"跨所敞口不可核算（fail-closed 拒单）: {exc}"

    try:
        rejection = venue_entry_gate(
            venue=target, asset=asset,
            exposure_fail=exposure_fail,
            position_mode=_position_mode,
            declared_modes=declared, entry_ready_modes=ready,
            mode_checked=mode_checked)
    except Exception as exc:
        return False, f"入场闸门执行失败（fail-closed 拒单）: {exc}"
    if rejection is None:
        return True, ""
    return False, f"{rejection.get('stage')}: {rejection.get('detail')}"


def submit_protected_limit_order(inst_id: str, side: str, pos_side: str, size: float, price: float, tp_px: float, sl_px: float, venue_ctx: Optional[Dict[str, Any]] = None,
    *,
    confirm_signal_reservation,
    record_open_intent,
    release_signal_reservation,
    route_and_reserve_signal,
    MAX_LEVERAGE,
    MIN_LEVERAGE,
    canonical_base,
    current_environment,
    fetch_ticker,
    okx_rest,
    quantize_size,
    venue_registry) -> Tuple[bool, str]:
    """Submit a protected limit order; acceptance is not treated as a fill.

    venue_ctx：US-003 决策面上下文（AI 信号入口单必须带）。带上下文 → 先过选所路由
    + 预算原子预留，任一失败返回 (False, "路由拒绝/预算预留拒绝: <reason>")，本轮
    不下单；不带上下文 = 非 AI 信号的通用提交（保留 US-007 listing gate 契约），
    只 warn 不闸门——新增开仓路径时必须传 ctx。
    """
    env = current_environment()  # 审计 C2：冻结周期环境单源（同 close 路径）
    _reservation = None
    target_venue = "okx"
    if isinstance(venue_ctx, dict):
        # 垃圾数值一律视同"没给"（不许抛）—— `venue_ctx` 可能来自缓存/回填，
        # 一个 "abc" 不该让整轮下单炸掉；缺失即由下游按 0 处理（不可判定）。
        def _ctx_num(_key):
            try:
                return float(venue_ctx.get(_key) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        # ---- US-003 决策面前置闸：选所路由 + 预算原子预留（失败即本轮不下单）----
        # 路由层只认**钱**（张数在此不参与任何推导，见 routing_policy 的说明）。
        _routing = route_and_reserve_signal(
            inst_id, side, price,
            notional_usdt=_ctx_num("notional_usdt"),
            margin_usdt=_ctx_num("margin_usdt"),
            intent_id=str(venue_ctx.get("intent_id") or ""),
            leverage=_ctx_num("leverage"))
        if not _routing["ok"]:
            return False, str(_routing.get("error") or "路由拒绝")
        _reservation = _routing.get("reservation")
        # 单所（OKX）系统：路由只可能选中 OKX（`VENUE_SUBMITTERS` 亦只有 OKX），
        # 落单场所恒为 OKX。
        target_venue = "okx"
        venue_ctx.setdefault("target_venue", target_venue)
        venue_ctx.setdefault("venue", target_venue)
    else:
        print(f"[US-003 决策面] warn {inst_id} 提交未携带 venue_ctx——"
              f"未经选所路由/预算预留，仅限非 AI 信号通用路径")

    # 环境维合约存在性对账（US-007）：目录拉不到 → fail-open 放行（对账是增强不是闸门）；
    # 已下架/未上市（如 SUI 在 demo 被下架）→ fail-closed 拒单，reason 透传。
    #
    # inst_id 是 OKX 形态（BTC-USDT-SWAP）；对账前先经 native_symbol_pure 翻译成
    # 目标所原生合约码（纯元数据，绝不实例化适配器→零出网）。
    try:
        from astra_backend.exchanges.listing import ensure_contract_listed
        native_contract = venue_registry.native_symbol_pure(
            canonical_base(inst_id), target_venue)
        _check = ensure_contract_listed(target_venue, "demo" if env.simulated else "live", native_contract)
        if not _check.ok:
            print(f"[listing gate] 拒绝下单 {inst_id}→{native_contract} ({target_venue}): {_check.reason}")
            release_signal_reservation(_reservation, "合约对账拒绝")
            return False, f"合约对账拒绝: {_check.reason}"
    except Exception as _le:
        print(f"[listing gate] warn 对账不可用，跳过（不阻塞）: {_le}")
    # Check if we are running in simulated/demo mode and price diverged significantly from demo orderbook
    effective_px = price
    effective_tp = tp_px
    effective_sl = sl_px

    # 审计④(2026-09-13)：现价单次读取，demo rescale 与幻觉锚共用——两次读可互相
    # 错位，且旧代码只有 simulated+okx 才取价，live/外所永远拿不到锚（裸奔真身）。
    _tick_last_raw = None
    _anchor_last = 0.0
    try:
        _tick_last_raw = (fetch_ticker(inst_id) or {}).get("last")
        if _tick_last_raw:
            _anchor_last = float(_tick_last_raw)
    except Exception as _ae:
        print(f"[价格锚定] warn 现价获取失败，本单跳过锚定/rescale: {_ae}")

    if env.simulated and target_venue == "okx":
        try:
            demo_last = _anchor_last
            if demo_last:
                if demo_last > 0 and price > 0:
                    divergence = abs(price - demo_last) / demo_last
                    # If live market price diverged from demo sandbox by more than 5% (e.g. ASTER / illiquid demo pair)
                    if divergence > 0.05:
                        scale = demo_last / price
                        prec = len(str(_tick_last_raw).split(".")[1]) if "." in str(_tick_last_raw) else 4
                        effective_px = round(price * scale, prec)
                        effective_tp = round(tp_px * scale, prec)
                        effective_sl = round(sl_px * scale, prec)
                        # Re-verify boundary constraints for demo sandbox
                        if pos_side == "long":
                            if effective_sl >= effective_px:
                                effective_sl = round(effective_px * 0.98, prec)
                            if effective_tp <= effective_px:
                                effective_tp = round(effective_px * 1.04, prec)
                        else:
                            if effective_sl <= effective_px:
                                effective_sl = round(effective_px * 1.02, prec)
                            if effective_tp >= effective_px:
                                effective_tp = round(effective_px * 0.96, prec)
        except Exception as _rsc_exc:
            # ⚠️ 第二百二十九刀：这里原来是**静默 `pass`** —— 沙盒报价重算一旦出 bug，
            # 交易照旧发出而**没有任何痕迹**（"算不出来 ≠ 没这回事"）。行为不变
            # （仍按原价/已算出的值提交、仍不阻断），但必须出声。
            print(f"[demo rescale] warn {inst_id} 沙盒报价重算失败，按当前值提交: {_rsc_exc}")

    # 委托订单模式（限价 / 市价）。**在此处读**而不是发单前才读：市价单必须先在
    # 这里按现价重锚保护价，才能进下面的几何复验与穿价闸。
    order_mode = str(os.getenv("ASTRA_ORDER_MODE", "limit")).strip().lower()

    # 市价单：真实成交价 = 下单一刻的现价，而 `effective_px/tp/sl` 是按**限价挂单
    # 计划**算的。若计划是回踩挂单位（做多、计划价明显低于现价），市价单会在现价
    # 成交而止盈价留在计划价上方不远处 ⇒ 止盈价低于真实成交价，做多的「止盈」
    # 变成亏损价并当场触发（开-秒平放血）。故先整体等比缩放到现价（保 R:R）。
    # 现价读不到 ⇒ **拒单**（fail-closed）：退回计划价继续下单正是要消除的形态。
    if order_mode == "market":
        from scripts.trader.brackets import reanchor_brackets_to_market
        _mk_prec = len(str(_tick_last_raw).split(".")[1]) if "." in str(_tick_last_raw) else 4
        _plan_tp, _plan_sl = effective_tp, effective_sl
        _anchored = reanchor_brackets_to_market(
            entry=effective_px, tp=effective_tp, sl=effective_sl,
            market=_anchor_last, is_long=(pos_side == "long"), prec=_mk_prec)
        if _anchored is None:
            _mk_rej = (f"市价单需按现价锚定保护价，但现价不可用"
                       f"（现价={_anchor_last:g}、计划价={effective_px:g}）")
            print(f"[市价锚定] 拒单 {inst_id}: {_mk_rej}")
            release_signal_reservation(_reservation, "市价锚定缺现价")
            return False, f"市价锚定拒绝: {_mk_rej}"
        effective_px, effective_tp, effective_sl = _anchored
        # ⚠️ 审计留痕：**上游拿不到这三个值**。`entry_execution.py` 组装的通知
        # （`entry_action_message`）用的是**计划价** TP/SL，与交易所实收的保护价不同；
        # 而 trader 子进程的 stdout 由 gateway 调度器 `capture_output=True` 只留末尾
        # 2000 字符 ⇒ 这行 print 不保证存活。故它只是**尽力留痕**，权威记录要靠
        # 「通知里的 TP/SL 是计划值」这一事实本身（已在 notifications 侧文档化）。
        print(f"[市价锚定] {inst_id} 现价={_anchor_last:g} "
              f"计划TP={_plan_tp:g}/SL={_plan_sl:g} → 实提TP={effective_tp:g}/SL={effective_sl:g}")

    # 通知复用：把**实际提交**的三价写回 `venue_ctx`（上游 `entry_execution.py`
    # 组装通知时读它）。市价档重锚后上游手里的 `limit_px/tp_px/sl_px` 已是**计划值**，
    # 与交易所实收不同 —— 2026-09 实测：ADA 空单通知写 TP=0.24/SL=0.2624，
    # 交易所实收 TP=0.2391/SL=0.2614（这笔只差 0.4%，因为计划价恰在现价附近）。
    # 计划价离现价越远偏差越大：计划是回踩挂单时，通知里的止损会落在**真实成交价的
    # 错误一侧**（多单计划 100000/现价 110000 ⇒ 通知说 SL=95000，实收却是 104500），
    # 看通知会误以为"止损已被击穿"。故这里无条件回写（限价档即原值，逐位不变）。
    # ── 止盈宽度平滑收窄 ────────────────────────────────────────────────────
    # 该夹取此前只长在已移除的统一执行路由里，OKX 直签路径没有 ⇒
    # 同一条 AI 决策被其它场所收窄、选中 OKX 却不会。现在 OKX 是唯一场所，
    # 夹取就在这里做一次（锚定后的 `effective_tp`），与实际发单方一致。
    try:
        from scripts.trader.brackets import clamp_take_profit_width
        _tp_prec = len(str(effective_px).split(".")[1]) if "." in str(effective_px) else 2
        _tp_atr = 0.0
        if isinstance(venue_ctx, dict):
            try:
                _tp_atr = float(venue_ctx.get("atr") or 0.0)
            except (TypeError, ValueError):
                _tp_atr = 0.0
        effective_tp = clamp_take_profit_width(
            is_long=(pos_side == "long"),
            limit_px=effective_px, sl_px=effective_sl, tp_px=effective_tp,
            atr=_tp_atr, prec=_tp_prec)
    except Exception as exc:      # 收窄失败不阻断下单
        print(f"[止盈宽度] warn {inst_id} 收窄失败，按原 TP 发送: {exc}")

    if isinstance(venue_ctx, dict):
        venue_ctx["submitted_px"] = effective_px
        venue_ctx["submitted_tp"] = effective_tp
        venue_ctx["submitted_sl"] = effective_sl

    # Final Non-Bypassable Verification: verify actual effective price, tp and sl
    from scripts.order_risk import validate_quote_geometry_and_rr
    action_type = "BUY_LONG" if pos_side == "long" else "SELL_SHORT"
    _ai_conf = float(venue_ctx.get("confidence", 0.0) or 0.0) if isinstance(venue_ctx, dict) else 0.0
    is_valid, reason, _ = validate_quote_geometry_and_rr(action_type, effective_px, effective_tp, effective_sl, confidence=_ai_conf)
    if not is_valid:
        print(f"[Order Rejected] 最终有效开仓报价未通过核心安全复验: {reason} (px={effective_px}, tp={effective_tp}, sl={effective_sl})")
        release_signal_reservation(_reservation, "核心安全复验拒绝")
        return False, f"最终订单核心安全复验拒绝: {reason}"

    # 审计④(2026-09-13)：LLM 幻觉入场价锚定——几何/R:R 只验 entry/tp/sl 相互关系，
    # 从不比对现价。危险形态是「穿价」：BUY 限价挂在现价上方 → 即时成交于意外价，
    # 而配套 SL 触发价锚在幻觉 entry 上、相对真实成交价可能即刻触发 → 开-秒平循环
    # 放血（demo+okx 有 5% rescale 兜底，live 此前裸奔）。回踩方向的远挂单
    # 是合法策略（不穿价即放行，OKX 侧 4 分钟超时撤兜底）。_anchor_last 来自上方
    # 单次读价；取价失败不阻断（行情断时黑天鹅哨兵/熔断已另行 fail-closed），但必吼。
    if _anchor_last > 0 and effective_px > 0:
        _cross_pct = float(os.getenv("ASTRA_MAX_PRICE_CROSS_PCT", "0.005") or 0.005)
        _far_pct = float(os.getenv("ASTRA_MAX_PRICE_FAR_PCT", "0.50") or 0.50)
        if action_type == "BUY_LONG" and effective_px > _anchor_last * (1.0 + _cross_pct):
            _rej = f"入场价穿价幻觉：BUY 限价 {effective_px:g} 高于现价 {_anchor_last:g} 超阈值({max(0.0,(effective_px/_anchor_last-1)*100):.2f}%>{_cross_pct*100:.1f}%)，将即时成交于意外价且 SL 锚点失真"
            print(f"[价格锚定] 拒单 {inst_id}: {_rej}")
            release_signal_reservation(_reservation, "价格锚定拒绝")
            return False, f"价格锚定拒绝: {_rej}"
        if action_type == "SELL_SHORT" and effective_px < _anchor_last * (1.0 - _cross_pct):
            _rej = f"入场价穿价幻觉：SELL 限价 {effective_px:g} 低于现价 {_anchor_last:g} 超阈值({max(0.0,(1-effective_px/_anchor_last)*100):.2f}%>{_cross_pct*100:.1f}%)，将即时成交于意外价且 SL 锚点失真"
            print(f"[价格锚定] 拒单 {inst_id}: {_rej}")
            release_signal_reservation(_reservation, "价格锚定拒绝")
            return False, f"价格锚定拒绝: {_rej}"
        if abs(effective_px - _anchor_last) / _anchor_last > _far_pct:
            _rej = f"入场价与现价距离 {abs(effective_px/_anchor_last-1)*100:.1f}% 超荒谬阈值 {_far_pct*100:.0f}%，判定为幻觉报价拒单"
            print(f"[价格锚定] 拒单 {inst_id}: {_rej}")
            release_signal_reservation(_reservation, "价格锚定拒绝")
            return False, f"价格锚定拒绝: {_rej}"

    # ── 入场闸门（同向敞口 / 持仓模式）────────────────────────────────────────
    # OKX 直签（`okx_rest.place_order`）不经过任何统一执行路由，必须在这里补跑，
    # 否则就会出现审计发现的那处不对称：**OKX 的仓占着敞口上限、OKX 的下单却不查上限**。
    # 判据本身在 `astra_backend/execution/venue_gate.py`，此处只备 IO。
    _gate_ok, _gate_why = _shared_venue_entry_gate(
        venue=target_venue,
        asset=canonical_base(inst_id),
        action=action_type,
        # 敞口闸门用**夹取前**的保证金
        margin_unclamped=(_ctx_num("margin_usdt") if isinstance(venue_ctx, dict) else 0.0),
        leverage=(_ctx_num("leverage") if isinstance(venue_ctx, dict) else 0.0),
        confidence=(_ctx_num("confidence") if isinstance(venue_ctx, dict) else 0.0),
        current_environment=current_environment)
    if not _gate_ok:
        print(f"[入场闸门] 拒单 {inst_id} ({target_venue.upper()}): {_gate_why}")
        if _reservation is not None:
            release_signal_reservation(_reservation, "入场闸门拒绝")
        return False, f"入场闸门拒绝: {_gate_why}"

    # 审计④5(2026-09-13)：OKX 直下路径从不落 AI 裁决杠杆——张数按 ai_lever 折算，
    # 但账户档位不变 → 实际保证金/强平价按旧档算，风险模型与实况脱节（净模式或
    # 10x 旧档可把 3x 计划仓的强平价拉得极近）。best-effort 发单前对齐档位：失败仅
    # warn 不阻断（保护腿/张数/几何已定，杠杆只影响保证金效率，绝不因此裸奔）。
    _want_lever = 0.0
    if isinstance(venue_ctx, dict):
        try:
            _want_lever = float(venue_ctx.get("leverage") or 0.0)
        except (TypeError, ValueError):
            _want_lever = 0.0
    if _want_lever > 0:
        _want_lever = max(1.0, min(_want_lever, float(MAX_LEVERAGE or 20.0)))
        try:
            okx_rest.set_leverage(inst_id, int(_want_lever), mgn_mode="cross",
                                  pos_side=(pos_side or None))
        except Exception as lev_exc:
            print(f"[杠杆落地] warn {inst_id} 设档至 {int(_want_lever)}x 失败，"
                  f"按账户现档发单（不影响 TP/SL 覆盖）: {lev_exc}")

    # `order_mode` 已在本函数前半段读过（市价重锚需要它）；此处只据它选单型与是否带价。
    ord_type = "market" if order_mode == "market" else "limit"
    entry_px = None if ord_type == "market" else effective_px

    # ── OKX 发单量：从**保证金**换算 ──────────────────────────────────────────
    # 2026-09-28（用户拍板「交易全改成保证金和杠杆」）。
    #
    # 此前 OKX 用的是调用方按【保证金闸门夹取**之前**】算出的张数，而闸门结果
    # `venue_ctx` 里的 margin_usdt 此前只被已移除的多所路径消费 ⇒ **同一把闸门对
    # OKX 形同虚设**：AI 计划额 / 权益占比 / 单标的封顶任一小于"张数隐含额"时，
    # OKX 却仍按夹取前的大张数下单。
    #
    # 现在 OKX 在场所边界从钱反推（`quote_qty_to_native` 的 OKX 等价式）：
    # **意图是钱，原生数量只在边界出现一次**。
    #
    # 等价性：闸门**未**夹取时 `margin == size_implied == size×ctVal×px/lever`，
    # 反推得到同一张数（逐位相同）；夹取时反推得到**更小**的张数 —— 那正是本修法
    # 的目的（见 `tests/trading/test_okx_margin_derived_size.py` 的网格对拍）。
    #
    # `venue_ctx` 缺失（非 AI 通用通路）时保留调用方给的张数：那条路径本就没有保证金。
    _okx_size_from_margin = None
    if isinstance(venue_ctx, dict):
        # 垃圾数值一律视同"没给"（与上方路由段同规则）：不抛，退回调用方给的张数。
        def _okx_num(_key):
            try:
                return float(venue_ctx.get(_key) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        _okx_m = _okx_num("margin_usdt")
        _okx_ct = _okx_num("ct_val")
        _okx_min = _okx_num("min_sz")
        _okx_lev = _okx_num("leverage")
        if _okx_m > 0 and _okx_ct > 0 and _okx_lev > 0 and effective_px > 0:
            _okx_want = (_okx_m * _okx_lev) / (_okx_ct * effective_px)
            _okx_size_from_margin = quantize_size(_okx_want, _okx_min or 1.0)
            if _okx_size_from_margin <= 0:
                _min_notional = (_okx_min or 1.0) * _okx_ct * effective_px
                release_signal_reservation(_reservation, "保证金换算张数低于最小下单量")
                return False, (f"{inst_id} 按保证金 {_okx_m:.2f}U × {_okx_lev:g}x 换算出的张数"
                               f"低于交易所最小下单量（最小下单名义 {_min_notional:.2f}U）"
                               f"—— 请提高单笔保证金或改用其他标的")
            size = _okx_size_from_margin

    try:
        rows = okx_rest.place_order(
            inst_id, side, f"{size:g}",
            pos_side=pos_side, td_mode="cross", ord_type=ord_type,
            px=entry_px, attach_tp=effective_tp, attach_sl=effective_sl,
        )
    except Exception as exc:
        release_signal_reservation(_reservation, "下单异常")
        return False, str(exc)
    order_id = None
    for row in rows:
        order_id = row.get("ordId") or row.get("orderId")
        if order_id:
            break
    if not order_id:
        release_signal_reservation(_reservation, "交易所未返回可核验订单号")
        return False, "exchange accepted response without a verifiable order id"
    record_open_intent(inst_id, side)
    confirm_signal_reservation(_reservation)
    return True, str(order_id)

