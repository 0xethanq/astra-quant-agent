"""
ASTRA 物理拦截插件规范
====================
id: 01_macro_trend_filter
name: 4H 宏观大周期顺势铁律
version: 1.0.0
author: ASTRA Official
description: 4H大级别多头通道下严禁逆势摸顶开空；4H大级别空头承压下严禁逆势抄底接飞刀 (Fail-Closed)。
tags: 趋势过滤, 核心风控, 官方预设
"""

def check_risk(package: dict, decision: dict, context: dict) -> tuple[bool, str]:
    """
    检查大级别趋势一致性：
    - 在 4H 多头通道中拦截 SELL_SHORT
    - 在 4H 空头承压中拦截 BUY_LONG
    """
    action = str(decision.get("action", "WAIT")).upper()
    if action == "WAIT":
        return True, ""

    macro_4h = str(package.get("macro_4h", "") or "")
    if action == "SELL_SHORT" and "4H_MACRO_BULL" in macro_4h:
        return False, "4H大级别处于多头主升通道，顺势铁律拦截逆势摸顶开空，安全降级为 WAIT。"
    if action == "BUY_LONG" and "4H_MACRO_BEAR" in macro_4h:
        return False, "4H大级别处于空头承压通道，顺势铁律拦截逆势接飞刀做多，安全降级为 WAIT。"

    return True, ""
