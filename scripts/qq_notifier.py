"""Professional notification publisher bridging durable ASTRA Gateway events across channels."""
from __future__ import annotations
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from astra_gateway.publisher import publish


def _publish(event_type: str, title: str, message: str, payload: dict | None = None, priority: int = 50) -> bool:
    try:
        publish(event_type, title, message, payload=payload, priority=priority)
        return True
    except Exception:
        return False


def _format_symbol(inst: str, venue: str = "okx") -> str:
    """Intelligently format symbol according to exchange conventions without hardcoding -SWAP."""
    raw = str(inst or "").strip()
    if not raw:
        return "UNKNOWN-SWAP"
    clean = raw.replace("-USDT-SWAP", "").replace("-USDT", "").replace("USDT", "").replace("_USDT", "").upper()
    v = str(venue or "okx").lower()
    if "binance" in v:
        return f"{clean}USDT 永续"
    elif "gate" in v:
        return f"{clean}_USDT 永续"
    return f"{clean}-USDT-SWAP"


def send_qq_message(text: str) -> bool:
    """Compatibility symbol: true means durably queued, not synchronously delivered."""
    return _publish("notification.generic", "📢 【系统状态通知】", text, priority=50)


def notify_trade_open(
    inst: str,
    side: str,
    sz: int | float,
    px: float,
    strategy: str,
    reason: str,
    tp_px: float | None = None,
    sl_px: float | None = None,
    leverage: int = 3,
    *,
    tp1_px: float | None = None,
    scale_out_ratio: float = 0.50,
    venue: str = "okx",
    margin_usdt: float | None = None,
    notional_usdt: float | None = None,
    rr_ratio: float | str | None = None,
    confidence: float | None = None,
    market_regime: str | None = None,
    council_role: str | None = None,
    policy_version: str | None = None,
    **kwargs: Any,
) -> bool:
    """Triggered when an order is placed and accepted by exchange gateway with OCO & scale-out protection."""
    is_long = "多" in side or "BUY" in side.upper()
    direction_emoji = "🟢 多单 BUY" if is_long else "🔴 空单 SELL"
    symbol_str = _format_symbol(inst, venue)
    venue_name = str(venue or "OKX").upper()

    header_lines = [
        f"🏢 执行交易所：{venue_name}",
        f"⚡ 交易标的：{symbol_str}",
    ]
    if policy_version:
        header_lines.append(f"🏷️ 策略版本：{policy_version}")
    elif strategy:
        header_lines.append(f"🎯 触发策略：{strategy}")

    if market_regime:
        header_lines.append(f"🌐 宏观体制：{market_regime}")
    if council_role or confidence is not None:
        c_parts = []
        if council_role:
            c_parts.append(f"{council_role}提案")
        if confidence is not None:
            c_parts.append(f"置信度 {confidence:.1f}%")
        header_lines.append(f"👥 投委会协同：{' · '.join(c_parts)}")

    # Position & Execution details
    pos_details = [f"{direction_emoji}（{sz} 张 | {leverage}x 杠杆）"]
    if margin_usdt and margin_usdt > 0:
        pos_details.append(f"保证金 {margin_usdt:.2f} U")
    elif sz and px > 0:
        # Auto estimate margin if not provided
        est_notional = float(sz) * px
        pos_details.append(f"预估保证金 ~{est_notional / max(1, leverage):.2f} U")

    if notional_usdt and notional_usdt > 0:
        pos_details.append(f"货值 ~{notional_usdt:.1f} U")

    exec_lines = [
        f"🧭 决策方向：{' | '.join(pos_details)}",
        f"💵 挂单入场：{px}",
    ]

    # Auto deduce geometric risk-reward ratio if not provided
    if rr_ratio is None and tp_px and sl_px and px > 0:
        if is_long and px > sl_px:
            rr_ratio = round((tp_px - px) / (px - sl_px), 2)
        elif not is_long and sl_px > px:
            rr_ratio = round((px - tp_px) / (sl_px - px), 2)

    if rr_ratio:
        rr_str = f"{rr_ratio:.2f} R" if isinstance(rr_ratio, (int, float)) else str(rr_ratio)
        exec_lines.append(f"🎯 几何盈亏比：{rr_str}")

    # Auto calculate Scale-Out Take-Profit TP1 if not explicitly passed
    if (tp1_px is None or tp1_px <= 0) and tp_px and sl_px and px > 0:
        if is_long and tp_px > px and px > sl_px:
            tp_span = tp_px - px
            sl_span = px - sl_px
            step = min(tp_span * 0.52, sl_span * 1.20)
            tp1_px = round(px + step, 4 if px < 10 else (2 if px < 1000 else 1))
        elif not is_long and px > tp_px and sl_px > px:
            tp_span = px - tp_px
            sl_span = sl_px - px
            step = min(tp_span * 0.52, sl_span * 1.20)
            tp1_px = round(px - step, 4 if px < 10 else (2 if px < 1000 else 1))

    # Protective Brackets & Scale-Out (TP1 + TP2)
    bracket_lines = []
    if sl_px and sl_px > 0 and px > 0:
        sl_pct = abs(px - sl_px) / px * 100
        bracket_lines.append(f"  🔴 云端硬止损 (SL)：{sl_px} (-{sl_pct:.2f}%)")

    if tp1_px and tp1_px > 0 and px > 0:
        tp1_pct = abs(tp1_px - px) / px * 100
        pct_label = int(scale_out_ratio * 100) if scale_out_ratio else 50
        bracket_lines.append(f"  🥇 首批止盈 (TP1 · {pct_label}%仓位)：{tp1_px} (+{tp1_pct:.2f}%)")
        bracket_lines.append(f"     └─ 🎯 达标动作：市价平仓{pct_label}%锁定收益，剩余仓位自动保本移损锁死胜率！")

    if tp_px and tp_px > 0 and px > 0:
        tp_pct = abs(tp_px - px) / px * 100
        if tp1_px:
            bracket_lines.append(f"  🚀 终极波段 (TP2 · 剩余仓位)：{tp_px} (+{tp_pct:.2f}%)")
            bracket_lines.append("     └─ 🎯 达标动作：零风险放飞，全速追逐大趋势大波段！")
        else:
            bracket_lines.append(f"  🎯 目标止盈 (TP)：{tp_px} (+{tp_pct:.2f}%)")

    msg_parts = header_lines + exec_lines
    if bracket_lines:
        msg_parts.append("🛡️ 攻防梯位与双轨止盈规划：\n" + "\n".join(bracket_lines))
    if reason:
        msg_parts.append(f"💡 决策归因：{reason}")

    message = "\n".join(msg_parts)
    title_venue = f"[{venue_name}] " if venue_name != "OKX" else ""
    return _publish(
        "trade.opened",
        f"🚀 【实盘开仓提醒】{title_venue}{inst} {direction_emoji}",
        message,
        {
            "instrument": inst,
            "venue": venue,
            "side": side,
            "size": sz,
            "price": px,
            "strategy": strategy,
            "tp": tp_px,
            "tp1": tp1_px,
            "sl": sl_px,
            "leverage": leverage,
            "margin_usdt": margin_usdt,
            "rr_ratio": rr_ratio,
        },
        priority=90,
    )


