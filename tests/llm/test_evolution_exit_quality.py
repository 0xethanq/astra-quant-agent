"""离场质量分析（`scripts/evolution/exit_quality.py`，方向 3）的回归。

## 这个测试在守什么

台账能算"这笔赚/亏多少"，算不出**这笔本来能赚多少**。离场质量模块用 MFE/MAE
回答"吐回去多少、兑现了多少"，它的价值**完全**取决于口径是否诚实：

| 判据 | 为什么 |
|---|---|
| R 口径只用真证据 | 缺 `initial_stop_px` ⇒ `give_back_r` 必须是 `None`，**不许**用默认止损凑 |
| 百分比口径独立成立 | 没有止损距离也要能算 `give_back_pct` / `exit_efficiency_pct`（否则整块失效） |
| 机制表只认机制确认 | `inferred`（按金额猜的）行进机制优劣表 ⇒ 会把猜测当成机制效果 |
| 纯浮盈不算"兑现率" | MFE ≤ 0 时谈兑现率是伪命题（分母为负会得出"兑现 −300%"这种怪数） |
| 样本不足要说不足 | 每张表带 `sample`，达不到阈值进 `insufficient`，不许静默给结论 |

另有一个**生产实况**判据：历史台账（82 笔）**一行证据都没有**，此时必须明说
"暂不可评估"，而不是显示 0%/0R 让人误以为"效果为零"。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.evolution.exit_quality import (  # noqa: E402
    MIN_SAMPLE, analyze_exit_quality, classify_row, render_exit_quality_brief,
)


def _row(inst="BTC", side="多", *, open_px=100.0, close_px=102.0, net_pnl=2.0,
         mfe_pct=None, mae_pct=None, entry_px=None, initial_stop_px=None,
         exit_cause="", source="mechanism"):
    """台账平仓行形状（含 `close_evidence` join 进来的证据字段）。"""
    row = {
        "inst": inst, "side": side, "open_px": open_px, "close_px": close_px,
        "net_pnl": net_pnl, "exit_reason": "🛑 止损离场",
        "exit_reason_source": source, "exit_cause": exit_cause,
    }
    if mfe_pct is not None:
        row["mfe_pct"] = mfe_pct
    if mae_pct is not None:
        row["mae_pct"] = mae_pct
    if entry_px is not None:
        row["entry_px"] = entry_px
    if initial_stop_px is not None:
        row["initial_stop_px"] = initial_stop_px
    # R 口径只有在 entry_px / initial_stop_px 齐备时才算得出来
    if mfe_pct is not None and entry_px and initial_stop_px:
        one_r_pct = abs(entry_px - initial_stop_px) / entry_px * 100.0
        row["mfe_r"] = round(mfe_pct / one_r_pct, 4)
    return row


class ClassifyRowTests(unittest.TestCase):
    def test_give_back_in_r_uses_the_frozen_stop(self):
        """★ 核心：到过 +2R，实收 +0.5R ⇒ 回吐 1.5R。

        1R = |100 − 96| / 100 = 4% 的价格距离；MFE 8% ⇒ 2R；实收 2% ⇒ 0.5R。
        """
        s = classify_row(_row(open_px=100.0, close_px=102.0, mfe_pct=8.0,
                              entry_px=100.0, initial_stop_px=96.0))
        self.assertAlmostEqual(s["one_r_pct"], 4.0)
        self.assertAlmostEqual(s["mfe_r"], 2.0)
        self.assertAlmostEqual(s["realized_r"], 0.5)
        self.assertAlmostEqual(s["give_back_r"], 1.5)
        self.assertAlmostEqual(s["give_back_pct"], 6.0)
        self.assertAlmostEqual(s["exit_efficiency_pct"], 25.0)

    def test_missing_stop_yields_no_r_but_keeps_percentages(self):
        """★ 没有初始止损 ⇒ R 全为 None，百分比照给（不硬凑一个 1R）。"""
        s = classify_row(_row(open_px=100.0, close_px=102.0, mfe_pct=8.0))
        self.assertIsNone(s["one_r_pct"])
        self.assertIsNone(s["mfe_r"])
        self.assertIsNone(s["realized_r"])
        self.assertIsNone(s["give_back_r"])
        self.assertAlmostEqual(s["give_back_pct"], 6.0, msg="百分比不依赖止损，必须在")
        self.assertAlmostEqual(s["exit_efficiency_pct"], 25.0)

    def test_short_side_realized_move_is_sign_flipped(self):
        """空头：价格下跌才是浮盈。实收口径必须按方向取号。"""
        s = classify_row(_row(side="空", open_px=100.0, close_px=98.0, mfe_pct=5.0,
                              entry_px=100.0, initial_stop_px=104.0))
        self.assertAlmostEqual(s["realized_pct"], 2.0, msg="空头跌 2% ⇒ 实收 +2%")
        self.assertAlmostEqual(s["one_r_pct"], 4.0)
        self.assertAlmostEqual(s["realized_r"], 0.5)

    def test_never_profitable_row_has_no_efficiency(self):
        """★ 从没浮盈过（MFE ≤ 0）⇒ 兑现率无意义，必须为 None。"""
        s = classify_row(_row(open_px=100.0, close_px=99.0, mfe_pct=-0.5, mae_pct=-3.0))
        self.assertIsNone(s["exit_efficiency_pct"])
        self.assertIsNotNone(s["give_back_pct"], "回吐口径仍可算（负数表示从未浮盈）")

    def test_row_without_any_evidence_is_skipped(self):
        """★ 只有开平价/平仓价、没有 MFE/MAE 的行**不入样**。

        否则"证据覆盖率"会被虚报成 100%（历史 82 笔全都有开平价），
        "缺证据"这件事就反而看不见了。
        """
        self.assertIsNone(classify_row(_row(open_px=100.0, close_px=102.0)),
                          "无浮动偏移证据的行不得进样本")
        self.assertIsNone(classify_row(None))

    def test_side_aliases_and_junk_never_masquerade(self):
        self.assertEqual(classify_row(_row(side="long", mfe_pct=1.0))["side"], "long")
        self.assertEqual(classify_row(_row(side="空", mfe_pct=1.0))["side"], "short")
        # 方向认不出 ⇒ 实收算不出，但 MFE/MAE 仍在
        s = classify_row(_row(side="net", mfe_pct=3.0))
        self.assertIsNone(s["realized_pct"])
        self.assertEqual(s["mfe_pct"], 3.0, "方向不明不影响浮动偏移本身")

    def test_bool_is_not_a_price(self):
        s = classify_row(_row(open_px=True, mfe_pct=3.0))
        self.assertIsNone(s["realized_pct"], "`float(True)==1.0` 不得被当成价格")


class MechanismTableTests(unittest.TestCase):
    def test_inferred_rows_are_excluded_from_the_mechanism_table(self):
        """★ 按金额猜出来的离场原因**不许**进机制优劣表（那是把猜测当机制）。"""
        rows = ([_row(exit_cause="ratchet_lock", source="mechanism", mfe_pct=5.0)] * 3
                + [_row(exit_cause="momentum_tp", source="inferred", mfe_pct=5.0)] * 5)
        analysis = analyze_exit_quality(closed_trades=rows)
        causes = [m["exit_cause"] for m in analysis["by_mechanism"]]
        self.assertIn("ratchet_lock", causes)
        self.assertNotIn("momentum_tp", causes, "推断行不得进机制表")

    def test_mechanism_table_is_ranked_worst_first(self):
        rows = ([_row(inst="A", exit_cause="hard_stop", net_pnl=-30.0, mfe_pct=1.0)] * 4
                + [_row(inst="B", exit_cause="ratchet_lock", net_pnl=+20.0, mfe_pct=5.0)] * 4)
        analysis = analyze_exit_quality(closed_trades=rows)
        labels = [m["exit_cause"] for m in analysis["by_mechanism"]]
        self.assertEqual(labels, ["hard_stop", "ratchet_lock"], "最差机制排最前")

    def test_no_mechanism_rows_is_declared_not_hidden(self):
        """空机制表必须**明说**"不是效果好"，而不是留空让人自行乐观解读。"""
        analysis = analyze_exit_quality(
            closed_trades=[_row(mfe_pct=3.0, source="inferred", exit_cause="")] * 10)
        self.assertEqual(analysis["by_mechanism"], [])
        self.assertTrue(any("尚无机制确认" in s for s in analysis["insufficient"]))

    def test_labels_are_chinese_prose(self):
        analysis = analyze_exit_quality(
            closed_trades=[_row(exit_cause="ratchet_lock", mfe_pct=5.0)] * 10)
        self.assertEqual(analysis["by_mechanism"][0]["label"], "阶梯锁利")


class TimeStopTests(unittest.TestCase):
    def test_cut_while_positive_is_counted(self):
        """★ 时间止损最该被盯的形态：「曾有浮盈却亏损离场」= 砍在半路上。"""
        rows = [
            _row(exit_cause="time_stop", mfe_pct=4.0, net_pnl=-5.0),   # 曾浮盈，亏着走
            _row(exit_cause="time_stop", mfe_pct=3.0, net_pnl=-2.0),   # 同上
            _row(exit_cause="time_stop", mfe_pct=-0.5, net_pnl=1.0),   # 从未浮盈，反而赚
        ]
        ts = analyze_exit_quality(closed_trades=rows)["time_stop"]
        self.assertEqual(ts["n"], 3)
        self.assertEqual(ts["cut_while_positive"], 2)

    def test_absent_time_stop_is_declared(self):
        analysis = analyze_exit_quality(
            closed_trades=[_row(exit_cause="hard_stop", mfe_pct=1.0)] * 10)
        self.assertIsNone(analysis["time_stop"])
        self.assertTrue(any("未发生时间止损" in s for s in analysis["insufficient"]))


class SymbolMatrixTests(unittest.TestCase):
    def test_per_symbol_matrix_finds_bad_exit_symbols(self):
        rows = ([_row(inst="BTC", net_pnl=-40.0, mfe_pct=6.0,
                      entry_px=100.0, initial_stop_px=98.0)] * 9
                + [_row(inst="ARB", net_pnl=+25.0, mfe_pct=4.0,
                        entry_px=100.0, initial_stop_px=98.0)] * 9)
        matrix = {m["inst"]: m for m in analyze_exit_quality(closed_trades=rows)["per_symbol"]}
        # "离场烂"的定义 = 回吐更多（BTC 到过 3R 只拿 1R，ARB 到过 2R 也拿 1R）
        self.assertGreater(matrix["BTC"]["avg_give_back_r"],
                           matrix["ARB"]["avg_give_back_r"])
        self.assertEqual(matrix["BTC"]["n"], 9)

    def test_thin_symbols_are_disclosed(self):
        rows = ([_row(inst="BTC", mfe_pct=3.0)] * 10 + [_row(inst="XRP", mfe_pct=3.0)] * 2)
        analysis = analyze_exit_quality(closed_trades=rows)
        self.assertTrue(any("XRP" in s and "样本" in s for s in analysis["insufficient"]))


class InsufficientEvidenceTests(unittest.TestCase):
    def test_historical_ledger_says_unassessable_not_zero(self):
        """★ 生产实况：历史台账一行证据都没有 ⇒ 明说"暂不可评估"。"""
        analysis = analyze_exit_quality(closed_trades=[_row() for _ in range(82)])
        self.assertEqual(analysis["evidence_rows"], 0)
        self.assertIsNone(analysis["overall"])
        brief = render_exit_quality_brief(analysis)
        self.assertIn("暂不可评估", brief)
        self.assertNotIn("0.0R", brief, "不得把'无数据'渲染成'效果为零'")

    def test_low_r_sample_is_flagged(self):
        rows = [_row(mfe_pct=3.0)] * 10   # 有 MFE 但无 entry/stop ⇒ 无 R
        analysis = analyze_exit_quality(closed_trades=rows)
        self.assertEqual(analysis["r_rows"], 0)
        self.assertTrue(any("R 口径" in s for s in analysis["insufficient"]))

    def test_min_sample_threshold_is_configurable(self):
        rows = [_row(exit_cause="ratchet_lock", mfe_pct=3.0)] * 3
        strict = analyze_exit_quality(closed_trades=rows, min_sample=10)
        loose = analyze_exit_quality(closed_trades=rows, min_sample=2)
        self.assertTrue(any("仅 3" in s for s in strict["insufficient"]))
        self.assertEqual(loose["min_sample"], 2)

    def test_empty_input_is_survivable(self):
        for junk in (None, [], "x", 42):
            with self.subTest(junk=junk):
                analysis = analyze_exit_quality(closed_trades=junk)
                self.assertEqual(analysis["evidence_rows"], 0)
                self.assertIsInstance(render_exit_quality_brief(analysis), str)


class RenderBriefTests(unittest.TestCase):
    def test_brief_renders_mechanism_and_give_back(self):
        rows = ([_row(inst="BTC", exit_cause="hard_stop", net_pnl=-30.0, mfe_pct=6.0,
                      entry_px=100.0, initial_stop_px=98.0)] * 9
                + [_row(inst="ARB", exit_cause="ratchet_lock", net_pnl=+18.0, mfe_pct=4.0,
                        entry_px=100.0, initial_stop_px=98.0)] * 9)
        brief = render_exit_quality_brief(analyze_exit_quality(closed_trades=rows))
        self.assertIn("【离场质量】", brief)
        self.assertIn("硬止损", brief)
        self.assertIn("阶梯锁利", brief)
        self.assertIn("回吐", brief)
        self.assertIn("兑现率", brief)

    def test_missing_values_render_as_dash_not_zero(self):
        """★ 无值必须显示 `--`，不许显示 0（0 会被读成"实测为零"）。"""
        rows = [_row(inst="BTC", exit_cause="ratchet_lock", net_pnl=None, mfe_pct=None,
                     mae_pct=None, open_px=None, close_px=None)] * 2
        brief = render_exit_quality_brief(analyze_exit_quality(closed_trades=rows))
        self.assertIsInstance(brief, str)

    def test_brief_handles_junk(self):
        self.assertIn("暂不可评估", render_exit_quality_brief(None))
        self.assertIn("暂不可评估", render_exit_quality_brief({}))


class ProductionWiringTests(unittest.TestCase):
    def test_deterministic_insights_include_exit_quality(self):
        """兜底认知必须带上离场质量（模型全链失败时用户仍看得到回吐）。"""
        from scripts.self_improvement_engine import derive_deterministic_insights
        rows = [_row(inst="BTC", mfe_pct=5.0, entry_px=100.0, initial_stop_px=98.0,
                     exit_cause="ratchet_lock")] * 12
        insights = derive_deterministic_insights(rows, {"total": 12})
        joined = " ".join(insights)
        self.assertIn("离场质量", joined)

    def test_deterministic_insights_survive_evidence_free_rows(self):
        from scripts.self_improvement_engine import derive_deterministic_insights
        rows = [_row() for _ in range(12)]
        joined = " ".join(derive_deterministic_insights(rows, {"total": 12}))
        self.assertIn("暂不可评估", joined)


if __name__ == "__main__":
    unittest.main()
