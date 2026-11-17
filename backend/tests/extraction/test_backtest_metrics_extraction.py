"""`scripts/backtest/metrics.py`（阶段 4·B3 第四十刀）回归。

## 抽了什么

`scripts/backtest_engine.py::BacktestEngine.run` 里剩下两块：

| 块 | 原位置 | 行数 |
|---|---|---|
| `build_entry_candidate` | L244–268 | 25 行 |
| `compute_performance_metrics` | L270–298 | 29 行 |

| | 之前 | 之后 |
|---|---|---|
| `BacktestEngine.run()` | 192 行 | **154 行** |
| `backtest_engine.py` | 436 行 | **399 行** |
| `scripts/backtest/metrics.py` | — | 157 行（新） |

## 两处必须守的既有口径（改了就改变产出）

1. **`losing` 用 `pnl_usd <= 0`** → **零盈亏计入亏损**，影响 `win_rate` 与
   `profit_factor`；
2. **`profit_factor` / `sortino` 的封顶是 `99.0`**（不是 `inf`，为 JSON 可序列化）。

## 一处"看起来等价、实则不同"的陷阱

`rr` 在原实现里是**调用方**算好的局部量；`build_entry_candidate` 的 `rr`
必须是**显式形参**。若图省事写成 `sig.get("rr", 0.0)`：
- 原实现：`rr = sig.get("rr", 0.0)` → 缺键得 `0.0`；
- 我若写 `sig.get("rr")` → 缺键得 `None` → `None * float` 抛 `TypeError`。
本文件用 `test_missing_rr_key_does_not_crash` 钉住。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts" / "backtest" / "metrics.py"
FACADE = ROOT / "scripts" / "backtest_engine.py"

from scripts.backtest.metrics import (  # noqa: E402
    build_entry_candidate,
    compute_performance_metrics,
)


class _Trade:
    """`TradeRecord` 的最小替身：只需 `pnl_usd` 与 `r_multiple`。"""

    def __init__(self, pnl_usd, r_multiple=0.0):
        self.pnl_usd = pnl_usd
        self.r_multiple = r_multiple


# --------------------------------------------------------- 入场装配


class BuildEntryCandidateTest(unittest.TestCase):
    def _run(self, sig, close=100.0, capital=10000.0, risk=0.02, slip=0.0002, rr=None):
        rr = sig.get("rr", 0.0) if rr is None else rr
        return build_entry_candidate(sig=sig, close=close, timestamp="T0",
                                     capital=capital, risk_per_trade_pct=risk,
                                     slippage=slip, rr=rr)

    def test_long_geometry(self):
        p = self._run({"action": "BUY", "atr": 100.0, "rr": 2.5}, close=100.0)
        self.assertEqual(p["direction"], "LONG")
        self.assertAlmostEqual(p["entry_price"], 100.0 * 1.0002, places=6)
        risk_dist = 100.0 * 2.0
        self.assertAlmostEqual(p["stop_loss"], p["entry_price"] - risk_dist, places=6)
        self.assertAlmostEqual(p["take_profit"], p["entry_price"] + risk_dist * 2.5, places=6)

    def test_short_geometry(self):
        p = self._run({"action": "SELL", "atr": 100.0, "rr": 2.5}, close=100.0)
        self.assertEqual(p["direction"], "SHORT")
        self.assertAlmostEqual(p["entry_price"], 100.0 * (1 - 0.0002), places=6)
        risk_dist = 100.0 * 2.0
        self.assertAlmostEqual(p["stop_loss"], p["entry_price"] + risk_dist, places=6)
        self.assertAlmostEqual(p["take_profit"], p["entry_price"] - risk_dist * 2.5, places=6)

    def test_entry_slippage_is_adverse_both_ways(self):
        """开仓滑点：多头买贵、空头卖便宜 —— 与平仓滑点方向**相反**，都是不利方向。"""
        long_p = self._run({"action": "BUY", "atr": 10.0, "rr": 2.0}, slip=0.01)
        self.assertGreater(long_p["entry_price"], 100.0, "多头应买贵")
        short_p = self._run({"action": "SELL", "atr": 10.0, "rr": 2.0}, slip=0.01)
        self.assertLess(short_p["entry_price"], 100.0, "空头应卖便宜")

    def test_size_is_risk_budget_over_risk_distance(self):
        p = self._run({"action": "BUY", "atr": 100.0, "rr": 2.0}, capital=10000.0, risk=0.02)
        expected = (10000.0 * 0.02) / (100.0 * 2.0)
        self.assertAlmostEqual(p["size"], expected, places=9)

    def test_missing_atr_defaults_to_close_times_1_2pct(self):
        """⚠️ 缺省是 `close * 0.012`（不是 0），否则 risk_dist=0、张数为 0。"""
        p = self._run({"action": "BUY", "rr": 2.0}, close=1000.0)
        self.assertAlmostEqual(p["size"], (10000.0 * 0.02) / (1000.0 * 0.012 * 2.0), places=9)

    def test_missing_rr_key_does_not_crash(self):
        """⚠️ `rr` 必须是显式形参：缺 `rr` 键时 `sig.get("rr")` 会给 `None` → TypeError。"""
        try:
            p = self._run({"action": "BUY", "atr": 100.0})   # 无 rr 键
        except TypeError as exc:  # pragma: no cover - 不应发生
            self.fail(f"缺 rr 键时抛了 TypeError（说明取了 None）: {exc}")
        self.assertAlmostEqual(p["take_profit"], p["entry_price"], places=6,
                               msg="rr 缺省为 0 时止盈应等于开仓价")

    def test_zero_atr_yields_zero_size(self):
        p = self._run({"action": "BUY", "atr": 0.0, "rr": 2.0})
        self.assertEqual(p["size"], 0.0, "risk_dist=0 时张数必须为 0（不得除零）")

    def test_returned_keys_are_exactly_the_original(self):
        p = self._run({"action": "BUY", "atr": 100.0, "rr": 2.0})
        self.assertEqual(set(p), {"direction", "entry_time", "entry_price",
                                  "stop_loss", "take_profit", "size"})

    def test_timestamp_is_passed_through(self):
        p = build_entry_candidate(sig={"action": "BUY", "atr": 10.0, "rr": 2.0},
                                  close=100.0, timestamp="2026-09-01T00:00:00Z",
                                  capital=1e4, risk_per_trade_pct=0.02, slippage=0.0)
        self.assertEqual(p["entry_time"], "2026-09-01T00:00:00Z")


# --------------------------------------------------------- 绩效统计


class ComputeMetricsTest(unittest.TestCase):
    def _run(self, trades, capital=11000.0, initial=10000.0, returns=None,
             max_dd=0.05):
        return compute_performance_metrics(
            trades=trades, capital=capital, initial_capital=initial,
            returns_list=returns if returns is not None else [0.01, -0.005, 0.02],
            max_drawdown=max_dd)

    def test_win_rate_uses_strictly_positive(self):
        m = self._run([_Trade(100.0), _Trade(-50.0), _Trade(0.0)])
        self.assertAlmostEqual(m["win_rate"], 100.0 / 3, places=6,
                               msg="零盈亏既不算赢也不算赢 —— 只有 >0 计入")

    def test_zero_pnl_counts_as_loss(self):
        """⚠️ `losing` 是 `pnl_usd <= 0` —— 零盈亏计入**亏损**（既有口径）。"""
        m = self._run([_Trade(0.0), _Trade(0.0)])
        self.assertEqual(m["winning_trades"], 0)
        self.assertEqual(m["losing_trades"], 2)

    def test_profit_factor_caps_at_99_when_no_losses(self):
        """⚠️ 无亏损且有盈利 → 封顶 99.0（不是 inf，为 JSON 可序列化）。"""
        m = self._run([_Trade(100.0), _Trade(50.0)])
        self.assertEqual(m["profit_factor"], 99.0)

    def test_profit_factor_zero_when_no_win_no_loss(self):
        m = self._run([])
        self.assertEqual(m["profit_factor"], 0.0)
        self.assertEqual(m["win_rate"], 0.0)
        self.assertEqual(m["avg_r"], 0.0)

    def test_profit_factor_ratio(self):
        m = self._run([_Trade(300.0), _Trade(-100.0)])
        self.assertAlmostEqual(m["profit_factor"], 3.0, places=9)

    def test_total_return(self):
        m = self._run([], capital=11000.0, initial=10000.0)
        self.assertAlmostEqual(m["total_return"], 10.0, places=9)

    def test_sharpe_and_sortino_zero_with_insufficient_returns(self):
        m = self._run([_Trade(1.0)], returns=[0.01])
        self.assertEqual(m["sharpe"], 0.0)
        self.assertEqual(m["sortino"], 0.0)

    def test_sortino_caps_at_99_when_no_downside(self):
        """⚠️ 无下行收益 → 索提诺封顶 99.0。"""
        m = self._run([_Trade(1.0)], returns=[0.01, 0.02, 0.03])
        self.assertEqual(m["sortino"], 99.0)

    def test_sharpe_uses_8760_annualization(self):
        import math
        rets = [0.01, -0.005, 0.02, 0.0]
        m = self._run([_Trade(1.0)], returns=rets)
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        expected = (mean / math.sqrt(var)) * math.sqrt(8760)
        self.assertAlmostEqual(m["sharpe"], expected, places=9)

    def test_constant_returns_do_not_divide_by_zero(self):
        """⚠️ `std_ret` 下限 1e-6：收益全相同不得崩，但夏普会被放大（原样）。"""
        import math
        m = self._run([_Trade(1.0)], returns=[0.01, 0.01, 0.01])
        self.assertNotEqual(m["sharpe"], 0.0)
        # ⚠️ 我第一版写 `> 1e6` —— 又是"凭直觉写期望值"。
        # 实算：(0.01 / 1e-6) * sqrt(8760) = 935948.7。
        self.assertAlmostEqual(m["sharpe"], (0.01 / 1e-6) * math.sqrt(8760), places=3,
                               msg="1e-6 下限会把夏普放大到 ~9.36e5（既有行为，原样保留）")

    def test_calmar_zero_when_no_drawdown(self):
        m = self._run([], max_dd=0.0)
        self.assertEqual(m["calmar"], 0.0)

    def test_calmar_ratio(self):
        m = self._run([], capital=11000.0, initial=10000.0, max_dd=0.05)
        self.assertAlmostEqual(m["calmar"], 10.0 / (0.05 * 100), places=9)

    def test_avg_r_averages_trade_r_multiples(self):
        m = self._run([_Trade(1.0, 1.0), _Trade(1.0, -0.5), _Trade(1.0, 2.0)])
        self.assertAlmostEqual(m["avg_r"], (1.0 - 0.5 + 2.0) / 3, places=9)

    def test_returns_all_documented_keys(self):
        m = self._run([_Trade(1.0)])
        self.assertEqual(set(m), {"win_rate", "profit_factor", "total_return",
                                  "sharpe", "sortino", "calmar", "avg_r",
                                  "winning_trades", "losing_trades"})

    def test_does_not_mutate_inputs(self):
        trades = [_Trade(100.0), _Trade(-50.0)]
        rets = [0.01, -0.02]
        before_t, before_r = list(trades), list(rets)
        self._run(trades, returns=rets)
        self.assertEqual(trades, before_t, "不得重排/改动 trades")
        self.assertEqual(rets, before_r, "不得改动 returns_list")

    def test_winning_and_losing_counts_sum_to_total(self):
        """两个计数必须覆盖全部成交（`>` 与 `<=` 恰好互补）。"""
        m = self._run([_Trade(1.0), _Trade(0.0), _Trade(-1.0), _Trade(2.0)])
        self.assertEqual(m["winning_trades"] + m["losing_trades"], 4)


class FacadeWiringTest(unittest.TestCase):
    def test_facade_calls_the_helpers(self):
        src = FACADE.read_text(encoding="utf-8")
        self.assertIn("build_entry_candidate(", src)
        self.assertIn("compute_performance_metrics(", src)

    def test_facade_no_longer_inlines_them(self):
        src = FACADE.read_text(encoding="utf-8")
        self.assertNotIn("risk_dist = atr * 2.0", src, "门面仍内联着入场装配")
        self.assertNotIn("gross_profit = sum(", src, "门面仍内联着绩效统计")
        self.assertNotIn("mean_ret = sum(", src, "门面仍内联着夏普计算")

    def test_facade_summary_uses_returned_counts(self):
        """`winning` / `losing` 两个列表搬走后，摘要必须改用返回的计数，否则 NameError。"""
        src = FACADE.read_text(encoding="utf-8")
        self.assertIn('_metrics["winning_trades"]', src)
        self.assertIn('_metrics["losing_trades"]', src)

    def test_module_has_no_module_level_side_effects(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        bare = [n for n in tree.body
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
        self.assertEqual(bare, [], "模块层不应有裸调用")


if __name__ == "__main__":
    unittest.main()
