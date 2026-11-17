"""证据链健康度（方向 1：可观测性）的回归。

## 这个测试在守什么

自进化复盘的可信度取决于两个**可量化**的比例：

| 尺子 | 问的问题 | 2026-10 改造前实测 |
|---|---|---|
| `evidence_coverage_pct` | 平仓行里有多少带着**开仓现场快照**？ | **0%**（82 笔全无） |
| `exit_cause_coverage_pct` | 离场原因有多少来自**机制确认**（而非按金额猜）？ | **0%**（41% 是"止盈推定"） |

判据三族：

1. **计数诚实**：`exit_reason_source` 的三档（mechanism / inferred / 无标记）必须分开数，
   无标记的历史行**不得**被算进 mechanism；
2. **百分比不撒谎**：分母 0 ⇒ `0.0`（不是 `nan`、不抛异常）；分子不得超过分母；
3. **缺口可读**：`evidence_gap_reasons` 要说出"缺什么、缺多少、为什么"，
   让模型不必自己从数字揣摩 —— 这正是本次改造要交付的"台账缺什么"的可见性。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.evolution.observability import audit_snapshot_observability  # noqa: E402
from scripts.evolution.report import derive_evidence_coverage  # noqa: E402


def _trade(*, obs="DYNAMICS_OBSERVED", snap=None, source=""):
    row = {"snapshot_observability": obs, "exit_reason_source": source}
    if snap is not None:
        row["entry_snapshot"] = snap
    return row


class AuditCountsTests(unittest.TestCase):
    def test_exit_sources_are_counted_separately(self):
        audit = audit_snapshot_observability([
            _trade(source="mechanism"), _trade(source="mechanism"),
            _trade(source="inferred"),
            _trade(source=""),
        ])
        self.assertEqual(audit["exit_mechanism"], 2)
        self.assertEqual(audit["exit_inferred"], 1)
        self.assertEqual(audit["exit_unlabeled"], 1, "无标记的历史行必须单列")
        self.assertEqual(audit["total"], 4)

    def test_unlabeled_is_never_counted_as_mechanism(self):
        """★ 历史行没有 `exit_reason_source` ⇒ 绝不能当作"机制确认"。"""
        audit = audit_snapshot_observability([_trade(source="") for _ in range(5)])
        self.assertEqual(audit["exit_mechanism"], 0)
        self.assertEqual(audit["exit_unlabeled"], 5)

    def test_entry_snapshot_presence_counts_only_non_empty_dicts(self):
        audit = audit_snapshot_observability([
            _trade(snap={"macd_hist": 1.0}),   # 有现场
            _trade(snap={}),                    # 空字典 = 没有
            _trade(snap=None),                  # 显式 None
            _trade(),                           # 键缺失
            _trade(snap="not-a-dict"),          # 类型漂移
        ])
        self.assertEqual(audit["entry_snapshot_present"], 1)

    def test_legacy_keys_are_untouched(self):
        """既有四档 + `math_observable` 语义不得因本次扩充而变。"""
        audit = audit_snapshot_observability([
            _trade(obs="DYNAMICS_OBSERVED"), _trade(obs="PARTIAL"),
            _trade(obs="PRICE_ONLY"), _trade(obs="NONE"), _trade(obs="NONE"),
        ])
        self.assertEqual(audit["DYNAMICS_OBSERVED"], 1)
        self.assertEqual(audit["PARTIAL"], 1)
        self.assertEqual(audit["PRICE_ONLY"], 1)
        self.assertEqual(audit["NONE"], 2)
        self.assertEqual(audit["math_observable"], 2)
        self.assertEqual(audit["total"], 5)

    def test_unknown_tag_does_not_crash(self):
        audit = audit_snapshot_observability([_trade(obs="SOMETHING_NEW")])
        self.assertEqual(audit["SOMETHING_NEW"], 1)
        self.assertEqual(audit["total"], 1)


class CoverageDerivationTests(unittest.TestCase):
    def test_zero_coverage_speaks_plainly(self):
        """★ 改造前的真实状态：0% / 0%，缺口清单必须把原因说清楚。"""
        audit = audit_snapshot_observability([_trade(obs="PRICE_ONLY", source="") for _ in range(39)])
        entry, exit_c, gaps = derive_evidence_coverage(audit)
        self.assertEqual(entry, 0.0)
        self.assertEqual(exit_c, 0.0)
        joined = " | ".join(gaps)
        self.assertIn("梯队因子可观测 0/39", joined)
        self.assertIn("未标记 39/39", joined)
        self.assertIn("尚无一行离场原因来自**机制确认**", joined)

    def test_a_non_empty_snapshot_without_tier_factors_is_not_coverage(self):
        """★ 关键防自欺判据：快照非空但只有价格类观测 ⇒ 覆盖率**仍是 0%**。

        实测（生产 39 行）：`entry_snapshot_present` 已经是 100%，而
        `DYNAMICS_OBSERVED` 仍是 0 —— 若拿"快照非空"当覆盖率，报告头一行就会写
        "开仓现场覆盖 100%"，而复盘实际一个梯队因子都读不到，这个指标恰好
        掩盖了它本该暴露的缺口。
        """
        rows = [_trade(obs="PRICE_ONLY", snap={"price": 100.0}, source="mechanism")
                for _ in range(10)]
        audit = audit_snapshot_observability(rows)
        self.assertEqual(audit["entry_snapshot_present"], 10, "快照确实非空")
        self.assertEqual(audit["math_observable"], 0, "但梯队因子一个都不可观测")
        entry, _, gaps = derive_evidence_coverage(audit)
        self.assertEqual(entry, 0.0, "不得把'有快照'算成覆盖率")
        self.assertTrue(any("只有价格类观测" in g for g in gaps),
                        "必须明说'有快照但无梯队因子'")

    def test_observable_rows_drive_the_entry_coverage(self):
        rows = [_trade(obs="DYNAMICS_OBSERVED", snap={"macd_hist": 1.0}, source="mechanism"),
                _trade(obs="PARTIAL", snap={"macd_hist": 1.0}, source="mechanism"),
                _trade(obs="PRICE_ONLY", snap={"price": 1.0}, source="inferred")]
        entry, exit_c, _ = derive_evidence_coverage(audit_snapshot_observability(rows))
        self.assertAlmostEqual(entry, 66.7, places=1, msg="DYNAMICS_OBSERVED + PARTIAL")
        self.assertAlmostEqual(exit_c, 66.7, places=1)

    def test_full_coverage_is_silent(self):
        """全部可观测、全部机制确认 ⇒ 缺口清单为空（干净状态不制造噪音）。"""
        audit = audit_snapshot_observability(
            [_trade(obs="DYNAMICS_OBSERVED", snap={"macd_hist": 1.0}, source="mechanism")
             for _ in range(10)])
        entry, exit_c, gaps = derive_evidence_coverage(audit)
        self.assertEqual(entry, 100.0)
        self.assertEqual(exit_c, 100.0)
        self.assertEqual(gaps, [])

    def test_partial_coverage_is_reported_as_追赶期(self):
        rows = ([_trade(obs="DYNAMICS_OBSERVED", snap={"a": 1}, source="mechanism")] * 3
                + [_trade(obs="PRICE_ONLY", snap={"a": 1}, source="")] * 7)
        entry, exit_c, gaps = derive_evidence_coverage(audit_snapshot_observability(rows))
        self.assertEqual(entry, 30.0)
        self.assertEqual(exit_c, 30.0)
        joined = " | ".join(gaps)
        self.assertIn("仍有行缺现场", joined, "部分覆盖必须说成追赶期，而不是报成功")

    def test_inferred_rows_are_called_out_as_untrustworthy(self):
        audit = audit_snapshot_observability([
            _trade(snap={"a": 1}, source="mechanism"),
            _trade(snap={"a": 1}, source="inferred"),
        ])
        _, exit_c, gaps = derive_evidence_coverage(audit)
        self.assertEqual(exit_c, 50.0, "机制确认率只算 mechanism")
        joined = " | ".join(gaps)
        self.assertIn("属**推断** 1/2", joined)
        self.assertIn("不可当作机制事实引用", joined)

    def test_empty_sample_is_declared_unassessable(self):
        entry, exit_c, gaps = derive_evidence_coverage(audit_snapshot_observability([]))
        self.assertEqual((entry, exit_c), (0.0, 0.0))
        self.assertEqual(gaps, ["暂无平仓样本：证据链健康度不可评估"])

    def test_junk_input_never_raises_and_never_yields_nan(self):
        for junk in (None, {}, "x", [], 42):
            with self.subTest(junk=junk):
                entry, exit_c, gaps = derive_evidence_coverage(junk)
                self.assertEqual((entry, exit_c), (0.0, 0.0))
                self.assertIsInstance(gaps, list)

    def test_percentages_never_exceed_one_hundred(self):
        """分子大于分母的畸形输入也要封顶在 100%（否则页面会显示 300%）。"""
        entry, exit_c, _ = derive_evidence_coverage(
            {"total": 2, "math_observable": 5, "exit_mechanism": 9})
        self.assertEqual(entry, 100.0)
        self.assertEqual(exit_c, 100.0)


class ReportIntegrationTests(unittest.TestCase):
    def _build(self, snapshot_audit):
        from scripts.evolution.report import build_evolution_report
        return build_evolution_report(
            actions_taken=[], change_status="NO_CHANGE",
            insights=[], ledger_revision="rev", llm_review={}, long_term_memory=[],
            preserve_existing_memory=True, profit_factor=1.0, retired_lessons=[],
            snapshot_audit=snapshot_audit, timestamp_str="2026-10-01 12:00:00",
            total_trades=0, win_rate=0.0)

    def test_the_three_keys_are_present_and_derived(self):
        report = self._build(audit_snapshot_observability(
            [_trade(snap={"a": 1}, source="mechanism"), _trade(obs="PRICE_ONLY", source="")]))
        self.assertEqual(report["evidence_coverage_pct"], 50.0)
        self.assertEqual(report["exit_cause_coverage_pct"], 50.0)
        self.assertTrue(report["evidence_gap_reasons"])

    def test_snapshot_audit_is_still_passed_through_untouched(self):
        """派生不得改写既有透传字段（14 入参契约里 `snapshot_audit` 原样透出）。"""
        audit = {"total": 1, "x": 1}
        report = self._build(audit)
        self.assertEqual(report["snapshot_audit"], audit)

    def test_the_parameter_signature_is_thirteen(self):
        """★ 硬约束：证据链三键只能**派生**，不得靠加参数。

        2026-10：`constitution_readded` 随基准机制拆除 ⇒ 14 → **13** 个 kw-only 入参。
        抽取门（`tests/extraction/test_evolution_report_extraction.py`）逐项钉着这个数。
        """
        import ast
        src = (ROOT / "scripts" / "evolution" / "report.py").read_text(encoding="utf-8")
        fn = next(n for n in ast.parse(src).body
                  if isinstance(n, ast.FunctionDef) and n.name == "build_evolution_report")
        self.assertEqual(len(fn.args.kwonlyargs), 13)
        self.assertNotIn("constitution_readded",
                         [a.arg for a in fn.args.kwonlyargs],
                         "基准机制已拆除，该入参不得复活")


if __name__ == "__main__":
    unittest.main()
