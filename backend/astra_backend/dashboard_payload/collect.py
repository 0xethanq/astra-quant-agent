"""仪表盘载荷装配 —— 相位 1：核心账户状态抓取（结构优化阶段 2·B2 续刀）。

从 `astra_backend/dashboard_cache.py::update_cache_cycle`（拆分前 1021 行）中**纯搬家**相位 1：

平衡/持仓/挂单三项**并发**私有查询 → 单项失败只记 `source_errors` 并降级 →
三项同时报 `_NOT_READY_TEXT` 时判为「连接方式缺失」（专属 NOT_READY 语义）→
USDT 余额四元组解析 → 追踪器加载 → 持仓行/挂单行装配。

## 安全属性（与 trader 域同一套纪律）

- 段体 **AST 逐字**（对拍门 `tests/extraction/test_dashboard_collect_extraction.py` 直接比 AST）；
- 所有自由名（`_fetch_json` / `_core_*` / `okx_rest` / `_NOT_READY_TEXT` …）**同名 kw-only 入参**
  ⇒ 门面调用期解析，`patch.object(app, "okx_rest", …)` 这类测试缝照常生效；
- **不 import `astra_backend.dashboard_cache`**（会与 `routers/dashboard.py` 的 `import astra_backend.dashboard_cache` 成环）。
"""
from __future__ import annotations

from typing import Any, List, Tuple


def collect_core_account_state(*,
        source_errors,
        tz_beijing,
        ThreadPoolExecutor,
        _NOT_READY_TEXT,
        _core_collect_pending_order_rows,
        _core_collect_position_rows,
        _fetch_json,
        datetime,
        load_instruments,
        load_position_trackers,
        okx_rest):
    """相位 1：并发抓取余额/持仓/挂单 + 失败语义 + 连接缺失判定 + 基础解析。

    与拆分前的内联写法**逐条等价**（段体 AST 逐字）：
    - 三项核心私有查询要用同一个 `_fetch_json`，失败只记 `source_errors` 并降级为空列表；
    - 三项**同时**因 `_NOT_READY_TEXT` 失败 ⇒ `_private_not_ready`（"连接方式缺失"），
      与网络抖动区分开，页面据此显示人话文案；
    - `source_errors` 由**原地 append** 回传（只入参、不返回）。
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_bal = pool.submit(_fetch_json, okx_rest.balances)
        f_pos = pool.submit(_fetch_json, okx_rest.positions)
        f_ord = pool.submit(_fetch_json, okx_rest.pending_orders)
        balance_ok, bal_data, balance_error = f_bal.result()
        positions_ok, pos_data, positions_error = f_pos.result()
        orders_ok, orders_data, orders_error = f_ord.result()

    if not balance_ok:
        source_errors.append(f"balance: {balance_error}")
        bal_data = []
    if not positions_ok:
        source_errors.append(f"positions: {positions_error}")
        pos_data = []
    if not orders_ok:
        source_errors.append(f"orders: {orders_error}")
        orders_data = []

    # 三项核心私有查询同时因未配置凭证失败 → 这是「连接方式缺失」而非网络抖动，
    # data_health 用专属 NOT_READY 状态，页面区块据此显示人话文案。
    _private_not_ready = (
        not balance_ok and not positions_ok and not orders_ok
        and balance_error == _NOT_READY_TEXT
        and positions_error == _NOT_READY_TEXT
        and orders_error == _NOT_READY_TEXT
    )

    total_eq = 0.0
    avail_eq = 0.0
    cash_bal = 0.0
    upl_acc = 0.0

    if isinstance(bal_data, list) and bal_data:
        for d in bal_data[0].get("details", []):
            if d.get("ccy") == "USDT":
                total_eq = float(d.get("eq", 0.0) or 0.0)
                avail_eq = float(d.get("availBal", 0.0) or 0.0)
                cash_bal = float(d.get("cashBal", 0.0) or 0.0)
                upl_acc = float(d.get("upl", 0.0) or 0.0)
                break

    positions = []
    total_pos_upl = 0.0
    long_count = 0
    short_count = 0

    trackers = load_position_trackers()

    _pos_delta = _core_collect_position_rows(pos_data, positions, trackers,
                                            load_instruments=load_instruments)
    long_count += _pos_delta[0]
    short_count += _pos_delta[1]
    total_pos_upl += _pos_delta[2]

    # Parse Pending Maker Orders
    pending_orders_list = []
    _core_collect_pending_order_rows(
        orders_data, pending_orders_list, tz_beijing=tz_beijing, datetime=datetime)
    return (_private_not_ready, avail_eq, balance_ok, cash_bal, long_count, orders_data, pending_orders_list, positions, positions_ok, short_count, total_eq, total_pos_upl, trackers, upl_acc)

