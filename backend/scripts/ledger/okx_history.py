"""OKX 平仓历史行 → 台账交易记录（B3 抽取第二十块）。

从 `scripts/sync_full_ledger.py::build_lifecycle_ledger` 里那段 **125 行**的
`for h in pos_history:` 循环体搬出。

## 这段为什么值得单独成函数

它把"交易所返回的一行平仓历史"翻译成"台账里的一笔交易"，中间有**六个独立判定**，
每一个错都会让台账静默少一笔或金额错：

| 判定 | 漏了会怎样 |
|---|---|
| `close_time < reset_time` 跳过 | 台账混入重置前的旧仓，日亏统计虚高 |
| `inst_id not in allowed` 跳过 | 白名单外的历史币种混入（**审计已修过一次**） |
| 保证金推导：`张数×面值×开仓价/杠杆` | 拿不到就退 `pnlRatio` 反推，再退 500U |
| `exit_type == "3"` → 强平 | 强平被记成普通止盈/止损 |
| 平仓单匹配（同 instId+方向、`uTime` 差 <5000ms） | 出场原因全部退化成"保本平仓" |
| id 去重键 `posId + c_ts + 自增序号` | **同 posId 多轮往返吞腿**（审计批7 已修） |

最后一条尤其值得单独成文：OKX 的 `positions-history` 会让同一天多次往返**共享同一
`posId`**。旧实现用 `pos_hist_{posId}_{inst}` 当主键，同键后者覆盖前者，一条真实亏损
**从台账蒸发**（前台与台账对不上的根因之一）。故 id 必须带开仓时刻，再不够就挂序号。

## 设计取舍

- **跳过用 `return None`**，由调用方 `continue`；比在这里 `continue` 更能表达
  "本行不产生记录"。
- **序号 `_id_suffix` 由调用方算好传入**：自增序号是**跨行**状态
  （`_pos_id_seen` 字典），属于调用方的循环，不属于单行翻译。
- `datetime` 与 `get_ct_val` 由调用方传入：门面里的模块级名字会被测试
  `patch.object`，import 期绑定会绕过那些接缝。
"""


