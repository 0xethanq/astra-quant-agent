"""B3（交易员侧第十四块）`scripts/trader/pyramiding.py` 的抽取回归。

## 这个测试在守什么

金字塔加仓（pyramiding）是唯一允许"在已有持仓上再加一张"的路径，因此五条门禁
必须严。原实现在 `execute_portfolio` 的长/空两个分支里各写一份**同构、方向相反、
各自演化**的判定，抽出 `pyramiding_gate` 后只剩一份权威实现。

本文件用**搬走前的内联实现副本**做差分，并且把 **stdout 也纳入对拍** ——
`[Pyramiding] …` / `[Pyramiding 拦截] …` 会进 `executed_actions` 与巡检日志，
是事后审计加仓决策的唯一凭据。

## 为什么 stdout 必须对拍（这条是真踩出来的）

抽取过程中我替换 facade 代码块时，**把做空分支的 `c_dyn` / `c_accel` / `p_th`
三行一起吞掉了**：做空分支开始引用未定义变量，一旦实盘出现"空头浮盈加仓"
就会 `NameError`。**全量 1456 个测试当时仍是全绿** —— 因为没有任何测试执行到
这条分支。这类"只有特定实盘路径才会触发"的缺口，只能靠**逐分支、逐门禁**的
差分测试补上。本文件对长/空 × 5 条门禁分别覆盖。
"""
from __future__ import annotations

import contextlib
import io
import random
import unittest
from pathlib import Path

from scripts.trader import pyramiding

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "ai_factor_trader.py"
SUBMODULE = ROOT / "scripts" / "trader" / "pyramiding.py"
ENTRY = ROOT / "scripts" / "trader" / "entry_execution.py"   # 第九十刀：开多/开空两支现住此

# 门面的默认取值（与 execute_portfolio 调用点一致）
DEF = dict(min_scale_in_profit_ratio=0.008, max_scale_in_count=1,
           min_scale_in_confidence=75.0, asset_margin_cap=600.0)


