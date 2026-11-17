"""回测引擎的**入场装配**与**绩效统计**（结构优化阶段 4·B3 第四十刀）。

两块都搬自 `scripts/backtest_engine.py::BacktestEngine.run`：

| 块 | 原位置 | 行数 | 性质 |
|---|---|---|---|
| `build_entry_candidate` | L244–268 | 25 行 | 信号 → 候选开仓（方向/ATR 止损/止盈/张数） |
| `compute_performance_metrics` | L270–298 | 29 行 | **纯函数**：胜率/盈亏比/夏普/索提诺/卡玛/平均 R |

## 为什么这两块值得单独成模块

- `build_entry_candidate`：把"2.0×ATR 止损 + `rr` 倍止盈 + 风险百分比定张数"
  这套**仓位公式**从 190 行的循环里提出来，公式本身才看得清、才测得到；
- `compute_performance_metrics`：**一个纯函数**（输入 trades 与几个标量，
  输出全部绩效指标），此前埋在主循环后面，只能靠跑完整回测间接验证。

## 四处必须原样保留的"怪"写法

1. **`entry_px` 的滑点是单向有利的**：多头 `×(1+slip)`、空头 `×(1-slip)`
   —— 与 `lifecycle.py` 里**平仓**滑点（两个方向都往不利滑）**方向相反**。
   这不是矛盾：开仓滑点按"买贵/卖便宜"记，平仓滑点按"卖便宜/买贵"记，
   两者都取其**不利**方向。**勿"统一"成同号。**
2. **`losing` 用 `pnl_usd <= 0`**（不是 `< 0`）：**零盈亏计入亏损**。
   这会影响 `win_rate` 与 `profit_factor`，是既有口径。
3. **`profit_factor` 的封顶是 `99.0`**（不是 `inf`）：`gross_loss == 0` 且有盈利时
   返回 99.0 而非无穷 —— 为了 JSON 可序列化。`sortino` 无下行时同样封 99.0。
4. **`std_ret` 的下限是 `1e-6`**：`var_ret == 0`（收益全相同）时避免除零，
   代价是夏普被放大到极大值。原样保留。

## 年化因子 `8760`

`1H` K 线一年 `8760` 根 —— 硬编码在公式里。**不**改成参数、**不**抽成配置
（那会引入一个无消费者的旋钮，且改变既有产出）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

__all__ = ["build_entry_candidate", "compute_performance_metrics",
           "aggregate_portfolio"]

#: 1H K 线年化因子（原实现硬编码，保持原样）
HOURS_PER_YEAR = 8760


def build_entry_candidate(
    *,
    sig: Dict[str, Any],
    close: float,
    timestamp: str,
    capital: float,
    risk_per_trade_pct: float,
    slippage: float,
    rr: Any = None,
) -> Dict[str, Any]:
    """把一个已过门禁的信号装配成候选开仓 dict（**不**判断名额，由调用方判断）。

    返回的 dict 键与原实现完全一致：`direction` / `entry_time` / `entry_price` /
    `stop_loss` / `take_profit` / `size`。

    ⚠️ `rr` 是**显式形参**，不是从 `sig` 里现取。原实现里它是**调用方**算好的局部量
    （`rr = sig.get("rr", 0.0)`，在门禁判定之前），本块只是**读**它。
    我第一版写成 `sig.get("rr", 0.0)` —— 看起来等价，实则不同：
    `sig` 若**缺少** `"rr"` 键，`sig.get("rr")` 返回 `None`，
    `None * float` 会 `TypeError`，而原实现走的是 `0.0`。
    `rr=None` 时按 `0.0` 处理，与调用方的 `.get("rr", 0.0)` 完全一致。

    ⚠️ `atr` 的缺省是 `close * 0.012`（**不是** 0）：信号没有 ATR 时按收盘价的
    1.2% 估一个波动率，使 `risk_dist = atr * 2.0` 不为 0、张数可算。
    """
    rr = 0.0 if rr is None else rr
    direction = "LONG" if sig.get("action") == "BUY" else "SHORT"
    atr = sig.get("atr", close * 0.012)
    # 开仓滑点：多头买贵、空头卖便宜 —— 两个方向都取其**不利**方向。
    entry_px = close * (1 + slippage if direction == "LONG" else 1 - slippage)

    # 2.0x ATR wide stop loss & rr-multiple take profit
    risk_dist = atr * 2.0
    if direction == "LONG":
        sl = entry_px - risk_dist
        tp = entry_px + (risk_dist * rr)
    else:
        sl = entry_px + risk_dist
        tp = entry_px - (risk_dist * rr)

    risk_usd = capital * risk_per_trade_pct
    size = risk_usd / risk_dist if risk_dist > 0 else 0.0

    return {
        "direction": direction,
        "entry_time": timestamp,
        "entry_price": entry_px,
        "stop_loss": sl,
        "take_profit": tp,
        "size": size,
    }


def compute_performance_metrics(
    *,
    trades: List[Any],
    capital: float,
    initial_capital: float,
    returns_list: List[float],
    max_drawdown: float,
) -> Dict[str, float]:
    """由成交列表与权益序列算出全部绩效指标（纯函数，不改任何入参）。

    返回键：`win_rate` / `profit_factor` / `total_return` / `sharpe` / `sortino` /
    `calmar` / `avg_r` / **`winning_trades` / `losing_trades`**。

    ⚠️ `winning_trades` / `losing_trades` 是**计数**，由本函数一并返回 ——
    原实现里 `winning` / `losing` 两个**列表**被 `BacktestSummary` 直接引用
    （`len(winning)`）。抽走后若不在调用方重建列表，门面就会 `NameError`。
    返回计数而非列表，避免把中间列表泄漏成接口。

    ⚠️ 三处口径**原样保留**，改动即改变既有产出：

    - `losing` = `pnl_usd <= 0` → **零盈亏计入亏损**；
    - `profit_factor` 无亏损且有盈利时封顶 `99.0`（不是 `inf`，为 JSON 可序列化）；
    - `std_ret` 下限 `1e-6` → 收益全相同时夏普被放大（原样）。
    """
    winning = [t for t in trades if t.pnl_usd > 0]
    losing = [t for t in trades if t.pnl_usd <= 0]
    win_rate = (len(winning) / len(trades) * 100) if trades else 0.0

    gross_profit = sum(t.pnl_usd for t in winning)
    gross_loss = abs(sum(t.pnl_usd for t in losing))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    total_return = ((capital - initial_capital) / initial_capital) * 100

    # Sharpe & Sortino (Annualized 1H ~ 8760)
    if len(returns_list) > 1:
        mean_ret = sum(returns_list) / len(returns_list)
        var_ret = sum((r - mean_ret) ** 2 for r in returns_list) / (len(returns_list) - 1)
        std_ret = math.sqrt(var_ret) if var_ret > 0 else 1e-6
        sharpe = (mean_ret / std_ret) * math.sqrt(HOURS_PER_YEAR)

        downside = [r for r in returns_list if r < 0]
        if downside:
            var_down = sum(r**2 for r in downside) / len(downside)
            sortino = (mean_ret / math.sqrt(var_down)) * math.sqrt(HOURS_PER_YEAR)
        else:
            sortino = 99.0
    else:
        sharpe = 0.0
        sortino = 0.0

    calmar = (total_return / (max_drawdown * 100)) if max_drawdown > 0 else 0.0
    avg_r = (sum(t.r_multiple for t in trades) / len(trades)) if trades else 0.0

    return {
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_return": total_return,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "avg_r": avg_r,
        "winning_trades": len(winning),
        "losing_trades": len(losing),
    }


def aggregate_portfolio(
    *,
    asset_results: Dict[str, Dict[str, Any]],
    symbols: List[str],
    total_initial: float,
    total_final: float,
    total_gatekeeper_filtered: int,
    combined_trades: List[Any],
) -> Dict[str, Any]:
    """把各标的的回测摘要汇总成组合层摘要（纯计算，不改入参）。

    ## 单标量取的是**算术平均**，不是加权

    `sharpe_ratio` / `sortino_ratio` / `calmar_ratio` / `avg_r_multiple` /
    `profit_factor` 都是 `sum(各标的) / len(symbols)` —— **等权平均**，
    不是按资金或成交笔数加权。这是既有口径，**勿"改进"**：
    改成加权会改变产出，且历史上该值只用于粗看。

    ## ⚠️ 除数是 `len(symbols)`，不是 `len(asset_results)`

    原实现用前者。两者在当前调用点**恰好相等**（循环内每个 `sym` 都会写入
    `asset_results`），但语义不同 —— 故这里**显式接收 `symbols`** 而不是
    自己数 `asset_results`，以免将来某标的失败被跳过时静默改变分母。

    ## `equity_curve` 与 `recent_trades` 的取法

    - `equity_curve` 固定取 `BTC-USDT-SWAP`（组合曲线用 BTC 代表，既有行为）；
    - `recent_trades` 取合并列表的**前 15 笔**（不是后 15 笔）。
    """
    symbols = list(symbols)
    n = len(symbols)

    comb_trades_total = sum(res["total_trades"] for res in asset_results.values())
    comb_win_total = sum(res["winning_trades"] for res in asset_results.values())
    comb_loss_total = sum(res["losing_trades"] for res in asset_results.values())
    comb_win_rate = (comb_win_total / comb_trades_total * 100) if comb_trades_total > 0 else 0.0
    comb_return = ((total_final - total_initial) / total_initial) * 100

    sharpe_avg = sum(res["sharpe_ratio"] for res in asset_results.values()) / n
    max_dd_avg = max(res["max_drawdown_pct"] for res in asset_results.values())

    return {
        "symbol": "ALL_PORTFOLIO (6大主流币全组合)",
        "total_trades": comb_trades_total,
        "winning_trades": comb_win_total,
        "losing_trades": comb_loss_total,
        "win_rate_pct": round(comb_win_rate, 1),
        "profit_factor": round(sum(res["profit_factor"] for res in asset_results.values()) / n, 2),
        "initial_equity": round(total_initial, 2),
        "final_equity": round(total_final, 2),
        "total_return_pct": round(comb_return, 2),
        "max_drawdown_pct": round(max_dd_avg, 2),
        "sharpe_ratio": round(sharpe_avg, 2),
        "sortino_ratio": round(sum(res["sortino_ratio"] for res in asset_results.values()) / n, 2),
        "calmar_ratio": round(sum(res["calmar_ratio"] for res in asset_results.values()) / n, 2),
        "avg_r_multiple": round(sum(res["avg_r_multiple"] for res in asset_results.values()) / n, 2),
        "gatekeeper_filtered_count": total_gatekeeper_filtered,
        "equity_curve": asset_results.get("BTC-USDT-SWAP", {}).get("equity_curve", []),
        "recent_trades": combined_trades[:15],
    }
