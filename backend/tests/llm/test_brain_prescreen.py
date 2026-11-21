"""确定性预筛（`scripts/brain/prescreen.py`）契约门 —— 2026-11 上下文漏斗。

## 这个门守什么

预筛是「LLM 深度分析范围」的**唯一决定者**。它的失败方式不是抛异常，而是
**静默缩小分析范围**：漏掉一个在管持仓、把缺分标的误判为落选、或把「读不到持仓」
当成「没有持仓」。这类错误不会让任何下游报错，只会让某个仓位无人看管。

因此这里钉的是 design.md §2.3 的 8 条规则与它们的失败方向：

- 必选（持仓/挂单）无条件入选，且不占候选名额；
- 排序确定性：评分降序、同分按 `instId` 字典序；
- 缺分/坏分**不落选**（并入深度分析 + `degraded`）；
- 全池不可排序 / 持仓或挂单未知 / 内部异常 ⇒ **全量回退**（绝不缩小范围）；
- 候选上限可配置、钳制到 `[1, pool_size]`；
- 任何输入都不抛。
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.brain import prescreen  # noqa: E402
from scripts.brain.prescreen import (  # noqa: E402
    CANDIDATE_LIMIT_ENV,
    candidate_limit,
    select_deep_analysis_packages,
)

_MISSING = object()


def _pkg(inst_id, score=_MISSING, signal="WAIT", *, name=None, ranking=_MISSING):
    """构造一个最小数据包；`score=_MISSING` 表示 `factor_ranking` 里没有该键。"""
    pkg = {"instId": inst_id, "name": name if name is not None else inst_id.split("-")[0]}
    if ranking is not _MISSING:
        pkg["factor_ranking"] = ranking
    else:
        data = {}
        if score is not _MISSING:
            data["composite_alpha_score"] = score
        if signal is not _MISSING:
            data["signal_recommendation"] = signal
        pkg["factor_ranking"] = data
    return pkg


def _ids(packages):
    return [p["instId"] for p in packages]


def _select(packages, **kw):
    return select_deep_analysis_packages(packages, **kw)


class MandatorySelectionTests(unittest.TestCase):
    def test_mandatory_symbols_are_always_deep_and_do_not_consume_quota(self):
        packages = [
            _pkg("HHH-USDT-SWAP", 100.0),
            _pkg("GGG-USDT-SWAP", 90.0),
            _pkg("FFF-USDT-SWAP", 80.0),
            _pkg("POS-USDT-SWAP", -50.0),      # 必选：低分也必进
            _pkg("ORD-USDT-SWAP", -60.0),      # 必选：低分也必进
            _pkg("EEE-USDT-SWAP", 70.0),
        ]
        out = _select(packages,
                      mandatory_inst_ids={"POS-USDT-SWAP", "ORD-USDT-SWAP"}, limit=2)
        self.assertEqual(set(_ids(out["deep_packages"])),
                         {"POS-USDT-SWAP", "ORD-USDT-SWAP",
                          "HHH-USDT-SWAP", "GGG-USDT-SWAP"})
        meta = out["meta"]
        self.assertEqual(meta["mandatory_count"], 2)
        self.assertEqual(meta["candidate_count"], 2, "名额只作用于非必选标的")
        self.assertEqual(meta["screened_out_count"], 2)
        self.assertEqual(meta["mode"], "funnel")
        self.assertFalse(meta["prescreen_unavailable"])

    def test_mandatory_symbols_never_appear_in_the_screened_out_pool(self):
        packages = [_pkg(f"S{i}-USDT-SWAP", float(i)) for i in range(8)]
        out = _select(packages, mandatory_inst_ids={"S0-USDT-SWAP"}, limit=1)
        screened = {row["instId"] for row in out["screened_out"]}
        self.assertNotIn("S0-USDT-SWAP", screened)
        self.assertIn("S0-USDT-SWAP", _ids(out["deep_packages"]))

    def test_a_mandatory_symbol_without_a_score_is_not_reported_as_degraded(self):
        """缺分只影响"能否排序"；必选本来就不靠排序入选 ⇒ 不算降级。"""
        packages = [_pkg("POS-USDT-SWAP"), _pkg("A-USDT-SWAP", 1.0),
                    _pkg("B-USDT-SWAP", 2.0)]
        out = _select(packages, mandatory_inst_ids={"POS-USDT-SWAP"}, limit=5)
        self.assertIn("POS-USDT-SWAP", _ids(out["deep_packages"]))
        self.assertFalse(out["meta"]["degraded"])
        self.assertEqual(out["meta"]["missing_score_inst_ids"], [])

    def test_unknown_mandatory_ids_are_ignored(self):
        packages = [_pkg("A-USDT-SWAP", 1.0)]
        out = _select(packages, mandatory_inst_ids={"NOPE-USDT-SWAP"}, limit=5)
        self.assertEqual(out["meta"]["mandatory_count"], 0)
        self.assertEqual(_ids(out["deep_packages"]), ["A-USDT-SWAP"])

    def test_all_mandatory_pool_is_a_normal_funnel_not_a_false_fallback(self):
        """全池都是在管持仓时没有候选，但预筛**没有降级**（评分是可用的）。

        只看 `ranked`（必选不参与排序）会把这种轮次误标成
        `no_rankable_scores` 全量回退，提示词会写「本轮预筛降级」——
        范围虽未缩小，却是对用户/模型的假披露。"""
        packages = [_pkg("A-USDT-SWAP", 1.0), _pkg("B-USDT-SWAP", 2.0)]
        out = _select(packages, mandatory_inst_ids={"A-USDT-SWAP", "B-USDT-SWAP"},
                      limit=5)
        self.assertEqual(out["meta"]["mode"], "funnel")
        self.assertFalse(out["meta"]["prescreen_unavailable"])
        self.assertEqual(out["meta"]["reason"], "")
        self.assertEqual(out["meta"]["mandatory_count"], 2)
        self.assertEqual(out["meta"]["candidate_count"], 0)
        self.assertEqual(out["screened_out"], [])
        self.assertEqual(_ids(out["deep_packages"]), _ids(packages))

    def test_mandatory_scores_keep_the_funnel_alive_when_others_lack_scores(self):
        packages = [_pkg("POS-USDT-SWAP", 3.0), _pkg("MISS-USDT-SWAP")]
        out = _select(packages, mandatory_inst_ids={"POS-USDT-SWAP"}, limit=5)
        self.assertEqual(out["meta"]["mode"], "funnel")
        self.assertFalse(out["meta"]["prescreen_unavailable"])
        self.assertTrue(out["meta"]["degraded"])
        self.assertEqual(out["meta"]["missing_score_inst_ids"], ["MISS-USDT-SWAP"])
        self.assertEqual(set(_ids(out["deep_packages"])), set(_ids(packages)))
        self.assertEqual(out["screened_out"], [])


class RankingTests(unittest.TestCase):
    def test_top_limit_is_score_descending(self):
        packages = [_pkg(f"S{i}-USDT-SWAP", float(i)) for i in range(8)]
        out = _select(packages, limit=5)
        self.assertEqual(set(_ids(out["deep_packages"])),
                         {"S3-USDT-SWAP", "S4-USDT-SWAP", "S5-USDT-SWAP",
                          "S6-USDT-SWAP", "S7-USDT-SWAP"},
                         "应选中评分最高的 5 个（深度包按原始顺序输出）")
        self.assertEqual([row["instId"] for row in out["screened_out"]],
                         ["S2-USDT-SWAP", "S1-USDT-SWAP", "S0-USDT-SWAP"])

    def test_deep_packages_keep_the_original_package_order(self):
        """提示词稳定性：深度包必须按传入顺序输出，而不是按分数重排。"""
        packages = [_pkg("C-USDT-SWAP", 1.0), _pkg("A-USDT-SWAP", 3.0),
                    _pkg("B-USDT-SWAP", 2.0)]
        out = _select(packages, limit=3)
        self.assertEqual(_ids(out["deep_packages"]),
                         ["C-USDT-SWAP", "A-USDT-SWAP", "B-USDT-SWAP"])

    def test_ties_break_by_inst_id_ascending(self):
        packages = [_pkg("CCC-USDT-SWAP", 5.0), _pkg("AAA-USDT-SWAP", 5.0),
                    _pkg("BBB-USDT-SWAP", 5.0), _pkg("DDD-USDT-SWAP", 5.0)]
        out = _select(packages, limit=2)
        self.assertEqual(_ids(out["deep_packages"]),
                         ["AAA-USDT-SWAP", "BBB-USDT-SWAP"],
                         "同分必须按 instId 字典序，不得依赖输入顺序")
        self.assertEqual([row["rank"] for row in out["screened_out"]], [3, 4])

    def test_selection_is_independent_of_input_permutation(self):
        """输入顺序不得影响「谁入选/谁落选」；深度包自身仍按各自原始顺序输出。"""
        base = [_pkg("AAA-USDT-SWAP", 5.0), _pkg("BBB-USDT-SWAP", 5.0),
                _pkg("CCC-USDT-SWAP", 6.0), _pkg("DDD-USDT-SWAP", 4.0)]
        first = _select(base, limit=2)
        second = _select(list(reversed(base)), limit=2)
        self.assertEqual(sorted(_ids(first["deep_packages"])),
                         sorted(_ids(second["deep_packages"])))
        self.assertEqual([r["instId"] for r in first["screened_out"]],
                         [r["instId"] for r in second["screened_out"]])

    def test_screened_out_rows_carry_score_signal_rank_and_reason(self):
        packages = [_pkg("A-USDT-SWAP", 9.0, "BUY_LONG"),
                    _pkg("B-USDT-SWAP", 1.0, "WAIT")]
        row = _select(packages, limit=1)["screened_out"][0]
        self.assertEqual(row["instId"], "B-USDT-SWAP")
        self.assertEqual(row["name"], "B")
        self.assertEqual(row["score"], 1.0)
        self.assertEqual(row["signal"], "WAIT")
        self.assertEqual(row["rank"], 2)
        self.assertIn("Top 1", row["reason"])
        self.assertIn("评分 1.0", row["reason"])

    def test_deep_and_screened_out_cover_the_whole_pool_exactly_once(self):
        packages = [_pkg(f"S{i}-USDT-SWAP", float(i)) for i in range(11)]
        out = _select(packages, mandatory_inst_ids={"S0-USDT-SWAP"}, limit=5)
        covered = _ids(out["deep_packages"]) + [r["instId"] for r in out["screened_out"]]
        self.assertEqual(sorted(covered), sorted(_ids(packages)),
                         "预筛不得让任何标的静默消失或重复出现")

    def test_candidate_limit_larger_than_pool_screens_nobody_out(self):
        packages = [_pkg("A-USDT-SWAP", 1.0), _pkg("B-USDT-SWAP", 2.0)]
        out = _select(packages, limit=999)
        self.assertEqual(out["meta"]["candidate_limit"], 2)
        self.assertEqual(out["screened_out"], [])
        self.assertEqual(out["meta"]["candidate_count"], 2)


class MissingScoreTests(unittest.TestCase):
    BAD_SCORES = (None, "--", "", "12.5", True, False,
                  float("nan"), float("inf"), float("-inf"), [], {})

    def test_missing_or_broken_scores_are_never_screened_out(self):
        """★ D3：缺分不落选 —— 坏分标的全部并入深度分析并披露 degraded。"""
        packages = [_pkg("GOOD1-USDT-SWAP", 10.0), _pkg("GOOD2-USDT-SWAP", 9.0)]
        bad_packages = []
        for index, bad in enumerate(self.BAD_SCORES):
            pkg = _pkg(f"BAD{index}-USDT-SWAP", bad)
            packages.append(pkg)
            bad_packages.append(pkg)
        out = _select(packages, limit=1)
        deep = set(_ids(out["deep_packages"]))
        for pkg in bad_packages:
            self.assertIn(pkg["instId"], deep, f"坏分 {pkg['instId']} 被静默落选")
        self.assertTrue(out["meta"]["degraded"])
        self.assertEqual(set(out["meta"]["missing_score_inst_ids"]),
                         {pkg["instId"] for pkg in bad_packages})
        self.assertEqual([r["instId"] for r in out["screened_out"]],
                         ["GOOD2-USDT-SWAP"])

    def test_absent_factor_ranking_blob_counts_as_missing_score(self):
        packages = [_pkg("A-USDT-SWAP", 5.0), _pkg("B-USDT-SWAP", ranking=None),
                    _pkg("C-USDT-SWAP", ranking="junk"), _pkg("D-USDT-SWAP", ranking={})]
        out = _select(packages, limit=1)
        self.assertTrue(out["meta"]["degraded"])
        self.assertEqual(set(out["meta"]["missing_score_inst_ids"]),
                         {"B-USDT-SWAP", "C-USDT-SWAP", "D-USDT-SWAP"})
        self.assertEqual(set(_ids(out["deep_packages"])),
                         {"A-USDT-SWAP", "B-USDT-SWAP", "C-USDT-SWAP", "D-USDT-SWAP"})

    def test_whole_pool_unrankable_falls_back_to_everything(self):
        packages = [_pkg("A-USDT-SWAP"), _pkg("B-USDT-SWAP", "--")]
        out = _select(packages, limit=1)
        self.assertEqual(out["meta"]["mode"], "full_fallback")
        self.assertTrue(out["meta"]["prescreen_unavailable"])
        self.assertEqual(out["meta"]["reason"], "no_rankable_scores")
        self.assertEqual(out["screened_out"], [])
        self.assertEqual(_ids(out["deep_packages"]), _ids(packages))

    def test_all_mandatory_and_unscored_still_falls_back(self):
        """必选也全都没有评分 ⇒ 预筛确实不可用（没有被"必选"掩盖）。"""
        packages = [_pkg("A-USDT-SWAP"), _pkg("B-USDT-SWAP", None)]
        out = _select(packages, mandatory_inst_ids={"A-USDT-SWAP", "B-USDT-SWAP"})
        self.assertEqual(out["meta"]["mode"], "full_fallback")
        self.assertTrue(out["meta"]["prescreen_unavailable"])
        self.assertEqual(out["meta"]["reason"], "no_rankable_scores")
        self.assertEqual(_ids(out["deep_packages"]), _ids(packages))

    def test_a_zero_score_is_a_real_score_not_missing(self):
        """0 是合法评分（有符号分的中轴）—— 不得用 `default=0` 把它与缺分混为一谈。"""
        packages = [_pkg("ZERO-USDT-SWAP", 0.0), _pkg("GOOD-USDT-SWAP", 1.0)]
        out = _select(packages, limit=1)
        self.assertFalse(out["meta"]["degraded"])
        self.assertEqual(out["screened_out"][0]["instId"], "ZERO-USDT-SWAP")
        self.assertEqual(out["screened_out"][0]["score"], 0.0)

    def test_negative_scores_are_ranked_normally(self):
        packages = [_pkg("A-USDT-SWAP", -1.0), _pkg("B-USDT-SWAP", -5.0),
                    _pkg("C-USDT-SWAP", -10.0)]
        out = _select(packages, limit=2)
        self.assertEqual(_ids(out["deep_packages"]),
                         ["A-USDT-SWAP", "B-USDT-SWAP"])
        self.assertEqual(out["screened_out"][0]["instId"], "C-USDT-SWAP")


class UnknownInputsFallBackTests(unittest.TestCase):
    def test_positions_unreadable_falls_back_to_full_pool(self):
        packages = [_pkg(f"S{i}-USDT-SWAP", float(i)) for i in range(6)]
        out = _select(packages, positions_known=False, limit=1)
        self.assertEqual(out["meta"]["mode"], "full_fallback")
        self.assertTrue(out["meta"]["prescreen_unavailable"])
        self.assertEqual(out["meta"]["reason"], "positions_unreadable")
        self.assertEqual(_ids(out["deep_packages"]), _ids(packages))
        self.assertEqual(out["screened_out"], [])

    def test_pending_orders_unreadable_falls_back_to_full_pool(self):
        packages = [_pkg(f"S{i}-USDT-SWAP", float(i)) for i in range(6)]
        out = _select(packages, pending_orders_known=False, limit=1)
        self.assertEqual(out["meta"]["mode"], "full_fallback")
        self.assertTrue(out["meta"]["prescreen_unavailable"])
        self.assertEqual(out["meta"]["reason"], "pending_orders_unreadable")
        self.assertEqual(_ids(out["deep_packages"]), _ids(packages))

    def test_positions_failure_wins_when_both_are_unknown(self):
        out = _select([_pkg("A-USDT-SWAP", 1.0)],
                      positions_known=False, pending_orders_known=False)
        self.assertEqual(out["meta"]["reason"], "positions_unreadable")

    def test_internal_exception_falls_back_and_never_raises(self):
        class Exploding(dict):
            def get(self, key, default=None):
                if key == "factor_ranking":
                    raise RuntimeError("boom")
                return super().get(key, default)

        evil = Exploding({"instId": "EVIL-USDT-SWAP", "name": "EVIL"})
        out = _select([_pkg("A-USDT-SWAP", 1.0), evil], limit=1)
        self.assertEqual(out["meta"]["mode"], "full_fallback")
        self.assertTrue(out["meta"]["prescreen_unavailable"])
        self.assertEqual(out["meta"]["reason"], "prescreen_error:RuntimeError")
        self.assertEqual(len(out["deep_packages"]), 2)
        self.assertEqual(out["screened_out"], [])

    def test_exception_fallback_does_not_drop_a_generator_input(self):
        """异常回退不得重新迭代已被消费的生成器（否则回退集为空 = 全部丢）。"""
        class Exploding(dict):
            def get(self, key, default=None):
                if key == "factor_ranking":
                    raise RuntimeError("boom")
                return super().get(key, default)

        good = _pkg("A-USDT-SWAP", 1.0)
        evil = Exploding({"instId": "EVIL-USDT-SWAP", "name": "EVIL"})

        def stream():
            yield good
            yield evil

        out = _select(stream(), limit=1)
        self.assertEqual(out["meta"]["mode"], "full_fallback")
        self.assertEqual(out["deep_packages"], [good, evil],
                         "生成器入参在异常回退时不得静默丢包")

    def test_empty_pool_returns_empty_result_without_raising(self):
        out = _select([])
        self.assertEqual(out["deep_packages"], [])
        self.assertEqual(out["screened_out"], [])
        self.assertEqual(out["meta"]["mode"], "funnel")
        self.assertEqual(out["meta"]["pool_size"], 0)
        self.assertFalse(out["meta"]["prescreen_unavailable"])

    def test_weird_packages_are_never_dropped(self):
        packages = [None, 42, "junk", _pkg("A-USDT-SWAP", 1.0)]
        out = _select(packages, limit=1)
        # 没有 instId 的畸形包无法排序 ⇒ 并入深度分析，但不会让函数抛
        self.assertIn(packages[0], out["deep_packages"])
        self.assertIn(packages[2], out["deep_packages"])
        self.assertEqual(out["meta"]["mode"], "funnel")


class CandidateLimitTests(unittest.TestCase):
    def test_default_is_five(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(CANDIDATE_LIMIT_ENV, None)
            self.assertEqual(candidate_limit(11), 5)

    def test_env_value_is_read_at_call_time(self):
        with patch.dict(os.environ, {CANDIDATE_LIMIT_ENV: "2"}):
            self.assertEqual(candidate_limit(11), 2)
        with patch.dict(os.environ, {CANDIDATE_LIMIT_ENV: "7"}):
            self.assertEqual(candidate_limit(11), 7)

    def test_invalid_env_value_falls_back_to_the_safe_default(self):
        for raw in ("", "abc", "2.5x", None):
            with self.subTest(raw=raw), patch.dict(os.environ, {CANDIDATE_LIMIT_ENV: raw or ""}):
                self.assertEqual(candidate_limit(11), 5)

    def test_limit_is_clamped_into_one_to_pool_size(self):
        for raw, expected in ((0, 1), (-5, 1), (1, 1), (11, 11), (999, 11)):
            with self.subTest(raw=raw):
                self.assertEqual(candidate_limit(11, raw=raw), expected)

    def test_explicit_limit_argument_overrides_the_env(self):
        with patch.dict(os.environ, {CANDIDATE_LIMIT_ENV: "2"}):
            self.assertEqual(candidate_limit(11, raw=3), 3)

    def test_empty_pool_has_no_candidate_slots(self):
        self.assertEqual(candidate_limit(0), 0)

    def test_select_uses_the_env_limit_when_none_is_passed(self):
        packages = [_pkg(f"S{i}-USDT-SWAP", float(i)) for i in range(6)]
        with patch.dict(os.environ, {CANDIDATE_LIMIT_ENV: "2"}):
            out = _select(packages)
        self.assertEqual(out["meta"]["candidate_limit"], 2)
        self.assertEqual(out["meta"]["candidate_count"], 2)
        self.assertEqual(len(out["screened_out"]), 4)

    def test_select_clamps_a_non_numeric_limit_to_the_default(self):
        packages = [_pkg(f"S{i}-USDT-SWAP", float(i)) for i in range(8)]
        out = _select(packages, limit="not-a-number")
        self.assertEqual(out["meta"]["candidate_limit"], 5)

    def test_public_module_surface(self):
        self.assertEqual(prescreen.DEFAULT_CANDIDATE_LIMIT, 5)
        self.assertEqual(prescreen.CANDIDATE_LIMIT_ENV, "ASTRA_BRAIN_CANDIDATE_LIMIT")


if __name__ == "__main__":
    unittest.main()
