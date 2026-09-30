"""
ASTRA 物理拦截插件规范
====================
id: 03_adx_volatility_filter
name: 1H ADX 趋势强度门禁
version: 1.1.0
author: ASTRA Official
description: 过滤无序单边突破伪信号。顺势突破单需 1H ADX ≥ 18 以防假突破；震荡箱体边缘低吸高抛与均值回归不受此限，避免误杀箱体获利机会。
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
        # 震荡箱体/均值回归/支撑阻力低吸高抛属于非单边策略，低 ADX 是常态，不应被趋势门禁误杀
        summary = str(decision.get("summary_reason", "") or "") + " " + str(decision.get("market_structure", "") or "")
        is_range_or_mean_reversion = any(
            kw in summary for kw in ["箱体", "震荡", "均值回归", "支撑", "阻力", "回踩", "RANGE", "Range", "sweep", "Sweep", "反转"]
        )
        conf = float(decision.get("confidence", 0) or 0)
        if is_range_or_mean_reversion and conf >= 80.0:
            return True, ""

        return False, f"1H ADX 趋势强度仅 {adx:.1f}，处于无序震荡杂波市，安全降级为 WAIT。"

    return True, ""
