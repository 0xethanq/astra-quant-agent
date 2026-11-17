"""B3（交易员侧第十八块）`scripts/trader/leverage.py` 的抽取回归。

## 这个测试在守什么

`clamp_ai_leverage` 是"AI 说 20x、实际只准开 5x"这条风控链的**唯一落点**。
三件事按固定顺序发生，顺序错了就漏风控：

1. 夹到风控页配置的 `[MIN_LEVERAGE, MAX_LEVERAGE]`；
2. 再用池条目的 per-instrument `max_leverage` 收紧（取更严者）；
3. 把最终值随开仓通知透传。

**若把顺序反过来**（先池值、后配置区间），一个低于 `MIN_LEVERAGE` 的池值就会被
配置下限重新抬上去，池内收紧**静默失效**。这一条本文件专门钉住。

## 两条历史缺陷（注释里记着，测试里也钉着）

- **审计 P2-8**：旧实现只夹上限，`MIN_LEVERAGE` 在单所路径根本不成立
  → 1x 决策不会被抬到下限。
- **审计 P2-5**：池条目的 `max_leverage`（tier 派生 3x/5x）此前**无人读**
  → 池里写 3x，实际仍按全局 20x 开。
"""

from __future__ import annotations

import ast
import random
import unittest
from pathlib import Path

from scripts.trader import leverage

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "ai_factor_trader.py"
SUBMODULE = ROOT / "scripts" / "trader" / "leverage.py"
ENTRY = ROOT / "scripts" / "trader" / "entry_execution.py"   # 第九十刀：开多/开空两支现住此


def _legacy(ai_lever, *, min_leverage, max_leverage, inst_lever_cap):
    """搬走前 facade per-factor 循环里的内联夹取（逐字原样）。"""
    ai_lever = min(max(ai_lever, float(min_leverage or 0.0) or 1.0),
                   float(max_leverage or 20.0))
    tightened = False
    if inst_lever_cap > 0 and ai_lever > inst_lever_cap:
        tightened = True
        ai_lever = inst_lever_cap
    return ai_lever, tightened


class ClampParityTest(unittest.TestCase):
    def test_floor_is_applied(self):
        """审计 P2-8：1x 决策必须被抬到配置下限。"""
        lev, _ = leverage.clamp_ai_leverage(
            1.0, min_leverage=5.0, max_leverage=20.0, inst_lever_cap=0.0)
        self.assertEqual(lev, 5.0, "低于下限的决策必须被抬升")

    def test_ceiling_is_applied(self):
        lev, _ = leverage.clamp_ai_leverage(
            50.0, min_leverage=1.0, max_leverage=20.0, inst_lever_cap=0.0)
        self.assertEqual(lev, 20.0)

    def test_inside_range_is_untouched(self):
        lev, tightened = leverage.clamp_ai_leverage(
            7.0, min_leverage=1.0, max_leverage=20.0, inst_lever_cap=0.0)
        self.assertEqual(lev, 7.0)
        self.assertFalse(tightened)

    def test_per_instrument_cap_tightens(self):
        """审计 P2-5：池条目 3x 必须真的把 20x 压到 3x。"""
        lev, tightened = leverage.clamp_ai_leverage(
            20.0, min_leverage=1.0, max_leverage=20.0, inst_lever_cap=3.0)
        self.assertEqual(lev, 3.0)
        self.assertTrue(tightened, "被池值收紧时必须报告 tightened（调用点据此打日志）")

    def test_cap_equal_to_result_is_not_tightened(self):
        lev, tightened = leverage.clamp_ai_leverage(
            3.0, min_leverage=1.0, max_leverage=20.0, inst_lever_cap=3.0)
        self.assertEqual(lev, 3.0)
        self.assertFalse(tightened, "相等不算收紧")

    def test_zero_or_negative_cap_means_no_cap(self):
        for cap in (0.0, -1.0, -100.0):
            lev, tightened = leverage.clamp_ai_leverage(
                20.0, min_leverage=1.0, max_leverage=20.0, inst_lever_cap=cap)
            self.assertEqual(lev, 20.0, f"cap={cap} 应视为无上限")
            self.assertFalse(tightened)

    def test_min_missing_falls_back_to_one_not_zero(self):
        """`MIN_LEVERAGE or 0.0 or 1.0` —— 配置为 0/None 时兜底是 **1x**，不是 0x。"""
        for mn in (0.0, None):
            lev, _ = leverage.clamp_ai_leverage(
                0.0, min_leverage=mn, max_leverage=20.0, inst_lever_cap=0.0)
            self.assertEqual(lev, 1.0, f"min_leverage={mn!r} 应兜底到 1x")

    def test_max_missing_falls_back_to_twenty(self):
        for mx in (0.0, None):
            lev, _ = leverage.clamp_ai_leverage(
                100.0, min_leverage=1.0, max_leverage=mx, inst_lever_cap=0.0)
            self.assertEqual(lev, 20.0, f"max_leverage={mx!r} 应兜底到 20x")

    def test_order_matters_cap_then_floor_would_leak(self):
        """**核心不变式**：顺序必须是"先配置区间、后池值收紧"。

        若反过来（先池值、后区间），池值 0.5x 会被 `MIN_LEVERAGE=1.0` 重新抬回 1x，
        池内收紧**静默失效**。这里把错误顺序写出来，证明它确实会给出不同结果 ——
        从而说明"顺序"不是一个无关紧要的实现细节。
        """
        cap, mn, mx = 0.5, 1.0, 20.0
        good, _ = leverage.clamp_ai_leverage(
            10.0, min_leverage=mn, max_leverage=mx, inst_lever_cap=cap)
        # 错误顺序：先收紧再夹区间
        wrong = min(max(cap, mn or 1.0), mx)
        self.assertEqual(good, 0.5)
        self.assertEqual(wrong, 1.0)
        self.assertNotEqual(good, wrong, "顺序反了会让池内收紧失效 —— 必须钉住")

    def test_cap_below_config_floor_is_preserved(self):
        """池值低于配置下限时，结果就是池值（原实现没有二次下限保护）。

        这是**如实记录**而非"修好"：池文件是本地可信配置，原实现不设保护。
        若将来有人加了保护，这条会翻红，提醒他这是行为变更。
        """
        lev, tightened = leverage.clamp_ai_leverage(
            10.0, min_leverage=5.0, max_leverage=20.0, inst_lever_cap=2.0)
        self.assertEqual(lev, 2.0)
        self.assertTrue(tightened)

    def test_random_parity_with_legacy(self):
        rng = random.Random(20260924)
        vals = [0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 7.5, 20.0, 50.0, 100.0, -1.0]
        for _ in range(200000):
            a = rng.choice(vals)
            mn = rng.choice(vals + [None])
            mx = rng.choice(vals + [None])
            cap = rng.choice(vals + [None])
            kw = dict(min_leverage=mn, max_leverage=mx,
                      inst_lever_cap=0.0 if cap is None else cap)
            got = leverage.clamp_ai_leverage(a, **kw)
            exp = _legacy(a, **kw)
            self.assertEqual(got, exp, f"分叉: ai_lever={a} {kw}")

    def test_nan_and_inf_behaviour_matches_legacy(self):
        """异常输入下不得与搬走前分叉（原实现直接比较，不做 NaN 特判）。"""
        for a in (float("nan"), float("inf"), float("-inf")):
            kw = dict(min_leverage=1.0, max_leverage=20.0, inst_lever_cap=0.0)
            got = leverage.clamp_ai_leverage(a, **kw)
            exp = _legacy(a, **kw)
            # NaN != NaN，逐位比较会假红；改为比较 repr
            self.assertEqual(repr(got), repr(exp), f"ai_lever={a} 分叉")


