"""`scripts/factors/defaults.py`（B3 第二十五刀）回归。

## 这个测试在守什么

`build_default_factors` 是 `compute_instrument_factors`（438 行）开头那
**95 行默认值字面量**的原样搬运。它不读外部状态（除 `time.time()`），
但六 Pillar 的字段名、初值、占位符**全部是接口** —— 前端与主脑都按这张形状取值。

抽离的安全网有三层：

1. **AST 恒等**（`AstIdentityTest`）—— 与搬走前的字面量逐节点比对，
   证明"原样搬运"而不是"照着抄了一遍"；
2. **语义不变量**（`SemanticsTest`）—— 那些看起来"不统一、该归一"的值
   其实都有含义（见模块文档串），逐个钉住；
3. **`timestamp` 活性**（`TimestampTest`）—— 抽成模块级常量是最容易犯的错，
   后果是"所有标的、所有周期都拿到模块导入那一刻的时间"。
"""

from __future__ import annotations

import ast
import subprocess
import time
import unittest
from pathlib import Path

from scripts.factors.defaults import build_default_factors
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts" / "factors" / "defaults.py"
FACADE = ROOT / "scripts" / "factor_library.py"

PILLARS = (
    "trend_momentum", "volatility_channel", "volume_money_flow",
    "microstructure", "smart_money_derivatives",
    "calculus_dynamics", "definite_integrals", "probability_theory",
)


#: 抽取落地的那次提交（本刀）。字面量在**它的父提交**里存在。
EXTRACTION_COMMIT = "4aef066"
_BASE_REV = f"{EXTRACTION_COMMIT}^"


def _facade_dict_literal():
    """取**搬走前**门面里的原始字面量（抽取提交的父提交）。

    ⚠️ 不能用 `HEAD`：抽取提交本身就把字面量删了，用 HEAD 取到的是
    "已经没有该字面量"的版本，测试会在下一次提交后莫名变红 ——
    我第一版正是用 HEAD，提交后立刻红。故**钉死到具体提交的父提交**。
    """
    out = subprocess.run(
        ["git", "show", legacy_rev_path(f"{_BASE_REV}:scripts/factor_library.py")],
        capture_output=True, text=True, cwd=str(ROOT))
    if out.returncode != 0:
        return None
    tree = ast.parse(normalize(out.stdout))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef)
              and n.name == "compute_instrument_factors")
    assign = next(st for st in fn.body
                  if isinstance(st, ast.Assign)
                  and getattr(st.targets[0], "id", None) == "factors")
    return assign.value


class AstIdentityTest(unittest.TestCase):
    """证明"原样搬运"：新函数的返回字典与搬走前的字面量 AST **逐节点相同**。"""

    def test_new_return_is_a_dict(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "build_default_factors")
        ret = next(st for st in fn.body if isinstance(st, ast.Return))
        self.assertIsInstance(ret.value, ast.Dict)

    def test_facade_no_longer_contains_the_literal(self):
        src = FACADE.read_text(encoding="utf-8")
        self.assertNotIn('"signal_recommendation": "WAIT"', src,
                         "门面仍残留默认结构字面量")
        self.assertIn("build_default_factors(inst_id, name)", src)


class SemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = build_default_factors("BTC-USDT-SWAP", "BTC")

    def test_identity_fields(self):
        self.assertEqual(self.f["instId"], "BTC-USDT-SWAP")
        self.assertEqual(self.f["name"], "BTC")
        self.assertEqual(self.f["price"], 0.0)
        self.assertEqual(self.f["chg24h"], 0.0)
        self.assertEqual(self.f["composite_alpha_score"], 0.0)
        self.assertEqual(self.f["signal_recommendation"], "WAIT")

    def test_all_eight_pillars_present(self):
        for p in PILLARS:
            self.assertIsInstance(self.f[p], dict, p)
        self.assertEqual(sorted(k for k in self.f if isinstance(self.f[k], dict)),
                         sorted(PILLARS))

    def test_neutral_values_are_not_unified_to_zero(self):
        """**关键**：比率类用 1.0、百分位类用 50.0、幅度类用 0.0。

        统一成 0.0 会把"中性"变成"极度看空"。
        """
        self.assertEqual(self.f["volume_money_flow"]["vol_ratio_15m"], 1.0)
        self.assertEqual(self.f["microstructure"]["bid_ask_depth_ratio"], 1.0)
        self.assertEqual(self.f["trend_momentum"]["rsi_14"], 50.0)
        self.assertEqual(self.f["trend_momentum"]["kdj_j"], 50.0)
        self.assertEqual(self.f["probability_theory"]["continuation_prob_pct"], 50.0)
        self.assertEqual(self.f["probability_theory"]["breakdown_prob_pct"], 50.0)
        self.assertEqual(self.f["volatility_channel"]["atr_14"], 0.0)

    def test_variance_and_cvar_defaults(self):
        self.assertEqual(self.f["probability_theory"]["var_95_pct"], 1.5)
        self.assertEqual(self.f["probability_theory"]["cvar_95_pct"], 2.2)
        self.assertFalse(self.f["probability_theory"]["is_fat_tail"])

    def test_smart_money_is_explicitly_unavailable(self):
        """**不得**用 50/NEUTRAL/0 冒充真实信号。"""
        sm = self.f["smart_money_derivatives"]
        self.assertIs(sm["available"], False)
        self.assertEqual(sm["signal"], "UNAVAILABLE")
        self.assertIn("OKX CLI", sm["reason"])
        for k in ("weighted_long_pct", "smart_money_flow_usd", "oi_usd",
                  "long_short_ratio", "avg_long_entry", "avg_short_entry",
                  "top_win_rate"):
            self.assertEqual(sm[k], "--", f"{k} 应为占位符 --，而不是中性值")
        self.assertEqual(sm["funding_rate_pct"], 0.0, "资金费是唯一的真实数值字段")

    def test_regime_defaults(self):
        self.assertEqual(self.f["trend_momentum"]["trend_regime"], "NEUTRAL")
        self.assertEqual(self.f["volatility_channel"]["volatility_regime"], "NORMAL")
        self.assertEqual(self.f["volume_money_flow"]["obv_flow"], "NEUTRAL")
        self.assertEqual(self.f["volume_money_flow"]["flow_sentiment"], "BALANCED")
        self.assertEqual(self.f["microstructure"]["depth_bias"], "NEUTRAL")
        self.assertEqual(self.f["calculus_dynamics"]["power_regime"], "STEADY_FLUX")
        self.assertEqual(self.f["calculus_dynamics"]["regime"], "RANGE_LOW_VELOCITY")
        self.assertEqual(self.f["definite_integrals"]["integral_regime"],
                         "BALANCED_ENERGY")
        self.assertEqual(self.f["probability_theory"]["prob_regime"],
                         "GAUSSIAN_BALANCED")

    def test_taker_net_is_a_unit_string(self):
        """带单位字符串，不是数字 —— 归一成 0.0 会破坏前端渲染。"""
        v = self.f["volume_money_flow"]["taker_net_usd"]
        self.assertIsInstance(v, str)
        self.assertEqual(v, "0 U")

    def test_direction_is_int_zero(self):
        self.assertEqual(self.f["calculus_dynamics"]["direction"], 0)
        self.assertIsInstance(self.f["calculus_dynamics"]["direction"], int)

    def test_fresh_dict_each_call(self):
        """两次调用不得共享嵌套 dict（否则一处改动会串到所有标的）。"""
        a = build_default_factors("A", "a")
        b = build_default_factors("B", "b")
        self.assertIsNot(a["trend_momentum"], b["trend_momentum"])
        a["trend_momentum"]["rsi_14"] = 99.0
        self.assertEqual(b["trend_momentum"]["rsi_14"], 50.0)


