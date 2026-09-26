"""
ASTRA 物理拦截插件规范（策略广场官方示例模板）
=============================================
id: 99_custom_template_sample
name: 策略广场示例模板：动能背离与资金流拦截
version: 1.0.0
author: ASTRA Community / Plaza Template
description: 官方自定义风控插件示例模板。演示如何基于微积分加速度 a、累积能量 E 与聪明钱资金流编写专有物理拦截规则。
tags: 示例模板, 策略广场, 自定义开发
"""

def check_risk(package: dict, decision: dict, context: dict) -> tuple[bool, str]:
    """
    【策略广场开发者指南】
    你可以根据自己的量化逻辑自由扩展物理拦截规则！
    
    可用输入数据包括：
    1. package: 标的原生与衍生动能数据:
       - package['name']: 币种名称 (如 'BTC')
       - package['macro_4h']: 4H 宏观结构 ('4H_MACRO_BULL' / '4H_MACRO_BEAR' / '4H_MACRO_RANGE')
       - package['velocity_v']: 一阶对数价格速度 v
       - package['acceleration_a']: 二阶对数价格加速度 a (a < -0.25 通常表示动能严重失速)
       - package['jerk_j']: 三阶对数价格加加速度 j (剧烈冲击)
       - package['adx_1h']: 1小时趋势强度 ADX
       - package['smart_money']: 聪明钱多空比与净流入 (usdt)
       - package['last']: 现价
    
    2. decision: AI主脑初步建议:
       - decision['action']: 'BUY_LONG' / 'SELL_SHORT' / 'WAIT'
       - decision['confidence']: 置信度 (0 ~ 100)
       - decision['entry_price'], decision['take_profit_price'], decision['stop_loss_price']
       - decision['leverage'], decision['margin_usdt']
    
    3. context: 全局系统上下文:
       - context['active_inst_ids']: 当前持仓标的代码列表
       - context['usdt_available']: 当前账户可用资金
    
    返回值规范:
    - 返回 (True, "") 表示放行；
    - 返回 (False, "具体的拦截原因描述") 表示拦截该笔订单，系统将自动重写为 WAIT 并记录风控审计。
    """
    action = str(decision.get("action", "WAIT")).upper()
    if action == "WAIT":
        return True, ""

    # 示例规则 1: 动能严重失速时禁止做多
    try:
        acc = float(package.get("acceleration_a", 0) or 0)
        if action == "BUY_LONG" and acc < -0.6:
            return False, f"多头买入但二阶加速度 a={acc:.3f} 严重失速衰竭，广场示例插件拦截"
    except Exception:
        pass

    # 示例规则 2: 聪明钱大额逆向净流出时警示
    smart_money = package.get("smart_money", {})
    if isinstance(smart_money, dict):
        try:
            net_flow = float(smart_money.get("net_flow_usdt", 0) or 0)
            if action == "BUY_LONG" and net_flow < -10_000_000:
                return False, f"多头买入但聪明钱净流出 {net_flow/1e4:.1f}万 U，资金面严重背离，广场示例插件拦截"
        except Exception:
            pass

    return True, ""
