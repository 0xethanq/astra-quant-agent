"""挂单生命周期与归属对账的失败语义（第二百三十八刀）。

这两个函数是**撤单**的执行者，而撤单**不可逆**。它们的共同纪律：

- **读不到 ≠ 没有**：本地意图读不出来 ⇒ **一张都不撤** + fail-closed 拦本周期
  （旧写法把"文件坏了"当成"没有意图" ⇒ 每笔挂单都成了孤儿被撤 ⇒ 撤旧挂新循环）；
- **核验不了就拦轮**（网络/未知异常）；但**凭证已死**是例外：执行闸开着而密钥失效，
  该所不可能再收到新单 ⇒ 记入 `_BROKEN_VENUES`（本轮路由摘除其执行资格）并**跳过**，
  不拿凭证错误拦全链（审计#4 教训：那等于交易停摆）；
- **同向重复单收敛**：按创建时间只保最新一条为候选存活单，其余降级为重复单
  （修复外所"每轮重挂造成成对重复"）；
- **新鲜意图归属 → 保留**；超时/方向不符/无归属 → 撤销，原因必须写清。
"""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.trader.order_lifecycle import clean_stale_open_orders, reconcile_pending_orders

NOW_MS = 1_700_000_000_000


class _Okx:
    def __init__(self, *, pending=None, raises=None, cancel_raises=None):
        self._pending = pending if pending is not None else []
        self._raises = raises
        self.cancel_raises = cancel_raises
        self.cancelled = []

    def pending_orders(self):
        if self._raises is not None:
            raise self._raises
        return self._pending

    def cancel_order(self, inst_id, order_id):
        if self.cancel_raises is not None:
            raise self.cancel_raises
        self.cancelled.append((inst_id, order_id))


class _Adapter:
    def __init__(self, *, rows=None, raises=None, cancel_raises=None):
        self._rows = rows or []
        self._raises = raises
        self.cancel_raises = cancel_raises
        self.cancelled = []
        self.listed = []

    def open_orders(self):
        if self._raises is not None:
            raise self._raises
        return self._rows

    def list_open_orders(self, base):
        self.listed.append(base)
        if self._raises is not None:
            raise self._raises
        return self._rows

    def cancel_order(self, base, order_id):
        if self.cancel_raises is not None:
            raise self.cancel_raises
        self.cancelled.append((base, order_id))


def _registry(open_venues=("gate", "binance"), adapters=None, raises=None):
    adapters = adapters or {}

    def get_adapter(venue, environment=None):
        if raises is not None:
            raise raises
        return adapters[venue]

    return SimpleNamespace(
        execution_open=lambda v, mode: v in open_venues, get_adapter=get_adapter)


def _clean(*, okx=None, intents=(), env_mode="live", registry=None, instruments=None,
           keep=None, now_ms=None, intents_raiser=None):
    """跑一次 clean_stale_open_orders（默认：无外所、无意图、无挂单）。"""
    if intents_raiser is not None:
        load_intents = lambda: (_ for _ in ()).throw(intents_raiser)
    else:
        load_intents = lambda: list(intents)
    env = (lambda: SimpleNamespace(mode=env_mode)) if env_mode else \
        (lambda: (_ for _ in ()).throw(RuntimeError("env 不可读")))
    _now = (now_ms if now_ms is not None else NOW_MS) / 1000
    with patch("scripts.trader.order_lifecycle.time.time", lambda: _now):
        return clean_stale_open_orders(
            keep or set(), load_open_intents=load_intents, OPEN_INTENT_TTL_MS=60_000,
            _BROKEN_VENUES=set(), current_environment=env,
            load_instruments=(instruments if instruments is not None else (lambda: [])),
            okx_rest=okx or _Okx(), venue_registry=registry or _registry(open_venues=()))


class OkxStaleLifecycleTest(unittest.TestCase):
    def test_pending_read_failure_is_fail_closed(self):
        ok, why = _clean(okx=_Okx(raises=RuntimeError("网络断了")))
        self.assertFalse(ok)
        self.assertIn("invalid open-orders response", why)

    def test_stale_live_order_is_cancelled(self):
        old = {"instId": "BTC-USDT-SWAP", "ordId": "o1", "state": "live", "cTime": 1}
        okx = _Okx(pending=[old])
        ok, _ = _clean(okx=okx, now_ms=NOW_MS)
        self.assertTrue(ok)
        self.assertEqual(okx.cancelled, [("BTC-USDT-SWAP", "o1")])

    def test_fresh_or_non_live_or_kept_orders_are_left_alone(self):
        """宽限期内 / 非 live 状态 / 已判定归属（接管）⇒ 一律不动手。"""
        pending = [
            {"instId": "A-USDT-SWAP", "ordId": "fresh", "state": "live", "cTime": NOW_MS - 1000},
            {"instId": "B-USDT-SWAP", "ordId": "filled", "state": "filled", "cTime": 1},
            {"instId": "C-USDT-SWAP", "ordId": "kept", "state": "live", "cTime": 1},
            {"instId": "D-USDT-SWAP", "state": "live", "cTime": 1},      # 无 ordId
        ]
        okx = _Okx(pending=pending)
        ok, _ = _clean(okx=okx, now_ms=NOW_MS, keep={"kept"})
        self.assertTrue(ok)
        self.assertEqual(okx.cancelled, [], "只该撤「陈旧 + live + 无归属」的那种")

    def test_cancel_failure_blocks_the_cycle(self):
        stale = {"instId": "BTC-USDT-SWAP", "ordId": "o1", "state": "live", "cTime": 1}
        okx = _Okx(pending=[stale], cancel_raises=RuntimeError("撤单被拒"))
        ok, why = _clean(okx=okx, now_ms=NOW_MS)
        self.assertFalse(ok)
        self.assertIn("failed to cancel stale order", why)


