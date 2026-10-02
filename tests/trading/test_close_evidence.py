"""平仓证据归档（`scripts/trader/close_evidence.py`）的回归。

## 这个测试在守什么

自进化复盘的**离场证据**在平仓瞬间消失：追踪器被 `pop`，`highWaterMark`/
`lowWaterMark`/开仓快照随之不见；而机制级离场原因（返回值第二项）被调用方丢弃，
台账只能按盈亏金额**猜**（实测 41% 是"止盈推定"）。

本模块把这几样在 pop 之前钉成旁车记录。判据分三族：

| 族 | 守什么 |
|---|---|
| 标签归因 | `exit_cause` 只由**机制返回值**推导，认不出就诚实 `unknown`（不猜） |
| 数值诚实 | R 分母取不到 ⇒ `mfe_r`/`mae_r` 为 **None**，绝不用默认值硬凑；`bool` 不得伪装成价格 |
| 决策来源 | 委员会开启才记 `council`+席位；关闭记 `single_model`；**读不到记 `unknown`**（绝不在委员会模式下撒谎成单模型） |

沙箱纪律：所有写盘用例都指向 `TemporaryDirectory`，绝不碰生产 `data/`。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.trader import close_evidence as ce  # noqa: E402


def _tracker(**over):
    base = {
        "instId": "BTC-USDT-SWAP", "name": "BTC", "side": "long",
        "entryPx": 100.0, "initialStopPx": 95.0,
        "highWaterMark": 110.0, "lowWaterMark": 98.0,
        "entryTs": 1788000000, "entryTime": "2026-10-01 19:04:27",
        "policy_version": "v8.5.0@abc", "policy_hash": "abc",
        "strategy_tag": "🌊 顺势回踩", "takeProfitPx": 115.0,
        "scale_out_tp": 112.0, "scale_out_phase": 1,
        "decision_source": "council", "adopted_role": "trader_trend",
        "signal_snapshot": {"macd_hist": 1.5, "obi_pct": 22.0},
    }
    base.update(over)
    return base


class ExitCauseLabelTests(unittest.TestCase):
    def test_mechanism_returns_map_to_stable_labels(self):
        cases = {
            "已硬止损": "hard_stop",
            "保护失效安全退出": "protection_fail",
            "时间止损": "time_stop",
            "已阶梯锁利": "ratchet_lock",
            "已移动止盈": "momentum_tp",
            "平仓失败": "close_failed",
            "AI高置信度整仓退出 (OKX): 动能衰竭": "ai_close",
            "分批止盈": "scale_out",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(ce.exit_cause_label(raw), expected)

    def test_unknown_is_honest_not_guessed(self):
        """认不出就 `unknown` —— 台账侧据此标"推断"，不伪装成机制确认。"""
        for raw in ("", None, "持仓监控中", "某种没见过的原因"):
            with self.subTest(raw=raw):
                self.assertEqual(ce.exit_cause_label(raw), "unknown")


class EvidenceKeyTests(unittest.TestCase):
    def test_key_is_normalized_across_both_sides_of_the_join(self):
        """归档侧（`name`/`long`）与台账侧（`inst`/`多`）必须归一到同一个键。"""
        archive_key = ce.evidence_key(inst="BTC", side="long", open_time=" 2026-10-01 19:04:27 ")
        ledger_key = ce.evidence_key(inst="BTC-USDT-SWAP", side="多",
                                     open_time="2026-10-01 19:04:27")
        self.assertEqual(archive_key, ledger_key)
        self.assertEqual(archive_key, "BTC|long|2026-10-01 19:04:27")

    def test_side_aliases_and_unknown(self):
        self.assertEqual(ce.evidence_key(inst="X", side="空", open_time="t"), "X|short|t")
        self.assertEqual(ce.evidence_key(inst="X", side="sell", open_time="t"), "X|short|t")
        self.assertEqual(ce.evidence_key(inst="X", side="", open_time="t"), "X|unknown|t")


class BuildCloseEvidenceTests(unittest.TestCase):
    def test_excursions_and_r_multiples(self):
        rec = ce.build_close_evidence(
            tracker=_tracker(), position_key="BTC-USDT-SWAP_long",
            exit_cause="已阶梯锁利", closed_at="2026-10-01 21:00:00")
        self.assertEqual(rec["exit_cause"], "ratchet_lock")
        self.assertEqual(rec["exit_cause_raw"], "已阶梯锁利")
        # 1R = |100 - 95| = 5 ⇒ MFE (110-100)/5 = 2.0R、MAE (98-100)/5 = -0.4R
        self.assertEqual(rec["r_denominator"], 5.0)
        self.assertEqual(rec["mfe_r"], 2.0)
        self.assertEqual(rec["mae_r"], -0.4)
        self.assertEqual(rec["mfe_pct"], 10.0)
        self.assertEqual(rec["mae_pct"], -2.0)
        self.assertEqual(rec["decision_source"], "council")
        self.assertEqual(rec["adopted_role"], "trader_trend")
        self.assertEqual(rec["entry_snapshot"], {"macd_hist": 1.5, "obi_pct": 22.0})
        self.assertEqual(rec["inst"], "BTC")
        self.assertEqual(rec["side"], "long")

    def test_short_side_excursions_are_profit_oriented(self):
        """★ 空头：浮盈从 `lowWaterMark` 来，浮亏从 `highWaterMark` 来。

        追踪器的两个水位是**原始价格**，含义随方向翻转。不分方向地取
        `highWaterMark` 当浮盈极值，会把空头**整笔读反**（最痛的一瞬记成最大浮盈）。
        故本模块统一输出**盈亏口径**：MFE ≥ 0 表示"最强时浮盈 X"，MAE ≤ 0 表示浮亏。
        """
        rec = ce.build_close_evidence(
            tracker=_tracker(side="short", entryPx=100.0, initialStopPx=105.0,
                             highWaterMark=102.0, lowWaterMark=90.0),
            position_key="k", exit_cause="已移动止盈", closed_at="t")
        self.assertEqual(rec["r_denominator"], 5.0)
        self.assertEqual(rec["mfe_r"], 2.0, "空头浮盈 = (100-90)/5")
        self.assertEqual(rec["mae_r"], -0.4, "空头浮亏 = (100-102)/5")
        self.assertEqual(rec["mfe_pct"], 10.0)
        self.assertEqual(rec["mae_pct"], -2.0)

    def test_net_pos_side_falls_back_to_frozen_stop_geometry(self):
        """净持仓账户的 `posSide` 是 `net` ⇒ 从冻结的止损相对位置定方向。"""
        rec = ce.build_close_evidence(
            tracker=_tracker(side="net", entryPx=100.0, initialStopPx=95.0,
                             highWaterMark=110.0, lowWaterMark=98.0),
            position_key="k", exit_cause="时间止损", closed_at="t")
        self.assertEqual(rec["side"], "long", "止损在开仓价下方 ⇒ 多头")
        self.assertEqual(rec["mfe_r"], 2.0)

    def test_undeterminable_side_reports_no_excursions(self):
        """方向与止损几何都给不出方向 ⇒ 浮动盈亏留空，**不按多头瞎算**。"""
        rec = ce.build_close_evidence(
            tracker=_tracker(side="net", initialStopPx=None),
            position_key="k", exit_cause="时间止损", closed_at="t")
        self.assertEqual(rec["side"], "unknown")
        self.assertIsNone(rec["mfe_r"])
        self.assertIsNone(rec["mae_r"])
        self.assertIsNone(rec["mfe_pct"])
        self.assertIsNone(rec["mae_pct"])

    def test_missing_r_denominator_does_not_fabricate_an_r(self):
        """★ 没有初始止损 ⇒ R 为 None，但百分比仍给出（不硬凑 1R）。"""
        rec = ce.build_close_evidence(
            tracker=_tracker(initialStopPx=None), position_key="k",
            exit_cause="时间止损", closed_at="t")
        self.assertIsNone(rec["r_denominator"])
        self.assertIsNone(rec["mfe_r"])
        self.assertIsNone(rec["mae_r"])
        self.assertEqual(rec["mfe_pct"], 10.0, "百分比不依赖止损，必须仍在")

    def test_zero_distance_stop_does_not_divide_by_zero(self):
        rec = ce.build_close_evidence(
            tracker=_tracker(initialStopPx=100.0), position_key="k",
            exit_cause="已硬止损", closed_at="t")
        self.assertIsNone(rec["r_denominator"])
        self.assertIsNone(rec["mfe_r"])

    def test_bool_and_junk_never_masquerade_as_prices(self):
        """`True` 的 `float()` 是 1.0 —— 不得被当成价格（否则 R 全错）。"""
        rec = ce.build_close_evidence(
            tracker=_tracker(entryPx=True, initialStopPx="not-a-number",
                             highWaterMark=None, lowWaterMark=float("nan")),
            position_key="k", exit_cause="x", closed_at="t")
        self.assertIsNone(rec["entry_px"])
        self.assertIsNone(rec["initial_stop_px"])
        self.assertIsNone(rec["mfe_pct"])
        self.assertIsNone(rec["mae_pct"])

    def test_decision_source_unknown_when_tracker_has_none(self):
        """旧追踪器（本次改造前建立）没有来源字段 ⇒ `unknown`，不冒充单模型。"""
        t = _tracker()
        t.pop("decision_source")
        t.pop("adopted_role")
        rec = ce.build_close_evidence(tracker=t, position_key="k",
                                      exit_cause="时间止损", closed_at="t")
        self.assertEqual(rec["decision_source"], "unknown")
        self.assertIsNone(rec["adopted_role"])

    def test_non_dict_tracker_is_survivable(self):
        rec = ce.build_close_evidence(tracker=None, position_key="k",
                                      exit_cause=None, closed_at="t")
        self.assertEqual(rec["exit_cause"], "unknown")
        self.assertEqual(rec["inst"], "")
        self.assertIsNone(rec["mfe_r"])


class ResolveDecisionAttributionTests(unittest.TestCase):
    def _write(self, payload):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "ai_brain_decisions.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def test_council_ran_reports_seat(self):
        path = self._write({"BTC-USDT-SWAP": {"council": {"ran": True, "adopted_role": "trader_quant"}}})
        self.assertEqual(ce.resolve_decision_attribution("BTC-USDT-SWAP", cache_path=path),
                         ("council", "trader_quant"))

    def test_council_disabled_reports_single_model_without_seat(self):
        path = self._write({"BTC-USDT-SWAP": {"council": {"ran": False, "adopted_role": None}}})
        self.assertEqual(ce.resolve_decision_attribution("BTC-USDT-SWAP", cache_path=path),
                         ("single_model", None))

    def test_reject_all_keeps_the_marker(self):
        path = self._write({"BTC-USDT-SWAP": {"council": {"ran": True, "adopted_role": "REJECT_ALL"}}})
        self.assertEqual(ce.resolve_decision_attribution("BTC-USDT-SWAP", cache_path=path),
                         ("council", "REJECT_ALL"))

    def test_unreadable_or_unknown_symbol_is_unknown_not_single_model(self):
        """★ 读不到**不是**"单模型"：委员会模式下那样会撒谎，分段统计全错。"""
        path = self._write({"ETH-USDT-SWAP": {"council": {"ran": True, "adopted_role": "a"}}})
        self.assertEqual(ce.resolve_decision_attribution("BTC-USDT-SWAP", cache_path=path),
                         ("unknown", None))
        self.assertEqual(ce.resolve_decision_attribution("BTC-USDT-SWAP",
                                                         cache_path="/nonexistent/x.json"),
                         ("unknown", None))
        self.assertEqual(ce.resolve_decision_attribution("BTC-USDT-SWAP", cache_path=None),
                         ("unknown", None))

    def test_missing_council_block_is_unknown(self):
        path = self._write({"BTC-USDT-SWAP": {"decision": {"action": "WAIT"}}})
        self.assertEqual(ce.resolve_decision_attribution("BTC-USDT-SWAP", cache_path=path),
                         ("unknown", None))

    def test_corrupt_cache_is_survivable(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "broken.json")
        Path(path).write_text("{not json", encoding="utf-8")
        self.assertEqual(ce.resolve_decision_attribution("BTC", cache_path=path), ("unknown", None))


class AppendCloseEvidenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "closed_trade_evidence.json")

    def test_append_dedupes_by_key_last_wins(self):
        first = ce.build_close_evidence(tracker=_tracker(highWaterMark=105.0),
                                        position_key="k", exit_cause="已硬止损", closed_at="t1")
        second = ce.build_close_evidence(tracker=_tracker(highWaterMark=110.0),
                                         position_key="k", exit_cause="已阶梯锁利", closed_at="t2")
        self.assertEqual(first["key"], second["key"], "同一笔必须算出同一个键")
        self.assertTrue(ce.append_close_evidence(self.path, first))
        self.assertTrue(ce.append_close_evidence(self.path, second))
        records = ce.load_close_evidence(self.path)
        self.assertEqual(len(records), 1, "同键必须去重（后者覆盖）")
        self.assertEqual(records[0]["exit_cause"], "ratchet_lock")
        self.assertEqual(records[0]["high_water_mark"], 110.0)

    def test_distinct_positions_coexist(self):
        a = ce.build_close_evidence(tracker=_tracker(instId="BTC-USDT-SWAP", name="BTC"),
                                    position_key="a", exit_cause="时间止损", closed_at="t")
        b = ce.build_close_evidence(tracker=_tracker(instId="ETH-USDT-SWAP", name="ETH"),
                                    position_key="b", exit_cause="时间止损", closed_at="t")
        ce.append_close_evidence(self.path, a)
        ce.append_close_evidence(self.path, b)
        self.assertEqual(len(ce.load_close_evidence(self.path)), 2)

    def test_limit_truncates_keeping_newest(self):
        original = ce.CLOSE_EVIDENCE_LIMIT
        ce.CLOSE_EVIDENCE_LIMIT = 3
        try:
            for i in range(5):
                rec = ce.build_close_evidence(
                    tracker=_tracker(name=f"S{i}", instId=f"S{i}-USDT-SWAP"),
                    position_key=f"k{i}", exit_cause="时间止损", closed_at=f"t{i}")
                ce.append_close_evidence(self.path, rec)
            records = ce.load_close_evidence(self.path)
        finally:
            ce.CLOSE_EVIDENCE_LIMIT = original
        self.assertEqual(len(records), 3)
        self.assertEqual([r["inst"] for r in records], ["S2", "S3", "S4"], "保留最近的")

    def test_write_failure_returns_false_and_never_raises(self):
        """fail-soft：旁车写不进去绝不该打断交易周期。"""
        self.assertFalse(ce.append_close_evidence(None, {"key": "x"}))
        self.assertFalse(ce.append_close_evidence(self.path, None))
        # 指向一个"父路径是文件"的非法位置 ⇒ 必然失败，但不得抛异常
        blocker = os.path.join(os.path.dirname(self.path), "blocker")
        Path(blocker).write_text("x", encoding="utf-8")
        self.assertFalse(ce.append_close_evidence(os.path.join(blocker, "sub", "e.json"),
                                                  {"key": "x"}))

    def test_corrupt_archive_reads_as_empty_then_recovers(self):
        Path(self.path).write_text("[[[", encoding="utf-8")
        self.assertEqual(ce.load_close_evidence(self.path), [])
        rec = ce.build_close_evidence(tracker=_tracker(), position_key="k",
                                      exit_cause="时间止损", closed_at="t")
        self.assertTrue(ce.append_close_evidence(self.path, rec), "损坏旁车必须能被重建")
        self.assertEqual(len(ce.load_close_evidence(self.path)), 1)

    def test_archive_is_valid_json_with_schema_version(self):
        ce.append_close_evidence(self.path, ce.build_close_evidence(
            tracker=_tracker(), position_key="k", exit_cause="时间止损", closed_at="t"))
        payload = json.loads(Path(self.path).read_text(encoding="utf-8"))
        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["schema_version"], ce.EVIDENCE_SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
