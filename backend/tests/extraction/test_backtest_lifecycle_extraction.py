"""`scripts/backtest/lifecycle.py`（阶段 4·B3 第三十九刀）回归。

## 抽了什么

`scripts/backtest_engine.py::BacktestEngine.run` 的 L190–252（63 行）
—— 该函数 227 行里最大的一块内聚逻辑，也是**唯一**决定平仓价与盈亏的地方。

| | 之前 | 之后 |
|---|---|---|
| `BacktestEngine.run()` | 227 行 | **192 行** |
| `backtest_engine.py` | 470 行 | **436 行** |
| `scripts/backtest/lifecycle.py` | — | 146 行（新） |

## 本刀最该记住的一处：`r_dist` 的**来源**

我第一版 `settle_exit` 直接读 `pos["stop_loss"]` 算 `r_dist` —— **错的**。
原实现是在**保本锁定之前**算好 `r_dist` 一直用到结算。锁定一旦发生
（价格走到 +0.8R，止损被上移到开仓价），`pos["stop_loss"]` 就等于开仓价
→ `r_dist` 变 0 → `r_multiple` 退化成 0.0。

直方对比证实了分叉：

| | r_dist | r_multiple |
|---|---|---|
| 原实现（锁定前 10.0） | 10 | -0.009 |
| 我的第一版（锁定后 0.0） | 0 | 0.0 |

修法：`ExitDecision` 记下 `initial_stop_loss`，`settle_exit` 用它算 `r_dist`。
**`LegacyParityTest` 专门守这条。**

> 这也是"抽公共代码"的典型陷阱：搬动代码时，**变量的求值时机**比它的名字更容易丢。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts" / "backtest" / "lifecycle.py"
FACADE = ROOT / "scripts" / "backtest_engine.py"

from scripts.backtest.lifecycle import (  # noqa: E402
    ExitDecision,
    evaluate_position_exit,
    settle_exit,
)


# ----------------------------------------------- 从 git 历史抄回的原实现


def _legacy_exit(pos, h, l, c, slippage):
    """搬走前的出场判定（逐字抄自 git 历史，含保本锁定）。"""
    entry_px = pos["entry_price"]
    tp = pos["take_profit"]
    sl = pos["stop_loss"]
    r_dist = abs(entry_px - sl)

    exit_trade = False
    exit_price = c
    exit_reason = ""

    if pos["direction"] == "LONG":
        if h >= entry_px + (r_dist * 0.8) and pos["stop_loss"] < entry_px:
            pos["stop_loss"] = entry_px
        if l <= pos["stop_loss"]:
            exit_trade = True
            exit_price = pos["stop_loss"] * (1 - slippage)
            exit_reason = "STOP_LOSS"
        elif h >= tp:
            exit_trade = True
            exit_price = tp * (1 - slippage)
            exit_reason = "TAKE_PROFIT"
    else:
        if l <= entry_px - (r_dist * 0.8) and pos["stop_loss"] > entry_px:
            pos["stop_loss"] = entry_px
        if h >= pos["stop_loss"]:
            exit_trade = True
            exit_price = pos["stop_loss"] * (1 + slippage)
            exit_reason = "STOP_LOSS"
        elif l <= tp:
            exit_trade = True
            exit_price = tp * (1 + slippage)
            exit_reason = "TAKE_PROFIT"
    return exit_trade, exit_price, exit_reason, r_dist


def _legacy_settle(pos, exit_price, r_dist, taker_fee, maker_fee):
    """搬走前的结算（逐字抄自 git 历史）。`r_dist` 由调用方在**锁定前**算好。"""
    entry_px = pos["entry_price"]
    sz = pos["size"]
    fee = (entry_px * sz * taker_fee) + (exit_price * sz * maker_fee)
    pnl = ((exit_price - entry_px) if pos["direction"] == "LONG"
           else (entry_px - exit_price)) * sz - fee
    pnl_pct = pnl / (entry_px * sz) if (entry_px * sz) > 0 else 0.0
    r_mult = pnl / (r_dist * sz) if (r_dist * sz) > 0 else 0.0
    return pnl, pnl_pct, r_mult


def _pos(direction="LONG", entry=100.0, sl=90.0, tp=140.0, sz=10.0):
    return {"direction": direction, "entry_time": "T0", "entry_price": entry,
            "stop_loss": sl, "take_profit": tp, "size": sz}


class LegacyParityTest(unittest.TestCase):
    """与从 git 历史抄回的原实现逐项对拍（含保本锁定与 r_dist 来源）。"""

    #: (direction, entry, sl, tp, size, high, low, close, slippage)
    CASES = [
        # —— LONG ——
        ("LONG", 100.0, 90.0, 140.0, 10.0, 101.0, 99.0, 100.0, 0.0002),   # 无出场
        ("LONG", 100.0, 90.0, 140.0, 10.0, 101.0, 88.0, 95.0, 0.0002),    # 触及止损
        ("LONG", 100.0, 90.0, 140.0, 10.0, 145.0, 99.0, 144.0, 0.0002),   # 触及止盈
        ("LONG", 100.0, 90.0, 140.0, 10.0, 109.0, 100.5, 105.0, 0.0002),  # 锁定但不触止损
        ("LONG", 100.0, 90.0, 140.0, 10.0, 109.0, 99.5, 99.6, 0.0002),    # 锁定后回落到保本价
        ("LONG", 100.0, 90.0, 140.0, 10.0, 145.0, 88.0, 100.0, 0.0),      # 同根K线双触→按止损
        # —— SHORT ——
        ("SHORT", 100.0, 110.0, 60.0, 10.0, 101.0, 99.0, 100.0, 0.0002),  # 无出场
        ("SHORT", 100.0, 110.0, 60.0, 10.0, 112.0, 99.0, 105.0, 0.0002),  # 触及止损
        ("SHORT", 100.0, 110.0, 60.0, 10.0, 101.0, 59.0, 61.0, 0.0002),   # 触及止盈
        ("SHORT", 100.0, 110.0, 60.0, 10.0, 100.5, 91.0, 95.0, 0.0002),   # 锁定但不触止损
        ("SHORT", 100.0, 110.0, 60.0, 10.0, 100.5, 99.0, 100.0, 0.0002),  # 锁定后回落到保本价
        ("SHORT", 100.0, 110.0, 60.0, 10.0, 112.0, 88.0, 100.0, 0.0),     # 同根K线双触→按止损
    ]

    def test_exit_decision_parity(self):
        for case in self.CASES:
            direction, entry, sl, tp, sz, h, l, c, slip = case
            with self.subTest(case=case):
                p_old = _pos(direction, entry, sl, tp, sz)
                p_new = _pos(direction, entry, sl, tp, sz)
                o_exit, o_px, o_reason, o_r = _legacy_exit(p_old, h, l, c, slip)
                d = evaluate_position_exit(pos=p_new, high=h, low=l, close=c, slippage=slip)

                self.assertEqual(d.should_exit, o_exit, "出场判定分叉")
                self.assertEqual(d.exit_price, o_px, "出场价分叉")
                self.assertEqual(d.exit_reason, o_reason, "出场原因分叉")
                # 原实现的 `r_dist` 是"锁定前的 |entry - sl|"；换算回止损价比对。
                self.assertEqual(d.initial_stop_loss, sl,
                                 "initial_stop_loss 必须等于传入的止损（锁定前）")
                self.assertEqual(abs(entry - d.initial_stop_loss), o_r, "r_dist 分叉")
                self.assertEqual(p_new["stop_loss"], p_old["stop_loss"], "保本锁定后的止损分叉")

    def test_initial_stop_loss_preserved_for_settlement(self):
        """⚠️ 核心回归：`initial_stop_loss` 必须是**锁定前**的值。"""
        for case in self.CASES:
            direction, entry, sl, tp, sz, h, l, c, slip = case
            with self.subTest(case=case):
                p_new = _pos(direction, entry, sl, tp, sz)
                d = evaluate_position_exit(pos=p_new, high=h, low=l, close=c, slippage=slip)
                self.assertEqual(d.initial_stop_loss, sl,
                                 "initial_stop_loss 被锁定污染了 —— r_multiple 会退化成 0")

    def test_settlement_parity(self):
        """结算必须用**锁定前**的 r_dist —— 这是本刀差点写错的地方。"""
        for case in self.CASES:
            direction, entry, sl, tp, sz, h, l, c, slip = case
            with self.subTest(case=case):
                p_old = _pos(direction, entry, sl, tp, sz)
                p_new = _pos(direction, entry, sl, tp, sz)
                o_exit, o_px, o_reason, o_r_dist = _legacy_exit(p_old, h, l, c, slip)
                if not o_exit:
                    continue
                d = evaluate_position_exit(pos=p_new, high=h, low=l, close=c, slippage=slip)
                o = _legacy_settle(p_old, o_px, o_r_dist, 0.0005, 0.0002)
                n = settle_exit(pos=p_new, decision=d, taker_fee=0.0005, maker_fee=0.0002)
                self.assertEqual(n, o, "结算结果分叉（r_dist 来源错？）")

    def test_break_even_exit_keeps_nonzero_r_multiple(self):
        """锁定后按保本价出场时，`r_multiple` **不得**退化成 0.0。"""
        p_old = _pos("LONG", 100.0, 90.0, 140.0, 10.0)
        p_new = _pos("LONG", 100.0, 90.0, 140.0, 10.0)
        # 先冲 +0.8R（108）锁定，再回落到 99.5 触发止损（止损=开仓价 100）
        o_exit, o_px, o_reason, o_r_dist = _legacy_exit(p_old, 109.0, 99.5, 99.6, 0.0002)
        self.assertTrue(o_exit)
        self.assertEqual(o_reason, "STOP_LOSS")
        self.assertEqual(p_old["stop_loss"], 100.0, "应已保本锁定")

        d = evaluate_position_exit(pos=p_new, high=109.0, low=99.5, close=99.6, slippage=0.0002)
        _, _, r_mult = settle_exit(pos=p_new, decision=d,
                                   taker_fee=0.0005, maker_fee=0.0002)
        self.assertNotEqual(r_mult, 0.0,
                            "保本出场时 r_multiple 为 0 = 用了锁定后的 r_dist（退化）")
        # ⚠️ 我第一版在这里断言 `≈ -0.8R` —— **错的**。`-0.8R` 是"价格回撤到
        # +0.8R"这一档，而出场发生在**保本价**（止损已被上移到开仓价），
        # 故亏损只有手续费 + 一点点滑点，量级是 **-0.009R**。
        # 关键不是数值大小，而是它**不为 0**（为 0 才说明 r_dist 取错了）。
        expected = _legacy_settle(p_old, o_px, o_r_dist, 0.0005, 0.0002)[2]
        self.assertAlmostEqual(r_mult, expected, places=9)
        self.assertLess(r_mult, 0.0, "算上手续费应略亏")


# --------------------------------------------------------------- 规格断言


class ExitRuleTest(unittest.TestCase):
    def test_stop_loss_takes_precedence_over_take_profit(self):
        """⚠️ 同根 K 线同时触及止损与止盈时按**止损**算（保守口径）。

        `if 止损 / elif 止盈` 的顺序是**有意**的，改成"先判止盈"会系统性高估收益。
        """
        d = evaluate_position_exit(pos=_pos("LONG", 100.0, 90.0, 140.0, 10.0),
                                   high=145.0, low=85.0, close=100.0, slippage=0.0)
        self.assertTrue(d.should_exit)
        self.assertEqual(d.exit_reason, "STOP_LOSS", "双触必须按止损（保守）")

    def test_short_double_touch_also_prefers_stop_loss(self):
        d = evaluate_position_exit(pos=_pos("SHORT", 100.0, 110.0, 60.0, 10.0),
                                   high=115.0, low=55.0, close=100.0, slippage=0.0)
        self.assertEqual(d.exit_reason, "STOP_LOSS")

    def test_slippage_is_adverse_on_both_sides(self):
        """⚠️ 滑点是**单向不利**的：多头平仓 `×(1-slip)`、空头 `×(1+slip)`。

        两个方向都往不利方向滑，是悲观口径，**不是笔误** —— 勿"统一"成同号。
        """
        # ⚠️ 我第一版把 low 写成 99.0 —— 但 high=145 已经触发**保本锁定**
        # （止损被上移到开仓价 100），于是 low=99 先按 STOP_LOSS 出场，
        # 拿到的是 99.0 而不是止盈价。要验止盈滑点，low 必须**高于**锁定后的止损。
        long_exit = evaluate_position_exit(pos=_pos("LONG", 100.0, 90.0, 140.0, 10.0),
                                          high=145.0, low=101.0, close=144.0, slippage=0.01)
        self.assertEqual(long_exit.exit_reason, "TAKE_PROFIT")
        self.assertAlmostEqual(long_exit.exit_price, 140.0 * 0.99, places=6)
        short_exit = evaluate_position_exit(pos=_pos("SHORT", 100.0, 110.0, 60.0, 10.0),
                                            high=99.0, low=59.0, close=61.0, slippage=0.01)
        self.assertEqual(short_exit.exit_reason, "TAKE_PROFIT")
        self.assertAlmostEqual(short_exit.exit_price, 60.0 * 1.01, places=6)

    def test_no_exit_returns_close_as_price(self):
        d = evaluate_position_exit(pos=_pos("LONG", 100.0, 90.0, 140.0, 10.0),
                                   high=101.0, low=99.0, close=100.5, slippage=0.0)
        self.assertFalse(d.should_exit)
        self.assertEqual(d.exit_price, 100.5, "未出场时 exit_price 保留收盘价（原样）")
        self.assertEqual(d.exit_reason, "")

    def test_break_even_lock_only_when_stop_below_entry_long(self):
        p = _pos("LONG", 100.0, 90.0, 140.0, 10.0)
        evaluate_position_exit(pos=p, high=108.0, low=99.0, close=107.0, slippage=0.0)
        self.assertEqual(p["stop_loss"], 100.0, "+0.8R 应把止损上移到开仓价")

    def test_break_even_lock_does_not_lower_an_already_higher_stop(self):
        p = _pos("LONG", 100.0, 90.0, 140.0, 10.0)
        p["stop_loss"] = 105.0   # 已经高于开仓价
        evaluate_position_exit(pos=p, high=108.0, low=104.0, close=107.0, slippage=0.0)
        self.assertEqual(p["stop_loss"], 105.0, "不得把已更高的止损降回开仓价")

    def test_break_even_lock_not_triggered_below_threshold(self):
        p = _pos("LONG", 100.0, 90.0, 140.0, 10.0)
        evaluate_position_exit(pos=p, high=107.9, low=99.0, close=107.0, slippage=0.0)
        self.assertEqual(p["stop_loss"], 90.0, "未到 +0.8R 不得锁定")

    def test_short_break_even_lock_direction(self):
        p = _pos("SHORT", 100.0, 110.0, 60.0, 10.0)
        evaluate_position_exit(pos=p, high=101.0, low=91.0, close=92.0, slippage=0.0)
        self.assertEqual(p["stop_loss"], 100.0, "空头 -0.8R 应把止损下移到开仓价")


class SettlementTest(unittest.TestCase):
    def test_fee_uses_taker_on_entry_and_maker_on_exit(self):
        """手续费假设：入场市价（taker）+ 出场限价（maker）。"""
        p = _pos("LONG", 100.0, 90.0, 140.0, 10.0)
        d = ExitDecision(True, 140.0, "TAKE_PROFIT", 90.0)
        pnl, _, _ = settle_exit(pos=p, decision=d, taker_fee=0.001, maker_fee=0.0002)
        expected = (140.0 - 100.0) * 10.0 - ((100.0 * 10 * 0.001) + (140.0 * 10 * 0.0002))
        self.assertAlmostEqual(pnl, expected, places=6)

    def test_zero_pnl_pct_guard(self):
        """开仓名义为 0 时不得除零。"""
        p = _pos("LONG", 0.0, 0.0, 0.0, 0.0)
        d = ExitDecision(True, 0.0, "STOP_LOSS", 0.0)
        pnl, pnl_pct, r_mult = settle_exit(pos=p, decision=d, taker_fee=0.0, maker_fee=0.0)
        self.assertEqual((pnl, pnl_pct, r_mult), (0.0, 0.0, 0.0))

    def test_short_pnl_sign(self):
        """空头价格下跌应盈利。"""
        p = _pos("SHORT", 100.0, 110.0, 60.0, 10.0)
        d = ExitDecision(True, 60.0, "TAKE_PROFIT", 110.0)
        pnl, _, _ = settle_exit(pos=p, decision=d, taker_fee=0.0, maker_fee=0.0)
        self.assertAlmostEqual(pnl, (100.0 - 60.0) * 10.0, places=6)


class FacadeWiringTest(unittest.TestCase):
    def test_facade_calls_the_helpers(self):
        src = FACADE.read_text(encoding="utf-8")
        self.assertIn("evaluate_position_exit(", src)
        self.assertIn("settle_exit(", src)
        self.assertIn("from scripts.backtest.lifecycle import", src)

    def test_facade_no_longer_inlines_the_lifecycle(self):
        src = FACADE.read_text(encoding="utf-8")
        self.assertNotIn('exit_reason = "STOP_LOSS"', src, "门面仍内联着出场判定")
        self.assertNotIn("Break-even lock rule", src, "门面仍内联着保本锁定")

    def test_module_has_no_module_level_side_effects(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        bare = [n for n in tree.body
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
        self.assertEqual(bare, [], "模块层不应有裸调用")


if __name__ == "__main__":
    unittest.main()
