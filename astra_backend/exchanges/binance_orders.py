"""Binance 下单参数构建的两条**判定规则**（从 `exchanges/binance.py` 搬出）。

| 函数 | 规则 |
|---|---|
| `build_order_params(...)` | 把 `qty`/`price` 按合约 `step`/`tick` **向下取整**成交易所要的字符串（去尾零），据 `price` 有无选 `LIMIT`/`MARKET`，并落 `newClientOrderId` / `positionSide` / `reduceOnly` |
| `apply_protective_qty_policy(...)` | 保护单（止盈/止损）的**数量策略**：给了数量 ⇒ `quantity` + `reduce_only=True` + `close_position=False`；没给 ⇒ `close_position=True`（整仓平） |

## 两条安全契约（本模块存在的理由）

1. **`reduceOnly` 与 `positionSide` 互斥**（审计 §2 契约）：对冲模式下同时下 `reduceOnly`
   会被交易所拒单且语义不清，故这里**主动抛 `ValueError`**，而不是把矛盾参数发出去。
   原先该判断埋在下单方法中段、外包一层 `signed_request`，很难单独验证。
2. 数量策略的 `reduce_only` / `close_position` 组合决定"平多少"：给数量时**限该数量**，
   未给数量时**整仓平**。两处（TP/SL）原是**逐字重复**的 6 行，合并后不会再各自漂移。

`place_order` 中 `self.fetch_instrument_spec(...)` 与 `self.signed_request(...)` 留在门面，
`spec` 作为入参传入 ⇒ 本模块**零 `self`、零 IO**。
"""

from decimal import ROUND_DOWN, Decimal
from typing import Any, Dict


def build_order_params(*,
        inst,
        position_side,
        price,
        qty,
        reduce_only,
        s,
        spec,
        text,
        tif):
    step = Decimal(str(spec.step_size if spec else 1e-6))
    qty_dec = (Decimal(str(qty)) / step).to_integral_value(rounding=ROUND_DOWN) * step
    qty_str = format(qty_dec, "f").rstrip("0").rstrip(".") if "." in format(qty_dec, "f") else format(qty_dec, "f")

    params: Dict[str, Any] = {
        "symbol": inst,
        "side": s,
        "quantity": qty_str,
    }

    if price is not None and float(price) > 0:
        params["type"] = "LIMIT"
        params["timeInForce"] = tif.upper()
        tick = Decimal(str(spec.tick_size if spec else 0.1))
        px_dec = (Decimal(str(price)) / tick).to_integral_value(rounding=ROUND_DOWN) * tick
        params["price"] = format(px_dec, "f").rstrip("0").rstrip(".") if "." in format(px_dec, "f") else format(px_dec, "f")
    else:
        params["type"] = "MARKET"

    if text:
        params["newClientOrderId"] = str(text).strip()
    if position_side:
        params["positionSide"] = str(position_side).upper()
    if reduce_only:
        if position_side:
            raise ValueError("reduceOnly 与 positionSide 互斥（对冲模式禁 reduceOnly，审计 §2 契约）")
        params["reduceOnly"] = "true"
    return params


def apply_protective_qty_policy(*,
        req_kwargs,
        qty_str):
    if qty_str:
        req_kwargs["quantity"] = qty_str
        req_kwargs["reduce_only"] = True
        req_kwargs["close_position"] = False
    else:
        req_kwargs["close_position"] = True


def send_protective_order(*, build_algo_order_request, inst, opp_side, position_side,
                          private_algo_send, qty_str, trigger_price, type_, wt):
    """按触发价是否有效决定是否发单；返回 algoId（缺则 orderId，皆无则 `""`）。

    本函数由 `BinanceAdapter.attach_protective_orders` 的两段**近乎逐字重复**的代码合并而来
    （第一百一十六刀）：两段只差 `type_`（TAKE_PROFIT_MARKET / STOP_MARKET）、触发价与结果键，
    合并后不会再各自漂移。

    ## 与原实现的行为等价性（写给后来者，避免"看起来变了"的误判）

    原实现是 `if trigger 有效: ... if isinstance(data, dict): res[key] = str(...)`，
    即"仅在响应是 dict 时赋值（可能是空串）"；本函数返回 `""` 时调用方**无条件赋值**。
    因为 `res` 的初值就是 `""`、且返回值恒为 `str`，两种情况下的最终 `res` **完全相同**；
    触发价无效时原实现根本不动 `res`（仍是 `""`），等价性同样成立。

    `build_algo_order_request` / `private_algo_send` 由调用方**按实例属性取出后传入**
    ⇒ 实例级覆盖（含测试里的 stub）仍然生效。
    """
    if trigger_price is not None and float(trigger_price) > 0:
        req_kwargs = {
            "symbol": inst,
            "side": opp_side,
            "type_": type_,
            "trigger_price": trigger_price,
            "working_type": wt,
            "position_side": position_side,
        }
        apply_protective_qty_policy(req_kwargs=req_kwargs, qty_str=qty_str)

        req = build_algo_order_request(**req_kwargs)
        data = private_algo_send(req)
        if isinstance(data, dict):
            return str(data.get("algoId") or data.get("orderId") or "")
    return ""
