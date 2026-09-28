"""三所入场闸门**平权矩阵**（2026-09-28 用户拍板「检查三所是否都遵循系统策略与风控」）。

## 这个门在守什么

审计发现入场闸门被**实现了两遍**，而只有一遍接了 OKX：

| 闸门 | `execution_router`（gate/binance） | OKX 直签链 |
|---|---|---|
| 跨所同向敞口上限（`ASTRA_MAX_TOTAL_EXPOSURE_USDT`，**启用中**） | ✓ | **✗** |
| 池 `min_confidence` / `max_open` / `dry_run` | ✓ | **✗** |
| 持仓模式只读体检 | ✓ | **✗**（`detect_position_mode` 早在第一百九十三刀就为 OKX 实现，却**无人调用**） |

最坏的一处是不对称的是敞口：`check_total_exposure` 的统计口径**明确把 OKX 的仓算进去**
（`execution_router._exposure_venues` 为此专门写过一段：OKX 走直签、
`execution_open("okx")` 恒 False，按开闸判会把持仓最多的 OKX 整个漏掉）——
于是出现

    **OKX 的仓占着上限，而 OKX 的下单不查上限。**

加重情节：提示词对主脑写「跨所同向敞口上限 … 超出执行层拒开」
（`scripts/ai_brain_trader.build_risk_budget_lines`）——走到 OKX 时是**空头支票**。
历史上该闸门真的拦过单（2026-09-25 日志：GATE「将达 13630990U，超上限 3000U」），
那时同标的同方向的 OKX 单会**静默通过**。

## 四组断言

1. **策略单源**：判据只在 `astra_backend/execution/venue_gate.py` 里实现一次，
   且**两条执行路径各调用一次** ⇒ 将来往里加闸门自动覆盖三所；
2. **场所无关**：同一组参数对 `okx` / `gate` / `binance` 逐个产出一致的拒单；
3. **头号回归**：走 **OKX 直签路径**的入场单，真的会被跨所同向敞口闸门拦下；
4. **无遗漏阶段**：`execution_router` 里每个 `_fail("<stage>")` 要么由共用闸门产出、
   要么在「场所机制」白名单里 —— 出现未归类的新阶段即红。
"""

from __future__ import annotations

import ast
import os
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

VENUES = ("okx", "gate", "binance")

#: 共用闸门负责的阶段（策略）—— 应当对**每一个**场所都生效。
GATE_STAGES = ("exposure", "venue_dry_run", "venue_pool", "position_mode")

#: 场所**机制**阶段：它们天然只属于某条执行路径（合约规格、原生载荷、
#: 保护腿回读等），不属于"三所必须同尺"的风控策略。
VENUE_MECHANICS_STAGES = frozenset({
    "validate",     # 决策数值形状
    "leverage",     # 夹取（且 scripts 侧另有 clamp_ai_leverage）
    "sizing",       # 原生数量换算
    "specs",        # 合约规格
    "price",        # 现价可得性
    "risk_gate",    # 几何/R:R 复验
    "listing",      # 环境维合约对账
    "precheck",     # 己仓归属对账
    "entry",        # 开仓载荷
    "protective",   # 保护腿
    "close",        # 平仓载荷
})


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class StrategyIsSingleSourcedTest(unittest.TestCase):
    """判据只有一份实现，且两条执行路径都调用它。"""

    def test_the_gate_policy_lives_in_exactly_one_module(self):
        src = _read("astra_backend/execution/venue_gate.py")
        for needle in ("venue_dry_run", "venue_pool", "position_mode", "准入币种"):
            self.assertIn(needle, src, f"共用闸门里丢了「{needle}」判据")

    def test_the_router_no_longer_reimplements_the_policy(self):
        """router 不得再**内联**这些判据 —— 那正是"实现两遍、只有一遍接 OKX"的成因。"""
        src = _read("astra_backend/execution_router.py")
        self.assertIn("_venue_entry_gate(", src, "router 没有调用共用闸门")
        for inlined in ("池配置 dry_run=true", "准入币种清单为空", "已达池上限 max_open="):
            self.assertNotIn(inlined, src,
                             f"router 又内联了闸门文案「{inlined}」⇒ 判据分裂成两份")

    def test_both_execution_paths_invoke_the_gate(self):
        for rel in ("astra_backend/execution_router.py", "scripts/trader/order_submit.py"):
            tree = ast.parse(_read(rel))
            calls = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and (
                         (isinstance(n.func, ast.Name) and n.func.id in ("_venue_entry_gate", "venue_entry_gate"))
                         or (isinstance(n.func, ast.Attribute) and n.func.attr == "venue_entry_gate"))]
            self.assertGreaterEqual(len(calls), 1,
                                    f"{rel} 没有调用共用入场闸门 ⇒ 该路径上的所不受闸门约束")

    def test_every_non_router_venue_is_gated_in_order_submit(self):
        """OKX 不经 router ⇒ `order_submit` 必须为它补跑（否则闸门对其失效）。"""
        src = _read("scripts/trader/order_submit.py")
        self.assertIn("_ROUTER_DISPATCHED_VENUES", src)
        self.assertIn("_shared_venue_entry_gate(", src)
        self.assertIn('"okx"', _read("astra_backend/exchanges/registry.py") + src,
                      "OKX 必须仍在登记场所里")


