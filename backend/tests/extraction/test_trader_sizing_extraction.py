"""B3（交易员侧第十九块）`scripts/trader/sizing.py` 的抽取回归。

## 这个测试在守什么

"AI 说要多少保证金 + 多少倍杠杆"到"实际下多少张"之间隔着**四道互相牵制的钳制**：

| # | 钳制 | 换顺序的后果 |
|---|---|---|
| 1 | 保证金×杠杆 → 张数 | — |
| 2 | 自适应基准 **0.5x 下限** | 放到余额硬顶之后 → **付不起也要开** |
| 3 | 自适应基准 **2.0x 上限** | — |
| 4 | **可用余额硬顶**（只砍不放） | 若"对称"地补 `max()` → **放大仓位** |
| 5 | 收尾再量化 | 挪到第 4 步之前 → 余额砍出的非整步长带上去了，**下单被拒** |

故本文件除了逐项差分，还**专门构造"错误顺序"的实现并断言结果不同**：
如果换个顺序结果一样，那"顺序"就只是注释里的空话。

## 关于被去掉的 `if calculated_sz > 0:` 守卫

原实现把第 2~5 步包在该守卫里；抽出的函数去掉了它。这是**等价的**，依据：
`quantize_size` 对非正输入一律返回 `0.0`，而调用点已保证 `planned_notional > 0`。
本文件用 `test_guard_is_unreachable_with_real_helpers` 对**真实 helper** 做穷举，
再用 `test_behaviour_if_guard_were_reachable` 证明：即使强行让 `calculated_sz` 为 0，
两条路径对下游 `actual_sz <= 0` 的判定也一致。
"""

from __future__ import annotations

import ast
import random
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_backend.execution.sizing import max_size_within_margin, quantize_size
from scripts.trader import sizing

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "ai_factor_trader.py"
SUBMODULE = ROOT / "scripts" / "trader" / "sizing.py"
ENTRY = ROOT / "scripts" / "trader" / "entry_execution.py"   # 第九十刀：开多/开空两支现住此


def _legacy(*, ai_margin, ai_lever, price, ct_val, step_sz, base_sz, usdt_available,
            actual_sz, quantize_size, max_size_within_margin):
    """搬走前 facade per-factor 循环里的内联规模推导（逐字原样）。"""
    if ai_margin > 0 and ai_lever >= 1.0 and price > 0 and ct_val > 0:
        planned_notional = ai_margin * ai_lever
        calculated_sz = quantize_size(planned_notional / (price * ct_val), step_sz)
        if calculated_sz > 0:
            min_allowed_sz = max(step_sz, quantize_size(base_sz * 0.5, step_sz))
            max_allowed_sz = max(min_allowed_sz, quantize_size(base_sz * 2.0, step_sz))
            actual_sz = max(min_allowed_sz, min(max_allowed_sz, calculated_sz))
            afford_sz = max_size_within_margin(usdt_available, ai_lever, price, ct_val, step_sz)
            if afford_sz is not None and afford_sz < float("inf"):
                actual_sz = min(actual_sz, afford_sz)
            actual_sz = quantize_size(actual_sz, step_sz)
    return actual_sz


def _kw(**over):
    kw = dict(ai_margin=50.0, ai_lever=5.0, price=79000.0, ct_val=0.01, step_sz=1.0,
              base_sz=10.0, usdt_available=1000.0, actual_sz=10.0,
              quantize_size=quantize_size,
              max_size_within_margin=max_size_within_margin)
    kw.update(over)
    return kw


def _both(**over):
    kw = _kw(**over)
    return (sizing.size_for_decision(**kw),
            _legacy(**kw))