def notify_trade_close(
    inst: str,
    pnl: float,
    stage: str,
    exit_px: float,
    roi_pct: float | None = None,
    duration_str: str | None = None,
    *,
    side: str | None = None,
    entry_px: float | None = None,
    fee: float | None = None,
    net_pnl: float | None = None,
    venue: str = "okx",
    is_partial: bool = False,
    **kwargs: Any,
) -> bool:
    """Triggered upon position exit, profit lock, stop loss, or partial scale-out."""
    venue_name = str(venue or "OKX").upper()
    symbol_str = _format_symbol(inst, venue)
    is_partial_exit = is_partial or "分批" in stage or "首批" in stage

    # Calculate net pnl if fee is provided
    effective_net = net_pnl if net_pnl is not None else (pnl - fee if fee is not None else pnl)
    is_win = effective_net > 0
    is_be = abs(effective_net) < 0.05 or "保本" in stage

    if is_partial_exit:
        status_tag = "🎉 【阶梯止盈 TP1 达成】"
        roi_str = f" (+{roi_pct:.2f}%)" if roi_pct is not None else ""
        pnl_text = f"+{effective_net:.4f} USDT{roi_str} (首批 50% 利润落袋)"
    elif is_be:
        status_tag = "⚖️ 【保本结清】"
        pnl_text = f"±0.00 USDT (保本移损退出，杜绝亏损)"
    elif is_win:
        status_tag = "🎉 【盈利落袋】"
        roi_str = f" (+{roi_pct:.2f}%)" if roi_pct is not None else ""
        pnl_text = f"+{effective_net:.4f} USDT{roi_str}"
    else:
        status_tag = "🛡️ 【风控止损】"
        roi_str = f" ({roi_pct:.2f}%)" if roi_pct is not None else ""
        pnl_text = f"{effective_net:.4f} USDT{roi_str}"

    msg_lines = [
        f"🏢 执行交易所：{venue_name}",
        f"⚡ 交易标的：{symbol_str}",
    ]
    if side:
        side_label = "🟢 多单" if ("多" in side or "long" in str(side).lower()) else "🔴 空单"
        msg_lines.append(f"🧭 持仓方向：{side_label}")

    msg_lines.append(f"📌 平仓类型：{stage}")

    # Price comparison
    if entry_px and entry_px > 0:
        msg_lines.append(f"🏁 退出价格：{exit_px} (开仓均价: {entry_px})")
    else:
        msg_lines.append(f"🏁 退出价格：{exit_px}")

    # PnL breakdown
    if fee is not None and fee > 0:
        msg_lines.append(f"💰 到手净利：{pnl_text} (毛利: {pnl:+.4f} U | 交易手续费: -{fee:.4f} U)")
    else:
        msg_lines.append(f"💰 结算收益：{pnl_text}")

    if duration_str:
        msg_lines.append(f"⏱️ 持仓时长：{duration_str}")

    if is_partial_exit:
        msg_lines.append("🛡️ 后续风控：剩余 50% 仓位已自动收紧至保本止损位，本单胜率下限完全锁死，开启零风险放飞！")

    message = "\n".join(msg_lines)
    title_venue = f"[{venue_name}] " if venue_name != "OKX" else ""
    return _publish(
        "trade.closed",
        f"{status_tag} {title_venue}{inst} 盈亏: {effective_net:+.2f} U",
        message,
        {
            "instrument": inst,
            "venue": venue,
            "pnl": effective_net,
            "gross_pnl": pnl,
            "fee": fee,
            "stage": stage,
            "exit_price": exit_px,
            "entry_price": entry_px,
            "is_partial": is_partial_exit,
        },
        priority=95,
    )