class ReconcileTest(unittest.TestCase):
    def _run(self, *, pending="__auto__", trackers=None, intents=(), okx=None,
             intents_raiser=None, side_map=None):
        okx = okx or _Okx()
        if pending == "__auto__":
            pending = okx.pending_orders() if okx._raises is None else None
        if intents_raiser is not None:
            load_intents = lambda: (_ for _ in ()).throw(intents_raiser)
        else:
            load_intents = lambda: list(intents)
        return reconcile_pending_orders(
            trackers if trackers is not None else {}, now_ms=NOW_MS, pending=pending,
            _order_pos_side=side_map or (lambda side: "long" if side == "buy" else "short"),
            load_open_intents=load_intents, load_trackers=lambda: {},
            OPEN_INTENT_TTL_MS=60_000,
            RECONCILE_REASON_SIDE_MISMATCH="方向不一致",
            RECONCILE_REASON_INTENT_STALE="周期意图已失效",
            RECONCILE_REASON_ORPHAN="无对应意图", okx_rest=okx)

    def test_pending_read_failure_is_fail_closed(self):
        ok, kept = self._run(pending=None, okx=_Okx(raises=RuntimeError("网络")))
        self.assertFalse(ok)
        self.assertEqual(kept, set())

    def test_non_list_response_is_fail_closed(self):
        ok, _ = self._run(pending={"instId": "BTC-USDT-SWAP"})
        self.assertFalse(ok, "响应非列表 ⇒ 不可判定 ⇒ 拦本轮，绝不当作空")

    def test_unreadable_intents_are_fail_closed_and_cancel_nothing(self):
        order = {"instId": "BTC-USDT-SWAP", "ordId": "o1", "side": "buy", "state": "live"}
        okx = _Okx()
        ok, kept = self._run(pending=[order], okx=okx, intents_raiser=RuntimeError("坏文件"))
        self.assertFalse(ok)
        self.assertEqual(kept, set())
        self.assertEqual(okx.cancelled, [], "意图不可读时绝不撤单")

    def test_tracker_attribution_takes_over(self):
        order = {"instId": "BTC-USDT-SWAP", "ordId": "o1", "side": "buy", "state": "live"}
        okx = _Okx()
        ok, kept = self._run(pending=[order], okx=okx,
                             trackers={"BTC-USDT-SWAP_long": {"trailingStopPx": 1}})
        self.assertTrue(ok)
        self.assertEqual(kept, {"o1"})
        self.assertEqual(okx.cancelled, [])

    def test_side_mismatch_is_cancelled(self):
        order = {"instId": "BTC-USDT-SWAP", "ordId": "o1", "side": "sell", "state": "live"}
        okx = _Okx()
        intents = [{"instId": "BTC-USDT-SWAP", "side": "buy", "ts": NOW_MS - 1000}]
        ok, kept = self._run(pending=[order], okx=okx, intents=intents)
        self.assertTrue(ok)
        self.assertEqual(okx.cancelled, [("BTC-USDT-SWAP", "o1")])
        self.assertEqual(kept, set())

    def test_stale_intent_is_cancelled_not_taken_over(self):
        order = {"instId": "BTC-USDT-SWAP", "ordId": "o1", "side": "buy", "state": "live"}
        okx = _Okx()
        intents = [{"instId": "BTC-USDT-SWAP", "side": "buy", "ts": NOW_MS - 999_999}]
        ok, _ = self._run(pending=[order], okx=okx, intents=intents)
        self.assertTrue(ok)
        self.assertEqual(okx.cancelled, [("BTC-USDT-SWAP", "o1")], "超 TTL 的意图不作归属")

    def test_orphan_without_any_intent_is_cancelled(self):
        order = {"instId": "BTC-USDT-SWAP", "ordId": "o1", "side": "buy", "state": "live"}
        okx = _Okx()
        ok, _ = self._run(pending=[order], okx=okx)
        self.assertTrue(ok)
        self.assertEqual(okx.cancelled, [("BTC-USDT-SWAP", "o1")])

    def test_newest_intent_decides_attribution(self):
        """审计·PEPE 永动机：必须按**最新**意图判归属（旧写法取最老 ⇒ 撤旧挂新无限循环）。"""
        order = {"instId": "PEPE-USDT-SWAP", "ordId": "o1", "side": "buy", "state": "live"}
        okx = _Okx()
        intents = [
            {"instId": "PEPE-USDT-SWAP", "side": "buy", "ts": NOW_MS - 999_999},   # 老（超 TTL）
            {"instId": "PEPE-USDT-SWAP", "side": "buy", "ts": NOW_MS - 1000},      # 新（有效）
        ]
        ok, kept = self._run(pending=[order], okx=okx, intents=intents)
        self.assertTrue(ok)
        self.assertEqual(kept, {"o1"}, "最新意图有效 ⇒ 接管保留（不得按最老意图撤销）")
        self.assertEqual(okx.cancelled, [])

    def test_non_dict_and_non_live_entries_are_skipped(self):
        okx = _Okx()
        ok, kept = self._run(pending=["垃圾", {"instId": "BTC-USDT-SWAP", "ordId": "o2",
                                              "side": "buy", "state": "filled"}], okx=okx)
        self.assertTrue(ok)
        self.assertEqual(kept, set())
        self.assertEqual(okx.cancelled, [])

    def test_cancel_failure_returns_false_with_partial_kept(self):
        orders = [
            {"instId": "AAA-USDT-SWAP", "ordId": "keep1", "side": "buy", "state": "live"},
            {"instId": "BBB-USDT-SWAP", "ordId": "orphan", "side": "buy", "state": "live"},
        ]
        okx = _Okx(cancel_raises=RuntimeError("撤单被拒"))
        ok, kept = self._run(pending=orders, okx=okx,
                             trackers={"AAA-USDT-SWAP_long": {}})
        self.assertFalse(ok, "撤销失败 ⇒ 对账自身失败 ⇒ fail-closed")
        self.assertEqual(kept, {"keep1"}, "已判定接管的保留集必须随失败一并返回")