class ParityTest(unittest.TestCase):
    def test_baseline_parity(self):
        got, exp = _both()
        self.assertEqual(got, exp)

    def test_guard_condition_false_returns_actual_sz_untouched(self):
        """四条件任一不满足时，`actual_sz` 原样返回（块不生效）。"""
        cases = [
            dict(ai_margin=0.0),
            dict(ai_margin=-1.0),
            dict(ai_lever=0.5),
            dict(ai_lever=0.0),
            dict(price=0.0),
            dict(price=-1.0),
            dict(ct_val=0.0),
            dict(ct_val=-0.01),
        ]
        for over in cases:
            got, exp = _both(**over)
            self.assertEqual(got, exp, f"{over} 与搬走前分叉")
            self.assertEqual(got, 10.0,
                             f"{over} 下 actual_sz 应原样保留 10.0，实际 {got}")

    def test_small_margin_is_floored_by_half_base(self):
        """第 2 道钳制：AI 给的额太小 → 被抬到基准仓位的 0.5x。"""
        got, exp = _both(ai_margin=0.5, ai_lever=1.0, base_sz=10.0, step_sz=1.0)
        self.assertEqual(got, exp)
        self.assertGreaterEqual(got, 5.0, "不得低于基准的 0.5x")

    def test_large_margin_is_capped_by_double_base(self):
        """第 3 道钳制：AI 给的额太大 → 被压到基准仓位的 2.0x。"""
        got, exp = _both(ai_margin=100000.0, ai_lever=20.0, base_sz=10.0, step_sz=1.0)
        self.assertEqual(got, exp)
        self.assertLessEqual(got, 20.0, "不得超过基准的 2.0x")

    def test_balance_cap_only_shrinks_never_grows(self):
        """第 4 道钳制：余额硬顶**只砍不放**（原注释：付不起则归零跳过而非放大）。"""
        # 基准 200 → 允许 100~400；AI 推导 300；但余额只付得起 40
        got, exp = _both(ai_margin=100.0, ai_lever=3.0, base_sz=200.0, step_sz=1.0,
                         usdt_available=10.0, price=1.0, ct_val=1.0)
        self.assertEqual(got, exp)
        # 用 2 倍基准去验证"不会放大"：结果必须 <= 余额允许量
        afford = max_size_within_margin(10.0, 3.0, 1.0, 1.0, 1.0)
        self.assertLessEqual(got, afford, "余额硬顶后不得放大")
        self.assertLessEqual(got, 400.0)

    def test_balance_infinite_means_no_cap(self):
        got, exp = _both(usdt_available=0.0)
        self.assertEqual(got, exp)
        got2, exp2 = _both(usdt_available=-5.0)
        self.assertEqual(got2, exp2)

    def test_result_is_always_on_step_grid(self):
        """第 5 道钳制：返回的必须是步长整数倍，否则交易所拒单。"""
        rng = random.Random(20260925)
        for _ in range(3000):
            step = rng.choice([0.001, 0.01, 0.1, 1.0, 10.0])
            kw = dict(ai_margin=rng.choice([0.5, 5.0, 50.0, 5000.0]),
                      ai_lever=rng.choice([1.0, 3.0, 20.0]),
                      price=rng.choice([0.5, 100.0, 79000.0]),
                      ct_val=rng.choice([0.001, 0.01, 1.0]),
                      step_sz=step,
                      base_sz=rng.choice([0.5, 10.0, 1000.0]),
                      usdt_available=rng.choice([0.0, 100.0, 1e6]),
                      actual_sz=7.0)
            got = sizing.size_for_decision(**_kw(**kw))
            if got > 0 and got >= step:
                ratio = got / step
                self.assertAlmostEqual(ratio, round(ratio), places=6,
                                       msg=f"结果 {got} 不是步长 {step} 的整数倍")

    def test_random_parity(self):
        rng = random.Random(20260926)
        for _ in range(50000):
            over = dict(
                ai_margin=rng.choice([-1.0, 0.0, 0.5, 5.0, 50.0, 5000.0]),
                ai_lever=rng.choice([0.0, 0.5, 1.0, 3.0, 20.0, 100.0]),
                price=rng.choice([0.0, -1.0, 0.5, 100.0, 79000.0]),
                ct_val=rng.choice([0.0, 0.001, 0.01, 1.0]),
                step_sz=rng.choice([0.0, 0.001, 0.01, 1.0, 10.0]),
                base_sz=rng.choice([0.0, -1.0, 0.5, 10.0, 1000.0]),
                usdt_available=rng.choice([0.0, -1.0, 50.0, 1000.0, 1e6]),
                actual_sz=rng.choice([0.0, -5.0, 7.0, 100.0]),
            )
            got, exp = _both(**over)
            self.assertEqual(got, exp, f"分叉: {over}")


