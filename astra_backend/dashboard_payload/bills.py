"""OKX 账单（bills）聚合（结构优化阶段 4·B3 第二十一刀）。

原样搬自 `astra_backend/dashboard_cache.py::update_cache_cycle` 的「账单聚合」段（49 行）。

## 这段在算什么

把 OKX `account/bills` 的原始账单流水聚成仪表盘要用的四类量：

| 输出 | 含义 |
|---|---|
| `cum_total_fees` | **累计**手续费（不受重置时间限制） |
| `today_fees` | 当日手续费 |
| `today_funding` | 当日资金费 |
| `funding_history_list` | 资金费明细行（时间/币种/收付描述/金额/张数） |
| `orders_by_key` | 平仓单按「分钟 + 币种」聚合成交（gross_pnl / fee / pnl 三档） |

## 三个容易出错的细节（都原样保留）

1. **遍历顺序是 `reversed(bills_data)`**。OKX 账单是**倒序**返回的，而
   `funding_history_list` 与 `orders_by_key` 都要按时间正序铺给前端；
   若改成正序遍历，历史列表会反序、聚合键的首次出现时间也会取错。
2. **`today_bj_str in dt_bj` 是子串判断**，不是相等。"当日"靠
   `"2026-09-14" in "2026-09-14 10:00:00"` 成立；用 `==` 会全部落空。
3. **资金费提前 `continue`**：命中 `type == "8"` 或 `subType in {"173","174"}`
   就**不再**走下面的平仓聚合分支。删掉这个 `continue` 会让资金费行被
   当成平仓单计入 `orders_by_key`，当日盈亏凭空多出资金费。

## 与门面的分工

本函数是**纯计算**：不改任何外部状态，`orders_by_key` / `funding_history_list`
都在函数内新建并随返回值给出。`reset_time_str`、`today_bj_str`、`tz_beijing`
由门面在**调用时**解析并注入 —— 门面这些名字会被测试 `patch.object`
（见 `tests/ui/test_dashboard_payload_seam.py`），import 期绑定会让补丁静默失效。
"""
from __future__ import annotations

__all__ = ["aggregate_bills"]


def aggregate_bills(bills_data, *, reset_time_str, today_bj_str, tz_beijing, datetime):
    """聚合 OKX 账单流水。

    返回 5 元组 `(orders_by_key, today_realized_gross, today_fees,
    cum_total_fees, today_funding, funding_history_list)` 的 dict：

    ```python
    {
        "orders_by_key": {...},       # 平仓聚合，键 f"{分钟}_{币种}"
        "today_realized_gross": 0.0,  # 原实现里恒为 0（见下）
        "today_fees": 0.0,
        "cum_total_fees": 0.0,
        "today_funding": 0.0,
        "funding_history_list": [...],
    }
    ```

    `today_realized_gross` 在原实现里只是个**初始化占位**（本段从不写入它），
    故此处照抄返回 0.0，由调用方沿用其后续逻辑。
    """
    orders_by_key: dict = {}
    today_realized_gross = 0.0
    today_fees = 0.0
    cum_total_fees = 0.0
    today_funding = 0.0
    funding_history_list = []

    if isinstance(bills_data, list):
        for b in reversed(bills_data):
            ts = int(b.get("ts", 0) or 0) / 1000.0
            dt_bj = datetime.datetime.fromtimestamp(ts, tz=tz_beijing).strftime("%Y-%m-%d %H:%M:%S")
            if dt_bj < reset_time_str:
                continue

            sub_type = str(b.get("subType", ""))
            b_type = str(b.get("type", ""))
            inst = b.get("instId", "").replace("-USDT-SWAP", "")
            pnl = float(b.get("pnl", 0) or 0)
            fee = float(b.get("fee", 0) or 0)
            bal_chg = float(b.get("balChg", 0) or 0)
            sz = float(b.get("sz", 0) or 0)

            # Accumulate all trading fees (Cum & Today)
            cum_total_fees += fee
            if today_bj_str in dt_bj:
                today_fees += fee

            if b_type == "8" or sub_type in ["173", "174"]:
                funding_pnl = (bal_chg if bal_chg != 0 else pnl)
                if today_bj_str in dt_bj:
                    today_funding += funding_pnl
                funding_desc = "收取资金费 (+)" if sub_type == "174" or funding_pnl > 0 else "支付资金费 (-)"
                funding_history_list.append({
                    "time": dt_bj,
                    "inst": inst,
                    "type_desc": funding_desc,
                    "pnl": round(funding_pnl, 6),
                    "pos_sz": f"{sz} 张"
                })
                continue

            if sub_type in ["5", "6"]: # Closed order
                # Group by exact Minute + Inst + Close Action
                time_min = dt_bj[:16]
                agg_key = f"{time_min}_{inst}"
                if agg_key not in orders_by_key:
                    orders_by_key[agg_key] = {
                        "time": dt_bj,
                        "inst": inst,
                        "gross_pnl": 0.0,
                        "fee": 0.0,
                        "pnl": 0.0
                    }
                orders_by_key[agg_key]["gross_pnl"] += pnl
                orders_by_key[agg_key]["fee"] += fee
                orders_by_key[agg_key]["pnl"] += (pnl + fee)

    return {
        "orders_by_key": orders_by_key,
        "today_realized_gross": today_realized_gross,
        "today_fees": today_fees,
        "cum_total_fees": cum_total_fees,
        "today_funding": today_funding,
        "funding_history_list": funding_history_list,
    }
