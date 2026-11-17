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
from pathlib import Path
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


def _size_precision_of(step: float) -> int:
    s = f"{step:.8f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


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
    # ⚠️ 单位纪律：`ctVal`/`minSz`/尺寸精度优先取**持仓记录**上挂的值
    # （`curr_pos`），缺失时才回落 `f[...]`（OKX 合约池口径）⇒ OKX 路径逐位不变。
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
    # 用户 2026-09-28 拍板：OKX 的"张"是合约单位，且**各币种的合约面值算法都不一样**
    # ⇒ 张数不能跨币种比，交易员无法从它判断"这笔占了我多少钱"。张数仍用于
    # **切分计算**本身（必须），但绝不进入文案。
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

    # 1b. 交易所侧 TP1 腿**已成交**的识别（2026-09-29 双腿方案）。
    #     双腿方案下首批止盈由交易所瞬时执行，本引擎的职责从"平仓"变成"收尾"：
    #     发现持仓张数掉到 `建仓张数 ×(1−比例)` 及以下 ⇒ 腿已成交，
    #     于是**不再市价平仓**，只做保本移损 + 台账 + 通知（各一次）。
    #     旧 tracker 没有 `entry_sz` ⇒ 本轮只补记、不判定（避免把"早已分批过"
    #     的历史持仓误判成刚成交）。
    px_prec = int(f.get("precision", 2) or 2)
    ratio = max(0.1, min(0.9, float(SCALE_OUT_RATIO or 0.50)))
    try:
        entry_sz = float(t.get("entry_sz") or 0.0)
    except (TypeError, ValueError):
        entry_sz = 0.0
    if entry_sz <= 0:
        t["entry_sz"] = pos_sz
    else:
        expected_remaining = entry_sz * (1.0 - ratio)
        # 容差：腿的尺寸按 minSz 向下夹取，实际成交可能比理论值略小。
        if pos_sz <= expected_remaining + max(min_sz * 0.5, entry_sz * 0.001):
            return _finalize_scale_out_after_leg_fill(
                t, curr_pos=curr_pos, inst_id=inst_id, name=name, is_long=is_long,
                pos_side=pos_side, entry_px=entry_px, cur_px=cur_px, pos_sz=pos_sz,
                entry_sz=entry_sz, ratio=ratio, px_prec=px_prec,
                timestamp_full=timestamp_full, executed_actions=executed_actions,
                record_trade=record_trade, notify_trade_close=notify_trade_close,
                close_fee=close_fee, close_trade_payload=close_trade_payload,
                TAKER_FEE_RATE=TAKER_FEE_RATE,
                ensure_cloud_position_protection=ensure_cloud_position_protection,
                okx_rest=okx_rest,
                ct_val=ct_val,
                min_sz=min_sz,
            )

    # 2. 计算首批止盈目标价位（TP1）——**冻结**（已有值就用已有值）。
    #    旧实现每轮用当轮 ATR 重算并覆盖，导致"交易所挂着的 TP1"与"软件判定的
    #    TP1"随 ATR 漂移而分叉；双腿方案要求两者逐位相同。详见 `tp1.py`。
    from scripts.trader.tp1 import freeze_tp1, format_trigger_text
    tp1_px = freeze_tp1(t, entry_px=entry_px, atr=f.get("atr", 0.0), is_long=is_long,
                        prec=px_prec, multiple=float(SCALE_OUT_TRIGGER_ATR or 1.20))
    trigger_threshold = abs(tp1_px - entry_px)

    # 3. 浮盈判定
    cur_profit_px = (cur_px - entry_px) if is_long else (entry_px - cur_px)
    if cur_profit_px < trigger_threshold:
        current_desc = str(t.get("stage_desc") or "")
        if not current_desc or "监控中" in current_desc or "TP1" in current_desc:
            gain_pct = abs(tp1_px - entry_px) / entry_px * 100 if entry_px > 0 else 0.0
            t["stage_desc"] = (f"持有中 (首批止盈目标 TP1: {tp1_px:g} · +{gain_pct:.1f}% · "
                               f"达标平{ratio*100:.0f}%保本)")
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

    # `ratio` 已在上方（TP1 冻结段）解析，此处直接复用，避免同一函数两处口径。
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
            # clOrdId 前缀 `SO`（Scale-Out）：台账侧据此把"首批分批止盈"与
            # "AI 主动止盈平仓"分开 —— 旧实现只能按盈亏多少 `net_pnl>3.0` **猜**原因，
            # 于是分批止盈在台账里一直显示成"目标止盈达成"（用户看不出它发生过）。
            _so_clordid = f"SO{int(time.time())}"
            res = okx_rest.place_order(
                inst_id,
                close_side,
                f"{close_sz:g}",
                pos_side=pos_side,
                td_mode="cross",
                ord_type="market",
                reduce_only=True,
                cl_ord_id=_so_clordid,
            )
            order_success = True
            order_detail = str(res)
        except Exception as exc:
            order_success = False
            order_detail = f"OKX分批平仓异常: {exc}"
    else:
        # 已移除场所的历史持仓：instId 与 OKX 同名，绝不能把它的
        # instId 交给 OKX 直签接口（平的是别人的仓）。只读留痕跳过，不抛异常、不平仓。
        executed_actions.append(
            f"[{name}] 非 OKX 场所({pos_venue})历史持仓，只读跳过分批止盈（不下发任何交易所指令）")
        return False, f"非 OKX 场所({pos_venue})，只读跳过"

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

    # 门槛文案用**百分比**（旧写法 `+{:.2f}` 对 ARB 这类低价标的恒显示 +0.00，人看不懂）。
    msg_action = (f"[{name}] 🎯 达到首批止盈门槛({format_trigger_text(trigger_threshold, entry_px)})，已市价平仓 "
                  f"{ratio*100:.0f}% (保证金 {_margin_of(close_sz):.2f}U)，锁定盈利 "
                  f"+{realized_pnl:.2f}U；余仓保证金 ~{_margin_of(remaining_sz):.2f}U "
                  f"推进至保本位 {breakeven_sl}")
    executed_actions.append(msg_action)

    _append_scale_out_event({
        "ts": timestamp_full, "instId": inst_id, "name": name,
        "side": "long" if is_long else "short", "mode": "software",
        "ratio": ratio, "entry_sz": float(t.get("entry_sz") or pos_sz),
        "close_sz": close_sz, "remaining_sz": remaining_sz,
        "entry_px": entry_px, "exit_px": cur_px, "tp1_px": tp1_px,
        "realized_pnl": round(realized_pnl, 4), "fee": round(fee_val, 4),
        "breakeven_sl": breakeven_sl, "venue": pos_venue,
    })

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

    # ⚠️ 2026-09-30（通知单一事实源）：这里**不再**发布 `trade.closed`。
    #     同一笔分批止盈此前会被**两条独立路径**各发一张卡片：本路径（现场估算，
    #     且不带手续费/ROI/时长）与台账同步路径（OKX 成交流水口径，带手续费、ROI、
    #     时长）。实测同一天同一笔出现两条互相矛盾的数字（SUI +28.32 对 +18.11、
    #     DOGE −35.73 对 −37.71、XRP −30.73 对 −32.63），用户据此认定"数据不对"。
    #     现在 **只有台账路径**（`sync_full_ledger` → `ledger/notify.py`）发布金额类
    #     通知 —— 它是唯一握有交易所真实成交价与手续费的口径；本路径的即时信息
    #     仍通过 `executed_actions` 动作行与追踪器 `stage_desc` 呈现（用户立刻看得到），
    #     只是不再声称金额。`notify_trade_close` 参数保留以维持注入面（不再调用）。
    _ = notify_trade_close

    return True, "首批分批平仓成功"


