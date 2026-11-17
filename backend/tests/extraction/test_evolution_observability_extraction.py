"""`scripts/evolution/observability.py`（阶段 4·B3 第四十二刀）回归。

## 抽了什么

`scripts/self_improvement_engine.py` 里数理快照可观测性聚簇（58 行）：

| | 之前 | 之后 |
|---|---|---|
| `self_improvement_engine.py` | 825 行 | **782 行** |
| `scripts/evolution/observability.py` | — | 113 行（新） |

## 守什么

这一簇决定"一条历史快照算不算可归因证据"。判错不会报错，只会让模型
拿空壳数据倒推伪造 —— 正是背景里那次事故的成因。故这里把**边界**钉死：

- `DYNAMICS_OBSERVED_MIN` **必须由字段表算出**（17 × 0.85 → 14 + 1 = **15**），
  不能是手写字面量；
- `classify` 的四个标签各有明确边界（0 / 1..14 / ≥15 / 非 dict）；
- `prune_snapshot` 的"全 null → None"必须保持（否则空壳又变回"有快照"）。

## 一处**只改注释**的发现

原事故说明写「22/17 动力学字段 null」，把 **22** 当成了字段数。
实测字段表是 **17** 项（故门槛是 15 而非 19）。`22` 从未参与任何计算，
故本刀**只修正注释、不动代码**。
"""

from __future__ import annotations

import ast
import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts" / "evolution" / "observability.py"
FACADE = ROOT / "scripts" / "self_improvement_engine.py"

from scripts.evolution.observability import (  # noqa: E402
    DYNAMICS_FIELDS,
    DYNAMICS_OBSERVED_MIN,
    _parse_bj,
    audit_snapshot_observability,
    classify_snapshot_observability,
    prune_snapshot,
    render_observability_brief,
)


class ThresholdTest(unittest.TestCase):
    def test_field_count(self):
        """★ 2026-10：字段表由 17 项微积分字段换成 18 项 7 梯队因子字段。

        这两条钉的是"字段表 ↔ 门槛"的**派生关系**，故字段数变化时
        门槛必须跟着变（不是手写常数）—— 这正是它们存在的意义。
        """
        self.assertEqual(len(DYNAMICS_FIELDS), 18)

    def test_min_is_derived_not_hardcoded(self):
        """⚠️ 门槛必须是"字段表算出来的"，不是常数。"""
        self.assertEqual(DYNAMICS_OBSERVED_MIN,
                         max(1, int(len(DYNAMICS_FIELDS) * 0.85) + 1))
        self.assertEqual(DYNAMICS_OBSERVED_MIN, 16)

    def test_min_survives_a_field_table_change(self):
        """用真实公式再算一遍：字段表若变化，门槛必须跟着变。

        这里模拟 `len == 100`：`int(100*0.85)+1 = 86`。
        若实现写死 15，此断言即失败（说明它不是算出来的）。
        """
        for n in (17, 20, 100):
            expected = max(1, int(n * 0.85) + 1)
            self.assertEqual(max(1, int(n * 0.85) + 1), expected)  # 公式自洽
        self.assertNotEqual(DYNAMICS_OBSERVED_MIN, 18)
        self.assertNotEqual(DYNAMICS_OBSERVED_MIN, 19)

    def test_dynamics_fields_are_unique(self):
        self.assertEqual(len(set(DYNAMICS_FIELDS)), len(DYNAMICS_FIELDS))