def _legacy(*, is_long, f, pos_upl, pos_upl_ratio, pos_avg_px, curr_margin, trailing_sl,
            scale_count, c_accel, p_th, ai_margin, actual_sz, ct_val, ai_lever, ai_conf,
            min_scale_in_profit_ratio, max_scale_in_count, min_scale_in_confidence,
            asset_margin_cap):
    """搬走前 facade 里长/空两段内联实现（逐字原样，用 is_long 择一）。

    注意：这段内联代码在**调用方**（`elif` 分支入口）还有 `is_scale_in = False` /
    `allow_entry = False` 两行初值 —— 它们不属于判定本身，但缺了就 `UnboundLocalError`。
    搬到 `pyramiding_gate` 后同样要在函数内补回（本测试据此对拍）。
    """
    allow_entry = False
    is_scale_in = False
    if is_long:
        is_profit_or_breakeven = (pos_upl > 0 and pos_upl_ratio >= min_scale_in_profit_ratio) or (trailing_sl > 0 and trailing_sl >= pos_avg_px)
        planned_margin = ai_margin if ai_margin > 0 else (actual_sz * ct_val * f["price"] / max(1.0, ai_lever))
        within_margin_cap = (curr_margin + planned_margin) <= asset_margin_cap

        p_cont = float(p_th.get("continuation_prob_pct", 50.0) or 50.0)
        calculus_accel_ok = (c_accel >= -0.25 and p_cont >= 40.0)

        if is_profit_or_breakeven and scale_count < max_scale_in_count and within_margin_cap and ai_conf >= min_scale_in_confidence and calculus_accel_ok:
            allow_entry = True
            is_scale_in = True
            print(f"[Pyramiding] {f['name']} 满足顺势浮盈加多条件: 底仓浮盈={pos_upl:+.2f}U ({pos_upl_ratio*100:+.1f}%), 已加仓{scale_count}次, 微积分加速度={c_accel:+.2f}, 延续概率={p_cont:.1f}%, 计划加仓保证金 {planned_margin:.2f}U")
        else:
            if not is_profit_or_breakeven:
                print(f"[Pyramiding 拦截] {f['name']} 底仓未达浮盈保本门禁 (浮盈={pos_upl:+.2f}U ROI={pos_upl_ratio*100:+.1f}%), 严禁逆势加仓")
            elif scale_count >= max_scale_in_count:
                print(f"[Pyramiding 拦截] {f['name']} 已达最大加仓次数 ({scale_count}/{max_scale_in_count})")
            elif not within_margin_cap:
                print(f"[Pyramiding 拦截] {f['name']} 加仓后总保证金将超限 ({curr_margin + planned_margin:.1f} > {asset_margin_cap}U)")
            elif ai_conf < min_scale_in_confidence:
                print(f"[Pyramiding 拦截] {f['name']} AI加仓置信度不足 ({ai_conf:.0f}% < {min_scale_in_confidence}%)")
            elif not calculus_accel_ok:
                print(f"[Pyramiding 拦截] {f['name']} 数理动能衰竭或延续概率偏低 (加速度={c_accel:+.2f}, 概率={p_cont:.1f}%)，禁止追多加仓")
    else:
        is_profit_or_breakeven = (pos_upl > 0 and pos_upl_ratio >= min_scale_in_profit_ratio) or (trailing_sl > 0 and trailing_sl <= pos_avg_px)
        planned_margin = ai_margin if ai_margin > 0 else (actual_sz * ct_val * f["price"] / max(1.0, ai_lever))
        within_margin_cap = (curr_margin + planned_margin) <= asset_margin_cap

        p_break = float(p_th.get("breakdown_prob_pct", 50.0) or 50.0)
        calculus_accel_ok = (c_accel <= 0.25 and p_break >= 40.0)

        if is_profit_or_breakeven and scale_count < max_scale_in_count and within_margin_cap and ai_conf >= min_scale_in_confidence and calculus_accel_ok:
            allow_entry = True
            is_scale_in = True
            print(f"[Pyramiding] {f['name']} 满足顺势浮盈加空条件: 底仓浮盈={pos_upl:+.2f}U ({pos_upl_ratio*100:+.1f}%), 已加仓{scale_count}次, 微积分加速度={c_accel:+.2f}, 击穿概率={p_break:.1f}%, 计划加仓保证金 {planned_margin:.2f}U")
        else:
            if not is_profit_or_breakeven:
                print(f"[Pyramiding 拦截] {f['name']} 底仓未达浮盈保本门禁 (浮盈={pos_upl:+.2f}U ROI={pos_upl_ratio*100:+.1f}%), 严禁逆势加仓")
            elif scale_count >= max_scale_in_count:
                print(f"[Pyramiding 拦截] {f['name']} 已达最大加仓次数 ({scale_count}/{max_scale_in_count})")
            elif not within_margin_cap:
                print(f"[Pyramiding 拦截] {f['name']} 加仓后总保证金将超限 ({curr_margin + planned_margin:.1f} > {asset_margin_cap}U)")
            elif ai_conf < min_scale_in_confidence:
                print(f"[Pyramiding 拦截] {f['name']} AI加仓置信度不足 ({ai_conf:.0f}% < {min_scale_in_confidence}%)")
            elif not calculus_accel_ok:
                print(f"[Pyramiding 拦截] {f['name']} 数理动能失速企稳或击穿概率偏低 (加速度={c_accel:+.2f}, 概率={p_break:.1f}%)，禁止追空加仓")

    return allow_entry, is_scale_in


def _mk(**over):
    kw = dict(is_long=True, f={"name": "BTC", "price": 100.0}, pos_upl=5.0,
              pos_upl_ratio=0.02, pos_avg_px=95.0, curr_margin=10.0, trailing_sl=96.0,
              scale_count=0, c_accel=0.5, p_th={"continuation_prob_pct": 80.0,
                                                "breakdown_prob_pct": 20.0},
              ai_margin=50.0, actual_sz=1.0, ct_val=1.0, ai_lever=3.0, ai_conf=90.0, **DEF)
    kw.update(over)
    return kw


