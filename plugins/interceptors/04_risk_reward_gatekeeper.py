"""
ASTRA 物理拦截插件规范
====================
id: 04_risk_reward_gatekeeper
name: 动态正期望与弹性盈亏比门禁
version: 2.0.0
author: ASTRA Official
description: 执行层真实风险收益比校验。结合入场点、止盈目标与云端止损线计算真实 R:R，并协同 AI 置信度进行动态数学期望评估，严守绝对底线，放行高胜率优质结构。
tags: 盈亏比, 动态数学期望, 赔率保障, 官方预设
"""

def check_risk(package: dict, decision: dict, context: dict) -> tuple[bool, str]:
    action = str(decision.get("action", "WAIT")).upper()
    if action == "WAIT":
        return True, ""

    try:
        entry = float(decision.get("entry_price", 0) or 0)
        tp = float(decision.get("take_profit_price", 0) or 0)
        sl = float(decision.get("stop_loss_price", 0) or 0)
    except (ValueError, TypeError):
        return False, "订单价格几何参数缺失或非浮点数，安全降级为 WAIT。"

    # 动态读取全局最低盈亏比门禁（单一事实源：scripts/risk_constants.py）
    try:
        from scripts.risk_constants import MIN_RISK_REWARD_RATIO
        min_rr = float(MIN_RISK_REWARD_RATIO)
    except Exception:
        try:
            import os
            min_rr = float(os.getenv("ASTRA_MIN_RISK_REWARD", "2.0"))
        except Exception:
            min_rr = 2.0

    rr = 0.0
    if action == "BUY_LONG" and entry > sl > 0 and tp > entry:
        rr = (tp - entry) / (entry - sl)
    elif action == "SELL_SHORT" and sl > entry > tp > 0:
        rr = (entry - tp) / (sl - entry)

    # 绝对系统安全底线：任何情况下盈亏比不得低于 1.2:1（防手续费与滑点倒挂）
    ABS_MIN_RR = 1.2
    if rr < ABS_MIN_RR:
        return False, f"模型报价盈亏比 {rr:.2f}R 低于系统绝对安全底线 {ABS_MIN_RR:.1f}R，执行层降级为 WAIT。"

    if rr < min_rr:
        try:
            conf = float(decision.get("confidence", 0) or 0)
        except (ValueError, TypeError):
            conf = 0.0

        p_win = conf / 100.0
        expected_r = p_win * rr - (1.0 - p_win) * 1.0
        if conf >= 80.0 and expected_r >= 0.30:
            return True, ""

        return False, f"模型报价盈亏比 {rr:.2f}R 未满足全局风控 {min_rr:.1f}R 门禁，执行层降级为 WAIT。"

    return True, ""