class TimestampTest(unittest.TestCase):
    """⚠️ 抽成模块级常量是最容易犯、后果最隐蔽的错。"""

    def test_timestamp_is_live_not_frozen(self):
        a = build_default_factors("X", "x")["timestamp"]
        time.sleep(1.05)
        b = build_default_factors("X", "x")["timestamp"]
        self.assertGreater(b, a,
                           "timestamp 被冻结了 —— 若写成模块级常量，"
                           "所有标的/周期都会拿到模块导入那一刻的时间")

    def test_timestamp_is_int_seconds(self):
        ts = build_default_factors("X", "x")["timestamp"]
        self.assertIsInstance(ts, int)
        self.assertAlmostEqual(ts, time.time(), delta=5)

    def test_module_has_no_dict_level_constant(self):
        """源码层面：不得存在模块级字典常量（那就是冻结形状）。"""
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                self.assertNotIsInstance(node.value, ast.Dict,
                                         f"模块级字典常量 {ast.unparse(node.targets)} "
                                         "会把 timestamp 与嵌套结构一起冻结")

    def test_time_call_inside_the_function(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "build_default_factors")
        self.assertTrue(any(isinstance(n, ast.Call) for n in ast.walk(fn)),
                        "函数体内应含 time.time() 调用")


class ProductionSnapshotShapeTest(unittest.TestCase):
    """与**生产快照**对照：默认结构的形状必须与实盘产出的因子一致。

    ⚠️ 这条测试的价值与局限都要说清：

    - 价值：`data/factor_library_snapshot.json` 是**真实产出**。若默认结构与它
      有任何键位分叉（少了某个 Pillar 字段、多了个幽灵键），这里立刻红 ——
      比"我自己写两份期望值互相对照"强得多。
    - 局限：快照是**当前实现**跑出来的。所以它只能证明"结构与产出同形"，
      **不能证明产出本身正确**（§33.3 那次的教训：样本 == 实现不等于正确）。
      "产出正确"由 `compute_instrument_factors` 既有的测试保证。
    - 快照缺失时跳过（例如全新 checkout 尚未跑过因子库），不假绿。
    """

    SNAPSHOT = ROOT / "data" / "factor_library_snapshot.json"

    def _items(self):
        if not self.SNAPSHOT.exists():
            self.skipTest("无生产因子快照")
        import json
        snap = json.loads(self.SNAPSHOT.read_text(encoding="utf-8"))
        insts = snap.get("instruments")
        if not insts:
            self.skipTest("快照里没有 instruments")
        return insts if isinstance(insts, list) else list(insts.values())

    def test_top_level_keys_match(self):
        default = build_default_factors("x", "x")
        for it in self._items():
            self.assertEqual(sorted(it), sorted(default),
                             f"{it.get('instId')} 顶层键与默认结构分叉")

    def test_every_pillar_key_set_matches(self):
        default = build_default_factors("x", "x")
        for it in self._items():
            for pillar in PILLARS:
                self.assertIn(pillar, it, f"{it.get('instId')} 缺 Pillar {pillar}")
                self.assertEqual(
                    sorted(it[pillar]), sorted(default[pillar]),
                    f"{it.get('instId')}.{pillar} 键位与默认结构分叉")

    def test_smart_money_missing_semantics_survives_roundtrip(self):
        """缺失语义必须原样进快照 —— 被中性值替换就是"UI 说谎"。若已接入新数据源则校验真实可用性。"""
        for it in self._items():
            sm = it.get("smart_money_derivatives")
            if not isinstance(sm, dict):
                continue
            if not sm.get("available"):
                self.assertEqual(sm.get("signal"), "UNAVAILABLE")
            else:
                self.assertIn("weighted_long_pct", sm)


class ImportSafetyTest(unittest.TestCase):
    def test_module_imports_nothing_from_the_facade(self):
        """不得反向 import 门面（会造成循环导入）。"""
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("factor_library", (node.module or ""),
                                 "子模块不得反向 import factor_library")
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotEqual(a.name, "factor_library")

    def test_import_is_absolute_not_relative(self):
        """仓里以 `scripts.` 顶层包导入；用相对导入会让两种入口方式分叉。"""
        src = MODULE.read_text(encoding="utf-8")
        self.assertIn("from scripts.factors.defaults import build_default_factors",
                      FACADE.read_text(encoding="utf-8"))

    def test_subpackage_has_init(self):
        self.assertTrue((ROOT / "scripts" / "factors" / "__init__.py").exists(),
                        "子包缺 __init__.py 时，`scripts.factors.defaults` "
                        "在某些 sys.path 组合下会导入失败")


if __name__ == "__main__":
    unittest.main()
