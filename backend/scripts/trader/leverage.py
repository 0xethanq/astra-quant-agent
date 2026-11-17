"""AI 决策盘口的**杠杆夹取**（B3 抽取第十八块）。

从 `scripts/ai_factor_trader.py::execute_portfolio` 的 per-factor 循环里搬出。
原实现是一段约 18 行、含两处打印的内联逻辑。

## 这块为什么值得单独成函数

它是"AI 说 20x、实际只准开 5x"这条风控链的**唯一落点**。三件事按固定顺序发生：

1. **配置区间夹取**：把 AI 给的杠杆夹到风控页配置的 `[MIN_LEVERAGE, MAX_LEVERAGE]`。
   审计 P2-8 记录的缺陷是旧实现**只夹上限**，导致风控页设的下限在市场侧不成立。
2. **池内单标的收紧**：池条目带 per-instrument `max_leverage`（tier 派生 3x/5x），
   与全局上限**取更严者**。审计 P2-5 记录的缺陷是这个字段此前**无人读**。
3. **落档**：把最终值随开仓通知一并透传（旧实现曾恒写 `3`，5x 仓也通知「3x 杠杆」，
   属票圈谎报）。

顺序很重要：先夹配置区间、再用池值收紧。若反过来，一个低于 `MIN_LEVERAGE` 的
池值会绕过下限。

## 返回值

`(leverage, tightened)` —— `tightened` 表示是否被池内上限收紧，调用点据此打印
`[杠杆闸门]` 日志（日志文案留在门面，保持输出逐字不变）。
"""
from __future__ import annotations


def clamp_ai_leverage(ai_lever, *, min_leverage, max_leverage, inst_lever_cap):
    """把 AI 杠杆夹进配置区间，再用池内单标的上限收紧。

    逐字保留原实现的语义：

    - 下限：`min(max(ai_lever, float(MIN_LEVERAGE or 0.0) or 1.0), float(MAX_LEVERAGE or 20.0))`
      —— 注意 `MIN_LEVERAGE or 0.0` 后还有 `or 1.0`：**配置缺省或为 0 时兜底到 1x**，
      而不是 0x；`MAX_LEVERAGE` 缺省兜底到 20x。
    - `inst_lever_cap <= 0` 视为"无池内上限"，不收紧（原实现即如此）。
    - 池值收紧**不做下限保护** —— 若池值本身低于 `MIN_LEVERAGE`，结果就低于下限。
      这是原实现的行为（池文件是本地可信配置），此处**原样保留**，不擅自"修好"。

    参数全部入参，不在 import 期绑定风控常量 —— 门面会被
    `pin_baseline_risk_env()` 原地重载（`astra_backend/README.md` §5）。
    """
    lev = min(max(ai_lever, float(min_leverage or 0.0) or 1.0),
              float(max_leverage or 20.0))
    tightened = False
    if inst_lever_cap > 0 and lev > inst_lever_cap:
        lev = inst_lever_cap
        tightened = True
    return lev, tightened