def notify_sl_updated(
    inst: str,
    side: str,
    old_sl: float,
    new_sl: float,
    reason: str = "浮盈达标，启动保本移损锁死胜率",
    *,
    venue: str = "okx",
    cur_px: float | None = None,
    profit_pct: float | None = None,
    **kwargs: Any,
) -> bool:
    """Triggered when SL is moved to Breakeven or trailed higher."""
    venue_name = str(venue or "OKX").upper()
    symbol_str = _format_symbol(inst, venue)
    side_label = "🟢 多单" if ("多" in side or "long" in str(side).lower()) else "🔴 空单"

    lines = [
        f"🏢 执行交易所：{venue_name}",
        f"⚡ 交易标的：{symbol_str}",
        f"🧭 持仓方向：{side_label}",
    ]
    if cur_px and cur_px > 0:
        pct_str = f" (+{profit_pct:.2f}%)" if profit_pct is not None else ""
        lines.append(f"📈 当前市价：{cur_px}{pct_str}")

    lines.extend([
        f"🛡️ 止损上移：{old_sl} ➔ {new_sl}（保本防线）",
        f"🔒 策略意图：{reason}",
        "✨ 状态变更：【🔒 零风险保护中】该笔交易已彻底杜绝亏损风险！",
    ])

    message = "\n".join(lines)
    title_venue = f"[{venue_name}] " if venue_name != "OKX" else ""
    return _publish(
        "trade.sl_updated",
        f"🛡️ 【保本锁利移损】{title_venue}{inst}",
        message,
        {"instrument": inst, "venue": venue, "side": side, "old_sl": old_sl, "new_sl": new_sl},
        priority=85,
    )


def notify_interceptor_blocked(
    inst: str,
    action: str,
    interceptor_name: str,
    reason: str,
    venue: str = "okx",
) -> bool:
    """Triggered when fail-closed physical interceptor cuts off an impulsive AI order."""
    venue_name = str(venue or "OKX").upper()
    symbol_str = _format_symbol(inst, venue)
    action_label = "🟢 追多" if "LONG" in action.upper() else "🔴 追空"

    message = (
        f"🏢 目标交易所：{venue_name}\n"
        f"⚡ 交易标的：{symbol_str}\n"
        f"🤖 模型提案：{action_label}（已被底座物理切断）\n"
        f"🛑 拦截门禁：{interceptor_name}\n"
        f"📋 拦截原因：{reason}\n"
        f"🔒 底座防线：Fail-Closed 强制降级观望，严守风控纪律，拒绝冲动交易。"
    )
    return _publish(
        "risk.interceptor_blocked",
        f"🛡️ 【物理硬风控拦截】{inst} {action_label}提案已切断",
        message,
        {"instrument": inst, "action": action, "interceptor": interceptor_name, "reason": reason},
        priority=70,
    )


def notify_circuit_breaker(macro_event: str, reason: str) -> bool:
    """Triggered when market wide circuit breaker or risk defense triggers."""
    message = (
        f"⚠️ 预警等级：CRITICAL 宏观异动\n"
        f"🌐 触发事件：{macro_event}\n"
        f"🛑 熔断动作：全自动暂停新开仓，开启全闭环防守\n"
        f"📋 详细成因：{reason}\n"
        f"🛡️ 风控状态：全所现有在管仓位已启动最高级别紧密跟踪防线。"
    )
    return _publish(
        "risk.triggered",
        "🚨 【黑天鹅避险熔断预警】",
        message,
        {"event": macro_event, "reason": reason},
        priority=100,
    )


def notify_daily_summary(summary_text: str) -> bool:
    """Triggered for morning/evening executive reports."""
    return _publish("briefing.ready", "📊 【每日量化执行与资产简报】", summary_text, priority=40)


def notify_evolution_report(winrate: float, total_trades: int, summary: str, top_lesson: str) -> bool:
    """Triggered after self-improvement cycle finishes daily cognitive post-mortem."""
    message = (
        f"🧬 复盘样本：最近 {total_trades} 笔实盘平仓 | 样本胜率: {winrate}%\n"
        f"📈 演进方向：{summary}\n"
        f"💡 提炼心法：{top_lesson}\n"
        f"🛡️ 记忆管理：黄金交易心法已自动同步沉淀至长期推演记忆。"
    )
    return _publish(
        "evolution.completed",
        f"🧬 【AI 大脑自进化完成】胜率 {winrate}%",
        message,
        {"winrate": winrate, "total_trades": total_trades},
        priority=60,
    )
