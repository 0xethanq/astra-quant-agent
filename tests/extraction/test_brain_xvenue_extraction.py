"""B3（主脑侧第二块）`scripts/brain/xvenue.py` 的抽取回归。

## 这个测试在守什么

`ai_brain_trader.py` 原 L446-L676（231 行）的跨所采集链整段搬进
`scripts/brain/xvenue.py`。与 `packages.py` 那块不同，**这块原本就有测试覆盖**
（`tests/venues/test_xvenue_prompt.py` 15 例），所以真正的风险不是"没人知道它坏了"，
而是「**搬走时把测试缝一起搬没了**」—— 表现是既有测试静默变成空转或直接报错。

因此这里专门守**注入契约**：

1. `_XV_HEALTH` 状态必须仍住在门面，且**每次调用都是同一个 dict**
   （不是子模块里的副本）—— `tests/venues/test_xvenue_prompt.py:120` 直接断言
   `abt._XV_HEALTH`，若状态被搬进子模块，那条断言会开始"看一个永远为空的字典"。
2. `patch.object(abt, "_get_xvenue_adapter", …)` 必须仍能影响子模块内的取数。
3. `patch.object(abt, "VENUE_HEALTH_FILE", …)` 必须仍能改到落盘路径。
4. 门面壳必须真的在转发（实现体确实搬走了，不是留在原地又抄一份）。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.ai_brain_trader as abt
from scripts.brain import xvenue

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "ai_brain_trader.py"
SUBMODULE = ROOT / "scripts" / "brain" / "xvenue.py"

# 只在子模块里存在、门面不应再有的实现体特征行
_IMPL_ONLY_MARKERS = (
    '            "bin_last": xv.get("bin_last"), "bin_basis_pct": _basis(xv.get("bin_last")),',
    '                def _basis(v, _ref=okx_px):',
    '        okx_ok = [p["name"] for p in packages if safe_float(p.get("price", 0)) > 0]',
)


class ImplementationActuallyMovedTest(unittest.TestCase):
    def test_impl_bodies_live_in_submodule_not_facade(self):
        facade = FACADE.read_text(encoding="utf-8")
        sub = SUBMODULE.read_text(encoding="utf-8")
        for marker in _IMPL_ONLY_MARKERS:
            self.assertIn(marker, sub, f"实现体未搬入子模块: {marker!r}")
            self.assertNotIn(marker, facade, f"门面仍留有实现体（应只剩薄壳）: {marker!r}")

    def test_facade_shells_delegate(self):
        facade = FACADE.read_text(encoding="utf-8")
        for shell in ("_xv_record_impl(", "_xv_flush_health_impl(", "_xv_binance_snapshot_impl(",
                      "_xv_gate_snapshot_impl(", "_fetch_cross_venue_matrix_impl(",
                      "_xv_divergence_notes_impl(", "_xvenue_prompt_line_impl(",
                      "_xvenue_enabled_impl()"):
            self.assertIn(shell, facade, f"门面壳缺少转发 {shell}")

    def test_submodule_does_not_own_health_state(self):
        """`_XV_HEALTH` 的声明必须留在门面 —— 搬进子模块会让既有断言看空字典。"""
        sub = SUBMODULE.read_text(encoding="utf-8")
        self.assertNotIn("_XV_HEALTH: ", sub, "状态不得在子模块里另起一份")
        self.assertNotIn("_XV_HEALTH.setdefault", sub)
        facade = FACADE.read_text(encoding="utf-8")
        self.assertIn("_XV_HEALTH: Dict[str, Dict[str, Any]] = {}", facade)


class InjectionContractTest(unittest.TestCase):
    """三处既定测试缝在搬运后必须仍然生效。"""

    def test_health_state_is_the_facade_dict(self):
        before = dict(abt._XV_HEALTH)
        self.addCleanup(lambda: (abt._XV_HEALTH.clear(), abt._XV_HEALTH.update(before)))
        abt._xv_record("unittest-venue", "ZZZ", False, 0.0, "boom")
        self.assertIn("unittest-venue", abt._XV_HEALTH, "记录没有写进门面的 _XV_HEALTH")
        self.assertIn("ZZZ", abt._XV_HEALTH["unittest-venue"]["failed"])

    def test_flush_reads_the_records_written_by_record(self):
        """跨函数状态贯通：`_xv_record` 写的必须被 `_xv_flush_health` 读到。

        这条守的是"门面把**同一个**状态对象传给了两个壳"。若只把 `_xv_record`
        的 health 传对、而 `_xv_flush_health` 传了别的对象，单个函数的断言照样绿
        —— 只有跨函数对拍才抓得到。
        """
        before = dict(abt._XV_HEALTH)
        self.addCleanup(lambda: (abt._XV_HEALTH.clear(), abt._XV_HEALTH.update(before)))
        abt._xv_record("unittest-venue", "ZZZ", False, 0.0, "boom")
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "vh.json")
            with patch.object(abt, "VENUE_HEALTH_FILE", f):
                abt._xv_flush_health([{"name": "ZZZ", "price": 100.0}])
            doc = json.loads(Path(f).read_text(encoding="utf-8"))
        self.assertIn("unittest-venue", doc["venues"],
                      "落盘结果里没有 _xv_record 刚写的 venue —— 两个壳没共享同一份状态")
        self.assertIn("ZZZ", doc["venues"]["unittest-venue"]["failed"])

    def test_patched_adapter_is_observed_by_submodule(self):
        """`patch.object(abt, "_get_xvenue_adapter", …)` 必须仍能拦下真实取数。"""
        calls = []

        class FakeAd:
            def fetch_ticker(self, base):
                calls.append(base)
                return {"last": 123.0}

            def fetch_top_trader_ratio(self, base):
                return 1.5

            def fetch_funding_rate(self, base):
                return 0.0001

        before = dict(abt._XV_HEALTH)
        self.addCleanup(lambda: (abt._XV_HEALTH.clear(), abt._XV_HEALTH.update(before)))
        with patch.object(abt, "_get_xvenue_adapter", lambda v: FakeAd()):
            got = abt._xv_binance_snapshot("ZZZ")
        self.assertEqual(calls, ["ZZZ"], "补丁后的适配器没有被调用")
        self.assertIsNotNone(got)
        self.assertEqual(got["last"], 123.0)

    def test_patched_health_file_is_observed(self):
        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "vh.json")
            with patch.object(abt, "VENUE_HEALTH_FILE", f):
                abt._xv_flush_health([{"name": "BTC", "price": 100.0}])
            self.assertTrue(os.path.exists(f), "VENUE_HEALTH_FILE 补丁未生效（落到了真实路径）")

    def test_matrix_is_fail_soft_with_exploding_adapter(self):
        def boom(_venue):
            raise RuntimeError("offline")

        before = dict(abt._XV_HEALTH)
        self.addCleanup(lambda: (abt._XV_HEALTH.clear(), abt._XV_HEALTH.update(before)))
        # ⚠️ 第七十七刀：矩阵收尾必调 `_xv_flush_health`（fail-soft 也 flush），
        # 原先只 patch 适配器 → 本次"失败健康"被**写进生产 venue_health.json**
        # （离线守护实测 1 次；同文件上方用例自己就示范了正确 patch）。
        with tempfile.TemporaryDirectory() as td, \
                patch.object(abt, "_get_xvenue_adapter", boom), \
                patch.object(abt, "VENUE_HEALTH_FILE",
                             os.path.join(td, "vh.json")):
            abt.fetch_cross_venue_matrix([{"name": "BTC", "price": 100.0}])  # 不得抛

    def test_xvenue_disabled_short_circuits(self):
        with patch.dict(os.environ, {"ASTRA_XVENUE_PROMPT": "0"}):
            self.assertFalse(abt._xvenue_enabled())


class SubmodulePureFunctionTest(unittest.TestCase):
    """子模块可直接单测（不依赖门面），确认搬过来的是自洽的一坨。"""

    def test_divergence_notes_detects_conflict(self):
        # 一所以主导、另一所以空主导 → 必须标注（US-003 阈值语义）
        self.assertIn("大户比分歧", xvenue._xv_divergence_notes({"bin_ls": 2.13, "gate_ls": 0.81}))
        self.assertEqual(xvenue._xv_divergence_notes({"bin_ls": 1.5, "gate_ls": 1.5}), "")

    def test_prompt_line_needs_prices(self):
        f = lambda v, d=0.0: float(v or d)  # noqa: E731  注入版 safe_float
        self.assertEqual(xvenue._xvenue_prompt_line({"name": "X", "price": 0}, safe_float=f), "")
        self.assertEqual(xvenue._xvenue_prompt_line({"name": "X", "price": 100.0}, safe_float=f), "")
        line = xvenue._xvenue_prompt_line(
            {"name": "X", "price": 100.0, "xvenue": {"bin_last": 100.5}}, safe_float=f)
        self.assertIn("跨所比对", line)
        self.assertIn("基差+0.500%", line)


if __name__ == "__main__":
    unittest.main()
