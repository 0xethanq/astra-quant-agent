"""开仓结果的**方向相关内容**构造（B3 抽取第十六块）。

从 `scripts/ai_factor_trader.py::execute_portfolio` 的 `if accepted:` 块里，
把"随方向翻转的文案与参数"抽成两个纯函数。

## 这块在解决什么

原实现在长/空两侧各写一遍（共 4 处通知 + 4 条动作文案），方向只影响：

| 载体 | 做多 | 做空 |
|---|---|---|
| 加仓动作文案 | `🚀 AI顺势浮盈金字塔加多挂单已提交` | `🌪️ AI顺势浮盈金字塔加空挂单已提交` |
| 开仓动作文案 | `AI限价多单已提交待成交` | `AI限价空单已提交待成交` |
| 失败文案 | `AI限价多单提交失败` | `AI限价空单提交失败` |
| 加仓通知 `side` | `多 (顺势加多)` | `空 (顺势加空)` |
| 开仓通知 `side` | `多` | `空` |
| 加仓通知 `strategy` | `🚀 顺势金字塔加多` | `🌪️ 顺势金字塔加空` |

**六处文案 × 两个方向 = 12 个必须保持一致的字符串常量**，散落在 74 行里。
文案错了不会让程序崩，会让**交易通知说错方向** —— 而通知是用户判断
"这单是多是空"的唯一来源。这是本次抽取真正的动机：把文案收成单一来源。

## 单型字为什么在 2026-09 之后不再是常量

上表里的「限价」此前是**硬编码字面量**。后台可切市价单
（`ASTRA_ORDER_MODE=market`，写进 `.env`）之后，这句话就变成了谎话：

    2026-09-26 12:45  [ARB] AI限价多单已提交待成交 309.4张@0.2228

当时 `.env` 里就是 `market`，那笔 ARB 单**实发市价单**。文案说谎的代价不只是不雅 ——
**运维与排障无法从日志判断实际发的是哪种单**（本轮排障就被它误导过一次），
而"委托单型"是"钱以什么方式出去"的关键事实。故单型字改由 `_order_word()` 现取。

⚠️ 这里**允许读环境变量**，是本模块唯一的不纯之处，与抽取时的"全部入参"
口径有出入，但**刻意如此**：另一种写法是把单型当参数从 `entry_execution.py`
的入场循环逐层传下来，而那 300 行循环由本仓**最严的抽取门**
（`test_trader_entry_execution_extraction.py`，AST 逐字对拍）看守，
其 docstring 明言"漏一个参数 ⇒ 生产里 NameError，而测试套件不会报"。
为了一个**展示用**的字去动那条路径，风险与收益不成比例。

规模上也要说清楚：这 74 行里只有约 12 行是"随方向变化"的内容，**其余全是
两边逐字相同的样板**（`pending_inst_ids.add` / `reserved_slot_count += 1` /
`if notify_trade_open:` / `reason=str(ai_reason)` / `tp_px=tp_px` / `sl_px=sl_px`）。
因此本块**只抽方向相关部分**，不把样板也包进来 —— 后者会把副作用
（`save_trackers`、`pending_inst_ids`、`reserved_*` 计数）藏进子模块，
既不减行数，又让门面的状态变更不再一目了然。这是有意的取舍，不是没抽完。

## 刻意留在门面的

- `leverage=int(ai_lever),` —— 门面有计数锚点（`test_audit_batch5_d_tails.py`）
  数它的出现次数（4 处），用来保证"四处开仓通知都携带钳制后的真实杠杆"。
  注释记录的历史缺陷是曾恒写 `3`，导致 5x 仓也通知「3x 杠杆」（票圈谎报）。
  故这 4 行必须以字面量留在门面，本模块只提供 `**kwargs` 的其余部分。
- 全部状态变更（`save_trackers` / `pending_inst_ids` / `reserved_slot_count` /
  `reserved_long_count` / `reserved_short_count`）—— 见上。
"""


import os


def _order_word() -> str:
    """当前委托单型的展示字：`市价` / `限价`（见模块 docstring 的 2026-09 说明）。

    语义与下单路径（`order_submit.py` / `execution_router.py`）**同源**：
    `ASTRA_ORDER_MODE` 只在取值恰为 `market` 时算市价，读不到/拼错一律退回 `限价`
    —— 与真实发单的兜底完全一致，故不会出现"文案说市价、实际发限价"。
    """
    return ("市价"
            if str(os.getenv("ASTRA_ORDER_MODE", "limit")).strip().lower() == "market"
            else "限价")