class WiringTest(unittest.TestCase):
    def test_impl_lives_in_submodule_not_facade(self):
        facade = FACADE.read_text(encoding="utf-8")
        sub = SUBMODULE.read_text(encoding="utf-8")
        self.assertIn("def clamp_ai_leverage(", sub)
        self.assertNotIn("def clamp_ai_leverage(", facade)

    def test_facade_calls_it_once_with_injected_constants(self):
        entry = ENTRY.read_text(encoding="utf-8")
        tree = ast.parse(entry)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "clamp_ai_leverage"]
        self.assertEqual(len(calls), 1, f"应恰有 1 处调用，实际 {len(calls)}")
        args = {k.arg for k in calls[0].keywords}
        self.assertEqual(args, {"min_leverage", "max_leverage", "inst_lever_cap"},
                         "风控常量必须调用期注入（门面会被原地重载）")
        rendered = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
        self.assertEqual(rendered["min_leverage"], "MIN_LEVERAGE")
        self.assertEqual(rendered["max_leverage"], "MAX_LEVERAGE")
        self.assertEqual(rendered["inst_lever_cap"], "_inst_lever_cap")

    def test_tightened_branch_still_logs(self):
        """被池值收紧时仍要打 `[杠杆闸门]` 日志（日志文案留在门面，逐字保留）。"""
        entry = ENTRY.read_text(encoding="utf-8")
        self.assertIn("if _lever_tightened:", entry)
        self.assertIn("已按池值收紧", entry)
        self.assertIn("超出配置区间", entry)

    def test_tightened_log_reports_pre_clamp_value(self):
        """日志里的"全局 Nx"必须是**夹取前**的原始 AI 杠杆。

        原实现打印的是进入池值收紧那一刻的 `ai_lever`（已过配置区间夹取）。
        若换成夹取后的值，日志会自相矛盾（"上限 3x < 全局 3x"）。
        """
        entry = ENTRY.read_text(encoding="utf-8")
        self.assertIn("_ai_lever_raw = ai_lever", entry,
                      "必须在夹取前留存原始值供日志使用")
        self.assertIn("{_ai_lever_raw:g}x", entry,
                      "收紧日志必须报告夹取前的值")

    def test_call_site_names_are_defined(self):
        from tests.source_scan import missing_names_at_helper_calls
        offenders = missing_names_at_helper_calls(
            "scripts/ai_factor_trader.py", "execute_portfolio",
            ("clamp_ai_leverage",), pkg_name="trader")
        self.assertEqual(offenders, {},
                         f"调用点引用了未定义的名字：{offenders}")

    def test_no_risk_constants_baked_at_import(self):
        """子模块不得在 import 期绑定风控常量（否则 `pin_baseline_risk_env`
        原地重载后用的是过期快照）。"""
        sub = SUBMODULE.read_text(encoding="utf-8")
        tree = ast.parse(sub)
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {(al.asname or al.name) for al in node.names}
                for banned in ("MIN_LEVERAGE", "MAX_LEVERAGE"):
                    self.assertNotIn(banned, names,
                                     f"子模块不得 import {banned}（必须调用期注入）")


if __name__ == "__main__":
    unittest.main()
