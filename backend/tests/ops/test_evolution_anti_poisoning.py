"""回归测试：自进化防投毒、小样本门禁、贝叶斯收缩、失效后时间归因与 60% 胜率规则保活。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from astra_backend.math_utils import clamp
from scripts import self_improvement_engine as SIE
from scripts.evolution.lesson_health import (
    ARCHIVE_HEALTH_THRESHOLD,
    ARCHIVE_MIN_SAMPLE,
    MIN_HEALTH_SAMPLE,
    refresh_lesson_health,
    score_cohort,
    score_lesson_against_trades,
)
from scripts.evolution.review_context import normalize_asset_multipliers


class EvolutionAntiPoisoningTests(unittest.TestCase):
    def test_asset_multipliers_locked_to_one_below_min_sample_and_shrink_above(self):
        # 5 distinct DYNAMICS_OBSERVED BTC positions + 4 scale-out legs sharing same open_time -> count is 5 (<8)
        small_trades = [
            {"inst": "BTC-USDT-SWAP", "side": "long", "open_time": f"2026-11-0{i+1} 10:00:00", "snapshot_observability": "DYNAMICS_OBSERVED"}
            for i in range(5)
        ] + [
            {"inst": "BTC-USDT-SWAP", "side": "long", "open_time": "2026-11-01 10:00:00", "snapshot_observability": "DYNAMICS_OBSERVED"}
            for _ in range(4)
        ] + [
            # Non-observable ETH trades must NOT satisfy the sample threshold
            {"inst": "ETH-USDT-SWAP", "side": "long", "open_time": f"2026-11-{10+i} 10:00:00", "snapshot_observability": "PRICE_ONLY"}
            for i in range(12)
        ]
        res = normalize_asset_multipliers(
            TARGET_INSTRUMENTS=["BTC", "ETH"],
            clamp=clamp,
            llm_review={"asset_multipliers": {"BTC": 1.4, "ETH": 0.6}},
            closed_trades=small_trades,
        )
        self.assertEqual(res["BTC"], 1.0)
        self.assertEqual(res["ETH"], 1.0)

        # 10 distinct DYNAMICS_OBSERVED BTC trades -> Bayesian shrinkage 1.0 + (1.4 - 1.0) * (10 / 20) = 1.2
        ten_trades = [
            {"inst": "BTC-USDT-SWAP", "side": "short", "open_time": f"2026-11-{10+i} 12:00:00", "snapshot_observability": "DYNAMICS_OBSERVED"}
            for i in range(10)
        ]
        res2 = normalize_asset_multipliers(
            TARGET_INSTRUMENTS=["BTC", "ETH"],
            clamp=clamp,
            llm_review={"asset_multipliers": {"BTC": 1.4, "ETH": 0.5}},
            closed_trades=ten_trades,
        )
        self.assertEqual(res2["BTC"], 1.2)
        self.assertEqual(res2["ETH"], 1.0)

    def test_lesson_health_does_not_mis_archive_60pct_win_rate_rule_at_n10_or_n15(self):
        # 60% win rate with avg win 12 and avg loss -10
        rows_10 = [{"inst": "SOL", "side": "多", "net_pnl": 12.0, "snapshot_observability": "DYNAMICS_OBSERVED"}] * 6 + [
            {"inst": "SOL", "side": "多", "net_pnl": -10.0, "snapshot_observability": "DYNAMICS_OBSERVED"}
        ] * 4
        scored_10 = score_cohort(rows_10)
        self.assertIsNotNone(scored_10)

        lesson = {
            "id": "l_good",
            "rule_text": "SOL 回踩 EMA21 企稳顺势做多",
            "enabled": True,
            "health_score": 90.0,
            "created_at": "2026-11-01T00:00:00+00:00",
        }
        updated_10, changes_10 = refresh_lesson_health([lesson], closed_trades=rows_10)
        self.assertTrue(updated_10[0]["enabled"], f"n=10 (<ARCHIVE_MIN_SAMPLE={ARCHIVE_MIN_SAMPLE}) 不得淘汰好规则")
        self.assertNotIn("archive", [c["action"] for c in changes_10])

        rows_15 = [{"inst": "SOL", "side": "多", "net_pnl": 12.0, "snapshot_observability": "DYNAMICS_OBSERVED"}] * 9 + [
            {"inst": "SOL", "side": "多", "net_pnl": -10.0, "snapshot_observability": "DYNAMICS_OBSERVED"}
        ] * 6
        updated_15, changes_15 = refresh_lesson_health([lesson], closed_trades=rows_15)
        self.assertTrue(
            updated_15[0]["enabled"],
            f"60% 胜率正期望规则不得被 ARCHIVE_HEALTH_THRESHOLD={ARCHIVE_HEALTH_THRESHOLD} 误杀: {changes_15}",
        )

    def test_post_effective_timestamp_attribution_ignores_pre_lesson_trades(self):
        pre_losses = [
            {
                "inst": "BNB",
                "side": "空",
                "net_pnl": -20.0,
                "open_time": f"2026-11-0{i+1} 08:00:00",
                "snapshot_observability": "DYNAMICS_OBSERVED",
            }
            for i in range(9)
        ] + [
            {
                "inst": "BNB",
                "side": "空",
                "net_pnl": -20.0,
                "open_time": f"2026-11-{10+i} 08:00:00",
                "snapshot_observability": "DYNAMICS_OBSERVED",
            }
            for i in range(7)
        ]
        # Created AFTER all pre_losses
        scored = score_lesson_against_trades(
            "BNB 反弹遇阻高空",
            closed_trades=pre_losses,
            min_sample=MIN_HEALTH_SAMPLE,
            created_at="2026-11-25T00:00:00+00:00",
        )
        self.assertIsNone(scored, "规则生效前的历史亏损单不得计入该规则健康分")

    def test_llm_proposed_rule_blocked_below_observable_cohort_floor(self):
        closed_trades = [
            {"inst": "XRP", "side": "long", "open_time": f"2026-11-2{i} 10:00:00", "snapshot_observability": "DYNAMICS_OBSERVED"}
            for i in range(4)
        ] + [
            {"inst": "BTC", "side": "short", "open_time": f"2026-11-1{i} 10:00:00", "snapshot_observability": "NONE"}
            for i in range(10)
        ]
        logs: list[str] = []
        status, kept = SIE.filter_lessons_by_observable_cohort(
            "ADD",
            ["XRP 回踩支撑做多必须等缩量确认"],
            [],
            closed_trades,
            log_fn=logs.append,
        )
        self.assertEqual(status, "NO_CHANGE")
        self.assertEqual(kept, [])
        self.assertTrue(any("拒绝小样本自进化规则" in line for line in logs))

    def test_archive_and_reset_poisoned_state_resets_multipliers_and_clears_small_lessons(self):
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            (tdir / "asset_multipliers.json").write_text(
                json.dumps({"multipliers": {"BTC": 1.35, "SOL": 0.65}}), encoding="utf-8"
            )
            (tdir / "structured_trading_memory.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "revision": "r1",
                        "lessons": [
                            {
                                "id": "lesson_small",
                                "category": "TACTICAL",
                                "rule_text": "小样本规则不应长期驻留记忆",
                                "enabled": True,
                                "health_score": 90.0,
                                "sample_size": 4,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with mock.patch.object(SIE, "TARGET_INSTRUMENTS", ["BTC", "SOL"]):
                res = SIE.archive_and_reset_poisoned_evolution_state(str(tdir))
            self.assertEqual(res["removed_lessons"], 1)
            self.assertTrue(res["multipliers_reset"])
            mults = json.loads((tdir / "asset_multipliers.json").read_text(encoding="utf-8"))["multipliers"]
            self.assertEqual(mults, {"BTC": 1.0, "SOL": 1.0})
            mem = json.loads((tdir / "structured_trading_memory.json").read_text(encoding="utf-8"))["lessons"]
            self.assertEqual(mem, [])


if __name__ == "__main__":
    unittest.main()
