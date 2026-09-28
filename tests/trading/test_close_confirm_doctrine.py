"""平仓回读确认：**受理 ≠ 平掉**（第二百五十三刀）。

`close_position_confirmed` 决定「**能不能改本地状态**」：只有回到交易所**读到归零**才算平掉。
三种失败必须彼此分清，因为排水完全不同：

| 情形 | 返回值 | 调用方该做什么 |
|---|---|---|
| 读回看到归零 | `(True, verified flat)` | 清本地状态 |
| 读回**读到仍然有仓** | `(False, still reports open … state unchanged)` | 保留 tracker、下周期重试 |
| 读回**一直读不到**（无一次成功响应） | `(False, … no successful exchange response / readback unavailable … state unchanged)` | 同上，但**要区分**是"读不到"而非"没平掉" |

其中最危险的一档是**假成功**：净持仓账户（`posSide="net"`）里用精确相等匹配会匹配不上，
`remaining` 恒 0 ⇒ **在仓位仍然开着的时候宣称「已平仓」**（第一百八十六刀修的就是这里）。
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.trader import venue_query
from scripts.trader.venue_query import close_position_confirmed


class _OkxRest:
    def __init__(self, *, close_raises=None, pending=None, pending_raises=None):
        self.close_raises = close_raises
        self._pending = pending or []
        self.pending_raises = pending_raises
        self.cancelled = []
        self.closed = []

    def pending_orders(self, inst_id):
        if self.pending_raises is not None:
            raise self.pending_raises
        return self._pending

    def cancel_order(self, inst_id, ord_id):
        self.cancelled.append((inst_id, ord_id))

    def close_position(self, inst_id, pos_side, td_mode="cross", auto_cxl=True):
        if self.close_raises is not None:
            raise self.close_raises
        self.closed.append((inst_id, pos_side))


def _pos(inst_id="BTC-USDT-SWAP", pos_side="long", size=0.0):
    return {"instId": inst_id, "posSide": pos_side, "pos": size}


class OkxCloseConfirmTest(unittest.TestCase):
    def setUp(self):
        # 回读循环 6 × 0.6s ⇒ 桩掉 sleep，否则用例白等数秒
        self._sleep = patch.object(venue_query.time, "sleep", lambda *_: None)
        self._sleep.start()
        self.addCleanup(self._sleep.stop)

    def _call(self, *, rest=None, query=None, before_size=10.0, pos_side="long",
              inst_id="BTC-USDT-SWAP"):
        rest = rest or _OkxRest()
        ok, detail = close_position_confirmed(
            inst_id, pos_side, before_size, "okx",
            okx_rest=rest,
            current_environment=lambda: SimpleNamespace(configured=True, mode="live"),
            query_positions=query or (lambda: (True, [], "")),
            fetch_other_venue_positions=lambda env: (True, {}, ""))
        return ok, detail, rest

    def test_flat_readback_confirms_close(self):
        ok, detail, rest = self._call()
        self.assertTrue(ok)
        self.assertIn("closed", detail)
        self.assertEqual(rest.closed, [("BTC-USDT-SWAP", "long")])

    def test_all_queries_failing_is_not_a_confirmed_close(self):
        """**读不到 ≠ 平掉了**：无一次成功响应 ⇒ `False`，且文案点名"验证失败"。"""
        ok, detail, _ = self._call(query=lambda: (False, [], "502"))
        self.assertFalse(ok)
        self.assertIn("no successful exchange response", detail)

    def test_still_open_reports_state_unchanged(self):
        ok, detail, _ = self._call(query=lambda: (True, [_pos(size=5.0)], ""))
        self.assertFalse(ok)
        self.assertIn("still reports an open position", detail)
        self.assertIn("before=10.0", detail)

    def test_net_position_mode_does_not_produce_false_success(self):
        """第一百八十六刀：净持仓账户 `posSide="net"` 必须**也算匹配**。

        若按精确相等匹配 ⇒ `remaining` 恒 0 ⇒ **仓还开着却宣称已平仓**（假成功，
        调用方会清掉 tracker ⇒ 孤儿仓脱管）。
        """
        ok, detail, _ = self._call(
            query=lambda: (True, [_pos(pos_side="net", size=5.0)], ""), pos_side="long")
        self.assertFalse(ok, "net 账户里仍有仓 ⇒ 绝不能报告成功")
        self.assertIn("still reports", detail)

    def test_close_command_failure_is_reported(self):
        rest = _OkxRest(close_raises=RuntimeError("rejected"))
        ok, detail, _ = self._call(rest=rest)
        self.assertFalse(ok)
        self.assertIn("close command failed", detail)

    def test_pending_order_preclean_failure_only_warns(self):
        """预撤挂单失败**只是告警**，不得阻断平仓（平仓才是目的）。"""
        rest = _OkxRest(pending_raises=RuntimeError("no such api"))
        ok, _, rest = self._call(rest=rest)
        self.assertTrue(ok, "预撤失败不该导致平仓不算")
        self.assertEqual(rest.closed, [("BTC-USDT-SWAP", "long")])

    def test_pending_orders_for_right_side_are_precancelled(self):
        rest = _OkxRest(pending=[{"posSide": "long", "ordId": "o1"},
                                 {"posSide": "short", "ordId": "o2"},
                                 {"posSide": "net", "ordId": "o3"},
                                 {"posSide": "long", "ordId": ""}])
        self._call(rest=rest)
        self.assertEqual(rest.cancelled, [("BTC-USDT-SWAP", "o1"), ("BTC-USDT-SWAP", "o3")],
                         "只撤同向或 net 的挂单；空 ordId 跳过")

    def test_residual_below_tolerance_counts_as_flat(self):
        """残余量低于 before_size 的 0.1% ⇒ 视为已平（交易所状态的正常抖动）。"""
        ok, _, _ = self._call(before_size=1000.0,
                              query=lambda: (True, [_pos(size=0.5)], ""))
        self.assertTrue(ok, "0.5 < 1000*0.001 ⇒ 视为归零")


if __name__ == "__main__":
    unittest.main()
