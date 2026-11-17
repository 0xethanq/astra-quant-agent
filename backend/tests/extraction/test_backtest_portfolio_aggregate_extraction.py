"""`scripts/backtest/metrics.py::aggregate_portfolio`（阶段 4·B3 第四十一刀）回归。

## 抽了什么

`scripts/backtest_engine.py::run_full_portfolio_backtest` 的 L328–356（29 行）
—— 把各标的回测摘要汇总成组合层摘要。

| | 之前 | 之后 |
|---|---|---|
| `run_full_portfolio_backtest()` | 78 行 | **55 行** |
| `backtest_engine.py` | 401 行 | **382 行** |
| `scripts/backtest/metrics.py` | 164 行 | 227 行 |

## 三条必须守的既有口径

1. **标量取算术平均（等权），不是加权**：`sharpe_ratio` / `sortino_ratio` /
   `calmar_ratio` / `avg_r_multiple` / `profit_factor` 都是 `sum / len(symbols)`；
2. **除数是 `len(symbols)`**，不是 `len(asset_results)` —— 两者当前恰好相等，
   但语义不同，故显式传 `symbols`；
3. **`recent_trades` 取前 15 笔**（不是后 15 笔）；`equity_curve` 固定取
   `BTC-USDT-SWAP`（无该标的则退回空列表）。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts" / "backtest" / "metrics.py"
FACADE = ROOT / "scripts" / "backtest_engine.py"

from scripts.backtest.metrics import aggregate_portfolio  # noqa: E402

SYMS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]


def _results(mult=1.0):
    out = {}
    for i, s in enumerate(SYMS):
        out[s] = {
            "total_trades": 7 + i, "winning_trades": 3, "losing_trades": 4 + i,
            "profit_factor": (2.5 + i) * mult, "sharpe_ratio": 1.2 * (i + 1) * mult,
            "sortino_ratio": (2.0 + i) * mult, "calmar_ratio": (3.0 + i) * mult,
            "avg_r_multiple": 0.1 * i, "max_drawdown_pct": 5.0 + i,
            "equity_curve": [{"time": f"t{i}", "equity": 100.0}],
        }
    return out


class AggregatePortfolioTest(unittest.TestCase):
    def _run(self, ar=None, symbols=None, ti=30000.0, tf=33000.0, gk=14, ct=None):
        return aggregate_portfolio(
            asset_results=_results() if ar is None else ar,
            symbols=SYMS if symbols is None else symbols,
            total_initial=ti, total_final=tf,
            total_gatekeeper_filtered=gk,
            combined_trades=list(range(40)) if ct is None else ct)

    def test_trade_counts_are_summed(self):
        p = self._run()
        self.assertEqual(p["total_trades"], 7 + 8 + 9)
        self.assertEqual(p["winning_trades"], 3 * 3)
        self.assertEqual(p["losing_trades"], 4 + 5 + 6)

    def test_win_rate_is_combined_not_averaged(self):
        """组合胜率用**合计**成交数算，不是各标的胜率的平均。"""
        p = self._run()
        self.assertAlmostEqual(p["win_rate_pct"], round(9 / 24 * 100, 1), places=6)

    def test_scalars_use_arithmetic_mean_over_symbols(self):
        """⚠️ 等权平均（`sum / len(symbols)`），**不是**按资金/笔数加权。"""
        ar = _results()
        p = self._run(ar)
        n = len(SYMS)
        self.assertAlmostEqual(p["sharpe_ratio"], round(sum(r["sharpe_ratio"] for r in ar.values()) / n, 2), places=6)
        self.assertAlmostEqual(p["sortino_ratio"], round(sum(r["sortino_ratio"] for r in ar.values()) / n, 2), places=6)
        self.assertAlmostEqual(p["calmar_ratio"], round(sum(r["calmar_ratio"] for r in ar.values()) / n, 2), places=6)
        self.assertAlmostEqual(p["avg_r_multiple"], round(sum(r["avg_r_multiple"] for r in ar.values()) / n, 2), places=6)
        self.assertAlmostEqual(p["profit_factor"], round(sum(r["profit_factor"] for r in ar.values()) / n, 2), places=6)

    def test_scalars_are_rounded_to_two_places(self):
        """⚠️ 负向验证暴露的覆盖盲区：默认夹具的均值**本来就整除**
        （3.6 / 4.8 / 7.2…），故"去掉 round()"也能通过。

        这里刻意选**均值需要进位**的值：`(1.005+2.005+3.005)/3 = 2.005`
        → `round(..., 2) = 2.0`（浮点表示下为 2.0，与不 round 的 2.005 可区分）。
        """
        ar = {s: {"total_trades": 1, "winning_trades": 1, "losing_trades": 0,
                  "profit_factor": 1.0, "sharpe_ratio": v, "sortino_ratio": v,
                  "calmar_ratio": v, "avg_r_multiple": v, "max_drawdown_pct": 1.0,
                  "equity_curve": []}
              for s, v in zip(SYMS, (1.005, 2.005, 3.005))}
        p = aggregate_portfolio(asset_results=ar, symbols=SYMS,
                                total_initial=100.0, total_final=110.0,
                                total_gatekeeper_filtered=0, combined_trades=[])
        mean = (1.005 + 2.005 + 3.005) / 3
        self.assertEqual(p["sharpe_ratio"], round(mean, 2))
        self.assertNotEqual(p["sharpe_ratio"], mean,
                            "未 round 时该值会保留 3 位小数（浮点上为 2.005）")

    def test_divisor_is_len_symbols_not_len_results(self):
        """⚠️ 除数是 `len(symbols)` —— 若某标的缺结果，分母**不**跟着缩。"""
        ar = _results()
        # 传入 4 个 symbol 但只有 3 份结果：分母应为 4
        p = aggregate_portfolio(asset_results=ar, symbols=SYMS + ["X-USDT-SWAP"],
                                total_initial=40000.0, total_final=44000.0,
                                total_gatekeeper_filtered=0, combined_trades=[])
        self.assertAlmostEqual(p["sharpe_ratio"],
                               round(sum(r["sharpe_ratio"] for r in ar.values()) / 4, 2), places=6,
                               msg="分母必须是 len(symbols) 而不是 len(asset_results)")

    def test_max_drawdown_uses_max_not_mean(self):
        p = self._run()
        self.assertAlmostEqual(p["max_drawdown_pct"], round(max(5.0, 6.0, 7.0), 2), places=6)

    def test_total_return_from_equities(self):
        p = self._run(ti=30000.0, tf=33000.0)
        self.assertAlmostEqual(p["total_return_pct"], 10.0, places=6)
        self.assertEqual(p["initial_equity"], 30000.0)
        self.assertEqual(p["final_equity"], 33000.0)

    def test_zero_trades_does_not_divide_by_zero(self):
        ar = {s: dict(v, total_trades=0, winning_trades=0, losing_trades=0)
              for s, v in _results().items()}
        p = self._run(ar=ar, tf=30000.0, gk=0, ct=[])
        self.assertEqual(p["win_rate_pct"], 0.0)
        self.assertEqual(p["total_trades"], 0)

    def test_recent_trades_are_the_first_fifteen(self):
        """⚠️ 取**前** 15 笔（不是后 15 笔）。"""
        p = self._run(ct=list(range(40)))
        self.assertEqual(p["recent_trades"], list(range(15)))

    def test_recent_trades_not_padded_when_few(self):
        p = self._run(ct=[1, 2, 3])
        self.assertEqual(p["recent_trades"], [1, 2, 3])

    def test_equity_curve_comes_from_btc(self):
        p = self._run()
        self.assertEqual(p["equity_curve"], [{"time": "t0", "equity": 100.0}])

    def test_equity_curve_empty_when_no_btc(self):
        ar = {k: v for k, v in _results().items() if k != "BTC-USDT-SWAP"}
        p = self._run(ar=ar, symbols=[s for s in SYMS if s != "BTC-USDT-SWAP"])
        self.assertEqual(p["equity_curve"], [], "无 BTC 标的时应退回空列表")

    def test_gatekeeper_count_passed_through(self):
        self.assertEqual(self._run(gk=42)["gatekeeper_filtered_count"], 42)

    def test_symbol_label_unchanged(self):
        self.assertEqual(self._run()["symbol"], "ALL_PORTFOLIO (6大主流币全组合)")

    def test_does_not_mutate_inputs(self):
        ar = _results()
        ct = list(range(40))
        before = {k: dict(v) for k, v in ar.items()}
        self._run(ar=ar, ct=ct)
        self.assertEqual({k: dict(v) for k, v in ar.items()}, before)
        self.assertEqual(ct, list(range(40)), "不得就地截断 combined_trades")

    def test_returns_all_summary_keys(self):
        self.assertEqual(set(self._run()), {
            "symbol", "total_trades", "winning_trades", "losing_trades",
            "win_rate_pct", "profit_factor", "initial_equity", "final_equity",
            "total_return_pct", "max_drawdown_pct", "sharpe_ratio", "sortino_ratio",
            "calmar_ratio", "avg_r_multiple", "gatekeeper_filtered_count",
            "equity_curve", "recent_trades"})


class FacadeWiringTest(unittest.TestCase):
    def test_facade_calls_the_helper(self):
        src = FACADE.read_text(encoding="utf-8")
        self.assertIn("aggregate_portfolio(", src)

    def test_facade_no_longer_inlines_the_aggregation(self):
        src = FACADE.read_text(encoding="utf-8")
        self.assertNotIn("comb_trades_total", src, "门面仍内联着组合汇总")
        self.assertNotIn("sharpe_avg", src, "门面仍内联着等权平均")

    def test_facade_keeps_the_payload_shape(self):
        """聚合搬走后，`full_payload` 的五个键必须原样保留。"""
        src = FACADE.read_text(encoding="utf-8")
        for key in ('"updated_at"', '"bar"', '"limit"', '"portfolio"',
                    '"by_symbol"', '"active_symbols"'):
            self.assertIn(key, src, f"门面丢了 {key}")

    def test_other_extracted_helpers_still_imported(self):
        src = FACADE.read_text(encoding="utf-8")
        for name in ("build_entry_candidate", "compute_performance_metrics"):
            self.assertIn(name, src)

    def test_module_has_no_module_level_side_effects(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        bare = [n for n in tree.body
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
        self.assertEqual(bare, [], "模块层不应有裸调用")


if __name__ == "__main__":
    unittest.main()