def money_size_text(*, margin_usdt=None, leverage=None, notional_usdt=None,
                    prefix="保证金", with_notional=False):
    """仓位大小的**统一口径**：保证金(USDT) + 杠杆（必要时补名义额）。

    ### 为什么全系统只说钱（2026-09-28 用户拍板）

    三所的"数量"**不是同一个单位**：OKX 是张（1 张 XRP = 100 XRP）、币安是**币数**、
    Gate 是自家张（1 张 XRP = 10 XRP）。更要命的是**各币种的合约面值算法都不一样**
    （BTC 一张可能是 0.01 币，XRP 一张是 100 币），所以"张数"既不能跨场所比、
    也不能跨币种比，用户根本无法从它判断"这笔占了我多少钱"。

    保证金是唯一跨场所、跨币种可比的量，杠杆决定名义敞口。故一切展示只说这两个，
    外加名义额（= 保证金 × 杠杆）作为敞口大小的直观值。

    取不到保证金时返回 `--` —— **绝不回落张数**（那正是旧文案把 199.9 XRP 说成
    26.87 张、把 49.9U 说成 6.72U 的原因）。
    """
    def _num(v):
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    parts = []
    _m = _num(margin_usdt)
    if _m > 0:
        parts.append(f"{prefix} {_m:.2f}U")
    _lv = _num(leverage)
    if _lv > 0:
        parts.append(f"{_lv:g}x 杠杆")
    _n = _num(notional_usdt)
    if with_notional and _n > 0:
        parts.append(f"名义 {_n:.0f}U")
    return " · ".join(parts) if parts else "--"


def entry_action_message(*, is_long, is_scale_in, name, margin_usdt, px, order_ref,
                         tp_px, sl_px, leverage=None):
    """开仓/加仓成功后的 `executed_actions` 文案（含方向与加仓标记）。

    ⚠️ 数量按**保证金 + 杠杆**说，不再说张数（见 `money_size_text`）。
    """
    _money = money_size_text(margin_usdt=margin_usdt, leverage=leverage)
    if is_scale_in:
        arrow = "🚀" if is_long else "🌪️"
        what = "加多" if is_long else "加空"
        return (f"[{name}] {arrow} AI顺势浮盈金字塔{what}挂单已提交 "
                f"{_money} @ {px} (order={order_ref}, TP={tp_px}, SL={sl_px})")
    what = "多" if is_long else "空"
    word = _order_word()
    # 市价单**当场成交**，写「待成交」不成立；限价单保持原文案逐字不变。
    tail = "已提交待成交" if word == "限价" else "已提交"
    return (f"[{name}] AI{word}{what}单{tail} "
            f"{_money} @ {px} (order={order_ref}, TP={tp_px}, SL={sl_px})")


def venue_executed_facts(venue_ctx):
    """下单**实提交**的 `(保证金U, 名义额U)`；取不到返回 `(None, None)`。

    `execution_router` 把实提交结果写在 `RouteResult` 上，`order_submit` 回写到
    `venue_ctx["venue_exec_*"]`。展示一律用这两个**钱**口径的值，不用计划值、
    更不用张数（实测 XRP：文案 `26.87 张｜预估 ~6.72U`，交易所实况 `199.9 XRP｜49.9U`）。

    取不到（OKX 直签链回写路径不同、或老调用方）时返回 `(None, None)`，
    由调用方回落计划值。
    """
    def _f(v):
        try:
            return float(v or 0.0)
        except (TypeError, ValueError):
            return 0.0

    ctx = venue_ctx if isinstance(venue_ctx, dict) else {}
    return (_f(ctx.get("venue_exec_margin")) or None,
            _f(ctx.get("venue_exec_notional")) or None)



def entry_failure_message(*, is_long, name, order_ref):
    """下单被拒后的 `executed_actions` 文案。"""
    return f"[{name}] AI{_order_word()}{'多' if is_long else '空'}单提交失败: {order_ref}"


def trade_open_kwargs(*, is_long, is_scale_in, name, margin_usdt, px, strat_tag,
                      ai_reason, tp_px, sl_px):
    """`notify_trade_open(...)` 的按关键字实参（**不含** `leverage`）。

    `leverage` 由调用点以字面量传入，以保留门面的计数锚点 —— 见模块 docstring。
    ⚠️ 2026-09-28：仓位大小按**保证金**说（不再传张数）—— 见 `money_size_text`。
    `sz=None` 是显式的：载荷里那个字段只作审计留档，与展示契约无关。
    """
    if is_scale_in:
        arrow = "🚀" if is_long else "🌪️"
        what = "加多" if is_long else "加空"
        return dict(inst=name, side=f"{'多' if is_long else '空'} (顺势{what})",
                    sz=None, px=px, strategy=f"{arrow} 顺势金字塔{what}",
                    reason=str(ai_reason), tp_px=tp_px, sl_px=sl_px,
                    margin_usdt=margin_usdt)
    return dict(inst=name, side="多" if is_long else "空",
                sz=None, px=px, strategy=strat_tag,
                reason=str(ai_reason), tp_px=tp_px, sl_px=sl_px,
                margin_usdt=margin_usdt)