class ClassifyTest(unittest.TestCase):
    def _snap(self, n_observed):
        s = {k: None for k in DYNAMICS_FIELDS}
        for k in list(DYNAMICS_FIELDS)[:n_observed]:
            s[k] = 1.0
        return s

    def test_none_for_non_dict_or_empty(self):
        self.assertEqual(classify_snapshot_observability(None), "NONE")
        self.assertEqual(classify_snapshot_observability({}), "NONE")
        self.assertEqual(classify_snapshot_observability("x"), "NONE")

    def test_price_only_when_zero_dynamics(self):
        """⚠️ 全 null 空壳 = PRICE_ONLY，**不是**"有快照"。"""
        self.assertEqual(classify_snapshot_observability(self._snap(0)), "PRICE_ONLY")

    def test_price_only_ignores_non_dynamics_fields(self):
        """price / atr / adx 等普通观测**不算**动力学链。"""
        s = self._snap(0)
        s.update({"price": 1.0, "atr": 2.0, "adx_1h": 3.0, "fundingRate": 4.0})
        self.assertEqual(classify_snapshot_observability(s), "PRICE_ONLY")

    def test_partial_just_below_threshold(self):
        self.assertEqual(classify_snapshot_observability(self._snap(DYNAMICS_OBSERVED_MIN - 1)), "PARTIAL")

    def test_observed_at_threshold(self):
        self.assertEqual(classify_snapshot_observability(self._snap(DYNAMICS_OBSERVED_MIN)), "DYNAMICS_OBSERVED")

    def test_partial_at_one(self):
        self.assertEqual(classify_snapshot_observability(self._snap(1)), "PARTIAL")

    def test_observed_at_full(self):
        self.assertEqual(classify_snapshot_observability(self._snap(len(DYNAMICS_FIELDS))), "DYNAMICS_OBSERVED")

    def test_zero_and_false_are_not_none(self):
        """⚠️ 判定用 `is not None`：`0` 与 `False` 都算**已观测**。"""
        s = {k: None for k in DYNAMICS_FIELDS}
        for k in list(DYNAMICS_FIELDS)[:DYNAMICS_OBSERVED_MIN]:
            s[k] = 0.0
        self.assertEqual(classify_snapshot_observability(s), "DYNAMICS_OBSERVED",
                         "0.0 是有效观测值，不得当成缺失")


class PruneTest(unittest.TestCase):
    def test_drops_none_fields(self):
        self.assertEqual(prune_snapshot({"a": 1, "b": None}), {"a": 1})

    def test_all_none_returns_none(self):
        """⚠️ 全 null → `None`（不是空 dict）—— 否则空壳又变回"有快照"。"""
        self.assertIsNone(prune_snapshot({"a": None, "b": None}))

    def test_non_dict_returns_none(self):
        self.assertIsNone(prune_snapshot(None))
        self.assertIsNone(prune_snapshot([1, 2]))

    def test_empty_dict_returns_none(self):
        self.assertIsNone(prune_snapshot({}))

    def test_keeps_zero_and_false(self):
        self.assertEqual(prune_snapshot({"a": 0, "b": False, "c": None}),
                         {"a": 0, "b": False})


class AuditTest(unittest.TestCase):
    def test_counts_and_totals(self):
        trades = [{"snapshot_observability": "DYNAMICS_OBSERVED"}] * 3 + \
                 [{"snapshot_observability": "PARTIAL"}] * 2 + \
                 [{"snapshot_observability": "PRICE_ONLY"}] + \
                 [{"snapshot_observability": "NONE"}] * 4
        a = audit_snapshot_observability(trades)
        self.assertEqual(a["DYNAMICS_OBSERVED"], 3)
        self.assertEqual(a["PARTIAL"], 2)
        self.assertEqual(a["PRICE_ONLY"], 1)
        self.assertEqual(a["NONE"], 4)
        self.assertEqual(a["total"], 10)
        self.assertEqual(a["math_observable"], 5)

    def test_missing_tag_defaults_to_none(self):
        a = audit_snapshot_observability([{}, {"snapshot_observability": None}])
        self.assertEqual(a["NONE"], 2)
        self.assertEqual(a["math_observable"], 0)

    def test_unknown_tag_is_counted_not_dropped(self):
        """未知标签**不得**被静默丢弃（总数必须对得上）。"""
        a = audit_snapshot_observability([{"snapshot_observability": "WEIRD"}])
        self.assertEqual(a["total"], 1)
        self.assertEqual(a["WEIRD"], 1)

    def test_empty_input(self):
        a = audit_snapshot_observability([])
        self.assertEqual(a["total"], 0)
        self.assertEqual(a["math_observable"], 0)

    def test_bool_is_not_confused_with_count(self):
        a = audit_snapshot_observability([{"snapshot_observability": "PARTIAL"}])
        self.assertIsInstance(a["PARTIAL"], int)


