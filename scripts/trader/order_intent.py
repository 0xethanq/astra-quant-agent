"""开仓意图的定价与下单载荷装配（B3 抽取第十五块）。

从 `scripts/ai_factor_trader.py::execute_portfolio` 的长/空两个 `if allow_entry:`
块里，把**完全同构**的前半段抽成两个函数。

## 抽出来的是哪两段

原来每个方向各写一遍：

1. **三价定价** —— 从 AI 决策里取 `entry_price` / `take_profit_price` /
   `stop_loss_price`，缺失则按盘口价与 `tp_dist` / `sl_dist` 兜底。
   方向差异只有两处：盘口用 `bidPx`（多）还是 `askPx`（空），
   以及兜底是 `±`（多）还是 `∓`（空）。
2. **下单载荷装配** —— 名义额、幂等 `intent_id`、以及传给
   `submit_protected_limit_order` 的 `venue_ctx`。方向差异只有三处：
   `"buy"/"sell"`、`"long"/"short"`、`BUY_LONG/SELL_SHORT` 意图标签。

## 刻意留在门面调用点的两行

    _order_margin = order_margin_gate(...)
    "max_margin_usdt": equity_margin_cap(usdt_available),

**这不是遗留，是有意设计。** 门面里有两条计数锚点
（`tests/audit/test_audit_config_p0_hardening.py`）专门数这两个名字在**门面文件里**的
出现次数，用来证明"开多/开空两条路径都经过了保证金闸门与权益顶"。
若把这两行搬进子包，门面就再也看不到它们，锚点要么翻红、要么（改成纯领域计数后）
失去"两条路径都在主路径上"这一层含义。

因此调用点仍以字面量形式写这两行，并把风控常量作为实参注入本模块 ——
既消掉了重复，又让锚点继续表达原意。
"""
from __future__ import annotations

import time


def resolve_entry_prices(*, is_long, ai_decision, f, prec, tp_dist, sl_dist):
    """按 AI 决策给定或盘口兜底，算出 `(limit_px, tp_px, sl_px)`。

    与搬走前的内联实现逐字一致：

    - `limit_px`：AI 的 `entry_price`（>0 时）否则 `bidPx`（多）/ `askPx`（空），
      再退回 `f["price"]`；
    - `tp_px`：AI 的 `take_profit_price`（>0 时）否则 `limit_px + tp_dist`（多）/
      `limit_px - tp_dist`（空）；
    - `sl_px`：AI 的 `stop_loss_price`（>0 时）否则 `limit_px - sl_dist`（多）/
      `limit_px + sl_dist`（空）。

    注意原实现里 `tp_px` / `sl_px` 在赋值前并不存在，兜底基准是 `limit_px` 本身；
    这里保持同样的求值顺序（先算 `limit_px`，再算另两价）。
    """
    limit_px = round(
        ai_decision.get("entry_price")
        if (ai_decision and ai_decision.get("entry_price", 0) > 0)
        else ((f.get("bidPx") if is_long else f.get("askPx")) or f["price"]),
        prec)
    tp_px = round(
        ai_decision.get("take_profit_price")
        if (ai_decision and ai_decision.get("take_profit_price", 0) > 0)
        else (limit_px + tp_dist if is_long else limit_px - tp_dist),
        prec)
    sl_px = round(
        ai_decision.get("stop_loss_price")
        if (ai_decision and ai_decision.get("stop_loss_price", 0) > 0)
        else (limit_px - sl_dist if is_long else limit_px + sl_dist),
        prec)
    return limit_px, tp_px, sl_px


def build_order_intent(*, is_long, inst_id, actual_sz, ct_val, min_sz, limit_px, ai_lever,
                       max_margin_usdt, margin_usdt, inst_lever_cap, ai_conf,
                       ai_info):
    """装配 `submit_protected_limit_order` 的方向参数与 `venue_ctx`。

    返回 `(side, pos_side, venue_ctx)`。`size` / `price` / `tp` / `sl` 由调用点直接
    传给下单函数，不在这里再包一层 —— 那只会把 4 个纯搬运参数搬来搬去。

    `margin_usdt`（保证金闸门结果）与 `max_margin_usdt`（权益顶）由调用点算好传入，
    见模块 docstring：那两行**必须留在门面**，是计数锚点的载体。

    ⚠️ 2026-09-28 口径统一（用户拍板「交易全改成保证金和杠杆」）：
    `notional_usdt` 改为 **保证金 × 杠杆**（钱），不再由张数乘面值反推。
    旧式 `actual_sz × ct_val × limit_px` 用的是**保证金闸门夹取之前**的张数 ——
    闸门一旦夹取（AI 计划额 / 权益占比 / 单标的封顶任一更小），这个名义额就被高估，
    而真正下的单按闸门后的保证金走 ⇒ 账实不符。
    `ct_val` / `min_sz` 随 `venue_ctx` 下传，供场所边界做**唯一一次**「钱 → 张」换算。
    """
    side = "buy" if is_long else "sell"
    pos_side = "long" if is_long else "short"
    venue_ctx = {
        "notional_usdt": round(float(margin_usdt or 0.0) * float(ai_lever or 0.0), 2),
        "margin_usdt": margin_usdt,
        "max_margin_usdt": max_margin_usdt,
        "leverage": ai_lever,
        # 审计 P2-5：池内单标的杠杆上限一并透传（router 取更严者）
        "max_leverage": inst_lever_cap,
        # 审计 P1-7：per-venue min_confidence 闸门需要原始置信度（决策载荷里本没有）
        "confidence": ai_conf,
        # 场所边界换算「保证金 → 原生数量」所需的合约规格（OKX 直签链用池子口径；
        # 币安/Gate 在 router 里取**该所自己的** spec，不读这里）。
        "ct_val": ct_val,
        "min_sz": min_sz,
        "intent_id": (f"{inst_id}:BUY_LONG" if is_long else f"{inst_id}:SELL_SHORT")
                     + f":{int(ai_info.get('timestamp') or time.time())}",
    }
    return side, pos_side, venue_ctx