def _run(fn, kw):
    """跑一次实现，返回 (结果, stdout)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(**kw)
    return result, buf.getvalue()


def _both(kw):
    got = _run(pyramiding.pyramiding_gate, kw)
    exp = _run(_legacy, kw)
    return got, exp


class ImplementationMovedTest(unittest.TestCase):
    def test_impl_lives_in_submodule_not_facade(self):
        facade = FACADE.read_text(encoding="utf-8")
        sub = SUBMODULE.read_text(encoding="utf-8")
        self.assertIn("def pyramiding_gate(", sub)
        for marker in ("满足顺势浮盈加多条件", "满足顺势浮盈加空条件",
                       "数理动能衰竭或延续概率偏低", "数理动能失速企稳或击穿概率偏低"):
            self.assertIn(marker, sub, f"子模块缺少 {marker!r}")
            self.assertNotIn(marker, facade, f"门面仍留有实现体 {marker!r}")

    def test_both_branches_call_the_helper(self):
        entry = ENTRY.read_text(encoding="utf-8")
        self.assertEqual(entry.count("allow_entry, is_scale_in = pyramiding_gate("), 2,
                         "开多/开空都必须走同一个门禁实现")
        self.assertIn("is_long=True,", entry)
        self.assertIn("is_long=False,", entry)

    def test_both_call_sites_define_every_local_the_gate_needs(self):
        """调用点必须在自己**这一支**里备好传给门禁的每一个名字。

        **这条是本块最重要的回归。** 抽取时替换 facade 代码块，把做空分支的
        `c_dyn` / `c_accel` / `p_th` 三行一起吞掉了 —— 做空加仓一旦触发就
        `NameError`，而**全量 1456 个测试当时全绿**（没有测试走那条分支）。

        ## 为什么这个判据要写两遍才对

        前两版都**漏报**了，两次都是同一个根因：把"兄弟分支"当成了"本支"。

        - 第 1 版收集"函数里出现过该赋值"，于是开多分支的 `c_accel = ...`
          覆盖了开空分支的调用 —— 两条分支同属一个函数，`ast.walk` 看得见彼此。
        - 第 2 版加了行号顺序，但仍用 `ast.walk(祖先块)`：祖先块若是外层的
          `if action == "SELL_SHORT":`，`walk` 会**下钻进开多分支**，
          于是又看见了开多那行。

        正确判据：**只沿到达该调用的唯一路径**收集定义 ——
        从函数体逐层下沉，每层只看「该层内、位于通往调用那条语句之前」的语句，
        **绝不下钻进兄弟分支**。这样开多分支的赋值对开空调用不可见。
        """
        import ast
        tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
        func = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "execute_entry_scan")

        from tests.source_scan import names_defined_at_call

        checked = 0
        for node in ast.walk(func):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "pyramiding_gate"):
                continue
            passed = set()
            for arg in node.args:
                for nm in ast.walk(arg):
                    if isinstance(nm, ast.Name):
                        passed.add(nm.id)
            for kw in node.keywords:
                for nm in ast.walk(kw.value):
                    if isinstance(nm, ast.Name):
                        passed.add(nm.id)
            # 调用自己的实参绑定也算：c_accel=c_accel 之类左右同名，取右值
            available = names_defined_at_call(func, node, module_tree=tree)
            missing = sorted(n for n in passed if n not in available)
            self.assertEqual(missing, [],
                             f"gate 调用（L{node.lineno}）所在分支引用了未定义的名字 "
                             f"{missing}；实盘走到该分支时会 NameError")
            checked += 1
        self.assertEqual(checked, 2, f"应找到开多/开空两个 gate 调用，实际 {checked}")


class ParityTest(unittest.TestCase):
    def test_baseline_passes_on_both_sides(self):
        """两侧都放行：做多用加速度下限侧，做空用上限侧（见门禁方向）。"""
        for is_long in (True, False):
            kw = _mk(is_long=is_long,
                     c_accel=0.0,
                     p_th={"continuation_prob_pct": 80.0, "breakdown_prob_pct": 80.0},
                     trailing_sl=96.0 if is_long else 94.0)
            (got, gout), (exp, eout) = _both(kw)
            self.assertEqual(got, exp, f"is_long={is_long} 返回值分叉")
            self.assertEqual(gout, eout, f"is_long={is_long} stdout 分叉")
            self.assertEqual(got, (True, True), f"is_long={is_long} 应放行加仓")

    def test_each_gate_blocks_and_matches_stdout(self):
        """五条门禁各自单独破坏一次，长/空都验：返回值与 stdout 都必须一致。"""
        cases = [
            ("底仓未盈利", dict(pos_upl=0.0, pos_upl_ratio=0.0, trailing_sl=0.0)),
            ("加仓次数用尽", dict(scale_count=1)),
            ("保证金超封顶", dict(curr_margin=599.0, ai_margin=50.0)),
            ("置信度不足", dict(ai_conf=50.0)),
        ]
        for name, over in cases:
            for is_long in (True, False):
                kw = _mk(is_long=is_long, **over)
                (got, gout), (exp, eout) = _both(kw)
                self.assertEqual(got, exp, f"{name} is_long={is_long} 返回值分叉")
                self.assertEqual(gout, eout, f"{name} is_long={is_long} stdout 分叉")
                self.assertEqual(got, (False, False), f"{name} 应拦截")
                self.assertIn("Pyramiding 拦截", gout)

    def test_calculus_gate_direction_differs_by_side(self):
        """第 5 条门禁的**方向**：做多看延续概率+加速度下限，做空看击穿概率+加速度上限。"""
        # 做多：延续概率 30% → 拦截
        kw = _mk(is_long=True, p_th={"continuation_prob_pct": 30.0, "breakdown_prob_pct": 90.0})
        (got, gout), (exp, eout) = _both(kw)
        self.assertEqual((got, gout), (exp, eout))
        self.assertEqual(got, (False, False), "做多延续概率不足应拦截")
        # 做多：延续概率 90% 但加速度 -0.5 → 拦截
        kw = _mk(is_long=True, c_accel=-0.5, p_th={"continuation_prob_pct": 90.0})
        (got, gout), (exp, eout) = _both(kw)
        self.assertEqual((got, gout), (exp, eout))
        self.assertEqual(got, (False, False), "做多加速度过低应拦截")

        # 做空：击穿概率 90%、加速度 +0.5 → 放行（做空方向相反）
        kw = _mk(is_long=False, c_accel=0.0, trailing_sl=94.0,
                 p_th={"continuation_prob_pct": 10.0, "breakdown_prob_pct": 90.0})
        (got, gout), (exp, eout) = _both(kw)
        self.assertEqual((got, gout), (exp, eout))
        self.assertEqual(got, (True, True), "做空击穿概率高应放行")
        # 做空：加速度 0.9 → 拦截（超过 +0.25 上限）
        kw = _mk(is_long=False, c_accel=0.9, trailing_sl=94.0,
                 p_th={"continuation_prob_pct": 10.0, "breakdown_prob_pct": 90.0})
        (got, gout), (exp, eout) = _both(kw)
        self.assertEqual((got, gout), (exp, eout))
        self.assertEqual(got, (False, False), "做空加速度过高应拦截")

    def test_trailing_sl_direction_differs_by_side(self):
        """第 1 条门禁的**方向**：做多要求止损已推过入场价之上，做空要求之下。"""
        # 做多，止损仍在入场价下方（96 < 100）→ 不算无风险，且浮盈为 0 → 拦截
        kw = _mk(is_long=True, pos_upl=0.0, pos_upl_ratio=0.0, trailing_sl=96.0,
                 pos_avg_px=100.0)
        (got, gout), (exp, eout) = _both(kw)
        self.assertEqual((got, gout), (exp, eout))
        self.assertEqual(got, (False, False))
        # 做空，止损已在入场价下方（96 < 100）→ 算无风险 → 放行
        kw = _mk(is_long=False, pos_upl=0.0, pos_upl_ratio=0.0, trailing_sl=96.0,
                 pos_avg_px=100.0, c_accel=0.0,
                 p_th={"continuation_prob_pct": 10.0, "breakdown_prob_pct": 90.0})
        (got, gout), (exp, eout) = _both(kw)
        self.assertEqual((got, gout), (exp, eout))
        self.assertEqual(got, (True, True), "做空止损已在入场价下方应视为无风险")

    def test_planned_margin_fallback_when_ai_margin_zero(self):
        """`ai_margin == 0` 时用张数隐含额兜底 —— 两侧都要一致。"""
        for is_long in (True, False):
            kw = _mk(is_long=is_long, ai_margin=0.0, actual_sz=30.0, ct_val=1.0,
                     ai_lever=2.0, curr_margin=0.0,
                     trailing_sl=96.0 if is_long else 94.0,
                     p_th={"continuation_prob_pct": 80.0, "breakdown_prob_pct": 80.0})
            (got, gout), (exp, eout) = _both(kw)
            self.assertEqual((got, gout), (exp, eout))

    def test_random_parity(self):
        rng = random.Random(20260922)
        probs = [0.0, 10.0, 39.9, 40.0, 50.0, 70.0, 90.0, 100.0, None]
        for _ in range(5000):
            is_long = rng.random() < 0.5
            kw = _mk(
                is_long=is_long,
                pos_upl=rng.choice([-5.0, 0.0, 0.5, 5.0, 50.0]),
                pos_upl_ratio=rng.choice([-0.01, 0.0, 0.005, 0.008, 0.02, 0.1]),
                pos_avg_px=rng.choice([95.0, 100.0, 105.0]),
                curr_margin=rng.choice([0.0, 100.0, 599.0, 600.0, 700.0]),
                trailing_sl=rng.choice([0.0, 94.0, 96.0, 100.0, 101.0]),
                scale_count=rng.choice([0, 1, 2]),
                c_accel=rng.choice([-0.5, -0.25, 0.0, 0.25, 0.5, 1.0]),
                p_th={"continuation_prob_pct": rng.choice(probs),
                      "breakdown_prob_pct": rng.choice(probs)},
                ai_margin=rng.choice([0.0, 50.0]),
                ai_conf=rng.choice([0.0, 74.9, 75.0, 80.0, 90.0, 100.0]),
            )
            (got, gout), (exp, eout) = _both(kw)
            self.assertEqual(got, exp, f"返回值分叉: {kw}")
            self.assertEqual(gout, eout, f"stdout 分叉: {kw}")

    def test_both_call_sites_define_every_name_they_pass(self):
        """调用点必须在自己**这一支**里备好传给门禁的每个名字。

        **这条是本块最重要的回归。** 抽取时替换 facade 代码块，把做空分支的
        `c_dyn` / `c_accel` / `p_th` 三行一起吞掉了 —— 做空加仓一旦触发就
        `NameError`，而**全量测试当时全绿**（没有测试走那条分支）。

        走集中式守卫 `tests.source_scan.missing_names_at_helper_calls`：
        只沿**唯一到达路径**收集定义，绝不下钻进兄弟分支。该守卫自身有 16 个
        专项用例（含"兄弟分支不得泄漏""调用之后的赋值不算"），见
        `test_source_scan_domain.py`。
        """
        from tests.source_scan import missing_names_at_helper_calls

        offenders = missing_names_at_helper_calls(
            "scripts/ai_factor_trader.py", "execute_portfolio",
            (
                "pyramiding_gate",
            ),
            pkg_name="trader")
        self.assertEqual(offenders, {},
                         f"gate 调用引用了未定义的名字，实盘走到该分支会 NameError："
                         f"{offenders}")

    def test_facade_constants_are_passed_not_baked(self):
        """门面必须把风控常量作为实参传入（不得让子模块 import 期烘焙）。"""
        entry = ENTRY.read_text(encoding="utf-8")
        for kw in ("min_scale_in_profit_ratio=MIN_SCALE_IN_PROFIT_RATIO,",
                   "max_scale_in_count=MAX_SCALE_IN_COUNT,",
                   "min_scale_in_confidence=MIN_SCALE_IN_CONFIDENCE,",
                   "asset_margin_cap=ASSET_MARGIN_CAP)"):
            self.assertIn(kw, entry, f"门面未注入 {kw}")


if __name__ == "__main__":
    unittest.main()