class GateIsVenueAgnosticTest(unittest.TestCase):
    """同一组参数对三所产出一致的判定。"""

    def _gate(self, **kw):
        from astra_backend.execution.venue_gate import venue_entry_gate
        base = dict(asset="BTC", confidence=90.0, pool={}, exposure_cap=0.0,
                    exposure_fail=None, open_count=None, mode_checked=False)
        base.update(kw)
        return venue_entry_gate(**base)

    def test_dry_run_blocks_every_venue(self):
        for v in VENUES:
            with self.subTest(venue=v):
                r = self._gate(venue=v, pool={"dry_run": True})
                self.assertIsNotNone(r)
                self.assertEqual(r["stage"], "venue_dry_run")

    def test_min_confidence_applies_to_every_venue(self):
        for v in VENUES:
            with self.subTest(venue=v):
                r = self._gate(venue=v, pool={"min_confidence": 72.0}, confidence=70.0)
                self.assertIsNotNone(r)
                self.assertEqual(r["stage"], "venue_pool")
                self.assertIn("低于", r["detail"])

    def test_max_open_applies_to_every_venue(self):
        for v in VENUES:
            with self.subTest(venue=v):
                r = self._gate(venue=v, pool={"max_open": 2}, open_count=2)
                self.assertIsNotNone(r)
                self.assertEqual(r["stage"], "venue_pool")
                self.assertIn("max_open=2", r["detail"])

    def test_exposure_applies_to_every_venue(self):
        fail = {"stage": "exposure", "detail": "跨所同向敞口将达 9000U，超上限 1000U",
                "ok": False}
        for v in VENUES:
            with self.subTest(venue=v):
                self.assertIs(self._gate(venue=v, exposure_fail=fail), fail)

    def test_position_mode_applies_to_every_venue(self):
        for v in VENUES:
            with self.subTest(venue=v):
                r = self._gate(venue=v, mode_checked=True, position_mode="unknown",
                               declared_modes=("net", "long_short"),
                               entry_ready_modes=("long_short",))
                self.assertIsNotNone(r)
                self.assertEqual(r["stage"], "position_mode")

    def test_unconfigured_assets_means_unrestricted_but_explicit_empty_means_stop(self):
        """★ `None`（未配置⇒不设限）与 `[]`（显式空池⇒停发）必须区分。

        此前两者都归一成 `[]`，而 `[]` 在执行层是"停发"、在选所层是"不设限" ——
        同一个值两层语义相反。
        """
        for v in VENUES:
            with self.subTest(venue=v, assets=None):
                self.assertIsNone(self._gate(venue=v, pool={"assets": None}),
                                  "未配置准入清单不该被当成空池停发")
            with self.subTest(venue=v, assets=[]):
                r = self._gate(venue=v, pool={"assets": []})
                self.assertIsNotNone(r)
                self.assertIn("空池", r["detail"])

    def test_no_probe_means_no_max_open_verdict(self):
        """探针没跑（`open_count is None`）时不得把"没探"渲染成"0 笔"而放行/误拒。"""
        for v in VENUES:
            with self.subTest(venue=v):
                self.assertIsNone(self._gate(venue=v, pool={"max_open": 1}, open_count=None))