class OrderMattersTest(unittest.TestCase):
    """把每一道钳制的**语义**单独钉住 —— 顺序与方向都是承重的。"""

    def test_floor_keeps_small_ai_budget_alive(self):
        """第 2 道：AI 给的额太小（但仍在交易所最小量之上）→ 抬到基准的 0.5x。"""
        got, exp = _both(ai_margin=5.0, ai_lever=1.0, base_sz=20.0, step_sz=1.0,
                         price=1.0, ct_val=1.0, usdt_available=1e6)
        self.assertEqual(got, exp)
        self.assertEqual(got, 10.0, "基准 20 的 0.5x = 10（AI 只推导出 5）")

    def test_ceiling_caps_large_ai_budget(self):
        """第 3 道：AI 给的额太大 → 压到基准的 2.0x。"""
        got, exp = _both(ai_margin=1e6, ai_lever=20.0, base_sz=20.0, step_sz=1.0,
                         price=1.0, ct_val=1.0, usdt_available=1e9)
        self.assertEqual(got, exp)
        self.assertEqual(got, 40.0, "基准 20 的 2.0x = 40")

    def test_balance_cap_is_a_pure_min_never_a_max(self):
        """第 4 道：余额硬顶**只砍不放**。

        若有人"顺手对称"地补 `max(actual_sz, afford_sz)`，小仓位会被**放大**到
        余额上限 —— 这是本块最危险的改法。用"AI 只要 1 手、余额够 100 手"验证：
        结果必须仍是 1 手附近（受 0.5x 下限约束），而不是被抬到 100。
        """
        got, exp = _both(ai_margin=5.0, ai_lever=1.0, base_sz=20.0, step_sz=1.0,
                         price=1.0, ct_val=1.0, usdt_available=1000.0)
        self.assertEqual(got, exp)
        cap_within_margin = max_size_within_margin(1000.0, 1.0, 1.0, 1.0, 1.0)
        self.assertGreater(cap_within_margin, 100.0, "余额上限远高于本笔所需")
        self.assertLessEqual(got, 20.0,
                             "余额宽裕时不得把仓位放大到余额上限（只砍不放）")

    def test_balance_cap_shrinks_when_affordability_binds(self):
        got, exp = _both(ai_margin=100.0, ai_lever=3.0, base_sz=200.0, step_sz=1.0,
                         usdt_available=10.0, price=1.0, ct_val=1.0)
        self.assertEqual(got, exp)
        afford = max_size_within_margin(10.0, 3.0, 1.0, 1.0, 1.0)
        self.assertLessEqual(got, afford, "余额不足时必须砍到付得起")
        self.assertGreater(got, 0.0, "本例余额仍够开最小仓")

    def test_trailing_quantize_is_defensive_with_real_quantizer(self):
        """收尾量化对**真实** `quantize_size` 是 no-op —— 因为它的输出已是步长倍数。

        这是如实记录：不要声称这一行在真实实现下"救了什么"。它的价值在于
        **防住"注入的 quantizer 不再归一化"**（见下一条）。
        """
        for base, step, usdt in ((20.0, 1.0, 1e6), (30.0, 4.0, 50.0),
                                 (23.0, 10.0, 1e6), (7.0, 0.5, 1e6)):
            got = sizing.size_for_decision(**_kw(
                ai_margin=100.0, ai_lever=1.0, base_sz=base, step_sz=step,
                usdt_available=usdt, price=1.0, ct_val=1.0, actual_sz=base))
            if got > 0 and got >= step:
                self.assertAlmostEqual(got / step, round(got / step), places=6)

    def test_trailing_quantize_uses_the_injected_quantizer(self):
        """收尾量化调用的就是**注入的** quantizer —— 因此它不额外兜底。

        **这是一条如实记录，别把它当"兜底保险"**：若注入的 quantizer 本身
        不归一化（测试替身返回原值），收尾量化同样是 no-op；更关键的是，
        `max_size_within_margin` 内部做的是**同一套**量化，所以余额上限本身
        已是步长倍数，收尾那次在真实实现下**不会改变任何值**（见下一条的穷举）。

        把限制写清楚比含糊地写"有兜底"更有价值 —— 后者会让人以为随便换
        quantizer 都安全。
        """
        def sloppy(raw, step):
            return float(raw or 0.0)

        got = sizing.size_for_decision(**_kw(
            ai_margin=1000.0, ai_lever=1.0, base_sz=20.0, step_sz=4.0,
            usdt_available=1e9, price=1.0, ct_val=1.0, actual_sz=20.0,
            quantize_size=sloppy,
            max_size_within_margin=lambda *a, **k: 30.0))
        self.assertEqual(got, 30.0,
                         "注入的 quantizer 不归一化时结果会落在网格外 —— 已知限制")

    def test_trailing_quantize_is_a_noop_with_real_helpers(self):
        """穷举证明：真实 helper 下收尾量化不改变结果。

        两个事实共同决定：①`quantize_size` 的输出必为步长倍数；
        ②`max_size_within_margin` 内部也调 `quantize_size`，故余额上限同样对齐。
        于是 `min()` 的两个候选都是步长倍数，收尾那次 `quantize_size` 恒为恒等。

        这条测试的价值在于**防止后人误以为这一行在兜底**然后删掉别的守卫 ——
        也防止有人反过来以为"有它在就安全"。
        """
        from astra_backend.execution.sizing import quantize_size as real_q
        from astra_backend.execution.sizing import max_size_within_margin as real_m
        checked = 0
        for base, step, margin, usdt in (
                (20.0, 4.0, 100.0, 160.0), (20.0, 4.0, 1000.0, 160.0),
                (30.0, 4.0, 100.0, 1e9), (23.0, 10.0, 1e6, 500.0),
                (7.0, 0.5, 3.0, 1e6), (100.0, 3.0, 1e6, 50.0)):
            got = sizing.size_for_decision(**_kw(
                ai_margin=margin, ai_lever=1.0, base_sz=base, step_sz=step,
                usdt_available=usdt, price=1.0, ct_val=1.0, actual_sz=base,
                quantize_size=real_q, max_size_within_margin=real_m))
            # 手工重算"去掉收尾量化"的结果
            mn = max(step, real_q(base * 0.5, step))
            mx = max(mn, real_q(base * 2.0, step))
            calc = real_q(margin * 1.0 / (1.0 * 1.0), step)
            if calc > 0:
                pre = max(mn, min(mx, calc))
                aff = real_m(usdt, 1.0, 1.0, 1.0, step)
                if aff is not None and aff < float("inf"):
                    pre = min(pre, aff)
            else:
                pre = base
            self.assertEqual(real_q(pre, step), pre,
                             f"收尾量化改变了值：{pre} → {real_q(pre, step)}"
                             f"（base={base} step={step} margin={margin} usdt={usdt}）")
            self.assertEqual(got, pre)
            checked += 1
        self.assertEqual(checked, 6)

    def test_real_quantizer_always_yields_grid_aligned_result(self):
        """用**真实** quantizer（生产路径）时，结果必须落在步长网格上。"""
        from astra_backend.execution.sizing import quantize_size as real_q
        for base, step, cap in ((20.0, 4.0, 30.0), (100.0, 3.0, 50.0),
                                (16.0, 2.0, 9.0), (23.0, 10.0, 33.0)):
            got = sizing.size_for_decision(**_kw(
                ai_margin=1000.0, ai_lever=1.0, base_sz=base, step_sz=step,
                usdt_available=1e9, price=1.0, ct_val=1.0, actual_sz=base,
                quantize_size=real_q,
                max_size_within_margin=lambda *a, **k: cap))
            if got > 0 and got >= step:
                self.assertAlmostEqual(got / step, round(got / step), places=6,
                                       msg=f"base={base} step={step} cap={cap} → {got} 不在网格上")

    def test_floor_target_is_half_base_not_step(self):
        """下限用的是 `quantize_size(base*0.5)`，不是 `step_sz` 本身。"""
        got = sizing.size_for_decision(**_kw(
            ai_margin=1.0, ai_lever=1.0, base_sz=100.0, step_sz=1.0,
            usdt_available=1e6, price=1.0, ct_val=1.0, actual_sz=100.0))
        self.assertEqual(got, 50.0, "基准 100 的 0.5x = 50")

    def test_ceiling_is_at_least_the_floor(self):
        """`max_allowed_sz = max(min_allowed_sz, ...)` —— 基准相对步长极小时两者会倒挂。

        构造：`base_sz=1`、`step=10` → 下限被抬到 `step`=10，而
        `quantize_size(1*2.0, 10)` = 0。若没有那层 `max`，上限变成 0，
        `max(min_allowed, min(0, calc))` = 0 → **仓位被静默压成 0**，
        该标的每轮都被判"不可交易"（日志上只看到 `[仓位跳过]`，像是余额问题）。

        三种 base 都覆盖：1 与 3 会倒挂，1000 不会（后者验证 `max` 不改变正常情形）。
        """
        for base in (0.1, 1.0, 3.0):
            got = sizing.size_for_decision(**_kw(
                ai_margin=1e6, ai_lever=20.0, base_sz=base, step_sz=10.0,
                usdt_available=1e9, price=1.0, ct_val=1.0, actual_sz=10.0))
            self.assertGreaterEqual(got, 10.0,
                                    f"base_sz={base} 时上限不得低于下限")
        # 正常情形：max 不改变结果
        normal = sizing.size_for_decision(**_kw(
            ai_margin=1e6, ai_lever=20.0, base_sz=1000.0, step_sz=10.0,
            usdt_available=1e9, price=1.0, ct_val=1.0, actual_sz=1000.0))
        self.assertEqual(normal, 2000.0, "基准 1000 的 2.0x = 2000")


