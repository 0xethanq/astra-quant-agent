"""单笔保证金闸门与 TradFi 交易时段判定（B3 抽取第十一块）。

从 `scripts/ai_factor_trader.py` 搬出三个**纯函数**：

| 函数 | 行数 | 作用 |
|---|---|---|
| `order_margin_gate` | 32 | OKX 下单保证金闸门 |
| `equity_margin_cap` | 7 | 权益占比硬顶 |
| `is_tradfi_market_liquid` | 20 | 美股常规交易时段（BJ 21:30 ~ 次日 04:00） |

## 为什么这三个可以搬

它们**只依赖风控常量**，不读 `order_margin_gate` 之外的任何模块状态。门面保留同名壳、
在**调用期**把常量传进来 —— 理由同 `prompt.py`：`risk_constants` 的 .env 改参由门面
重载刷新，子模块 import 期绑定会变成过期快照。

`is_tradfi_market_liquid` 的时间依赖是 `datetime`（标准库、非状态），直接 import。

## 门面侧的锚点为什么不受影响

`tests/audit/test_audit_config_p0_hardening.py:186` 是一条**计数锚点**：

    source.count("order_margin_gate(") == 3   # 1 定义 + 开多 + 开空

它数的是**门面单文件**里的出现次数。三个函数搬走后：
- 门面仍保留 **1 个同名壳**（`def order_margin_gate(...)` 那行）；
- 两条调用点都在 `execute_portfolio` 里，**本来就没动**。
所以计数仍是 3，锚点无需修改 —— 前提是门面壳的**函数名与括号**保持原样，
不要写成 `order_margin_gate = _order_margin_gate_impl` 这种别名赋值
（那会让计数掉到 2，锚点翻红，而这是**正确**的告警：说明调用路径被改写了）。
"""
import datetime




def order_margin_gate(planned_margin: float, *, size: float, price: float, ct_val: float,
                      leverage: float, usdt_available: float,
                      max_single_asset_margin=None, max_margin_equity_ratio=None) -> float:
    """OKX 下单保证金闸门。

    审计 P0-1(2026-09-13)：下单路径若不引用 `risk_constants`，OKX 路径那套
    「可用余额占比硬顶 / 单标的绝对封顶 / 已夹张数隐含额」就会全部失效
    （配置硬顶 20%、单标的绝对封顶 600U 形同虚设）。

    生效口径 = min(AI 计划额, 执行层已夹张数隐含保证金, 权益×占比, 单标的绝对封顶)。
    权益不可得（缺失≠0）时不臆造占比上限，但仍受绝对封顶与张数隐含额约束。
    """
    # 注入项解析：门面显式传；为兼容按 AST 抽取本函数体的隔离调用，None 时回退
    # 到 globals() 的同名值（不要写默认值常量 —— 那会固化成 import 期快照）。
    if max_single_asset_margin is None or max_margin_equity_ratio is None:
        _g = globals()
        if max_single_asset_margin is None:
            max_single_asset_margin = _g["MAX_SINGLE_ASSET_MARGIN"]
        if max_margin_equity_ratio is None:
            max_margin_equity_ratio = _g["MAX_MARGIN_EQUITY_RATIO"]
    lev = max(1.0, float(leverage or 1.0))
    try:
        size_implied = max(0.0, float(size) * float(ct_val) * float(price)) / lev
    except (TypeError, ValueError):
        size_implied = 0.0
    try:
        planned = max(0.0, float(planned_margin or 0.0))
    except (TypeError, ValueError):
        planned = 0.0
    caps = [c for c in (planned if planned > 0 else size_implied, size_implied,
                        float(max_single_asset_margin or 0.0)) if c > 0]
    try:
        equity = float(usdt_available or 0.0)
    except (TypeError, ValueError):
        equity = 0.0
    if equity > 0:
        caps.append(equity * max_margin_equity_ratio)
    return round(min(caps), 4) if caps else 0.0


def equity_margin_cap(usdt_available: float, *, max_margin_equity_ratio=None) -> float:
    """权益占比硬顶（0 = 权益不可得 → 不臆造上限，仅由绝对封顶兜底）。"""
    if max_margin_equity_ratio is None:
        max_margin_equity_ratio = globals()["MAX_MARGIN_EQUITY_RATIO"]
    try:
        equity = float(usdt_available or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return round(equity * max_margin_equity_ratio, 4) if equity > 0 else 0.0


def is_tradfi_market_liquid(asset_type: str) -> bool:
    """Strict US Regular Trading Window (BJ 21:30 ~ 次日 04:00)"""
    if asset_type in ["crypto", "commodity"]:
        return True
    
    tz_bj = datetime.timezone(datetime.timedelta(hours=8))
    now_bj = datetime.datetime.now(tz_bj)
    weekday = now_bj.weekday()
    hour = now_bj.hour
    minute = now_bj.minute

    # Weekend check
    if weekday == 5 and hour >= 5: return False
    if weekday == 6: return False
    if weekday == 0 and (hour < 21 or (hour == 21 and minute < 30)): return False

    # Mon-Fri Core Hours
    if (hour == 21 and minute >= 30) or (hour >= 22) or (hour < 4):
        return True
    return False
