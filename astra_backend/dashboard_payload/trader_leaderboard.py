"""分币种战绩榜（结构优化阶段 4·B3 第二十六刀）。

原样搬自 `astra_backend/dashboard_cache.py::update_cache_cycle` 的 `inst_leaderboard` 计算块。

## 这段在算什么

把 `by_inst`（`trade_stats.aggregate_trade_stats` 的产物，形如
`{"BTC": {"trades": 3, "wins": 2, "losses": 1, "pnl": 12.5}, ...}`）
转成前端表格用的行，按盈亏降序：

| 字段 | 说明 |
|---|---|
| `inst` | 币种基础名 |
| `trades` / `wins` / `losses` | 笔数（**注意含尘埃单**，口径来自 `by_inst`） |
| `win_rate` | `wins / trades × 100`，保留 1 位；`trades == 0` 时为 `0.0`（**不是**除零） |
| `pnl` | 该币种累计净盈亏，保留 2 位 |

## 三处易错点（均原样保留）

1. **胜率分母是 `trades` 而不是 `wins + losses`**。`by_inst["trades"]` **包含**
   被尘埃过滤掉的单子（`trade_stats` 里过滤发生在记账之后），而 `wins`/`losses`
   **不含**。所以 `win_rate` 的分母**大于** `wins + losses`。
   这是 `trade_stats` 那边刻意的口径差异，**不是 bug** —— 若这里改成
   `wins / (wins + losses)`，分币种胜率会与前端既有数字不一致。
2. **排序是 `pnl` 降序**（`reverse=True`），且**对相等值不稳定**（Python 的
   `sort` 稳定，但相等时保持 `by_inst` 的插入顺序 —— 即首笔交易出现的顺序）。
   不要"顺手"加二级排序键，那会改变同分组内的行序。
3. **`round(..., 2)` 只作用于 `pnl`**，笔数是整数直出。

## 与门面的分工

纯函数：只吃 `by_inst`，吐列表。不读任何外部状态。
"""
from __future__ import annotations

from typing import Any, Dict, List

__all__ = ["build_inst_leaderboard"]


def build_inst_leaderboard(by_inst: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """`by_inst` → 按盈亏降序的分币种行。

    返回新列表；`by_inst` 不被修改。
    """
    inst_leaderboard: List[Dict[str, Any]] = []
    for inst, s in by_inst.items():
        w_r = round((s["wins"] / s["trades"]) * 100, 1) if s["trades"] > 0 else 0.0
        inst_leaderboard.append({
            "inst": inst,
            "trades": s["trades"],
            "wins": s["wins"],
            "losses": s["losses"],
            "win_rate": w_r,
            "pnl": round(s["pnl"], 2)
        })
    inst_leaderboard.sort(key=lambda x: x["pnl"], reverse=True)
    return inst_leaderboard
