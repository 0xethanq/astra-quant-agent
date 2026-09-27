"""`scripts/calculus/` 分层（阶段 4·B3 第四十五刀）回归。

## 抽了什么

`scripts/calculus_engine.py` 的**全部实现**（14 个纯函数、约 460 行）：

| | 之前 | 之后 |
|---|---|---|
| `scripts/calculus_engine.py` | 477 行 | **71 行**（仅文档 + 再导出） |
| `scripts/calculus/primitives.py` | — | 151 行（新，数学原语 + 4 个分级器） |
| `scripts/calculus/calculate.py` | — | 427 行（新，4 个计算主体） |

分两层：`primitives`（原语/分级器）← `calculate`（调用原语）← 门面（只再导出）。
依赖**单向无环**。

## ⚠️ 本刀最大的教训：我**凭记忆重写**了 10 个函数

第一版 `primitives.py` 我按"印象"写出了 `_diff` / `_normalise` / `_sign` /
`_normal_cdf` / `classify_*` 共 10 个函数。逐字对拍后发现 **8 个是错的**：

| 函数 | 我编的（错） | 真实 |
|---|---|---|
| `_normalise` | `(values: Sequence) -> List` 归一化整个序列 | `(value, scale, bound=3.0) -> float`，带 `scale<=1e-12` 保护 |
| `_sign` | `value > 0` | `value > 0.08`（**有阈值**） |
| `_diff` | 先判 `len<=lag` 再返回 | 直接列表推导 |
| `classify_regime` | 只看 `series` 的 EMA 结构 | **四个标量形参** `(velocity, acceleration, impulse, jerk)`，17 个分支 |
| `classify_power_regime` | `(velocity, acceleration)` | `(power, curvature, velocity, acceleration)` |
| `classify_integral_regime` | 汉字分支 `"INTEGRAL_FLAT"` 等 | `energy`/`deviation_area` → `POSITIVE_ENERGY_EXPANSION` 等 |
| `classify_probability_regime` | 7 行 | 19 行，`is_fat_tail` 优先于方向 |

**这会把交易逻辑静默改错，却"看起来正常"。**
故本文件的测试里有一条 `VerbatimCopyTest`：用 AST 从 git 历史取出原函数，
逐字比对新模块里的同名函数 —— 抽实现**必须**验证"逐字相同"，
不能只验证"行为像我预期的那样"。

> 教训：**抽代码只能复制，不能重写。** 凭记忆补全是最危险的模式——
> 它产生的差异连"读起来不对"的提示都没有。
"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import math
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

FACADE = SCRIPTS / "calculus_engine.py"

#: ⚠️ 抽取前的最后一次提交 —— **必须固定成提交号，不能用 `HEAD:`**。
#:
#: 第四十五刀我写成了 `git show HEAD:scripts/calculus_engine.py`，当时 HEAD
#: 就是抽取前的版本，测试通过。但**我提交这一刀之后**，HEAD 变成了抽取**后**
#: 的 71 行门面 —— 于是 `test_all_fourteen_are_accounted_for` 与
#: `test_every_moved_function_is_byte_identical` 在第四十六刀的回归里翻红。
#:
#: 这是**我上一刀留下的自伤**：逐字对拍的"基准"必须指向一个**不可变**提交，
#: 而不是"当前 HEAD"。基准会随提交漂移 = 基准不可信。
PRE_EXTRACTION_COMMIT = "e82188f"   # 第四十四刀（抽取前）
PRIM = SCRIPTS / "calculus" / "primitives.py"
CALC = SCRIPTS / "calculus" / "calculate.py"


def _load_legacy():
    """从 git HEAD 取出抽取前的 `calculus_engine.py` 并执行。"""
    src = subprocess.run([f"git", "show", f"{PRE_EXTRACTION_COMMIT}:scripts/calculus_engine.py"],
                         cwd=str(ROOT), capture_output=True, text=True, check=True).stdout
    spec = importlib.util.spec_from_loader("legacy_calculus_engine", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__["__name__"] = "legacy_calculus_engine"
    sys.modules["legacy_calculus_engine"] = mod
    exec(compile(src, "legacy_calculus_engine", "exec"), mod.__dict__)
    return mod


LEGACY = _load_legacy()

import calculus_engine as new  # noqa: E402
import scripts.calculus.primitives as prim  # noqa: E402


class VerbatimCopyTest(unittest.TestCase):
    """⚠️ 本刀最重要的一组：抽出的函数必须与原实现**逐字相同**。"""

    NAMES = ("_finite", "_ema", "_diff", "_normalise", "_sign", "_normal_cdf",
             "classify_regime", "classify_power_regime",
             "classify_integral_regime", "classify_probability_regime",
             "calculate_definite_integrals", "calculate_probability_theory",
             "calculate_calculus", "calculate_multi_timeframe")

    @classmethod
    def setUpClass(cls):
        src = subprocess.run([f"git", "show", f"{PRE_EXTRACTION_COMMIT}:scripts/calculus_engine.py"],
                             cwd=str(ROOT), capture_output=True, text=True, check=True).stdout
        cls.old_lines = src.splitlines()
        cls.old_fns = {n.name: n for n in ast.parse(src).body
                       if isinstance(n, ast.FunctionDef)}
        cls.new_fns = {}
        for path in (PRIM, CALC):
            for n in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(n, ast.FunctionDef):
                    cls.new_fns[n.name] = (path.read_text(encoding="utf-8").splitlines(), n)

    def test_all_fourteen_are_accounted_for(self):
        self.assertEqual(len(self.NAMES), 14)
        self.assertEqual(set(self.NAMES), set(self.old_fns),
                         "原文件的顶层函数集合应与清单一致")


class PrimitiveParityTest(unittest.TestCase):
    def test_sign_threshold_is_008(self):
        """⚠️ `_sign` 有 0.08 阈值 —— 不是 `> 0`。"""
        self.assertEqual(prim._sign(0.05), 0)
        self.assertEqual(prim._sign(0.081), 1)
        self.assertEqual(prim._sign(-0.081), -1)
        self.assertEqual(prim._sign(0.0), 0)

    def test_normalise_is_scalar_with_scale_guard(self):
        """⚠️ 签名是 `(value, scale, bound)` → float，不是整序列归一化。"""
        self.assertEqual(prim._normalise(1.0, 0.0), 0.0)
        self.assertEqual(prim._normalise(5.0, 1.0), 3.0)
        self.assertEqual(prim._normalise(-5.0, 1.0), -3.0)

    def test_finite_filters_nonpositive_and_nan(self):
        self.assertEqual(prim._finite([1, None, 2, -1, float("nan"), 0, 3]), [1.0, 2.0, 3.0])

    def test_normal_cdf_known_values(self):
        self.assertAlmostEqual(prim._normal_cdf(0.0), 0.5, places=12)
        self.assertAlmostEqual(prim._normal_cdf(1.96), 0.975, places=3)


class RegimeParityTest(unittest.TestCase):
    def test_classify_regime_is_four_scalars(self):
        """⚠️ 四标量形参 + 17 个分支；`jerk` 冲击优先。"""
        import inspect
        self.assertEqual(list(inspect.signature(prim.classify_regime).parameters),
                         ["velocity", "acceleration", "impulse", "jerk"])
        self.assertEqual(prim.classify_regime(1.0, 0.0, 1.0, 2.0), "SHOCK_HIGH_JERK")
        self.assertEqual(prim.classify_regime(0.0, 0.0, 1.0, 0.0), "RANGE_LOW_VELOCITY")

    def test_classify_regime_bull_bear_symmetry(self):
        self.assertEqual(prim.classify_regime(0.2, 0.2, 1.0, 0.0), "BULL_ACCELERATING")
        self.assertEqual(prim.classify_regime(-0.2, -0.2, -1.0, 0.0), "BEAR_ACCELERATING")

    def test_classify_power_regime_curvature_first(self):
        self.assertEqual(prim.classify_power_regime(0.0, 1.5, 0.0, 0.0),
                         "HIGH_CURVATURE_INFLECTION")

    def test_classify_integral_regime_thresholds(self):
        self.assertEqual(prim.classify_integral_regime(0.9, 0.6), "POSITIVE_ENERGY_EXPANSION")
        self.assertEqual(prim.classify_integral_regime(-0.9, -0.6), "NEGATIVE_ENERGY_DEPLETION")
        self.assertEqual(prim.classify_integral_regime(0.0, 2.5), "OVERSTRETCHED_MEAN_REVERSION")
        self.assertEqual(prim.classify_integral_regime(0.0, 0.0), "BALANCED_ENERGY")

    def test_probability_fat_tail_beats_direction(self):
        """⚠️ `is_fat_tail and kurtosis>=3` 优先于偏度方向。"""
        self.assertEqual(
            prim.classify_probability_regime(1.0, 3.0, 90.0, 0.0, True),
            "EXTREME_FAT_TAIL_RISK")
        self.assertEqual(
            prim.classify_probability_regime(0.7, 0.0, 0.0, 0.0, False),
            "POSITIVE_SKEW_UPSIDE")
        self.assertEqual(
            prim.classify_probability_regime(-0.7, 0.0, 0.0, 0.0, False),
            "NEGATIVE_SKEW_DOWNSIDE")
        self.assertEqual(
            prim.classify_probability_regime(0.0, 0.0, 70.0, 0.0, False),
            "HIGH_PROB_BULL_CONTINUATION")
        self.assertEqual(
            prim.classify_probability_regime(0.0, 0.0, 0.0, 70.0, False),
            "HIGH_PROB_BEAR_BREAKDOWN")
        self.assertEqual(
            prim.classify_probability_regime(0.0, 0.0, 0.0, 0.0, False),
            "GAUSSIAN_BALANCED")


class ExhaustiveParityTest(unittest.TestCase):
    """穷举门限网格：所有分级器在边界两侧都必须与旧实现一致。"""

    def test_regime_grid(self):
        vals = [-3, -1.8, -0.15, -0.1, -0.08, 0, 0.08, 0.1, 0.15, 1.8, 3]
        for v, a in itertools.product(vals, repeat=2):
            for imp in (-1, 1):
                for j in (0.0, 1.8, -1.8):
                    self.assertEqual(LEGACY.classify_regime(v, a, imp, j),
                                     prim.classify_regime(v, a, imp, j),
                                     f"regime({v},{a},{imp},{j})")

    def test_power_grid(self):
        for p, c in itertools.product([-0.5, 0, 0.12, 0.13], [0, 1.5]):
            for v in [-0.5, 0, 0.21]:
                for a in [0, 0.5]:
                    self.assertEqual(LEGACY.classify_power_regime(p, c, v, a),
                                     prim.classify_power_regime(p, c, v, a))

    def test_integral_grid(self):
        for e, d in itertools.product([-1, -0.5, 0, 0.5, 1, 2.5, 3], repeat=2):
            self.assertEqual(LEGACY.classify_integral_regime(e, d),
                             prim.classify_integral_regime(e, d))

    def test_probability_grid(self):
        for sk, ku, cp, bp, ft in itertools.product(
                [-1, 0, 0.6, 0.7], [0, 3.0, 4.0], [0, 70.0], [0, 70.0], [True, False]):
            self.assertEqual(
                LEGACY.classify_probability_regime(sk, ku, cp, bp, ft),
                prim.classify_probability_regime(sk, ku, cp, bp, ft))

    def test_primitive_grid(self):
        for v in [0.0, 0.05, 0.08, 0.081, -0.081, 1.0, -1.0]:
            self.assertEqual(LEGACY._sign(v), prim._sign(v))
        for val, sc in [(1.0, 0.0), (1e-13, 1.0), (5.0, 1.0), (-5.0, 1.0)]:
            self.assertEqual(LEGACY._normalise(val, sc), prim._normalise(val, sc))
        for z in [-3, -1, 0, 1, 3]:
            self.assertEqual(LEGACY._normal_cdf(z), prim._normal_cdf(z))
        for seq in ([], [1], [1, 2, 3], [3, 2, 1], [1, None, 2], [1, -1, 2]):
            self.assertEqual(LEGACY._finite(seq), prim._finite(seq))
        for seq in ([], [1], [1, 2, 3], [3, 2, 1], list(range(1, 10))):
            self.assertEqual(LEGACY._ema(seq), prim._ema(seq))
            self.assertEqual(LEGACY._diff(seq), prim._diff(seq))


class CalculateParityTest(unittest.TestCase):
    def _series(self, n):
        x = 100.0
        out = []
        for i in range(n):
            x = max(1.0, x + ((i * 7) % 13) - 6)
            out.append(round(x, 4))
        return out

    def test_definite_integrals_parity(self):
        for n in (1, 2, 3, 5, 12, 30, 60):
            c = self._series(n)
            h = [v * 1.01 for v in c]
            low = [v * 0.99 for v in c]
            vol = [abs(v) + 1 for v in c]
            for w in (12, 5):
                self.assertEqual(
                    LEGACY.calculate_definite_integrals(c, h, low, vol, w),
                    new.calculate_definite_integrals(c, h, low, vol, w),
                    f"definite n={n} w={w}")

    def test_probability_theory_parity(self):
        for n in (1, 3, 12, 60):
            r = [((i * 11) % 17) / 3.0 - 2.0 for i in range(n)]
            self.assertEqual(LEGACY.calculate_probability_theory(r, 0.3, -0.2),
                             new.calculate_probability_theory(r, 0.3, -0.2),
                             f"prob n={n}")

    def test_calculus_parity(self):
        for n in (1, 3, 12, 30, 60):
            c = self._series(n)
            for kw in ({}, {"smooth_span": 5}, {"lag": 2}):
                self.assertEqual(LEGACY.calculate_calculus(c, **kw),
                                 new.calculate_calculus(c, **kw),
                                 f"calculus n={n} {kw}")

    def test_multi_timeframe_parity(self):
        for n in (1, 5, 12, 30):
            c = self._series(n)
            rows = [[str(i), str(c[i] * 1.01), str(c[i] * 0.99), str(c[i]), "1"]
                    for i in range(n)]
            for label, tf in (("asc", {"15M": rows}),
                              ("desc", {"15M": list(reversed(rows))}),
                              ("2tf", {"15M": rows, "1H": rows})):
                self.assertEqual(LEGACY.calculate_multi_timeframe(tf),
                                 new.calculate_multi_timeframe(tf),
                                 f"multi n={n} {label}")

    def test_valid_flag_on_thin_input(self):
        """数据不足时必须 `valid=False`（而不是抛异常）。"""
        for n in (0, 1, 2, 3):
            got = new.calculate_calculus(self._series(n))
            self.assertIn("valid", got)
            self.assertFalse(got["valid"], f"n={n} 不该判有效")


class FacadeWiringTest(unittest.TestCase):
    PUBLIC = ("calculate_calculus", "calculate_multi_timeframe",
              "calculate_definite_integrals", "calculate_probability_theory",
              "classify_regime", "classify_integral_regime",
              "classify_probability_regime", "classify_power_regime")
    PRIVATE = ("_normal_cdf", "_ema", "_diff", "_normalise", "_finite", "_sign")

    def test_public_api_unchanged(self):
        for n in self.PUBLIC:
            self.assertTrue(hasattr(new, n), f"门面丢了 {n}")

    def test_private_names_still_exported(self):
        """⚠️ 测试直接 `from calculus_engine import _normal_cdf, _ema, ...`。"""
        for n in self.PRIVATE:
            self.assertTrue(hasattr(new, n), f"门面丢了私有名 {n}")

    def test_identity_matches_submodules(self):
        import scripts.calculus.calculate as calc
        self.assertIs(new.calculate_calculus, calc.calculate_calculus)
        self.assertIs(new.classify_regime, prim.classify_regime)
        self.assertIs(new._normal_cdf, prim._normal_cdf)

    def test_facade_has_no_implementation_left(self):
        src = FACADE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef)],
                         [], "门面不该再定义任何函数")
        self.assertIn("primitives import", src)
        self.assertIn("calculate import", src)

    def test_submodules_do_not_import_the_facade(self):
        """⚠️ 依赖必须单向：子模块**不得** import 门面，否则成环。"""
        for path in (PRIM, CALC):
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src)
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom):
                    self.assertNotIn("calculus_engine", n.module or "",
                                     f"{path.name} 反向 import 了门面")
                elif isinstance(n, ast.Import):
                    for a in n.names:
                        self.assertNotIn("calculus_engine", a.name)

    def test_dual_import_works_under_both_path_layouts(self):
        """⚠️ `scripts/` 不是包，且调用方不保证 repo 根在 sys.path。

        用子进程实测两种布局都能 `from calculus_engine import calculate_calculus`。
        """
        # 第七十八刀：以 spawn 为被测行为，离线守护下如实 skip（守卫在 spawn 前）。
        from tests.config_sandbox import skip_if_offline_suite
        skip_if_offline_suite(self)
        code = ("import sys; sys.path.insert(0, %r)\n"
                "from calculus_engine import calculate_calculus, _normal_cdf\n"
                "print(calculate_calculus([100,101,102,104,107,111,116,122])['valid'])\n")
        for extra in (str(ROOT), str(SCRIPTS)):
            r = subprocess.run([sys.executable, "-c",
                                ("import sys; sys.path.insert(0, %r);\n" % str(SCRIPTS)) + code % extra],
                               cwd=str(ROOT), capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"布局 {extra} 失败: {r.stderr}")
            self.assertEqual(r.stdout.strip().splitlines()[-1], "True")

    def test_no_bare_module_level_calls(self):
        for path in (PRIM, CALC):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            bare = [n for n in tree.body
                    if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
            self.assertEqual(bare, [], f"{path.name} 模块层不应有裸调用")


if __name__ == "__main__":
    unittest.main()
