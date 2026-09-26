"""Binance Algo Service 请求构造器（结构优化阶段 4·B3 第五十九刀）。

## 为什么单独成模块

`astra_backend/exchanges/binance.py`（754 行）里有个形态上和其余部分完全不同的簇：
**US-004 Algo Service 的双轨契约构造器** —— 5 个 `@classmethod` + 3 个类常量
（`ALGO_ORDER_PATH` / `ALGO_TYPES` / `WORKING_TYPES`）+ 1 个 `@staticmethod`
（`_require_working_type`）。

它的特点：

- **零 I/O、零凭证、零签名** —— 纯 dict 构造 + fail-closed 校验；
- 与传送层（`signed_request` / `urlopen`）没有耦合；
- 但文件里它夹在"公共行情端点"与"私有签名面"之间，
  读代码时容易被当成网络层的一部分。

实测（传递纯度扫描）：该文件**没有任何模块级路径常量**，这簇是纯的。

## ⚠️ 用 **mixin** 而不是"搬成自由函数"

原实现全是 `@classmethod`，且**大量通过 `cls.` 与 `BinanceAdapter.` 访问类常量**
（`cls.ALGO_ORDER_PATH` / `cls.ALGO_TYPES` / `BinanceAdapter.WORKING_TYPES`）。
`tests/venues/test_venue_capability_semantics.py` 也是 `self.ad.build_algo_order_request(...)`
（实例上调用 classmethod）与 `binance.BinanceAdapter.WORKING_TYPES` 这样用。

若把方法搬成**自由函数**，上述 `cls` / 类属性访问**全部失效**；
搬成 mixin 则：

- `BinanceAdapter` 继承本 mixin → `self.ad.build_algo_order_request(...)` **不变**；
- `cls` 在运行时仍是 `BinanceAdapter` → `cls.ALGO_ORDER_PATH` **不变**；
- `BinanceAdapter.WORKING_TYPES` 经 MRO 仍能解析 → **不变**。

即：**公开表面与实例/类访问语义全部保持不变**，
`binance.py` 则少掉这 100 余行。

## ⚠️ 代码搬移只允许复制（第五十刀立的规矩）

本模块的函数体与原实现**逐字一致**，未做任何"顺手改进"；
`tests/test_binance_algo_requests.py::VerbatimCopyTest` 用 AST 比对钉住这一点。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional


class BinanceAlgoRequestsMixin:
    """Algo Service 请求构造：常量 + 构造器 + workingType 校验。

    ⚠️ 本 mixin **不定义** `__init__`、不读凭证、不发请求；
    它只被 `BinanceAdapter` 继承以保持 `cls` / 类属性访问语义不变。
    """

    # ==================================================================
    # US-004 · Algo Service 双轨契约（纯构造器可单测；发送通道显式未实装）
    # 审计 2026-09-10 §2：POST/GET/DELETE /fapi/v1/algoOrder 资源族独立于普通
    # /fapi/v1/order；SDK 独立方法 query_algo_order /
    # current_all_algo_open_orders / cancel_algo_order / cancel_all_algo_open_orders。
    # ==================================================================
    ALGO_ORDER_PATH = "/fapi/v1/algoOrder"
    ALGO_TYPES = ("STOP", "STOP_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_MARKET",
                  "TRAILING_STOP_MARKET")
    WORKING_TYPES = ("MARK_PRICE", "CONTRACT_PRICE", "INDEX_PRICE")

    @classmethod
    def _require_working_type(cls, working_type: Optional[str]) -> str:
        """workingType 显式必传——不依赖任何平台默认值（审计 §0-2）。

        ⚠️ 原实现是 `@staticmethod` 且写死 `BinanceAdapter.WORKING_TYPES`
        （即"读另一个类"）。搬进 mixin 后那个类名解析不到，故改为
        `@classmethod` + `cls.WORKING_TYPES` —— 经 MRO 仍解析到
        `BinanceAdapter` 上的同一份常量，**取值与语义不变**；
        调用点 `cls._require_working_type(...)` 也不变。
        """
        wt = str(working_type or "").strip().upper()
        if wt not in cls.WORKING_TYPES:
            raise ValueError(
                f"workingType 必须显式传入且合法（{'/'.join(cls.WORKING_TYPES)}），"
                f"收到 {working_type!r}——官方 Algo 默认是 CONTRACT_PRICE，本系统禁止吃默认值")
        return wt

    @classmethod
    def build_algo_order_request(cls, *, symbol: str, side: str, type_: str,
                                 trigger_price, working_type: str,
                                 quantity=None, price=None,
                                 reduce_only: Optional[bool] = None,
                                 close_position: Optional[bool] = None,
                                 position_side: Optional[str] = None,
                                 client_algo_id: Optional[str] = None) -> Dict[str, Any]:
        """条件单新建请求体（字段名按当前 Algo Service：triggerPrice/clientAlgoId，
        绝不是普通订单的 stopPrice/newClientOrderId）。非法组合 fail-closed。"""
        if not str(symbol or "").strip().upper().endswith("USDT"):
            raise ValueError(f"symbol 需为 USDⓈ-M 原生名（如 BTCUSDT），收到 {symbol!r}")
        t = str(type_ or "").strip().upper()
        if t not in cls.ALGO_TYPES:
            raise ValueError(f"type 需为 CONDITIONAL 族 {cls.ALGO_TYPES}，收到 {type_!r}")
        try:
            tp = Decimal(str(trigger_price))
        except Exception:
            raise ValueError(f"triggerPrice 非法: {trigger_price!r}")
        if tp <= 0:
            raise ValueError("triggerPrice 必须为正")
        body: Dict[str, Any] = {
            "symbol": str(symbol).upper(), "side": str(side).upper(), "type": t,
            "algoType": "CONDITIONAL",
            "triggerPrice": str(tp),
            "workingType": cls._require_working_type(working_type),
        }
        cp = bool(close_position)
        if cp:
            # closePosition=true 仅适用指定条件市价单，且与 quantity/reduceOnly 互斥（审计 §2）
            if not t.endswith("_MARKET"):
                raise ValueError("closePosition=true 仅适用 *_MARKET 条件市价单")
            if quantity not in (None, "", 0) or reduce_only:
                raise ValueError("closePosition=true 与 quantity/reduceOnly 互斥，不得并传")
            body["closePosition"] = "true"
        else:
            if quantity in (None, ""):
                raise ValueError("非 closePosition 条件单必须给 quantity")
            body["quantity"] = str(Decimal(str(quantity)))
            if reduce_only is not None:
                ro = bool(reduce_only)
                ps = str(position_side or "BOTH").upper()
                if ps in ("LONG", "SHORT") and ro:
                    # Hedge Mode 不可传 reduceOnly——平仓方向由 positionSide 表达（审计 §2）
                    raise ValueError("Hedge Mode（positionSide=LONG/SHORT）不可传 reduceOnly，"
                                     "用 positionSide 显式映射减仓方向")
                body["reduceOnly"] = "true" if ro else "false"
        ps = str(position_side or "").upper()
        if ps:
            if ps not in ("BOTH", "LONG", "SHORT"):
                raise ValueError(f"positionSide 非法: {position_side!r}")
            body["positionSide"] = ps
        if price not in (None, ""):
            body["price"] = str(Decimal(str(price)))
        if client_algo_id:
            body["clientAlgoId"] = str(client_algo_id)
        # 普通订单旧字段防呆：绝不明传
        for legacy in ("stopPrice", "newClientOrderId"):
            if legacy in body:
                raise ValueError(f"{legacy} 属普通订单字段，禁止传入 Algo API")
        return {"method": "POST", "path": cls.ALGO_ORDER_PATH, "body": body}

    @classmethod
    def build_algo_query_request(cls, *, algo_id=None, client_algo_id=None) -> Dict[str, Any]:
        """query_algo_order：按 algoId 或 clientAlgoId 单查。"""
        params: Dict[str, Any] = {}
        if algo_id is not None:
            params["algoId"] = str(algo_id)
        if client_algo_id:
            params["clientAlgoId"] = str(client_algo_id)
        if not params:
            raise ValueError("查询条件单需 algoId 或 clientAlgoId")
        return {"method": "GET", "path": cls.ALGO_ORDER_PATH, "params": params}

    @classmethod
    def build_algo_open_orders_request(cls, *, symbol: Optional[str] = None) -> Dict[str, Any]:
        """current_all_algo_open_orders：当前 algo 挂单（/fapi/v1/openAlgoOrders）。"""
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = str(symbol).upper()
        return {"method": "GET", "path": "/fapi/v1/openAlgoOrders", "params": params}

    @classmethod
    def build_algo_cancel_request(cls, *, algo_id=None, client_algo_id=None) -> Dict[str, Any]:
        """cancel_algo_order：单撤。"""
        params: Dict[str, Any] = {}
        if algo_id is not None:
            params["algoId"] = str(algo_id)
        if client_algo_id:
            params["clientAlgoId"] = str(client_algo_id)
        if not params:
            raise ValueError("撤销条件单需 algoId 或 clientAlgoId")
        return {"method": "DELETE", "path": cls.ALGO_ORDER_PATH, "params": params}

    @classmethod
    def build_algo_cancel_all_request(cls, *, symbol: str) -> Dict[str, Any]:
        """cancel_all_algo_open_orders：按合约全撤。"""
        if not str(symbol or "").strip():
            raise ValueError("全撤需指定 symbol")
        return {"method": "DELETE", "path": f"{cls.ALGO_ORDER_PATH}/all",
                "params": {"symbol": str(symbol).upper()}}