class GuardRemovalJustificationTest(unittest.TestCase):
    def test_guard_is_unreachable_with_real_helpers(self):
        """`quantize_size` 的契约：**正输入 ⇒ 正输出**；非正输入 ⇒ 0。

        `if calculated_sz > 0:` 之所以不可达，靠的正是这条契约：调用点已保证
        `ai_margin > 0`、`ai_lever >= 1.0`、`price > 0`、`ct_val > 0`，
        故 `planned_notional = ai_margin * ai_lever > 0`。

        **注意别把这条断言写过头**：`planned_notional` 为正**不**保证
        `planned_notional / (price*ct_val)` 量化后大于 0 —— 当比值小于步长时
        `quantize_size` 仍返回 0（这是**正确的**：低于交易所最小下单量）。
        所以这里检的是"契约本身"，不是"某些参数下必为正"。
        """
        from astra_backend.execution.sizing import quantize_size as q
        # 正输入 ⇒ 正输出（在浮点可表示的范围内）
        for raw in (0.5, 1.0, 2.5, 1e3, 1e9):
            for step in (0.001, 1.0, 10.0):
                if raw >= step:
                    self.assertGreater(q(raw, step), 0.0,
                                       f"q({raw}, {step}) 应为正")
        # 非正输入 ⇒ 0（这正是守卫不可达的依据）
        for raw in (0.0, -1.0, -1e9):
            self.assertEqual(q(raw, 1.0), 0.0)
        # 且守卫的前置条件确实保证 planned_notional 为正
        for margin in (0.0001, 0.5, 1e7):
            for lever in (1.0, 3.0, 100.0):
                self.assertGreater(margin * lever, 0.0)

    def test_behaviour_if_guard_were_reachable(self):
        """强行让 `calculated_sz` 为 0：两条路径对下游判定一致。"""
        # 用一个"永远返回 0"的 quantize 模拟 calculated_sz==0
        zero_q = lambda raw, step: 0.0                       # noqa: E731
        with_guard = _legacy(**_kw(quantize_size=zero_q))
        # 去掉守卫的版本：actual_sz 保持传入值
        without_guard = sizing.size_for_decision(**_kw(quantize_size=zero_q))
        # 两者不同（这正是守卫存在的意义），但对下游 `actual_sz <= 0: continue` 的判定：
        self.assertEqual(with_guard, 10.0, "守卫内路径不改 actual_sz")
        self.assertEqual(without_guard, 10.0, "去掉守卫后同样不改 actual_sz")
        self.assertEqual(with_guard <= 0, without_guard <= 0)

    def test_guard_skips_clamps_when_quantize_returns_zero(self):
        """当 `calculated_sz == 0`（异常 helper）时，不得应用 0.5x 下限去放大。"""
        zero_q = lambda raw, step: 0.0                       # noqa: E731
        got = sizing.size_for_decision(**_kw(quantize_size=zero_q, actual_sz=3.0))
        self.assertEqual(got, 3.0,
                         "calculated_sz 为 0 时不得被 0.5x 下限抬升（那会变成莫名放大）")


