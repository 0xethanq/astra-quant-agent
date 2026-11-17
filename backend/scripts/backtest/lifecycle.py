"""回测引擎的**持仓生命周期**判定（结构优化阶段 4·B3 第三十九刀）。

原样搬自 `scripts/backtest_engine.py::BacktestEngine.run` 的 L190–252（63 行）
—— 该函数 227 行里最大的一块内聚逻辑，且是**唯一**决定平仓价与盈亏的地方。

## 抽出来的是什么

每根 K 线对**已开仓位**做的三件事：

1. **保本锁定**：价格走到 `+0.8R` 后把止损移到开仓价（多头/空头方向相反）；
2. **出场判定**：先判止损、再判止盈（`if/elif` 顺序是**有意的** —— 同一根 K 线
   同时触及两者时按**止损**算，保守口径）；
3. **落袋结算**：手续费、盈亏、`R` 倍数，并把 `TradeRecord` 追加进 `trades`。

## 返回值约定：**不**原地改调用方的资金

原实现直接写 `self.capital += pnl`。搬出来后改为**返回 `pnl`**，由调用方自增：

- `capital` 是整数/浮点标量，Python 无法按引用改，塞进容器再传进来只会更难读；
- 返回 `(exit_decision, pnl)` 让"**结算了没有**"在调用点一眼可见
  （`pnl` 为 `None` 即未平仓）。

## 会**原地修改** `pos`（与原实现一致）

`pos["stop_loss"]` 的保本上移是**有意**的原地修改：下一次评估要用新止损。
调用方 `run()` 持有同一个 dict，故行为与原来完全一致。

## 一处刻意保留的"怪"写法

出场价上的滑点是**单向**的：多头平仓 `× (1 - slippage)`、空头 `× (1 + slippage)`
—— 两个方向都往**不利**方向滑。这是正确的悲观口径，不是笔误，**勿"统一"成同号**。

另注：`stop_loss` 用 `pos["stop_loss"]`（**可能已被本函数上移**），
而 `tp` 用函数开头从 `pos` 取出的局部量 —— 两者都保留原样。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

__all__ = ["evaluate_position_exit", "ExitDecision"]


class ExitDecision:
    """一次出场判定的结果（`should_exit=False` 时其余字段无意义）。"""

    __slots__ = ("should_exit", "exit_price", "exit_reason", "initial_stop_loss")

    def __init__(self, should_exit: bool, exit_price: float, exit_reason: str,
                 initial_stop_loss: float):
        self.should_exit = should_exit
        self.exit_price = exit_price
        self.exit_reason = exit_reason
        #: **保本锁定之前**的止损。结算 `r_multiple` 必须用它 —— 见 `settle_exit`。
        self.initial_stop_loss = initial_stop_loss

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return (f"ExitDecision(should_exit={self.should_exit}, "
                f"exit_price={self.exit_price}, exit_reason={self.exit_reason!r}, "
                f"initial_stop_loss={self.initial_stop_loss})")


def evaluate_position_exit(
    *,
    pos: Dict[str, Any],
    high: float,
    low: float,
    close: float,
    slippage: float,
) -> ExitDecision:
    """评估是否出场；会**原地**上移 `pos["stop_loss"]`（保本锁定）。

    `high` / `low` / `close` 是**当前 K 线**的高、低、收。
    """
    direction = pos["direction"]
    entry_px = pos["entry_price"]
    tp = pos["take_profit"]
    # ⚠️ 这个 `sl` 是**锁定之前**的止损，必须留到最后结算用。
    # 出场判定本身一律读 `pos["stop_loss"]`（因为保本锁定会在中途改写它），
    # 但 `r_multiple` 的分母必须用**初始**风险距离 —— 否则锁定一旦发生，
    # `pos["stop_loss"]` 变成开仓价 → `r_dist` 变 0 → `r_multiple` 退化成 0.0，
    # 与"以初始风险为单位"的语义（以及既有产出）不符。
    initial_stop_loss = pos["stop_loss"]
    r_dist = abs(entry_px - initial_stop_loss)

    exit_trade = False
    exit_price = close
    exit_reason = ""

    if direction == "LONG":
        # Break-even lock rule: move stop to entry once reached +0.8R
        if high >= entry_px + (r_dist * 0.8) and pos["stop_loss"] < entry_px:
            pos["stop_loss"] = entry_px

        if low <= pos["stop_loss"]:
            exit_trade = True
            exit_price = pos["stop_loss"] * (1 - slippage)
            exit_reason = "STOP_LOSS"
        elif high >= tp:
            exit_trade = True
            exit_price = tp * (1 - slippage)
            exit_reason = "TAKE_PROFIT"
    else:  # SHORT
        if low <= entry_px - (r_dist * 0.8) and pos["stop_loss"] > entry_px:
            pos["stop_loss"] = entry_px

        if high >= pos["stop_loss"]:
            exit_trade = True
            exit_price = pos["stop_loss"] * (1 + slippage)
            exit_reason = "STOP_LOSS"
        elif low <= tp:
            exit_trade = True
            exit_price = tp * (1 + slippage)
            exit_reason = "TAKE_PROFIT"

    return ExitDecision(exit_trade, exit_price, exit_reason, initial_stop_loss)


def settle_exit(
    *,
    pos: Dict[str, Any],
    decision: ExitDecision,
    taker_fee: float,
    maker_fee: float,
) -> Tuple[float, float, float]:
    """结算一次出场；返回 `(pnl_usd, pnl_pct, r_multiple)`。

    手续费 = 开仓按 `taker_fee` + 平仓按 `maker_fee`（原样保留：入场是市价吃单、
    出场是限价挂单的既有假设）。

    ⚠️ `r_dist` 用 `decision.initial_stop_loss`（**锁定前**的止损），**不是**
    `pos["stop_loss"]` —— 后者可能已被保本锁定上移到开仓价，那样 `r_dist` 会变 0、
    `r_multiple` 退化成 0.0，与既有产出不符。这是**我在本刀差点写错**的地方：
    第一版 `settle_exit` 直接读 `pos["stop_loss"]`，经直方对比才发现与原实现分叉。
    """
    direction = pos["direction"]
    entry_px = pos["entry_price"]
    sz = pos["size"]
    r_dist = abs(entry_px - decision.initial_stop_loss)
    exit_price = decision.exit_price

    fee = (entry_px * sz * taker_fee) + (exit_price * sz * maker_fee)
    pnl = ((exit_price - entry_px) if direction == "LONG" else (entry_px - exit_price)) * sz - fee
    pnl_pct = pnl / (entry_px * sz) if (entry_px * sz) > 0 else 0.0
    r_mult = pnl / (r_dist * sz) if (r_dist * sz) > 0 else 0.0
    return pnl, pnl_pct, r_mult
