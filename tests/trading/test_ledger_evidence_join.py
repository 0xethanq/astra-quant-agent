"""平仓行 ← 平仓证据 join（`scripts/ledger/evidence_join.py`）的回归。

## 这个测试在守什么

台账权威来源是**交易所平仓历史**，它只知道自己字段。复盘要的开仓快照 / MFE-MAE /
机制级离场原因只活在追踪器里（平仓即被 `pop`），由 `close_evidence` 落成旁车。
本模块负责把旁车 join 回平仓行 —— 判据围绕四件事：

| 判据 | 为什么 |
|---|---|
| 容差匹配（追踪器建档晚于交易所开仓 ≤20min） | 建档发生在成交后的首个巡检周期 ⇒ 精确相等必然匹配不上 |
| **事实 vs 猜测显式分离** | 旧实现把"止盈推定"和"首批分批止盈"混成一句话，41% 的行无法分辨可信度 |
| 一条证据只用一次 | 两个平仓行共享一条证据 ⇒ 回吐统计重复计数 |
| 绝不覆盖交易所字段 | 台账是成交事实源，派生数据不许改写它 |

纯函数：全部离线，不读盘不写盘。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.ledger.evidence_join import (  # noqa: E402
    EVIDENCE_MAX_LATE_SECONDS, SOURCE_INFERRED, SOURCE_MECHANISM,
    enrich_closed_rows_with_evidence, normalize_inst, normalize_side,
)


def _row(**over):
    base = {
        "id": "pos_hist_1_BTC", "inst": "BTC", "side": "多", "venue": "okx",
        "status": "closed", "open_time": "2026-10-01 10:00:00",
        "close_time": "2026-10-01 12:00:00", "net_pnl": 12.0,
        "exit_reason": "🛑 止损离场",
    }
    base.update(over)
    return base


def _evidence(**over):
    base = {
        "key": "BTC|long|2026-10-01 10:03:00",
        "inst": "BTC", "inst_id": "BTC-USDT-SWAP", "side": "long",
        "open_time": "2026-10-01 10:03:00", "closed_at": "2026-10-01 12:00:00",
        "exit_cause": "time_stop", "exit_cause_raw": "时间止损",
        "entry_snapshot": {"macd_hist": 1.5, "obi_pct": 22.0},
        "mfe_pct": 1.2, "mae_pct": -0.6, "mfe_r": 1.4, "mae_r": -0.7,
        "r_denominator": 250.0, "initial_stop_px": 78250.0,
        "high_water_mark": 81000.0, "low_water_mark": 79500.0,
        "policy_version": "v8.5.0@abc", "policy_hash": "abc",
        "strategy_tag": "🌊 顺势回踩", "scale_out_phase": 1,
        "decision_source": "council", "adopted_role": "trader_trend",
    }
    base.update(over)
    return base


class NormalizeTests(unittest.TestCase):
    def test_inst_and_side_normalization(self):
        self.assertEqual(normalize_inst("BTC-USDT-SWAP"), "BTC")
        self.assertEqual(normalize_inst(" BTC "), "BTC")
        self.assertEqual(normalize_side("多"), "long")
        self.assertEqual(normalize_side("SHORT"), "short")
        self.assertEqual(normalize_side("net"), "")
        self.assertEqual(normalize_side(None), "")


class MatchingTests(unittest.TestCase):
    def test_tracker_built_after_fill_still_matches(self):
        """★ 容差：追踪器建档比交易所开仓晚 3 分钟（常态）必须匹配上。"""
        rows = [_row()]
        out, stats = enrich_closed_rows_with_evidence(
            trades=rows, evidence=[_evidence(open_time="2026-10-01 10:03:00")])
        self.assertEqual(stats["matched"], 1)
        self.assertEqual(out[0]["exit_cause"], "time_stop")
        self.assertEqual(out[0]["exit_reason_source"], SOURCE_MECHANISM)
        self.assertEqual(out[0]["decision_source"], "council")
        self.assertEqual(out[0]["adopted_role"], "trader_trend")

    def test_beyond_late_window_is_not_matched(self):
        """超过 +20min 窗口 ⇒ 不是本笔的现场，宁可不匹配（禁止用未来/过期证据）。"""
        import datetime as _dt
        late = (_dt.datetime.strptime("2026-10-01 10:00:00", "%Y-%m-%d %H:%M:%S")
                + _dt.timedelta(seconds=EVIDENCE_MAX_LATE_SECONDS + 1)).strftime("%Y-%m-%d %H:%M:%S")
        rows = [_row()]
        out, stats = enrich_closed_rows_with_evidence(
            trades=rows, evidence=[_evidence(open_time=late)])
        self.assertEqual(stats["matched"], 0)
        self.assertEqual(out[0]["exit_reason_source"], SOURCE_INFERRED)

    def test_too_early_evidence_is_rejected(self):
        import datetime as _dt
        early = (_dt.datetime.strptime("2026-10-01 10:00:00", "%Y-%m-%d %H:%M:%S")
                 - _dt.timedelta(seconds=6 * 3600 + 60)).strftime("%Y-%m-%d %H:%M:%S")
        rows = [_row()]
        out, stats = enrich_closed_rows_with_evidence(
            trades=rows, evidence=[_evidence(open_time=early)])
        self.assertEqual(stats["matched"], 0)

    def test_closest_candidate_wins(self):
        rows = [_row()]
        far = _evidence(open_time="2026-10-01 10:15:00", exit_cause="hard_stop")
        near = _evidence(open_time="2026-10-01 10:02:00", exit_cause="time_stop")
        out, _ = enrich_closed_rows_with_evidence(trades=rows, evidence=[far, near])
        self.assertEqual(out[0]["exit_cause"], "time_stop", "取时刻最近的那一条")

    def test_side_mismatch_never_matches(self):
        """★ 方向必须一致：把空头开仓现场当多头成因是错的因果。"""
        rows = [_row(side="多")]
        out, stats = enrich_closed_rows_with_evidence(
            trades=rows, evidence=[_evidence(side="short")])
        self.assertEqual(stats["matched"], 0)
        self.assertEqual(out[0]["exit_reason_source"], SOURCE_INFERRED)

    def test_unresolvable_evidence_side_is_not_forced(self):
        rows = [_row(side="多")]
        out, stats = enrich_closed_rows_with_evidence(
            trades=rows, evidence=[_evidence(side="net")])
        self.assertEqual(stats["matched"], 0, "方向认不出 ⇒ 不强行匹配")

    def test_each_evidence_record_is_used_at_most_once(self):
        """★ 两笔同标的同方向的平仓，只有一条证据 ⇒ 只能给一笔，不许复制。"""
        rows = [
            _row(id="r1", open_time="2026-10-01 10:00:00"),
            _row(id="r2", open_time="2026-10-01 10:00:05"),
        ]
        out, stats = enrich_closed_rows_with_evidence(
            trades=rows, evidence=[_evidence(open_time="2026-10-01 10:02:00")])
        self.assertEqual(stats["matched"], 1, "一条证据只能用一次")
        sources = sorted(r["exit_reason_source"] for r in out)
        self.assertEqual(sources, [SOURCE_INFERRED, SOURCE_MECHANISM])

    def test_different_insts_do_not_cross_match(self):
        rows = [_row(inst="BTC"), _row(id="r2", inst="ETH")]
        out, stats = enrich_closed_rows_with_evidence(
            trades=rows, evidence=[_evidence(inst="ETH")])
        self.assertEqual(stats["matched"], 1)
        by_inst = {r["inst"]: r for r in out}
        self.assertEqual(by_inst["ETH"]["exit_reason_source"], SOURCE_MECHANISM)
        self.assertEqual(by_inst["BTC"]["exit_reason_source"], SOURCE_INFERRED)


class FactVersusGuessTests(unittest.TestCase):
    def test_unmatched_row_is_marked_inferred_never_left_unmarked(self):
        """★ 没匹配到也必须打标记 —— 否则"猜的"与"确认的"长得一样。"""
        rows = [_row()]
        out, stats = enrich_closed_rows_with_evidence(trades=rows, evidence=[])
        self.assertEqual(out[0]["exit_reason_source"], SOURCE_INFERRED)
        self.assertNotIn("exit_cause", out[0], "无证据不得编造机制级离场原因")
        self.assertEqual(stats["inferred"], 1)

    def test_unknown_exit_cause_is_inferred_not_mechanism(self):
        rows = [_row()]
        out, _ = enrich_closed_rows_with_evidence(
            trades=rows, evidence=[_evidence(exit_cause="unknown", exit_cause_raw="持仓监控中")])
        self.assertEqual(out[0]["exit_reason_source"], SOURCE_INFERRED)
        self.assertNotIn("exit_cause", out[0])

    def test_exchange_exit_reason_is_never_overwritten(self):
        """台账的 `exit_reason`（交易所侧口径）必须原样保留，机制标签另立字段。"""
        rows = [_row(exit_reason="🎯 止盈推定（未匹配平仓单）")]
        out, _ = enrich_closed_rows_with_evidence(
            trades=rows, evidence=[_evidence(exit_cause="time_stop")])
        self.assertEqual(out[0]["exit_reason"], "🎯 止盈推定（未匹配平仓单）")
        self.assertEqual(out[0]["exit_cause"], "time_stop")
        self.assertEqual(out[0]["exit_cause_raw"], "时间止损")

    def test_trade_facts_are_untouched(self):
        row = _row(net_pnl=-27.64, roi_pct=-9.56, margin=289.25)
        before = dict(row)
        out, _ = enrich_closed_rows_with_evidence(trades=[row], evidence=[_evidence()])
        for key, value in before.items():
            self.assertEqual(out[0][key], value, f"交易所既有字段 {key} 被改写了")


class ScopeTests(unittest.TestCase):
    def test_holding_rows_are_not_enriched(self):
        rows = [_row(status="holding", exit_reason="⏳ 运行监控中")]
        out, stats = enrich_closed_rows_with_evidence(
            trades=rows, evidence=[_evidence()])
        self.assertEqual(stats["closed_rows"], 0)
        self.assertNotIn("exit_reason_source", out[0], "持仓行不在本步范围内")

    def test_foreign_venue_rows_are_skipped_read_only(self):
        rows = [_row(venue="binance")]
        out, stats = enrich_closed_rows_with_evidence(
            trades=rows, evidence=[_evidence()])
        self.assertEqual(stats["closed_rows"], 0)
        self.assertNotIn("exit_reason_source", out[0])

    def test_junk_inputs_are_survivable(self):
        out, stats = enrich_closed_rows_with_evidence(trades=None, evidence=None)
        self.assertEqual(out, [])
        self.assertEqual(stats["closed_rows"], 0)
        out2, stats2 = enrich_closed_rows_with_evidence(
            trades=["not-a-dict", None], evidence=[None, "x"])
        self.assertEqual(stats2["closed_rows"], 0)

    def test_stats_add_up(self):
        rows = [
            _row(id="r1", inst="BTC"),
            _row(id="r2", inst="ETH"),
            _row(id="r3", inst="SOL"),
        ]
        out, stats = enrich_closed_rows_with_evidence(
            trades=rows,
            evidence=[_evidence(inst="BTC"), _evidence(inst="ETH", exit_cause="unknown")],
        )
        self.assertEqual(stats["closed_rows"], 3)
        self.assertEqual(stats["matched"], 2)
        self.assertEqual(stats["mechanism"], 1)
        self.assertEqual(stats["inferred"], 2)
        self.assertEqual(stats["matched"], stats["mechanism"] + 1)


if __name__ == "__main__":
    unittest.main()
