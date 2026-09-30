"""
ASTRA 物理拦截插件规范
====================
id: 01_macro_trend_filter
name: 4H 宏观大周期顺势铁律
version: 1.1.0
author: ASTRA Official
description: 4H大级别宏观顺势防单边踩踏。常规单严格顺应 4H 主浪方向；若出现 S 级多周期力竭/假突破反转证据且置信度 ≥ 85%，允许执行层弹性放行逆势反转与多空配对单。
tags: 趋势过滤, 核心风控, 官方预设
"""

def check_risk(package: dict, decision: dict, context: dict) -> tuple[bool, str]:
    """
    检查大级别趋势一致性：
    - 常规单严格顺应 4H 宏观方向
    - S 级反转形态（高置信度 + 微积分力竭/假突破/对冲）允许弹性放行，赋能模型波段见顶抓反转与多空配对交易
    """
    action = str(decision.get("action", "WAIT")).upper()
    if action == "WAIT":
        return True, ""

    macro_4h = str(package.get("macro_4h", "") or "")
    conf = float(decision.get("confidence", 0) or 0)
    calc = package.get("calculus", {}) or {}
    kinematic = str(calc.get("kinematic_regime") or "").upper()
    c_a = float(calc.get("acceleration") or calc.get("accel_1h") or 0.0)
    summary = str(decision.get("summary_reason") or "") + " " + str(decision.get("market_structure") or "")
    is_explicit_reversal = any(w in summary for w in ["反转", "诱多", "诱空", "背离", "见顶", "筑底", "力竭", "对冲", "Sweep", "sweep", "超跌", "REVERSAL", "COUNTER"])

    if action == "SELL_SHORT" and "4H_MACRO_BULL" in macro_4h:
        # 允许 S 级高置信度顶部反转/破位做空或跨品种配对对冲
        is_reversal = (
            conf >= 85.0 and is_explicit_reversal and (
                c_a <= -0.15
                or "REVERSING" in kinematic
                or "OVERSTRETCHED" in kinematic
            )
        )
        if is_reversal:
            return True, ""
        return False, "4H大级别处于多头主升通道，顺势铁律拦截逆势摸顶开空，安全降级为 WAIT。"

    if action == "BUY_LONG" and "4H_MACRO_BEAR" in macro_4h:
        # 允许 S 级高置信度底部超跌反抽/假跌破收回做多或跨品种配对对冲
        is_bottom = (
            conf >= 85.0 and is_explicit_reversal and (
                c_a >= 0.15
                or "REVERSING" in kinematic
                or "OVERSTRETCHED" in kinematic
            )
        )
        if is_bottom:
            return True, ""
        return False, "4H大级别处于空头承压通道，顺势铁律拦截逆势接飞刀做多，安全降级为 WAIT。"

    return True, ""