class OkxEntryIsGatedTest(unittest.TestCase):
    """★ 头号回归：**走 OKX 直签路径**的入场单必须真的过闸门。

    这是审计发现的核心缺陷 —— 此前 OKX 的下单不查任何池门禁与跨所敞口。
    本组直接驱动 `submit_protected_limit_order`（不经 router），断言它被拦下。
    """

    INST = "BTC-USDT-SWAP"
    DECISION = {"action": "BUY_LONG", "confidence": 95.0}

    def _submit(self, *, venue="okx", venue_ctx=None, stub=None, **over):
        import scripts.ai_factor_trader as aft          # noqa: F401  (门面副作用)
        from scripts.trader.order_submit import submit_protected_limit_order

        ctx = {"notional_usdt": 3000.0, "margin_usdt": 1000.0, "leverage": 3.0,
               "confidence": 95.0, "intent_id": "intent-1", "ct_val": 0.01, "min_sz": 0.01}
        ctx.update(venue_ctx or {})

        class _Okx:
            placed = False

            def set_leverage(self, *a, **k):
                return {}

            def place_order(self, *a, **k):
                self.placed = True
                return [{"ordId": "okx-1"}]

        proxy = _Okx()
        params = dict(
            confirm_signal_reservation=lambda r: None,
            record_open_intent=lambda i, s: None,
            release_signal_reservation=lambda r, why: None,
            route_and_reserve_signal=lambda *a, **k: {
                "ok": True, "venue": venue, "reservation": None},
            MAX_LEVERAGE=20, MIN_LEVERAGE=1,
            canonical_base=lambda i: i.split("-")[0],
            current_environment=lambda: SimpleNamespace(simulated=True, mode="demo"),
            fetch_ticker=lambda i: {"last": 79000.0},
            okx_rest=proxy,
            quantize_size=lambda raw, step: float(int(raw / (step or 1)) * (step or 1)),
            venue_registry=SimpleNamespace(registered_venues=lambda: ("okx",)))
        # ⚠️ 适配器替身由**本函数**负责进入作用域：若交给调用方在外层 `with`，
        # 会被这里的内层 `with` 覆盖（本仓踩过：外层 `mode="net"` 被内层默认值遮蔽，
        # 于是"模式体检"用例测的是默认值，恒过）。
        with patch("astra_backend.exchanges.listing.ensure_contract_listed",
                   return_value=SimpleNamespace(ok=True, reason=None)), \
             patch("scripts.order_risk.validate_quote_geometry_and_rr",
                   return_value=(True, "", 2.5)), \
             (stub or _direct_adapter()):
            res = submit_protected_limit_order(
                self.INST, "buy", "long", 3.0, 79000.0, 85000.0, 77000.0,
                venue_ctx=ctx, **params)
        return res, proxy

    def test_cross_venue_exposure_cap_is_enforced_on_the_okx_direct_path(self):
        """★ 核心回归：OKX 直签入场**必须**受跨所同向敞口上限约束。

        桩里的 OKX 已持有一大笔同向 BTC 多仓；上限压到 1000U ⇒ 本单必须被拒。
        修复前：`check_total_exposure` 的唯一调用点在 `execution_router`，
        OKX 直签路径**一个都没有**，于是这里会**放行**。
        """
        big = [{"base": "BTC", "side": "long", "size_signed": 1.0,
                "mark_price": 900000.0, "venue": "okx"}]
        with patch("scripts.risk_constants.MAX_TOTAL_EXPOSURE_USDT", 1000.0), \
             patch("astra_backend.exchanges.registry.venue_credentials",
                   lambda v, e=None: ("k", "s", "p")), \
             patch("astra_backend.exchanges.registry.registered_venues",
                   lambda: ("okx",)):
            (ok, why), _proxy = self._submit(stub=_direct_adapter(positions=big))
        self.assertFalse(ok, "跨所同向敞口超限，OKX 直签单必须被拒")
        self.assertIn("敞口", why, f"拒单理由应点明敞口闸门，实际: {why}")

    def test_exposure_failure_makes_the_okx_path_fail_closed(self):
        """敞口**读不到** ⇒ 拒单（绝不把"读不到"渲染成"没有敞口"）。"""
        with patch("scripts.risk_constants.MAX_TOTAL_EXPOSURE_USDT", 1000.0), \
             patch("astra_backend.exchanges.registry.venue_credentials",
                   lambda v, e=None: ("k", "s", "p")), \
             patch("astra_backend.exchanges.registry.registered_venues",
                   lambda: ("okx",)):
            (ok, why), _proxy = self._submit(
                stub=_direct_adapter(positions_raises=RuntimeError("读不到")))
        self.assertFalse(ok, "敞口读不到必须 fail-closed 拒单")
        self.assertIn("敞口", why)

    def test_okx_pool_dry_run_blocks_the_direct_path(self):
        """`okx.dry_run=true` 必须能停发 OKX（此前没有池概念，开关无处生效）。"""
        with patch("astra_backend.exchanges.routing_policy.load_venue_pool",
                   return_value={"dry_run": True, "assets": None, "max_open": 5,
                                 "min_confidence": 0.0, "margin_per_trade_usdt": 0.0}):
            (ok, why), proxy = self._submit()
        self.assertFalse(ok, "dry_run=true 却仍然发出了委托")
        self.assertIn("dry_run", why)
        self.assertFalse(proxy.placed, "被闸门拒了却仍然发单")

    def test_okx_pool_max_open_blocks_the_direct_path(self):
        rows = [{"base": "ETH", "side": "long", "size_signed": 1.0, "mark_price": 100.0,
                 "venue": "okx"}]
        with patch("astra_backend.exchanges.routing_policy.load_venue_pool",
                   return_value={"dry_run": False, "assets": None, "max_open": 1,
                                 "min_confidence": 0.0, "margin_per_trade_usdt": 0.0}):
            (ok, why), proxy = self._submit(stub=_direct_adapter(positions=rows))
        self.assertFalse(ok, "已达 max_open 却仍然发出了委托")
        self.assertIn("max_open", why)
        self.assertFalse(proxy.placed, "被闸门拒了却仍然发单")

    def test_okx_position_mode_is_checked(self):
        """OKX 的 `detect_position_mode`（第一百九十三刀就实现了）必须真的被调用。

        修复前它**无人调用** —— 探测方法存在，闸门却不在 OKX 路径上。
        """
        (ok, why), proxy = self._submit(stub=_direct_adapter(mode="net"))
        self.assertFalse(ok, "OKX 账户处于 net 模式（载荷未核验）时必须禁新开仓")
        self.assertIn("position_mode", why)
        self.assertFalse(proxy.placed, "被闸门拒了却仍然发单")

    def test_the_happy_path_still_passes_every_gate(self):
        """防空转：正常单必须**通过**（否则上面的拒单断言可能只是因为闸门恒定在拒）。"""
        (ok, why), proxy = self._submit()
        self.assertTrue(ok, f"正常单不该被拒: {why}")
        self.assertTrue(proxy.placed)


