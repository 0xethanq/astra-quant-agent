"""同向敞口闸门的**语义门**（单所口径；第一百一十一刀 + 多所拆除后收口）。

## 这个门在守什么

`astra_backend/execution/risk_gates.py::check_total_exposure` 是"**拒**不是夹"的
入场闸门：同向名义额合计（含本单）超上限 ⇒ 拒开。它只在 `total_exposure_cap > 0`
时才去读持仓（`cap=0` ⇒ 彻底短路，零网络）。

历史（真事故）：它的 `positions_reader` 曾一直只读**被下单的那一个场所**，
而文档写的是"跨所**同向名义额合计**" ⇒ 合计上限最多被突破到 N 倍。
本系统已收口为 **OKX 专用**，"跨所"的统计集合自然退化为 1 所；
但**判据本身没有退化** —— 本门钉的就是这些不变量：

1. 同向（同标的、同方向）持仓的名义额必须计入，并与本单名义额相加后再比上限；
2. 别币、反向持仓**不计入**；
3. `cap<=0` ⇒ 不得产生任何持仓读取（会白增网络调用与失败面）；
4. 读不到持仓 ⇒ **fail-closed**（拒开），绝不把"读不到"渲染成"没有敞口"；
5. 拒单载荷必须点明**敞口的场所归属**（诚实口径）。

⚠️ 另一半（"这条判据必须真的挂在 OKX 的下单路径上"）由
`tests/audit/test_three_venue_gate_parity.py` 的直签路径回归钉住。
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from astra_backend.execution.risk_gates import check_total_exposure  # noqa: E402


def _fail(stage, detail, venue="okx", **extra):
    return {"stage": stage, "detail": detail, "venue": venue, **extra}


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class SameSideExposureSumTest(unittest.TestCase):
    def _run(self, rows, *, cap=3000.0, action="SELL_SHORT", margin=300.0, leverage=5.0):
        return check_total_exposure(
            venue="okx", asset="BTC", action=action, margin=margin, leverage=leverage,
            total_exposure_cap=cap, all_positions=rows,
            positions_reader=lambda: rows, fail_factory=_fail)

    def test_same_side_exposure_is_summed_with_the_new_order(self):
        """已持同向 2000U + 本单 1500U ⇒ 3500U > 3000U ⇒ **拒**开（不是夹）。"""
        rows = [{"base": "BTC", "side": "short", "size_signed": -1.0,
                 "mark_price": 2000.0, "venue": "okx"}]
        r = self._run(rows)
        self.assertIsNotNone(r, "同向敞口必须计入合计")
        self.assertEqual(r["stage"], "exposure")
        self.assertEqual(r["contributing_venues"], ["okx"],
                         "拒开理由必须说清同向敞口来自哪个场所")
        self.assertIn("okx", r["detail"])

    def test_under_the_cap_is_allowed(self):
        rows = [{"base": "BTC", "side": "short", "size_signed": -1.0,
                 "mark_price": 100.0, "venue": "okx"}]
        # 同向 100U + 本单 300*5=1500U ⇒ 1600U < 3000U ⇒ 放行（防空转）
        self.assertIsNone(self._run(rows), "未超上限必须放行")
        self.assertIsNone(self._run(rows, margin=1.0, leverage=5.0),
                          "同向 100U + 本单 5U ⇒ 未超上限，必须放行")

    def test_other_asset_and_opposite_side_are_not_counted(self):
        rows = [{"base": "ETH", "side": "short", "size_signed": -10.0, "mark_price": 5000.0,
                 "venue": "okx"},
                {"base": "BTC", "side": "long", "size_signed": 10.0, "mark_price": 5000.0,
                 "venue": "okx"}]
        self.assertIsNone(self._run(rows, margin=0.0, leverage=0.0),
                          "别币/反向都不该计入同向敞口")

    def test_disabled_cap_never_reads_positions(self):
        """闸门停用（cap=0）时**不得**产生任何取数（代价边界）。"""
        def _boom():
            raise AssertionError("cap=0 时不该读持仓（会白增网络调用与失败面）")
        self.assertIsNone(check_total_exposure(
            venue="okx", asset="BTC", action="SELL_SHORT", margin=1.0, leverage=1.0,
            total_exposure_cap=0.0, all_positions=None, positions_reader=_boom,
            fail_factory=_fail))

    def test_read_failure_is_fail_closed(self):
        r = check_total_exposure(
            venue="okx", asset="BTC", action="SELL_SHORT", margin=1.0, leverage=1.0,
            total_exposure_cap=3000.0, all_positions=None,
            positions_reader=lambda: (_ for _ in ()).throw(RuntimeError("读不到持仓")),
            fail_factory=_fail)
        self.assertIsNotNone(r, "读不到持仓必须 fail-closed")
        self.assertEqual(r["stage"], "exposure")
        self.assertIn("无法读取持仓", r["detail"])


class ScopeIsSingleVenueTest(unittest.TestCase):
    """OKX 专用化后，敞口取数**不得**再去枚举其它场所。"""

    def test_the_live_gate_reads_only_the_entering_venue_adapter(self):
        """`order_submit` 的入场闸门只能从**本次场所的适配器**取持仓。

        多所执行面仍在时，`execution_router.collect_cross_venue_positions` 会遍历
        `registered_venues()` 逐所取数。收口为 OKX 专用后这条枚举路径必须消失 ——
        否则就是在为已移除的场所保留取数分支（且会真的去实例化/出网）。
        """
        src = _read("scripts/trader/order_submit.py")
        gate_src = src.split("def _shared_venue_entry_gate", 1)[1]
        self.assertNotIn("registered_venues", gate_src,
                         "入场闸门仍在按注册表枚举场所 ⇒ 多所取数分支没删干净")
        self.assertNotIn("collect_cross_venue_positions", gate_src,
                         "入场闸门仍在调用跨所持仓收集器（该模块已随多所执行面移除）")
        self.assertIn("check_total_exposure", gate_src,
                      "入场闸门必须仍然真的调用敞口判据（否则闸门形同虚设）")

    def test_no_multi_venue_execution_module_survives(self):
        for rel in ("astra_backend/execution_router.py", "astra_backend/venue_router.py",
                    "astra_backend/venue_routing/__init__.py"):
            self.assertFalse((ROOT / rel).exists(),
                             f"{rel} 应该已被移除（本系统 OKX 专用）")


class ProductionEnvGuardTest(unittest.TestCase):
    """诚实版护栏：**直接读 `.env`**，而不是读被 pytest 隔离过的 `os.environ`。"""

    def test_env_cap_and_gate_wiring_are_consistent(self):
        env_file = ROOT / ".env"
        if not env_file.exists():
            self.skipTest("无 .env（干净检出）")
        cap = None
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ASTRA_MAX_TOTAL_EXPOSURE_USDT="):
                try:
                    cap = float(line.split("=", 1)[1].strip().strip('"').strip("'"))
                except ValueError:
                    cap = None
        if cap in (None, 0.0):
            self.skipTest("生产未启用敞口上限 → 本闸门停用")
        # 生产**已启用**上限 ⇒ 必须确认闸门真的挂在 OKX 的下单路径上，否则上限形同虚设。
        src = _read("scripts/trader/order_submit.py")
        self.assertIn("check_total_exposure", src,
                      f"生产 .env 已配置 ASTRA_MAX_TOTAL_EXPOSURE_USDT={cap} —— "
                      "敞口闸门处于**生效**状态，必须挂在真实下单路径上")
        self.assertIn("exposure", src, "拒单阶段名必须是 exposure（供上层台账归因）")


if __name__ == "__main__":
    unittest.main()
