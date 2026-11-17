"""心法健康度生命周期（`scripts/evolution/lesson_health.py`，方向 4）的回归。

## 这个测试在守什么

改造前 `health_score` 是**纯装饰品**：只在基准常量与 `_new_lesson()` 里写死
（90/92/95/98/99），**从未重算、从未被读取**；注入排序是
`(is_baseline, created_at)` = **"新的赢"**。于是"心法库"实际只增不减：
一条落地后一直亏钱的战术心法，只要够新就挤掉更有效的旧心法（注入配额只有 8 条）。

判据五族：

| 族 | 守什么 |
|---|---|
| 人群析出 | 点名 BTC 的心法用 BTC 样本评价；双向心法**不加**方向过滤（否则按错的一半评价） |
| 分数可辩护 | 按胜率＋期望值打分，并**按样本量向 50 回归**（样本刚好达标时不敢给极端分） |
| **证据不足 = 未知** | 样本 < 阈值 ⇒ 返回 `None` ⇒ **保留原分、绝不改状态**（不许"算不出就默认健康"） |
| 归档三条件 | 低分 **且** 样本达标 **且** 非基准；基准心法**永不**归档；归档 = 停用留痕**不删除** |
| 排序承重 | 健康分高的先注入；分数缺失按 0（不冒充健康）；基准恒在最前 |
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.evolution.lesson_health import (  # noqa: E402
    ARCHIVE_HEALTH_THRESHOLD, MIN_HEALTH_SAMPLE, decide_archive, extract_cohort,
    rank_lessons, refresh_lesson_health, score_cohort, score_lesson_against_trades,
    select_cohort,
)


def _row(inst="BTC", side="多", net=10.0, *, obs="DYNAMICS_OBSERVED", cause=""):
    return {"inst": inst, "side": side, "net_pnl": net,
            "snapshot_observability": obs, "exit_cause": cause}


def _losing(inst="BTC", side="多", n=12, net=-10.0):
    return [_row(inst, side, net) for _ in range(n)]


def _winning(inst="BTC", side="多", n=12, net=10.0):
    return [_row(inst, side, net) for _ in range(n)]


class CohortExtractionTests(unittest.TestCase):
    def test_symbol_is_extracted_as_a_whole_word(self):
        """`ETH` 不得命中 `ETHFI`（子串假名会把心法挂到错的标的上）。"""
        cohort = extract_cohort("ETHFI 放量突破时追多", available_insts=["ETH", "ETHFI"])
        self.assertEqual(cohort["insts"], ["ETHFI"])

    def test_unidirectional_lesson_gets_a_side_filter(self):
        self.assertEqual(extract_cohort("顺势做多，回踩不破就低吸",
                                        available_insts=[])["side"], "long")
        self.assertEqual(extract_cohort("反弹承压时高抛做空",
                                        available_insts=[])["side"], "short")

    def test_bidirectional_lesson_gets_no_side_filter(self):
        """★ 同时点名多空 ⇒ 这条心法本身双向，按单边评价是错的。"""
        cohort = extract_cohort("多头通道顺势做多，空头通道反弹做空",
                               available_insts=[])
        self.assertEqual(cohort["side"], "", "双向心法不得套单边 cohort")

    def test_generic_lesson_has_an_empty_cohort(self):
        cohort = extract_cohort("波动率放大时缩减仓位", available_insts=["BTC"])
        self.assertEqual(cohort, {"insts": [], "side": "", "exit_causes": []})

    def test_exit_mechanism_is_extracted(self):
        self.assertIn("time_stop", extract_cohort("时间止损后不要立刻反手",
                                                  available_insts=[])["exit_causes"])
        self.assertIn("ratchet_lock", extract_cohort("阶梯锁利生效后按结构持有",
                                                     available_insts=[])["exit_causes"])


class CohortSelectionTests(unittest.TestCase):
    def test_filters_are_combined_with_and(self):
        rows = [
            _row("BTC", "多", 10.0, cause="time_stop"),
            _row("BTC", "空", 10.0, cause="time_stop"),
            _row("ETH", "多", 10.0, cause="time_stop"),
            _row("BTC", "多", 10.0, cause="hard_stop"),
        ]
        subset = select_cohort(rows, {"insts": ["BTC"], "side": "long",
                                      "exit_causes": ["time_stop"]})
        self.assertEqual(len(subset), 1, "各维度是 AND，不是 OR")

    def test_rows_without_pnl_are_excluded(self):
        rows = [_row("BTC", "多", 10.0), {"inst": "BTC", "side": "多"}]
        self.assertEqual(len(select_cohort(rows, {"insts": ["BTC"]})), 1)


class ScoringTests(unittest.TestCase):
    def test_all_winners_score_high_all_losers_low(self):
        self.assertGreater(score_cohort(_winning(n=20))["health_score"],
                           score_cohort(_losing(n=20))["health_score"])

    def test_score_regresses_toward_fifty_at_the_sample_floor(self):
        """★ 样本恰好达标 ⇒ 只信一半偏离（不许给"100 分神级心法"）。"""
        small = score_cohort(_winning(n=MIN_HEALTH_SAMPLE))["health_score"]
        large = score_cohort(_winning(n=MIN_HEALTH_SAMPLE * 8))["health_score"]
        self.assertLess(small, large)
        self.assertLess(small, 100.0)

    def test_expectancy_is_scale_free(self):
        """期望值必须与金额绝对规模无关（否则大仓位的心法永远"更健康"）。"""
        tiny = score_cohort([_row(net=1.0) for _ in range(12)])["health_score"]
        huge = score_cohort([_row(net=1000.0) for _ in range(12)])["health_score"]
        self.assertAlmostEqual(tiny, huge, places=1)

    def test_low_observability_halves_the_confidence(self):
        """★ 人群样本几乎都是"仅价格" ⇒ 心法赖以成立的因子不可观测，得分偏离减半。"""
        observed = score_cohort(_winning(n=20, net=10.0))["health_score"]
        blind = score_cohort([_row(net=10.0, obs="PRICE_ONLY") for _ in range(20)])
        self.assertTrue(blind["low_confidence"])
        self.assertLess(blind["health_score"], observed)

    def test_win_rate_is_reported(self):
        stats = score_cohort([_row(net=10.0), _row(net=-10.0)])
        self.assertEqual(stats["win_rate_pct"], 50.0)
        self.assertEqual(stats["sample_size"], 2)
        self.assertEqual(stats["net_pnl"], 0.0)

    def test_no_numeric_rows_returns_none(self):
        self.assertIsNone(score_cohort([{"inst": "BTC"}]))


class InsufficientEvidenceTests(unittest.TestCase):
    def test_no_trades_returns_none(self):
        self.assertIsNone(score_lesson_against_trades("顺势做多", closed_trades=[]))
        self.assertIsNone(score_lesson_against_trades("顺势做多", closed_trades=None))

    def test_thin_cohort_returns_none_not_a_default(self):
        """★ 核心：BTC 只有 8 笔 ⇒ 返回 `None`（**未知**），不是 90 分、也不是 0 分。"""
        rows = _winning("BTC", n=MIN_HEALTH_SAMPLE - 2) + _winning("ETH", n=50)
        self.assertIsNone(
            score_lesson_against_trades("BTC 单笔保证金必须严格遵守风险预算",
                                        closed_trades=rows),
            "样本不足必然是 None，绝不许给默认分")

    def test_sufficient_cohort_scores_with_a_stated_basis(self):
        rows = _losing("DOGE", n=15)
        scored = score_lesson_against_trades("DOGE 放量突破才追多", closed_trades=rows)
        self.assertIsNotNone(scored)
        self.assertEqual(scored["sample_size"], 15)
        self.assertIn("DOGE", scored["basis"])

    def test_junk_input_never_raises(self):
        for junk in (None, [], "x", 42):
            with self.subTest(junk=junk):
                self.assertIsNone(
                    score_lesson_against_trades("顺势做多", closed_trades=junk))


class ArchiveDecisionTests(unittest.TestCase):
    def test_low_score_with_insufficient_sample_is_not_archived(self):
        decision, reason = decide_archive({}, {"health_score": 10.0, "sample_size": 3})
        self.assertFalse(decision)
        self.assertIn("样本", reason)

    def test_low_score_with_enough_sample_is_archived(self):
        decision, reason = decide_archive(
            {}, {"health_score": 40.0, "sample_size": 20, "basis": "全样本"})
        self.assertTrue(decision)
        self.assertIn("停用存档", reason, "必须说明可人工恢复，不是删除")
        self.assertIn(str(ARCHIVE_HEALTH_THRESHOLD), reason)

    def test_healthy_score_is_kept(self):
        decision, reason = decide_archive(
            {}, {"health_score": ARCHIVE_HEALTH_THRESHOLD, "sample_size": 20})
        self.assertFalse(decision)
        self.assertIn("保持启用", reason)

    def test_unscorable_never_changes_state(self):
        decision, reason = decide_archive({}, None)
        self.assertFalse(decision)
        self.assertIn("证据不足", reason)


class RankingTests(unittest.TestCase):
    def test_baseline_first_then_health_then_recency(self):
        """★ 旧键是"新的赢"；新键必须让**更有效**的排在更新的前面。"""
        lessons = [
            {"rule_text": "old_but_healthy", "health_score": 88.0, "is_baseline": False,
             "created_at": "2026-01-01"},
            {"rule_text": "new_but_bad", "health_score": 30.0, "is_baseline": False,
             "created_at": "2026-12-31"},
            {"rule_text": "baseline", "health_score": 95.0, "is_baseline": True,
             "created_at": "2020-01-01"},
        ]
        order = [x["rule_text"] for x in rank_lessons(lessons)]
        self.assertEqual(order, ["baseline", "old_but_healthy", "new_but_bad"])

    def test_missing_health_score_ranks_below_scored_ones(self):
        """★ 没打过分的**不许冒充健康**（旧实现里它们默认带 90.0）。"""
        lessons = [
            {"rule_text": "unscored", "is_baseline": False, "created_at": "2026-12-31"},
            {"rule_text": "scored_low", "health_score": 5.0, "is_baseline": False,
             "created_at": "2026-01-01"},
        ]
        self.assertEqual([x["rule_text"] for x in rank_lessons(lessons)],
                         ["scored_low", "unscored"])

    def test_recency_breaks_ties(self):
        lessons = [
            {"rule_text": "older", "health_score": 80.0, "is_baseline": False,
             "created_at": "2026-01-01"},
            {"rule_text": "newer", "health_score": 80.0, "is_baseline": False,
             "created_at": "2026-06-01"},
        ]
        self.assertEqual([x["rule_text"] for x in rank_lessons(lessons)], ["newer", "older"])

    def test_junk_entries_are_dropped(self):
        """非字典条目被丢弃；空字典是无害的（不参与分数比较，按 0 排）。"""
        self.assertEqual([x for x in rank_lessons([None, "x", {}, {"rule_text": "ok"}])
                          if x.get("rule_text")], [{"rule_text": "ok"}])


class RefreshTests(unittest.TestCase):
    def _lesson(self, text="DOGE 放量突破才追多", **over):
        base = {"id": "lesson_x", "rule_text": text, "enabled": True,
                "health_score": 90.0, "is_baseline": False, "created_at": "2026-01-01",
                "ttl_days": 7}
        base.update(over)
        return base

    def test_losing_lesson_is_rescored_and_archived(self):
        updated, changes = refresh_lesson_health(
            [self._lesson()], closed_trades=_losing("DOGE", n=20))
        self.assertEqual(updated[0]["health_score"], changes[0]["new_health"])
        self.assertLess(updated[0]["health_score"], ARCHIVE_HEALTH_THRESHOLD)
        self.assertFalse(updated[0]["enabled"], "低分心法必须归档（停用）")
        self.assertEqual(updated[0]["shield_status"], "archived")
        self.assertIn("archived_reason", updated[0])
        self.assertIn("health_basis", updated[0], "必须留下'依据什么样本'的痕迹")
        actions = [c["action"] for c in changes]
        self.assertIn("archive", actions)

    def test_winning_lesson_is_rescored_but_stays_enabled(self):
        updated, changes = refresh_lesson_health(
            [self._lesson()], closed_trades=_winning("DOGE", n=20))
        self.assertTrue(updated[0]["enabled"])
        self.assertGreater(updated[0]["health_score"], ARCHIVE_HEALTH_THRESHOLD)
        self.assertNotIn("archived_at", updated[0])
        self.assertEqual([c["action"] for c in changes], ["rescore"])

    def test_insufficient_evidence_leaves_score_and_state_untouched(self):
        """★ 样本不足 ⇒ 原分原样、状态原样、无变更记录。"""
        lesson = self._lesson()
        updated, changes = refresh_lesson_health([lesson], closed_trades=_losing("DOGE", n=3))
        self.assertEqual(updated[0]["health_score"], 90.0, "算不出就保留原分")
        self.assertTrue(updated[0]["enabled"])
        self.assertEqual(changes, [])

    def test_every_lesson_is_scored_by_evidence_with_no_exemption(self):
        """★ 2026-10：不再有"基准心法豁免评分"。

        基准机制整体拆除后，所有心法一律按证据评分并按需归档 —— 旧实现里那句
        "基准分数是宪法级声明常量、连分数都不改"已无对象。
        """
        lesson = self._lesson(text="DOGE 顺势做多", id="lesson_x")
        lesson["health_score"] = 95.0
        updated, changes = refresh_lesson_health([lesson], closed_trades=_losing("DOGE", n=30))
        self.assertLess(updated[0]["health_score"], 95.0, "按证据重算必须生效")
        self.assertFalse(updated[0]["enabled"], "低分一律归档（无豁免）")
        self.assertTrue(changes)

    def test_the_baseline_field_is_no_longer_produced(self):
        """反向判据：**建档函数**不得再写 `is_baseline`（否则等于把机制偷偷加回来）。

        ⚠️ 判据放在**产出侧**（`_new_lesson`）而不是 `refresh_lesson_health`：
        后者是纯计算，不该顺手清洗历史条目里的未知字段（那会静默改写用户数据）。
        """
        from scripts import evolution_shield as es
        item = es._new_lesson("【风控】4H 多头回踩支撑且量能缩减时限价做多", 5)
        self.assertNotIn("is_baseline", item, "建档不得再产出基准字段")
        self.assertTrue(es._validate([item]), "新 schema 必须仍能通过校验")

    def test_refresh_does_not_invent_the_baseline_field(self):
        updated, _ = refresh_lesson_health(
            [{"id": "x", "rule_text": "DOGE 追多", "enabled": True,
              "health_score": 90.0, "created_at": "2026-01-01"}],
            closed_trades=_losing("DOGE", n=30))
        self.assertNotIn("is_baseline", updated[0])

    def test_archiving_never_deletes_entries(self):
        lessons = [self._lesson(id="a"), self._lesson(text="ETH 突破追多", id="b")]
        updated, _ = refresh_lesson_health(lessons, closed_trades=_losing("DOGE", n=20))
        self.assertEqual(len(updated), 2, "归档不得删除任何条目")
        self.assertTrue(all("rule_text" in x for x in updated))

    def test_original_list_is_not_mutated(self):
        """纯函数纪律：入参不得被就地改写（调用方可能还要用旧快照）。"""
        lesson = self._lesson()
        before = dict(lesson)
        refresh_lesson_health([lesson], closed_trades=_losing("DOGE", n=20))
        self.assertEqual(lesson, before)

    def test_junk_lessons_are_skipped(self):
        updated, changes = refresh_lesson_health(
            [None, "x", 42], closed_trades=_losing("DOGE", n=20))
        self.assertEqual(updated, [])
        self.assertEqual(changes, [])


class ShieldWiringTests(unittest.TestCase):
    def _active(self, text, health, *, created="2026-10-01T00:00:00+00:00"):
        """一条**未过期**的战术心法（`ttl_days` 给足，否则会被 TTL 挡掉）。"""
        return {"rule_text": text, "health_score": health, "enabled": True,
                "is_baseline": False, "created_at": created, "id": "id_" + text,
                "category": "TACTICAL", "ttl_days": 3650}

    def test_injection_priority_follows_health_not_recency(self):
        """★ 核心：注入配额只有 8 条。旧键"新的赢"会让一条烂心法挤掉好心法。

        这里造 10 条：健康分与"新旧"**完全反向**（最老的最高分）。
        正确行为 = 注入分最高的 8 条，被挤掉的必须是分最低的 2 条（也正好是最新的）。
        """
        from scripts import evolution_shield as es
        lessons = [self._active(f"L{i}", health=float(10 * i),
                                created=f"2026-10-{i + 1:02d}T00:00:00+00:00")
                   for i in range(1, 11)]
        report = es.injection_report(lessons)
        self.assertEqual(report["injected"], 8)
        dropped = {i["id"] for i in report["not_injected"]}
        self.assertEqual(dropped, {"id_L1", "id_L2"},
                         "被挤掉的必须是健康分最低的两条，而不是最旧的两条")

        rendered = es.render_lessons(lessons)
        # ⚠️ 必须按**整行**比较：`"L1"` 是 `"L10"` 的子串，子串断言会假绿/假红。
        lines = [ln.lstrip("- ").strip() for ln in rendered.splitlines() if ln.strip()]
        self.assertEqual(lines, ["L10", "L9", "L8", "L7", "L6", "L5", "L4", "L3"],
                         "提示词必须按健康分降序，且只有分最高的 8 条")

    def test_render_and_injection_agree_on_the_same_set(self):
        """面板与提示词必须是**同一份名单**（否则"实时透明注入"就是假的）。"""
        from scripts import evolution_shield as es
        lessons = [self._active(f"L{i}", health=float(10 * i),
                                created=f"2026-10-{i + 1:02d}T00:00:00+00:00")
                   for i in range(1, 11)]
        report = es.injection_report(lessons)
        rendered = es.render_lessons(lessons)
        self.assertEqual(report["injected"], rendered.count("- "),
                         "面板报的注入条数必须等于提示词实际条数")

    def test_health_refresh_is_exposed_on_the_shield(self):
        from scripts import evolution_shield as es
        self.assertTrue(callable(getattr(es, "refresh_health_from_evidence", None)))


if __name__ == "__main__":
    unittest.main()