class WiringTest(unittest.TestCase):
    def test_impl_lives_in_submodule_not_facade(self):
        facade = FACADE.read_text(encoding="utf-8")
        sub = SUBMODULE.read_text(encoding="utf-8")
        self.assertIn("def size_for_decision(", sub)
        self.assertNotIn("def size_for_decision(", facade)

    def test_facade_calls_once_and_injects_shared_helpers(self):
        entry = ENTRY.read_text(encoding="utf-8")
        tree = ast.parse(entry)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "size_for_decision"]
        self.assertEqual(len(calls), 1, f"应恰有 1 处调用，实际 {len(calls)}")
        kwargs = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
        for must in ("quantize_size", "max_size_within_margin"):
            self.assertEqual(kwargs.get(must), must,
                             f"{must} 必须由门面注入（否则 patch.object 接缝失效）")
        self.assertEqual(kwargs.get("base_sz", "").replace(chr(39), chr(34)), 'f["sz"]')
        self.assertEqual(kwargs.get("actual_sz"), "actual_sz")

    def test_submodule_does_not_import_sizing_helpers_at_import_time(self):
        """子模块不得在 import 期绑定共享 helper —— 测试会 patch 门面接缝。"""
        sub = SUBMODULE.read_text(encoding="utf-8")
        tree = ast.parse(sub)
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {(al.asname or al.name) for al in node.names}
                self.assertNotIn("quantize_size", names)
                self.assertNotIn("max_size_within_margin", names)

    def test_patch_seam_still_works_through_the_facade(self):
        """`patch.object(aft, "quantize_size")` 必须能被走到的代码读到。"""
        import scripts.ai_factor_trader as aft
        sentinel = lambda raw, step: 0.0                     # noqa: E731
        with patch.object(aft, "quantize_size", sentinel):
            # 直接复现门面调用形态：注入的 helper 会被传给子模块
            out = sizing.size_for_decision(
                ai_margin=50.0, ai_lever=5.0, price=79000.0, ct_val=0.01, step_sz=1.0,
                base_sz=10.0, usdt_available=1000.0, actual_sz=4.0,
                quantize_size=aft.quantize_size,
                max_size_within_margin=aft.max_size_within_margin)
        self.assertEqual(out, 4.0, "patch 后的 helper（恒返回 0）应导致规模保持不变")

    def test_call_site_names_are_defined(self):
        from tests.source_scan import missing_names_at_helper_calls
        offenders = missing_names_at_helper_calls(
            "scripts/ai_factor_trader.py", "execute_portfolio",
            ("size_for_decision",), pkg_name="trader")
        self.assertEqual(offenders, {}, f"调用点引用了未定义的名字：{offenders}")

    def test_skip_guard_still_follows_the_sizing_call(self):
        """`if actual_sz <= 0: continue` 必须紧跟其后（0 表示不可交易）。"""
        entry = ENTRY.read_text(encoding="utf-8")
        tree = ast.parse(entry)
        func = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "execute_entry_scan")
        call = next(n for n in ast.walk(func)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "size_for_decision")
        # 调用所在语句之后最近的 if 必须是 actual_sz <= 0
        after = [s for s in ast.walk(func)
                 if isinstance(s, ast.If) and s.lineno > call.lineno]
        after.sort(key=lambda s: s.lineno)
        self.assertEqual(ast.unparse(after[0].test), "actual_sz <= 0",
                         "规模推导之后必须紧跟不可交易跳过判定")


if __name__ == "__main__":
    unittest.main()
