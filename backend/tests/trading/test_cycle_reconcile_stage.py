"""相位 1（持仓与对账）输入失败语义与汇总口径（OKX 专用）。

覆盖 `fetch_positions_and_reconcile`：
1. 四条 abort 分支（持仓/挂单/余额/同合约多空并存）；
2. 仓位汇总口径（多空分计、净持仓不归多空、0 仓位不计）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.trader.cycle_stages import fetch_positions_and_reconcile  # noqa: E402


class _Env:
    def __init__(self, mode="demo"):
        self.mode = mode


class _OkxRest:
    def __init__(self, pending=(), balances=None, pending_raises=None, bal_raises=None):
        self._pending = list(pending)
        self._balances = balances if balances is not None else [
            {"details": [{"ccy": "USDT", "availBal": "1234.5"}]}]
        self._pending_raises = pending_raises
        self._bal_raises = bal_raises

    def pending_orders(self):
        if self._pending_raises is not None:
            raise self._pending_raises
        return list(self._pending)

    def balances(self):
        if self._bal_raises is not None:
            raise self._bal_raises
        return self._balances


class Rig:
    def __init__(self, *, positions=None, positions_ok=True, pending=(),
                 balances=None, okx=None, env_mode="demo",
                 pending_positions_raises=None, bal_raises=None, env_raises=False):
        self.reconciles: list = []
        self.positions = positions if positions is not None else [
            {"instId": "BTC-USDT-SWAP", "pos": "2", "posSide": "long"}]
        self.positions_ok = positions_ok
        self.okx = okx or _OkxRest(pending=pending, balances=balances,
                                   pending_raises=pending_positions_raises,
                                   bal_raises=bal_raises)
        self.env_mode = env_mode
        self.env_raises = env_raises

    def run(self, *, entries_blocked=False):
        def _env():
            if self.env_raises:
                raise RuntimeError("env down")
            return _Env(self.env_mode)

        out = fetch_positions_and_reconcile(
            entries_blocked=entries_blocked,
            current_environment=_env,
            okx_rest=self.okx,
            query_positions=lambda: (
                (True, self.positions, "") if self.positions_ok else (False, [], "持仓读不动")),
            reconcile_reservation_ledger=lambda *a, **k: self.reconciles.append((a, k)))
        return out


class PositionSummaryTest(unittest.TestCase):
    def _run(self, **kw):
        rig = Rig(**kw)
        return rig, rig.run()

    def test_long_and_short_are_counted_separately(self):
        rig, out = self._run(positions=[
            {"instId": "BTC-USDT-SWAP", "pos": "2", "posSide": "long"},
            {"instId": "ETH-USDT-SWAP", "pos": "3", "posSide": "short"}])
        self.assertIsNotNone(out)
        (active_pos_count, all_positions, entries_blocked, long_count,
         pending_inst_ids, real_pos_dict, reserved_long_count,
         reserved_short_count, reserved_slot_count, short_count,
         usdt_available) = out
        self.assertEqual(long_count, 1, "多头计数")
        self.assertEqual(short_count, 1, "空头计数")
        self.assertEqual(active_pos_count, 2, "活跃仓位数")
        self.assertEqual(sorted(real_pos_dict), ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])

    def test_zero_size_positions_are_not_counted(self):
        """数量为 0 的仓位行是「没有仓」，不许计入（否则槽位被虚占）。"""
        _, out = self._run(positions=[{"instId": "BTC-USDT-SWAP", "pos": "0", "posSide": "long"}])
        (active_pos_count, all_positions, entries_blocked, long_count,
         pending_inst_ids, real_pos_dict, reserved_long_count,
         reserved_short_count, reserved_slot_count, short_count,
         usdt_available) = out
        self.assertEqual(active_pos_count, 0)
        self.assertEqual(long_count, 0)
        self.assertEqual(real_pos_dict, {})

    def test_simultaneous_long_and_short_aborts_the_cycle(self):
        """同一合约多空同时存在 ⇒ 本周期中止（系统无法表达这种仓位，硬猜会算错）。"""
        _, out = self._run(positions=[
            {"instId": "BTC-USDT-SWAP", "pos": "2", "posSide": "long"},
            {"instId": "BTC-USDT-SWAP", "pos": "1", "posSide": "short"}])
        self.assertIsNone(out, "同合约多空并存必须 abort，而不是挑一边记账")

    def test_net_side_position_counts_as_neither_long_nor_short(self):
        _, out = self._run(positions=[{"instId": "BTC-USDT-SWAP", "pos": "2", "posSide": "net"}])
        (active_pos_count, all_positions, entries_blocked, long_count,
         pending_inst_ids, real_pos_dict, reserved_long_count,
         reserved_short_count, reserved_slot_count, short_count,
         usdt_available) = out
        self.assertEqual(active_pos_count, 1, "净持仓也要计入活跃仓位")
        self.assertEqual((long_count, short_count), (0, 0), "net 既不是 long 也不是 short")


class InputFailureSemanticsTest(unittest.TestCase):
    def test_positions_read_failure_aborts_the_cycle(self):
        out = Rig(positions_ok=False).run()
        self.assertIsNone(out, "持仓读不到 ⇒ 整周期 abort（读不到 ≠ 没有仓）")

    def test_pending_orders_read_failure_aborts_the_cycle(self):
        out = Rig(pending_positions_raises=RuntimeError("pending down")).run()
        self.assertIsNone(out, "挂单读不到 ⇒ 整周期 abort")

    def test_balance_read_failure_aborts_the_cycle(self):
        out = Rig(bal_raises=RuntimeError("bal down")).run()
        self.assertIsNone(out, "余额读不到 ⇒ 整周期 abort（不许拿 0 余额硬算仓位）")

    def test_pending_orders_are_counted_and_non_live_orders_skipped(self):
        pending = [
            {"instId": "BTC-USDT-SWAP", "posSide": "long", "state": "live"},
            {"instId": "ETH-USDT-SWAP", "posSide": "short", "state": "partially_filled"},
            {"instId": "SOL-USDT-SWAP", "posSide": "long", "state": "canceled"},
        ]
        out = Rig(pending=pending).run()
        self.assertIsNotNone(out)
        (active_pos_count, all_positions, entries_blocked, long_count,
         pending_inst_ids, real_pos_dict, reserved_long_count,
         reserved_short_count, reserved_slot_count, short_count,
         usdt_available) = out
        self.assertEqual(pending_inst_ids, {"BTC-USDT-SWAP", "ETH-USDT-SWAP"})
        # 活跃仓位 1 (BTC 多) + 挂单 2 (BTC 多, ETH 空) -> 槽位 1 + 2 = 3
        self.assertEqual(reserved_slot_count, 3)
        self.assertEqual(reserved_long_count, 2)  # 1 仓 + 1 挂
        self.assertEqual(reserved_short_count, 1)  # 0 仓 + 1 挂

    def test_usdt_available_is_read_from_the_balance_payload(self):
        balances = [{"details": [{"ccy": "BTC", "availBal": "1"}, {"ccy": "USDT", "availBal": "8888.5"}]}]
        out = Rig(balances=balances).run()
        self.assertEqual(out[10], 8888.5)

    def test_environment_read_failure_is_handled(self):
        out = Rig(env_raises=True).run()
        self.assertIsNotNone(out)


if __name__ == "__main__":
    unittest.main()
