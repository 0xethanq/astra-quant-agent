"""入场闸门**单源 + 直签路径覆盖**矩阵（2026-09-28 拍板；多所拆除后收口为单所口径）。

## 这个门在守什么

审计发现入场闸门被**实现了两遍**，而只有一遍接了 OKX：

| 闸门 | 旧 `execution_router`（另两所） | OKX 直签链 |
|---|---|---|
| 同向敞口上限（`ASTRA_MAX_TOTAL_EXPOSURE_USDT`，**启用中**） | ✓ | **✗** |
| 持仓模式只读体检 | ✓ | **✗**（`detect_position_mode` 早实现，却**无人调用**） |

最坏的一处是不对称的敞口 —— 即 **OKX 的仓占着上限，而 OKX 的下单不查上限**。

多所执行面（`execution_router` / `venue_router` / `venue_routing/`）已整体移除，
池门禁（`dry_run` / `assets` / `max_open` / `min_confidence`）随多所一起消失。
本门因此收口为**单所口径**：判据仍只有一份实现，且必须真的挂在唯一的
执行路径（OKX 直签：`scripts/trader/order_submit.py::_shared_venue_entry_gate`）上。

## 四组断言

1. **策略单源**：判据只在 `astra_backend/execution/venue_gate.py` 里实现一次，
   且**唯一**的调用点是 `order_submit` ⇒ 将来往里加闸门自动生效；
2. **无内联副本**：调用点不得把判据文案再写一遍（那正是"实现两遍"的成因）；
3. **头号回归**：走 OKX 直签路径的入场单，真的会被同向敞口闸门拦下，
   且敞口读不到时 **fail-closed**；
4. **无未归类阶段**：闸门产出的拒单阶段必须落在**已分类**的集合里 ——
   出现未归类的新阶段即红。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]

VENUES = ("okx",)

#: 共用闸门负责的阶段（策略）—— 必须**真的**产出这些阶段名。
GATE_STAGES = ("exposure", "position_mode")

#: 已分类的拒单阶段全集：`exposure` 由 `risk_gates.check_total_exposure` 产出、
#: 经闸门透传；`position_mode` 由闸门自己产出。
CLASSIFIED_STAGES = frozenset(GATE_STAGES)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class StrategyIsSingleSourcedTest(unittest.TestCase):
    """判据只有一份实现，且唯一的执行路径调用它。"""

    def test_the_gate_policy_lives_in_exactly_one_module(self):
        src = _read("astra_backend/execution/venue_gate.py")
        for needle in ("position_mode", "exposure_fail"):
            self.assertIn(needle, src, f"共用闸门里丢了「{needle}」判据")

    def test_the_only_call_site_is_the_okx_order_path(self):
        """全仓只应有一处调用 `venue_entry_gate` —— 多一处就是判据又要分裂。"""
        callers = []
        for rel in ("scripts/trader/order_submit.py",
                    "astra_backend/execution/risk_gates.py",
                    "scripts/trader/entry_execution.py"):
            tree = ast.parse(_read(rel))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "venue_entry_gate"):
                    callers.append(rel)
        self.assertEqual(callers, ["scripts/trader/order_submit.py"],
                         "共用入场闸门的调用点变了 ⇒ 要么有路径不受约束，要么判据分裂")

    def test_the_call_site_does_not_reinline_the_policy(self):
        """调用点不得再**内联**闸门判据文案 —— 那正是"实现两遍"的成因。"""
        src = _read("scripts/trader/order_submit.py")
        for inlined in ("无法只读确认持仓模式", "该模式下单/保护腿载荷未核验",
                        "跨所同向敞口将达"):
            self.assertNotIn(inlined, src,
                             f"order_submit 又内联了闸门文案「{inlined}」⇒ 判据分裂成两份")

    def test_the_okx_path_is_gated(self):
        src = _read("scripts/trader/order_submit.py")
        self.assertIn("_shared_venue_entry_gate(", src)
        self.assertIn("venue_entry_gate(", src)
        self.assertIn('"okx"', _read("astra_backend/exchanges/registry.py"),
                      "OKX 必须仍是登记场所")

    def test_the_multi_venue_execution_layer_is_gone(self):
        for rel in ("astra_backend/execution_router.py",
                    "astra_backend/venue_router.py",
                    "astra_backend/venue_routing/selection.py"):
            self.assertFalse((ROOT / rel).exists(), f"{rel} 应已随多所执行面移除")
        from astra_backend.exchanges import registered_venues
        self.assertEqual(list(registered_venues()), ["okx"],
                         "注册表里只应剩 OKX")


class GateBehaviourTest(unittest.TestCase):
    """闸门的判定行为（单所口径：场所无关性退化为"对 OKX 生效"）。"""

    def _gate(self, **kw):
        from astra_backend.execution.venue_gate import venue_entry_gate
        base = dict(asset="BTC", exposure_fail=None, mode_checked=False)
        base.update(kw)
        return venue_entry_gate(**base)

    def test_no_problem_means_pass(self):
        for v in VENUES:
            with self.subTest(venue=v):
                self.assertIsNone(self._gate(venue=v))

    def test_exposure_refusal_is_passed_through_verbatim(self):
        fail = {"stage": "exposure", "detail": "同向敞口将达 9000U，超上限 1000U",
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

    def test_a_not_entry_ready_mode_is_refused(self):
        """OKX 账户处于 `net`（载荷未核验）时必须禁新开仓 —— 这是**真实**的准入集合。"""
        r = self._gate(venue="okx", mode_checked=True, position_mode="net",
                       declared_modes=("net", "long_short"),
                       entry_ready_modes=("long_short",))
        self.assertIsNotNone(r)
        self.assertEqual(r["stage"], "position_mode")
        self.assertIn("net", r["detail"])

    def test_entry_ready_mode_passes(self):
        self.assertIsNone(self._gate(venue="okx", mode_checked=True,
                                     position_mode="long_short",
                                     declared_modes=("net", "long_short"),
                                     entry_ready_modes=("long_short",)))

    def test_no_probe_means_no_verdict(self):
        """调用方没做探测（`mode_checked=False`）时不得凭空判红。"""
        self.assertIsNone(self._gate(venue="okx", mode_checked=False,
                                     position_mode="unknown"))


class OkxEntryIsGatedTest(unittest.TestCase):
    """★ 头号回归：**走 OKX 直签路径**的入场单必须真的过闸门。

    本组直接驱动 `submit_protected_limit_order`（不经任何 router），断言它被拦下。
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

    def test_same_side_exposure_cap_is_enforced_on_the_okx_direct_path(self):
        """★ 核心回归：OKX 直签入场**必须**受同向敞口上限约束。

        桩里的 OKX 已持有一大笔同向 BTC 多仓；上限压到 1000U ⇒ 本单必须被拒。
        """
        big = [{"base": "BTC", "side": "long", "size_signed": 1.0,
                "mark_price": 900000.0, "venue": "okx"}]
        with patch("scripts.risk_constants.MAX_TOTAL_EXPOSURE_USDT", 1000.0):
            (ok, why), _proxy = self._submit(stub=_direct_adapter(positions=big))
        self.assertFalse(ok, "同向敞口超限，OKX 直签单必须被拒")
        self.assertIn("敞口", why, f"拒单理由应点明敞口闸门，实际: {why}")

    def test_exposure_failure_makes_the_okx_path_fail_closed(self):
        """敞口**读不到** ⇒ 拒单（绝不把"读不到"渲染成"没有敞口"）。"""
        with patch("scripts.risk_constants.MAX_TOTAL_EXPOSURE_USDT", 1000.0):
            (ok, why), _proxy = self._submit(
                stub=_direct_adapter(positions_raises=RuntimeError("读不到")))
        self.assertFalse(ok, "敞口读不到必须 fail-closed 拒单")
        self.assertIn("敞口", why)

    def test_okx_position_mode_is_checked(self):
        """OKX 的 `detect_position_mode` 必须真的被调用。"""
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
    """闸门产出的拒单阶段必须**已分类** —— 不得有第三类悄悄长出来。"""

    def _stage_literals(self, rel: str) -> set:
        stages = set()
        for node in ast.walk(ast.parse(_read(rel))):
            if (isinstance(node, ast.Dict)
                    and any(isinstance(k, ast.Constant) and k.value == "stage"
                            for k in node.keys)):
                for k, v in zip(node.keys, node.values):
                    if (isinstance(k, ast.Constant) and k.value == "stage"
                            and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                        stages.add(v.value)
        return stages

    def test_every_gate_stage_is_classified(self):
        stages = (self._stage_literals("astra_backend/execution/venue_gate.py")
                  | self._stage_literals("astra_backend/execution/risk_gates.py"))
        unclassified = stages - CLASSIFIED_STAGES
        self.assertEqual(
            unclassified, set(),
            f"出现未归类的拒单阶段 {sorted(unclassified)}：\n"
            "  若它是**入场风控策略** ⇒ 请搬进 venue_gate.venue_entry_gate\n"
            "  并把阶段名加进本文件的 CLASSIFIED_STAGES（附一句理由）。")

    def test_the_gate_owns_the_policy_stages(self):
        """策略阶段的**来源**必须落在共用闸门（或它的上游 `risk_gates`）。"""
        gate_src = _read("astra_backend/execution/venue_gate.py")
        risk_src = _read("astra_backend/execution/risk_gates.py")
        for s in GATE_STAGES:
            self.assertTrue(
                f'"{s}"' in gate_src or f'"{s}"' in risk_src,
                f"阶段 {s} 在共用闸门与 risk_gates 里都找不到 ⇒ 判据漂走了")
        # 闸门必须**调用**上游敞口判据的产物（而不是自己再写一遍）
        self.assertIn("exposure_fail", gate_src)
        self.assertIn("check_total_exposure", risk_src)

    def test_classification_is_not_vacuous(self):
        stages = (self._stage_literals("astra_backend/execution/venue_gate.py")
                  | self._stage_literals("astra_backend/execution/risk_gates.py"))
        self.assertTrue(stages, "一个拒单阶段都没扫到 ⇒ 本门与实现脱节")
        self.assertTrue(CLASSIFIED_STAGES & stages,
                        "已分类集合与实现产出的阶段完全不相交 ⇒ 分类表在自说自话")


# 本模块只做桩替换，绝不改任何真实配置/凭证。
def _direct_adapter(**kw):
    from tests.venue_gate_stub import direct_venue_gate_adapter
    return direct_venue_gate_adapter(**kw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