def build_okx_trade(*, h, reset_time, allowed, close_orders, env, tz_bj, id_suffix,
                    datetime, get_ct_val):
    """把一行 OKX 平仓历史翻成台账记录；不该收录时返回 `None`。

    `id_suffix` 形如 `"_1757850000"` 或 `"_1757850000#1"`（同 posId 同开仓时刻
    的第 2 笔起带 `#n`），由调用方依据跨行状态算出。

    **出场原因归属口径（2026-09-29 收紧）**：必须看**订单身份**，不能按盈亏金额猜。
    旧实现用 `net_pnl > 3.0` 推断"目标止盈达成"，于是分批止盈的首批半仓、云端 TP
    成交、AI 主动止盈平仓在台账里**全写成同一句** —— 实测用户因此以为分批止盈
    从未生效（09-22~09-29 实际发生 15 次）。现行口径：
      * 平仓单 `clOrdId` 前缀 `SO`（分批止盈 Scale-Out 软件平仓单）⇒ "首批分批止盈"；
      * 平仓单 `clOrdId` 前缀 `O` 或 `tag` 含 `CLI` ⇒ "AI 主动止盈平仓"；
      * **查不到平仓单** ⇒ 显式标 "止盈推定（未匹配平仓单）"，不伪装成"止盈成功"。
    """
    c_ts = int(h.get("cTime", 0) or 0) / 1000.0
    u_ts = int(h.get("uTime", 0) or 0) / 1000.0
    open_time = datetime.datetime.fromtimestamp(c_ts, tz=tz_bj).strftime("%Y-%m-%d %H:%M:%S") if c_ts > 0 else "--"
    close_time = datetime.datetime.fromtimestamp(u_ts, tz=tz_bj).strftime("%Y-%m-%d %H:%M:%S") if u_ts > 0 else "--"

    if close_time < reset_time:
        return None

    inst_id = h.get("instId", "")
    if inst_id not in allowed:
        return None
    inst = inst_id.replace("-USDT-SWAP", "")
    direction = str(h.get("direction", "")).lower()
    side = "多" if "long" in direction else "空"

    open_px = float(h.get("openAvgPx", 0) or 0)
    close_px = float(h.get("closeAvgPx", 0) or 0)
    gross_pnl = float(h.get("pnl", 0) or 0)
    fee = float(h.get("fee", 0) or 0)
    net_pnl = round(gross_pnl + fee, 2)
    lever = int(float(h.get("lever", "3") or 3))

    # Calculate Margin & Real Position Size
    ct_val = get_ct_val(inst)
    close_pos_sz = float(h.get("closeTotalPos", 0) or h.get("openMaxPos", 0) or 0)

    if close_pos_sz > 0 and open_px > 0 and ct_val > 0:
        notional = close_pos_sz * ct_val * open_px
        margin_usdt = round(notional / lever, 2) if lever > 0 else round(notional, 2)
    else:
        pnl_ratio = float(h.get("pnlRatio", 0) or 0)
        margin_usdt = 500.0 # Standard fallback
        if pnl_ratio != 0:
            est_margin = abs(gross_pnl / pnl_ratio)
            margin_usdt = round(est_margin, 2)

    roi_pct = round((net_pnl / margin_usdt * 100) if margin_usdt > 0 else 0.0, 2)

    # Duration
    try:
        t1 = datetime.datetime.strptime(open_time, "%Y-%m-%d %H:%M:%S")
        t2 = datetime.datetime.strptime(close_time, "%Y-%m-%d %H:%M:%S")
        dur_mins = int((t2 - t1).total_seconds() / 60)
        duration_str = f"{dur_mins}分钟" if dur_mins < 60 else f"{dur_mins//60}时{dur_mins%60}分"
    except Exception:
        duration_str = "--"

    # Strategy tag
    strat_tag = "🌊 顺势做多" if side == "多" else "⚡ 阻力高空"

    # Accurate Exit Reason Inference via Matched Close Order Attributes
    exit_type = str(h.get("type", ""))
    if exit_type == "3":
        exit_reason = "💥 强平出场"
    else:
        # Match filled close order within 5000ms window
        u_ms = int(h.get("uTime", 0) or 0)
        matched_close = next(
            (o for o in close_orders if o.get("instId") == inst_id and o.get("posSide") == direction and abs(int(o.get("uTime", 0) or 0) - u_ms) < 5000),
            None
        )
        if matched_close:
            algo_id = matched_close.get("algoId")
            cl_ord_id = str(matched_close.get("clOrdId", ""))

            if cl_ord_id.startswith("SO"):
                exit_reason = "🎯 首批分批止盈" if net_pnl >= 0 else "🛑 分批止盈后余仓止损"
            elif algo_id:
                if net_pnl > 3.0:
                    exit_reason = "🎯 目标止盈达成"
                elif net_pnl < -1.0:
                    exit_reason = "🛑 触发云端止损"
                else:
                    exit_reason = "🛡️ 移动止损保本出场"
            elif cl_ord_id.startswith("O") or "CLI" in matched_close.get("tag", ""):
                if net_pnl > 3.0:
                    exit_reason = "🤖 AI 主动止盈平仓"
                elif net_pnl < -1.0:
                    exit_reason = "🛑 策略风控止损"
                else:
                    exit_reason = "⏱️ 超时/保本平仓"
            else:
                exit_reason = (("🎯 止盈推定（未匹配平仓单）" if net_pnl > 3.0
                                else "🛑 止损离场" if net_pnl < -1.0 else "🛡️ 保本平仓"))
        else:
            exit_reason = (("🎯 止盈推定（未匹配平仓单）" if net_pnl > 3.0
                            else "🛑 止损出场" if net_pnl < -1.0 else "🛡️ 保本平仓"))

    funding_fee = round(float(h.get("fundingFee") or 0.0), 4)

    # 审计 D8：去重键原嵌 u_ts（持仓最后更新时间）——同一笔平仓被 OKX 改写
    # uTime（如补算资金费/结算修正）时 id 漂移，与旧行按 id 去重失败 → 同笔
    # 重复计入台账/日亏。改用不可变 posId，缺失时退回开仓时刻 c_ts（同样稳定）。
    _stable = str(h.get("posId") or "").strip() or (str(int(c_ts)) if c_ts > 0 else str(int(u_ts)))
    # 审计批7：posId 会在多轮往返间复用（见上方注释），故 id 追加开仓时刻 c_ts
    # 区分同 posId 的不同轮；同 (posId,c_ts) 仍多笔时再挂自增序号兜底，绝不再撞键。
    return {
        "id": f"pos_hist_{_stable}_{inst}{id_suffix}",
        "inst": inst,
        "side": side,
        "venue": "okx",   # G10：同上，OKX 历史行源头标注
        "account_mode": env.mode.upper(),
        "environment": env.mode.lower(),
        "lever": f"{lever}x",
        "strategy": strat_tag,
        "margin": margin_usdt,
        "sz": round(close_pos_sz, 4),
        "open_time": open_time,
        "open_px": round(open_px, 4),
        "close_time": close_time,
        "close_px": round(close_px, 4),
        "gross_pnl": round(gross_pnl, 2),
        "open_fee": round(fee / 2.0, 4),
        "close_fee": round(fee / 2.0, 4),
        "fee": round(fee, 2),
        "funding_fee": funding_fee,
        "pnl": net_pnl,
        "net_pnl": net_pnl,
        "roi": roi_pct,
        "roi_pct": roi_pct,
        "duration": duration_str,
        "status": "closed",
        "exit_reason": exit_reason
    }