class NoUnclassifiedRefusalStageTest(unittest.TestCase):
    """router 里的拒单阶段要么由共用闸门产出、要么是场所机制 —— 不得有第三类。"""

    def test_every_router_stage_is_gate_owned_or_venue_mechanics(self):
        stages = set()
        for node in ast.walk(ast.parse(_read("astra_backend/execution_router.py"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_fail" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                stages.add(str(node.args[0].value))
        gate_src = _read("astra_backend/execution/venue_gate.py")
        gate_stages = {s for s in stages if f'"{s}"' in gate_src}
        unclassified = stages - gate_stages - VENUE_MECHANICS_STAGES
        self.assertEqual(
            unclassified, set(),
            f"router 里出现未归类的拒单阶段 {sorted(unclassified)}：\n"
            "  若它是**三所都该同尺的风控策略** ⇒ 请搬进 venue_gate.venue_entry_gate\n"
            "  （否则 OKX 直签路径拿不到它）；若它天然只属于该执行路径 ⇒\n"
            "  加进本文件的 VENUE_MECHANICS_STAGES 并说明理由。")

    def test_the_gate_owns_the_policy_stages(self):
        """策略阶段的**来源**必须落在共用闸门（或它的上游 `risk_gates`）。

        `exposure` 由 `risk_gates.check_total_exposure` 产出、经闸门透传；
        其余三个阶段由闸门自己产出 —— 两者都是"单一策略源"的一部分。
        """
        gate_src = _read("astra_backend/execution/venue_gate.py")
        risk_src = _read("astra_backend/execution/risk_gates.py")
        for s in GATE_STAGES:
            self.assertTrue(
                f'"{s}"' in gate_src or f'"{s}"' in risk_src,
                f"阶段 {s} 在共用闸门与 risk_gates 里都找不到 ⇒ 判据漂走了")
        # 闸门必须**调用**上游敞口判据的产物（而不是自己再写一遍）
        self.assertIn("exposure_fail", gate_src)
        self.assertIn("check_total_exposure", risk_src)

    def test_the_allowlist_is_not_a_dumping_ground(self):
        """防空转：白名单必须是**具体**的场所机制，不能把策略阶段也吞进去。"""
        overlap = VENUE_MECHANICS_STAGES & set(GATE_STAGES)
        self.assertEqual(overlap, set(),
                         f"{sorted(overlap)} 同时被当成「场所机制」与「共用策略」⇒ 白名单在放水")
        self.assertLessEqual(len(VENUE_MECHANICS_STAGES), 15)


# 本模块只做桩替换，绝不改任何真实配置/凭证。
def _direct_adapter(**kw):
    from tests.venue_gate_stub import direct_venue_gate_adapter
    return direct_venue_gate_adapter(**kw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
