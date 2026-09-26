"""
ASTRA 物理拦截插件规范
====================
id: 03_adx_volatility_filter
name: 1H ADX 趋势强度门禁
version: 1.0.0
author: ASTRA Official
description: 过滤无序震荡垃圾市。当 1H ADX < 18 时严禁开仓，杜绝在猴市横盘中过度交易损耗手续费。
tags: 震荡过滤, ADX, 官方预设
"""

def check_risk(package: dict, decision: dict, context: dict) -> tuple[bool, str]:
    action = str(decision.get("action", "WAIT")).upper()
    if action == "WAIT":
        return True, ""

    try:
        adx = float(package.get("adx_1h", 0) or 0)
    except (ValueError, TypeError):
        adx = 0.0

    if 0 < adx < 18.0:
        return False, f"1H ADX 趋势强度仅 {adx:.1f}，处于无序震荡杂波市，安全降级为 WAIT。"

    return True, ""