class ReconcileDegradedInputTest(unittest.TestCase):
    def test_trackers_default_loader_is_used_when_none(self):
        """`trackers=None` ⇒ 回落到 `load_trackers()`（调用点没传时的取数路径）。"""
        order = {"instId": "BTC-USDT-SWAP", "ordId": "o1", "side": "buy", "state": "live"}
        okx = _Okx()
        called = []
        ok, kept = reconcile_pending_orders(
            None, now_ms=NOW_MS, pending=[order],
            _order_pos_side=lambda side: "long" if side == "buy" else "short",
            load_open_intents=lambda: [], load_trackers=lambda: (called.append(1), {})[1],
            OPEN_INTENT_TTL_MS=60_000, RECONCILE_REASON_SIDE_MISMATCH="方向不一致",
            RECONCILE_REASON_INTENT_STALE="周期意图已失效", RECONCILE_REASON_ORPHAN="无对应意图",
            okx_rest=okx)
        self.assertTrue(ok)
        self.assertEqual(called, [1], "trackers=None 时必须走默认取数函数")
        self.assertEqual(okx.cancelled, [("BTC-USDT-SWAP", "o1")], "无归属 ⇒ 孤儿撤销")

    def test_cancel_failure_on_side_mismatch_is_fail_closed(self):
        order = {"instId": "BTC-USDT-SWAP", "ordId": "o1", "side": "sell", "state": "live"}
        okx = _Okx(cancel_raises=RuntimeError("撤单被拒"))
        intents = [{"instId": "BTC-USDT-SWAP", "side": "buy", "ts": NOW_MS - 1000}]
        ok, kept = reconcile_pending_orders(
            {}, now_ms=NOW_MS, pending=[order],
            _order_pos_side=lambda side: "long" if side == "buy" else "short",
            load_open_intents=lambda: intents, load_trackers=lambda: {},
            OPEN_INTENT_TTL_MS=60_000, RECONCILE_REASON_SIDE_MISMATCH="方向不一致",
            RECONCILE_REASON_INTENT_STALE="周期意图已失效", RECONCILE_REASON_ORPHAN="无对应意图",
            okx_rest=okx)
        self.assertFalse(ok, "方向不符的撤销失败 ⇒ 对账失败 ⇒ fail-closed")
        self.assertEqual(kept, set())

    def test_cancel_failure_on_stale_intent_is_fail_closed(self):
        order = {"instId": "BTC-USDT-SWAP", "ordId": "o1", "side": "buy", "state": "live"}
        okx = _Okx(cancel_raises=RuntimeError("撤单被拒"))
        intents = [{"instId": "BTC-USDT-SWAP", "side": "buy", "ts": NOW_MS - 999_999}]
        ok, kept = reconcile_pending_orders(
            {}, now_ms=NOW_MS, pending=[order],
            _order_pos_side=lambda side: "long" if side == "buy" else "short",
            load_open_intents=lambda: intents, load_trackers=lambda: {},
            OPEN_INTENT_TTL_MS=60_000, RECONCILE_REASON_SIDE_MISMATCH="方向不一致",
            RECONCILE_REASON_INTENT_STALE="周期意图已失效", RECONCILE_REASON_ORPHAN="无对应意图",
            okx_rest=okx)
        self.assertFalse(ok, "超时意图的撤销失败 ⇒ 对账失败 ⇒ fail-closed")
        self.assertEqual(kept, set())


if __name__ == "__main__":
    unittest.main()
