"""Unit tests for Scale-Out Execution Engine (scripts/trader/scale_out.py)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

from scripts.trader.scale_out import execute_scale_out_if_eligible


class ScaleOutExecutionTests(unittest.TestCase):
    def setUp(self):
        # ⚠️ 2026-09-29：分批止盈新增了**事件流水**（`data/scale_out_events.jsonl`）。
        # 本用例走真实的成功路径 ⇒ 若不重定向落点，跑到哪里就把夹具行灌进**生产**流水。
        # 实测事故：一份"第一手证据"里混进 50 行假记录（entry 80000/exit 82000 之类）。
        import scripts.trader.scale_out as _so
        self._events_tmp = tempfile.TemporaryDirectory(prefix="astra-scaleout-events-")
        self.addCleanup(self._events_tmp.cleanup)
        _p = patch.object(_so, "SCALE_OUT_EVENTS_FILE",
                          Path(self._events_tmp.name) / "scale_out_events.jsonl")
        _p.start()
        self.addCleanup(_p.stop)
        self.mock_okx = MagicMock()
        self.mock_record_trade = MagicMock()
        self.mock_notify = MagicMock()
        self.mock_ensure_oco = MagicMock()
        self.mock_close_fee = MagicMock(return_value=0.5)
        self.mock_payload = MagicMock(return_value={"action": "close"})

        self.sample_f_long = {
            "instId": "BTC-USDT-SWAP",
            "name": "BTC",
            "price": 82000.0,
            "atr": 1000.0,
            "precision": 2,
            "ctVal": 1.0,
            "minSz": 0.01,
            "market_data_valid": True,
        }

        self.sample_pos_long = {
            "side": "long",
            "avgPx": 80000.0,
            "pos": 10.0,
            "venue": "okx",
        }

        self.sample_trackers = {
            "BTC-USDT-SWAP_long": {
                "initialSz": 10.0,
                "currentSz": 10.0,
                "takeProfitPx": 85000.0,
                "trailingStopPx": 78000.0,
                "scale_out_phase": 0,
                "scale_count": 0,
            }
        }

    def test_disabled_by_switch(self):
        with patch("scripts.trader.scale_out.SCALE_OUT_ENABLED", False):
            actions = []
            ok, reason = execute_scale_out_if_eligible(
                self.sample_f_long, self.sample_pos_long, self.sample_trackers,
                "2026-09-20 12:00:00", actions,
                okx_rest=self.mock_okx,
            )
            self.assertFalse(ok)
            self.assertEqual(reason, "分批止盈未启用")
            self.assertEqual(len(actions), 0)
            self.mock_okx.place_order.assert_not_called()

    def test_profit_below_trigger_threshold(self):
        # cur_px = 80500, entry = 80000 -> profit = 500 < 2.0 * 1000 (2000)
        # ⚠️ 阈值来自**代码基线**（测试环境由 pin_baseline_risk_env 钉住，不读用户 .env），
        #    2026-09-30 起基线 = 2.0×ATR 落袋 35%（用户拍板的盈亏比矫正）
        f_low_profit = dict(self.sample_f_long, price=80500.0)
        actions = []
        ok, reason = execute_scale_out_if_eligible(
            f_low_profit, self.sample_pos_long, self.sample_trackers,
            "2026-09-20 12:00:00", actions,
            okx_rest=self.mock_okx,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "浮盈未达分批止盈门槛")
        self.mock_okx.place_order.assert_not_called()
        # 验证未达标时已为操盘手和主脑计算并存入首批止盈位 TP1
        t = self.sample_trackers["BTC-USDT-SWAP_long"]
        self.assertEqual(t.get("scale_out_tp"), 82000.0)
        self.assertIn("首批止盈目标 TP1: 82000", t.get("stage_desc", ""))
        self.assertIn("达标平35%保本", t.get("stage_desc", ""), "文案必须跟着比例走，不许写死 50%")

    def test_insufficient_size_graceful_degrade(self):
        # pos = 0.01, minSz = 0.01 -> 0.01 < 2 * 0.01, cannot split
        pos_tiny = dict(self.sample_pos_long, pos=0.01)
        actions = []
        ok, reason = execute_scale_out_if_eligible(
            self.sample_f_long, pos_tiny, self.sample_trackers,
            "2026-09-20 12:00:00", actions,
            okx_rest=self.mock_okx,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "保证金不足以切分")
        self.assertIn("降级为全仓追踪", actions[0])
        self.mock_okx.place_order.assert_not_called()

    def test_notification_failure_does_not_change_the_outcome(self):
        """**本路径不再发布金额通知**（2026-09-30 通知单一事实源）。

        打桩一个"必炸"的通知通道，结果必须**完全不变**：平仓单照打、返回值仍是成功。
        这同时钉住两件事：① 通知不是本路径的职责（改由台账路径发布 —— 它握有交易所
        真实成交价与手续费）；② 就算有人把调用加回来，通知故障也绝不能影响钱路。
        """
        self.mock_okx.place_order.return_value = [{"ordId": "12345"}]
        self.mock_okx.pending_algo_orders.return_value = [
            {"algoId": "algo_1", "posSide": "long", "state": "live"}
        ]
        boom = MagicMock(side_effect=RuntimeError("通知通道炸了"))
        actions = []
        ok, reason = execute_scale_out_if_eligible(
            self.sample_f_long, self.sample_pos_long, self.sample_trackers,
            "2026-09-20 12:00:00", actions,
            okx_rest=self.mock_okx,
            record_trade=self.mock_record_trade,
            notify_trade_close=boom,
            close_fee=self.mock_close_fee,
            close_trade_payload=self.mock_payload,
            ensure_cloud_position_protection=self.mock_ensure_oco,
        )
        self.assertTrue(ok, f"通知失败不得改变平仓结果：{reason}")
        self.assertEqual(reason, "首批分批平仓成功")
        boom.assert_not_called()
        self.mock_record_trade.assert_called_once()

    def test_trade_recording_failure_currently_propagates(self):
        """⚠️ **实测边界（如实钉住现状，未擅自改）**：与「通知」不同，**台账记账是裸调用**
        （`record_trade(...)` 没有 `try` 包裹，只有 `notify_trade_close` 那一段有）。
        于是台账写失败会把异常抛给调用方 —— **而平仓单此刻已经打到交易所了**。

        为什么值得记：这一族（本仓反复出现的形态）是「**成交已发生，副作用失败不该改变结果**」；
        通知做到了 best-effort，台账没有，两者**不一致**。改它属钱路行为变更
        （涉及是否重试、如何披露记账缺口）⇒ 列为待议项。
        """
        self.mock_okx.place_order.return_value = [{"ordId": "12345"}]
        self.mock_okx.pending_algo_orders.return_value = [
            {"algoId": "algo_1", "posSide": "long", "state": "live"}
        ]
        boom = MagicMock(side_effect=RuntimeError("台账库锁住了"))
        actions = []
        with self.assertRaises(RuntimeError):
            execute_scale_out_if_eligible(
                self.sample_f_long, self.sample_pos_long, self.sample_trackers,
                "2026-09-20 12:00:00", actions,
                okx_rest=self.mock_okx,
                record_trade=boom,
                notify_trade_close=self.mock_notify,
                close_fee=self.mock_close_fee,
                close_trade_payload=self.mock_payload,
                ensure_cloud_position_protection=self.mock_ensure_oco,
            )

    def test_successful_long_scale_out_and_state_lock(self):
        # profit = 82000 - 80000 = 2000 >= 1.2 * 1000
        self.mock_okx.place_order.return_value = [{"ordId": "12345"}]
        self.mock_okx.pending_algo_orders.return_value = [
            {"algoId": "algo_1", "posSide": "long", "state": "live"}
        ]

        actions = []
        ok, reason = execute_scale_out_if_eligible(
            self.sample_f_long, self.sample_pos_long, self.sample_trackers,
            "2026-09-20 12:00:00", actions,
            okx_rest=self.mock_okx,
            record_trade=self.mock_record_trade,
            notify_trade_close=self.mock_notify,
            close_fee=self.mock_close_fee,
            close_trade_payload=self.mock_payload,
            ensure_cloud_position_protection=self.mock_ensure_oco,
        )

        self.assertTrue(ok)
        self.assertEqual(reason, "首批分批平仓成功")
        
        # 验证下达平仓市价单（reduceOnly=True，卖出 3.5 张 = 10 × 35%）
        # 2026-09-29：平仓单带 clOrdId 前缀 `SO`（Scale-Out）—— 台账侧据此把
        # "首批分批止盈"与"AI 主动止盈平仓"分开（旧实现按盈亏金额猜原因，
        # 于是分批止盈在台账里一直显示成"目标止盈达成"）。
        self.mock_okx.place_order.assert_called_once_with(
            "BTC-USDT-SWAP", "sell", "3.5",
            pos_side="long", td_mode="cross", ord_type="market", reduce_only=True,
            cl_ord_id=ANY,
        )

        # 验证旧 OCO 被撤销
        self.mock_okx.cancel_algo_orders.assert_called_once_with(["algo_1"], inst_id="BTC-USDT-SWAP")

        # 验证新 OCO 重挂：剩余 6.5 张，保本止损价 80200 (80000 + 0.25%)
        self.mock_ensure_oco.assert_called_once_with(
            "BTC-USDT-SWAP", "long", 6.5, 85000.0, 80200.0
        )

        # 验证 tracker 状态变更与金字塔加仓互斥锁定
        t = self.sample_trackers["BTC-USDT-SWAP_long"]
        self.assertEqual(t["scale_out_phase"], 1)
        self.assertEqual(t["currentSz"], 6.5)
        self.assertEqual(t["scale_count"], 999)
        self.assertEqual(t["trailingStopPx"], 80200.0)

        # 验证台账写入；金额通知**不再**由本路径发布（改由台账路径，见其 docstring）
        self.mock_record_trade.assert_called_once()
        self.mock_notify.assert_not_called()

    def test_idempotent_no_duplicate_scale_out(self):
        # scale_out_phase 已为 1 时，再次调用直接拒绝，绝不重复平仓
        self.sample_trackers["BTC-USDT-SWAP_long"]["scale_out_phase"] = 1
        actions = []
        ok, reason = execute_scale_out_if_eligible(
            self.sample_f_long, self.sample_pos_long, self.sample_trackers,
            "2026-09-20 12:00:00", actions,
            okx_rest=self.mock_okx,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "已执行过分批平仓")
        self.mock_okx.place_order.assert_not_called()

    def test_ledger_holding_row_reflects_scale_out_status(self):
        import sys
        from pathlib import Path
        scripts_dir = str(Path(__file__).resolve().parents[2] / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from scripts.sync_full_ledger import _holding_row
        import datetime

        trackers = {
            "BTC-USDT-SWAP_long": {
                "scale_out_phase": 1,
                "stage_desc": "已分批止盈50% (余5张 · 保本止损 80200)",
            }
        }
        mock_env = MagicMock(mode="live")
        tz = datetime.timezone(datetime.timedelta(hours=8))
        pos_raw = {
            "instId": "BTC-USDT-SWAP",
            "pos": "5.0",
            "posSide": "long",
            "avgPx": "80000",
            "markPx": "82000",
            "upl": "10000",
            "lever": "3",
            "cTime": "1789857503880",
        }
        row = _holding_row(
            pos_raw, "okx",
            env=mock_env,
            trackers=trackers,
            tz_bj=tz,
            allowed={"BTC-USDT-SWAP"},
            council_by_inst={},
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "holding")
        self.assertIn("已分批止盈50%", row["exit_reason"])
        self.assertEqual(row["scale_out_phase"], 1)

    def test_binance_scale_out_cancels_old_protective_and_sets_reduce_only(self):
        pos_bn = {
            "side": "long",
            "avgPx": 80000.0,
            "pos": 10.0,
            "venue": "binance",
            "raw": {"positionSide": "BOTH"},
        }
        trackers = {
            "BTC-USDT-SWAP_long": {
                "initialSz": 10.0,
                "currentSz": 10.0,
                "takeProfitPx": 85000.0,
                "trailingStopPx": 78000.0,
                "scale_out_phase": 0,
                "scale_count": 0,
            }
        }
        actions = []
        ok, reason = execute_scale_out_if_eligible(
            self.sample_f_long, pos_bn, trackers,
            "2026-09-20 12:00:00", actions,
            record_trade=self.mock_record_trade,
            notify_trade_close=self.mock_notify,
            close_fee=self.mock_close_fee,
            close_trade_payload=self.mock_payload,
        )
        self.assertFalse(ok)
        self.assertIn("非 OKX 场所", reason)

    def test_gate_scale_out_cancels_old_protective_and_sets_reduce_only(self):
        pos_gate = {
            "side": "long",
            "avgPx": 80000.0,
            "pos": 10.0,
            "venue": "gate",
        }
        trackers = {
            "BTC-USDT-SWAP_long": {
                "initialSz": 10.0,
                "currentSz": 10.0,
                "takeProfitPx": 85000.0,
                "trailingStopPx": 78000.0,
                "scale_out_phase": 0,
                "scale_count": 0,
            }
        }
        actions = []
        ok, reason = execute_scale_out_if_eligible(
            self.sample_f_long, pos_gate, trackers,
            "2026-09-20 12:00:00", actions,
            record_trade=self.mock_record_trade,
            notify_trade_close=self.mock_notify,
            close_fee=self.mock_close_fee,
            close_trade_payload=self.mock_payload,
        )
        self.assertFalse(ok)
        self.assertIn("非 OKX 场所", reason)

    def test_cycle_parts_scale_out_tp_derivation(self):
        from scripts.brain.cycle_parts import _calculate_scale_out_tp, build_history_record

        # 多头：80000 + 2.0 * 1000 = 82000（基线 2.0×ATR，见 risk_constants）
        tp_long = _calculate_scale_out_tp(80000.0, "BUY_LONG", 1000.0, precision=2)
        self.assertEqual(tp_long, 82000.0)

        # 空头：80000 - 2.0 * 1000 = 78000
        tp_short = _calculate_scale_out_tp(80000.0, "SELL_SHORT", 1000.0, precision=2)
        self.assertEqual(tp_short, 78000.0)

        # WAIT 或无价格返回 None
        self.assertIsNone(_calculate_scale_out_tp(0.0, "WAIT", 1000.0))
        self.assertIsNone(_calculate_scale_out_tp(80000.0, "WAIT", 0.0))

        # build_history_record 集成测试
        pkgs = [{"name": "BTC", "instId": "BTC-USDT-SWAP", "atr": 1000.0, "precision": 2}]
        std_cache = {
            "BTC-USDT-SWAP": {
                "decision": {
                    "action": "BUY_LONG",
                    "confidence": 88,
                    "entry_price": 80000.0,
                    "stop_loss_price": 79000.0,
                    "take_profit_price": 85000.0,
                    "risk_reward_ratio": 5.0,
                    "summary_reason": "4H结构突破做多",
                },
                "data_quality": {"status": "ok"},
            }
        }
        rec = build_history_record(
            time_str="2026-09-20 10:00:00",
            policy_version="v8.1.1",
            policy_hash="test_hash",
            policy_snapshot={},
            policy_summary="",
            macro_summary="情绪健康",
            council_status={"ran": True},
            ai_last_prompt="",
            pos_mgmt_list=[],
            council_transcript=None,
            packages=pkgs,
            standard_cache=std_cache,
        )
        self.assertEqual(len(rec["top_opportunities"]), 1)
        opp = rec["top_opportunities"][0]
        self.assertEqual(opp["scale_out_tp"], 82000.0)
        self.assertEqual(opp["take_profit_price"], 85000.0)


class CrossVenueUnitScaleTests(unittest.TestCase):
    """外所分批止盈必须用**该所自己的**合约面值与最小步长。

    三所持仓接管时新增（用户报「币安/Gate 的仓一直挂在那、也不会被平」）：
    `f["ctVal"]` / `f["minSz"]` 来自 **OKX 合约池**（DOGE = 1000 张面值），
    而 Binance 的 `pos` 是**币数**、Gate 的是**自家张数**（DOGE 面值 10）。
    沿用 OKX 口径 ⇒ 名义额与平仓手续费错 1000 倍，切片量也按错误步长对齐
    （真下单就是按错的数量平仓）。持仓记录上的值必须优先。
    """

    def _f(self):
        # 现价 0.101：越过基线门槛 2.0×ATR（0.09615 + 2.0×0.002 = 0.10015）
        return {"instId": "DOGE-USDT-SWAP", "name": "DOGE", "price": 0.101,
                "atr": 0.002, "precision": 4, "ctVal": 1000.0, "minSz": 0.01,
                "market_data_valid": True}

    def _run(self, pos):
        adapter = MagicMock()
        adapter.place_order.return_value = {"id": "x"}
        registry = MagicMock()
        registry.get_adapter.return_value = adapter
        fee = MagicMock(return_value=0.0)
        trackers = {"DOGE-USDT-SWAP_long": {"scale_out_phase": 0}}
        ok, reason = execute_scale_out_if_eligible(
            self._f(), pos, trackers, "2026-09-28 12:00:00", [],
            venue_registry=registry, record_trade=MagicMock(),
            notify_trade_close=MagicMock(), close_fee=fee,
            close_trade_payload=MagicMock(return_value={}))
        return ok, reason, adapter, fee

    def test_gate_uses_its_own_contract_value_not_the_okx_pool_value(self):
        pos = {"side": "long", "avgPx": 0.09615, "pos": 861.0, "venue": "gate",
               "ctVal": 10.0, "minSz": 10.0, "precision": 0}
        ok, reason, adapter, fee = self._run(pos)
        self.assertFalse(ok)
        self.assertIn("非 OKX 场所", reason)

    def test_binance_uses_coin_units_with_a_contract_value_of_one(self):
        pos = {"side": "long", "avgPx": 0.09615, "pos": 861.0, "venue": "binance",
               "ctVal": 1.0, "minSz": 1.0, "precision": 0}
        ok, reason, adapter, fee = self._run(pos)
        self.assertFalse(ok)
        self.assertIn("非 OKX 场所", reason)

    def test_an_okx_position_still_falls_back_to_the_pool_values(self):
        """没有持仓级覆盖时逐位回落 OKX 口径 —— 不许改变 OKX 路径的行为。"""
        pos = {"side": "long", "avgPx": 0.09615, "pos": 861.0, "venue": "okx"}
        fee = MagicMock(return_value=0.0)
        okx_rest = MagicMock()
        okx_rest.place_order.return_value = {"ordId": "1"}
        registry = MagicMock()
        registry.get_adapter.return_value = MagicMock()
        ok, reason = execute_scale_out_if_eligible(
            self._f(), pos, {"DOGE-USDT-SWAP_long": {"scale_out_phase": 0}},
            "2026-09-28 12:00:00", [],
            okx_rest=okx_rest, venue_registry=registry,
            record_trade=MagicMock(), notify_trade_close=MagicMock(),
            close_fee=fee, close_trade_payload=MagicMock(return_value={}))
        self.assertTrue(ok, reason)
        self.assertEqual(fee.call_args[0][1], 1000.0,
                         "OKX 无覆盖值 ⇒ 沿用合约池面值")


if __name__ == "__main__":
    unittest.main()