#: 事件流水落点（模块常量：**唯一**，便于用例 patch 到临时目录）。
#: ⚠️ 真实事故（2026-09-29 本轮）：写成函数内局部路径时，用例无法重定向 ——
#: 跑一遍测试就往**生产** `data/scale_out_events.jsonl` 里灌进一批夹具行
#: （`entry_px: 80000 / exit_px: 82000` 这种一眼假的记录），流水失去可信度。
#: 落成常量后，`patch.object(scale_out, "SCALE_OUT_EVENTS_FILE", tmp)` 即可隔离。
SCALE_OUT_EVENTS_FILE = Path(__file__).resolve().parents[2] / "data" / "scale_out_events.jsonl"
#: 生产落点快照（**不随 patch 变化**）：测试防御要拿它比对，否则"patch 到临时目录"
#: 会被自己判成"仍在写生产"而拒绝。
_PRODUCTION_EVENTS_FILE = SCALE_OUT_EVENTS_FILE


def _append_scale_out_event(record: Dict[str, Any]) -> bool:
    """把分批止盈事件追加到 `SCALE_OUT_EVENTS_FILE`（只追加，永不重写）。

    为什么单独留一份流水：台账只记"整笔持仓的最终结果"，2026-09-29 实测用户在
    后台看到的是"目标止盈达成"，**看不出分批发生过**（ARB 那笔前半 +17.09U、
    余仓保本 +0.00U，被汇总成一行 +21.57U）。这份流水是"分批止盈是否生效"的
    第一手证据，也是 `/metrics` 的计数来源。

    ⚠️ **测试防御**：这份文件已被登记进 `tests/__init__.py` 的写保护名单
    （`_PROTECTED_CONFIG_FILES`）—— 用例里若没把 `SCALE_OUT_EVENTS_FILE` patch 到
    临时目录，`open(..., "a")` 会被测试守卫拦下，日志里留下一行"写入失败"，
    而**生产流水一个字节都不会动**。本模块不读任何测试专用环境变量（那会把
    测试的旋钮塞进生产代码，且 `tests/audit/test_env_keys_are_documented.py`
    要求每个被读取的键都能在 `env.example` 里找到）。
    """
    try:
        import json as _json
        path = Path(SCALE_OUT_EVENTS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(_json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception as exc:                      # 观测失败绝不影响钱路
        print(f"[Scale-Out] 事件流水写入失败（不影响交易）: {exc}")
        return False


def _finalize_scale_out_after_leg_fill(
    t: Dict[str, Any], *, curr_pos: Dict[str, Any], inst_id: str, name: str, is_long: bool,
    pos_side: str, entry_px: float, cur_px: float, pos_sz: float, entry_sz: float,
    ratio: float, px_prec: int, timestamp_full: str, executed_actions: List[str],
    record_trade, notify_trade_close, close_fee, close_trade_payload,
    TAKER_FEE_RATE: float, ensure_cloud_position_protection, okx_rest,
    ct_val: float, min_sz: float = 0.01,
) -> Tuple[bool, str]:
    """交易所侧 TP1 腿**已成交**后的收尾（不再市价平仓）。

    与"软件市价平仓"的差别只有一个：成交已经发生，本函数不碰仓位，
    只做**保本移损 + 余仓保护 + 状态机 + 台账 + 通知 + 流水**。

    ⚠️ `ct_val` 必须由**调用方**传入（它已按"持仓级覆盖 > 合约池"的口径算好）。
    本函数**不得**再从 `curr_pos` 自取面值：2026-09-30 真机事故的根因就是这里
    写了 `curr_pos.get("ctVal") or 1.0` —— OKX 持仓记录里**根本没有** `ctVal`
    （见 `factors.py` 的 `"ctVal": float(p["ctVal"]) if p.get("ctVal") else None`），
    于是面值静默退化成 1：ETH（面值 0.1）盈亏与手续费被**放大 10×**
    （+24.33U 报成 +243.28U、手续费 1.02U 报成 10.24U），ARB（面值 10）
    则被**缩小 10×**（+17.10U 报成 1.84U）。同一 `_cv` 还把"余仓保证金"
    文案写成 ETH ~2273.85U（真值 ~228U）、ARB ~15.32U（真值 ~151U）。
    """
    tp1_px = float(t.get("scale_out_tp") or 0.0)
    # 尺寸精度按 min_sz 派生，绝不用价格精度 px_prec（BTC tickSz=0.1 精度为 1，会把 0.015 张抹成 0）
    sz_prec = _size_precision_of(min_sz)
    close_sz = round(entry_sz * ratio, sz_prec)
    if min_sz > 0:
        close_sz = math.floor(close_sz / min_sz + 1e-9) * min_sz
        close_sz = round(close_sz, sz_prec)
    if close_sz <= 0:
        close_sz = max(entry_sz - pos_sz, 0.0)
        close_sz = round(close_sz, sz_prec)
    _cv = float(ct_val or 0.0)
    if _cv <= 0:
        # 读不到 ≠ 没有：不静默用 1.0 假装正确，先吼一声再按 1.0 兜底继续。
        # 状态机（保本移损/余仓保护）必须照做 —— 上报口径的问题不得让钱路停摆。
        print(f"[Scale-Out] warn {name} 合约面值不可判定（持仓与合约池都没有 ctVal）"
              f" ⇒ 金额口径按 1.0 兜底，上报数字可能失真")
        _cv = 1.0
    _lever = float(curr_pos.get("lever", curr_pos.get("leverage", 0.0)) or 0.0) or 1.0
    # 腿的成交价用 TP1 触发价近似（真实成交价由 OKX 匹配引擎决定，差异在 tick 级）。
    exit_px = tp1_px if tp1_px > 0 else cur_px
    realized_pnl = close_sz * _cv * ((exit_px - entry_px) if is_long else (entry_px - exit_px))
    fee_val = (close_fee(close_sz, _cv, exit_px, TAKER_FEE_RATE) if close_fee
               else close_sz * _cv * exit_px * TAKER_FEE_RATE)

    breakeven_cushion = 0.0025 * entry_px
    breakeven_sl = round((entry_px + breakeven_cushion) if is_long else (entry_px - breakeven_cushion), px_prec)
    take_profit_px = float(t.get("takeProfitPx", 0.0) or 0.0)
    if ensure_cloud_position_protection and take_profit_px > 0:
        try:
            ensure_cloud_position_protection(inst_id, pos_side, pos_sz, take_profit_px, breakeven_sl)
        except Exception as exc:
            print(f"[Scale-Out] 腿成交后云端保护更新异常: {exc}")

    # 余仓止损同步：若交易所仍挂着已建立的余仓保护单，将止损触发价同步推进至保本位
    if okx_rest:
        try:
            from scripts.trader.cloud_protection import sync_cloud_algo_stop
            sync_cloud_algo_stop(inst_id, pos_side, breakeven_sl, reason="首批止盈后余仓移损保本", okx_rest=okx_rest)
        except Exception as sync_exc:
            print(f"[Scale-Out] 腿成交后余仓云端保本止损修改异常: {sync_exc}")

    t["scale_out_phase"] = 1
    t["scale_out_tp"] = None
    t["currentSz"] = pos_sz
    t["trailingStopPx"] = breakeven_sl
    t["scale_count"] = 999
    t["stage_desc"] = (f"已分批止盈{ratio*100:.0f}% (交易所侧腿成交 · 余仓保证金 "
                       f"~{round(pos_sz * _cv * cur_px / _lever, 2)}U · 保本止损 {breakeven_sl})")

    msg = (f"[{name}] 🎯 首批止盈腿已在交易所成交（{ratio*100:.0f}% · 约 "
           f"{close_sz:g} 张），锁定盈利 +{realized_pnl:.2f}U；"
           f"余仓保本止损推进至 {breakeven_sl}")
    executed_actions.append(msg)

    _append_scale_out_event({
        "ts": timestamp_full, "instId": inst_id, "name": name,
        "side": "long" if is_long else "short", "mode": "exchange_leg",
        "ratio": ratio, "entry_sz": entry_sz, "close_sz": close_sz, "remaining_sz": pos_sz,
        "entry_px": entry_px, "exit_px": exit_px, "tp1_px": tp1_px,
        "realized_pnl": round(realized_pnl, 4), "fee": round(fee_val, 4),
        "breakeven_sl": breakeven_sl, "venue": "okx",
    })

    if record_trade and close_trade_payload:
        record_trade(close_trade_payload(
            is_long=is_long,
            timestamp_full=timestamp_full,
            name=name,
            action_type="分批止盈",
            side_suffix="首批平仓（交易所侧腿）",
            pos_sz=close_sz,
            cur_px=exit_px,
            fee=fee_val,
            pnl=realized_pnl,
            remark=(f"TP1={tp1_px:g} 由交易所侧算法腿瞬时成交（非 15 分钟巡检平仓），"
                    f"余仓保本止损 {breakeven_sl}"),
        ))

    # ⚠️ 2026-09-30（通知单一事实源）：这里**不再**发布 `trade.closed`。
    #     这是本轮真机事故的现场：本路径用 `tp1_px` 近似成交价、且**当时面值取错**
    #     （ETH 报 +243.28U / 手续费 10.24U，真值 +24.33U / 1.02U），而台账路径
    #     稍后（≤1 分钟）会用 OKX 真实成交价发一条正确卡片 ⇒ 用户同时收到两条、
    #     数字差 10×。金额类通知一律由台账路径发布；本路径的"腿已成交 + 保本移损"
    #     信息由上面的 `executed_actions` 动作行与追踪器 `stage_desc` 承载。
    _ = notify_trade_close

    return True, "首批止盈腿已成交，收尾完成"