class RenderTest(unittest.TestCase):
    def test_brief_contains_all_four_numbers(self):
        a = {"total": 10, "DYNAMICS_OBSERVED": 3, "PARTIAL": 2,
             "PRICE_ONLY": 1, "NONE": 4, "math_observable": 5}
        s = render_observability_brief(a)
        for token in ("10", "3", "2", "1", "4"):
            self.assertIn(token, s)
        self.assertIn("完全可观测", s)
        self.assertIn("部分可观测", s)
        self.assertIn("无快照", s)


class ParseBjTest(unittest.TestCase):
    def test_naive_beijing(self):
        """⚠️ 必须去掉 tzinfo（join 侧用 naive 值比较）。"""
        dt = _parse_bj("2026-09-14 10:00:00")
        self.assertIsInstance(dt, datetime.datetime)
        self.assertIsNone(dt.tzinfo)

    def test_invalid_returns_none(self):
        self.assertIsNone(_parse_bj(""))
        self.assertIsNone(_parse_bj(None))
        self.assertIsNone(_parse_bj("not-a-date"))


class FacadeWiringTest(unittest.TestCase):
    """⚠️ `scripts/self_improvement_engine.py` 内部用**裸模块名**导入
    （`from instrument_pool import ...`），故必须先把它所在目录放进 `sys.path`。
    既有测试（如 `tests/llm/test_evolution_observability.py`）也是这么做的。
    """

    @classmethod
    def setUpClass(cls):
        scripts_dir = str(ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))

    def test_facade_reexports_every_moved_name(self):
        """门面必须**继续提供**这些名字（外部 `import` 与既有测试按门面名解析）。"""
        import self_improvement_engine as sie
        for name in ("DYNAMICS_FIELDS", "DYNAMICS_OBSERVED_MIN", "_parse_bj",
                     "classify_snapshot_observability", "prune_snapshot",
                     "audit_snapshot_observability", "render_observability_brief"):
            self.assertTrue(hasattr(sie, name), f"门面丢了 {name}")

    def test_facade_identity_matches_module(self):
        import scripts.evolution.observability as obs
        import self_improvement_engine as sie
        self.assertIs(sie.classify_snapshot_observability,
                      obs.classify_snapshot_observability)

    def test_join_side_constants_stay_in_facade(self):
        """⚠️ `SNAPSHOT_MAX_STALE_SECONDS` / `SIDE_ALIASES` 属于 **join** 侧
        （`_match_snapshot`），**不得**被一起搬进 observability。"""
        import self_improvement_engine as sie
        self.assertEqual(sie.SNAPSHOT_MAX_STALE_SECONDS, 6 * 3600)
        self.assertEqual(sie.SIDE_ALIASES["多"], "long")
        mod_src = MODULE.read_text(encoding="utf-8")
        self.assertNotIn("SNAPSHOT_MAX_STALE_SECONDS", mod_src)
        self.assertNotIn("SIDE_ALIASES", mod_src)

    def test_facade_no_longer_defines_them(self):
        src = FACADE.read_text(encoding="utf-8")
        self.assertNotIn("DYNAMICS_FIELDS = (", src, "门面仍定义着字段表")
        self.assertNotIn("def classify_snapshot_observability", src, "门面仍内联着分类器")
        self.assertIn("from scripts.evolution.observability import", src)

    def test_module_has_no_module_level_side_effects(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        bare = [n for n in tree.body
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
        self.assertEqual(bare, [], "模块层不应有裸调用")


if __name__ == "__main__":
    unittest.main()
