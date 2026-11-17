"""`scripts/trader/position_universe.py`（B3 第三十一刀）回归。

## 这个测试在守什么

`collect_okx_position_payloads` 决定**送给 AI 的"持仓全景"长什么样**。
AI 看到的持仓与真实持仓不一致，就会基于不存在的仓位做决策 ——
这类错误**不会报错**，只会让模型持续误判。

## ⚠️ OKX 专用化（2026-09 多所执行面整体下架）

`merge_cross_venue_positions`（跨所持仓汇入）已随外所适配器 / 场所路由 / 跨所接管
一并删除 —— 本系统只在 OKX 上持仓，"持仓全景"不再合成外所记录。
因此本文件只保留 OKX 侧的装配契约；`venue` 字段的 `setdefault` 语义仍然保留：
历史遗留（含已下架场所）的 `venue` 值必须**原样透传**，不得被覆盖或报错。

## 易错点（详见模块文档串）

| # | 细节 | 错了会怎样 |
|---|---|---|
| 1 | OKX 侧 `venue` 用 **`setdefault`** | 无条件覆盖会抹掉因子快照里已有的真实场所 |
| 2 | 追踪器键 `f"{instId}_{position.get('side','')}"` | 键拼错 → 静默拿不到追踪器 → 止损/水位全 `None` → 提示词显示"无止损线" |

## 为什么必须覆盖"追踪器缺失"

第 2 条是**静默失效**：键拼错时 `trackers.get(...)` 不抛错，只返回 `{}`，
于是 `trailingStopPx` 等字段变成 `None` —— 模型看到的持仓"没有止损线"。
断言必须**直接检查这些字段的值**，而不是"函数跑通了"。
"""

from __future__ import annotations

import ast
import copy
import random
import unittest
from pathlib import Path

from scripts.trader.position_universe import (
    collect_okx_position_payloads,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "scripts" / "trader" / "position_universe.py"
FACADE = ROOT / "scripts" / "ai_factor_trader.py"


# ------------------------------------------------------------ legacy 实现


def _legacy_collect(all_factors, trackers):
    active_pos_list = []
    for f in all_factors:
        position = f.get("position")
        if not position:
            continue
        position_payload = dict(position)
        position_payload.setdefault("venue", "okx")
        tracker = trackers.get(f"{f['instId']}_{position.get('side', '')}", {})
        position_payload["trailingStopPx"] = tracker.get("trailingStopPx")
        position_payload["highWaterMark"] = tracker.get("highWaterMark")
        position_payload["lowWaterMark"] = tracker.get("lowWaterMark")
        position_payload["takeProfitPx"] = tracker.get("takeProfitPx")
        position_payload["stage_desc"] = tracker.get("stage_desc", "")
        position_payload["atr"] = f.get("atr", 0.0)
        active_pos_list.append(position_payload)
    return active_pos_list


# ------------------------------------------------------------ OKX 侧


class CollectOkxTest(unittest.TestCase):
    def _f(self, **over):
        """⚠️ helper 我第一版写错了：`dict.update(over)` 后又 `f.update(f)`，
        后者是 no-op —— 于是 `over` **根本没生效**（我传 `instId=...` 被静默忽略，
        报错的却是 legacy 那侧）。现在正确合并 `over`。"""
        f = {"instId": "BTC-USDT-SWAP", "name": "BTC", "atr": 123.4,
             "position": {"side": "long", "pos": "1", "avgPx": "100"}}
        f.update(over)
        return f

    def test_no_position_is_skipped(self):
        out = collect_okx_position_payloads([{"instId": "X"}, {"instId": "Y", "position": None}], {})
        self.assertEqual(out, [])

    def test_empty_position_dict_is_skipped(self):
        """`{}` 是假值 —— 与 `None` 一样跳过。"""
        out = collect_okx_position_payloads([{"instId": "X", "position": {}}], {})
        self.assertEqual(out, [])

    def test_venue_defaults_to_okx(self):
        out = collect_okx_position_payloads([self._f()], {})
        self.assertEqual(out[0]["venue"], "okx")

    def test_existing_venue_is_respected(self):
        """**核心**：`setdefault` 不是无条件赋值。

        快照里已有的 `venue` 必须**逐字保留** —— 包括历史遗留的、现已下架的
        场所名（只读容错：既不改写也不报错）。
        """
        out = collect_okx_position_payloads([self._f(position={"side": "long", "venue": "gate"})], {})
        self.assertEqual(out[0]["venue"], "gate",
                         "因子快照已有的 venue 必须保留")
        out2 = collect_okx_position_payloads([self._f(position={"side": "long", "venue": "okx"})], {})
        self.assertEqual(out2[0]["venue"], "okx")

    def test_tracker_lookup_key_is_instid_underscore_side(self):
        trackers = {"BTC-USDT-SWAP_long": {"trailingStopPx": "95",
                                           "highWaterMark": "150",
                                           "lowWaterMark": "90",
                                           "takeProfitPx": "130",
                                           "stage_desc": "移动止盈中"}}
        out = collect_okx_position_payloads([self._f()], trackers)
        p = out[0]
        self.assertEqual(p["trailingStopPx"], "95")
        self.assertEqual(p["highWaterMark"], "150")
        self.assertEqual(p["lowWaterMark"], "90")
        self.assertEqual(p["takeProfitPx"], "130")
        self.assertEqual(p["stage_desc"], "移动止盈中")

    def test_wrong_key_shape_yields_none_fields(self):
        """键形态不对（如用 `instId` 而不是 `instId_side`）→ 字段全 None。

        这条把"键拼错就静默失效"的症状钉住：**不抛错，只是字段变 None**。
        """
        trackers = {"BTC-USDT-SWAP": {"trailingStopPx": "95"}}
        out = collect_okx_position_payloads([self._f()], trackers)
        self.assertIsNone(out[0]["trailingStopPx"], "键不含 _side 时取不到")
        self.assertEqual(out[0]["stage_desc"], "")
        self.assertIsNone(out[0]["highWaterMark"])

    def test_missing_tracker_gives_none_but_empty_stage_desc(self):
        out = collect_okx_position_payloads([self._f()], {})
        p = out[0]
        self.assertIsNone(p["trailingStopPx"])
        self.assertIsNone(p["highWaterMark"])
        self.assertIsNone(p["lowWaterMark"])
        self.assertIsNone(p["takeProfitPx"])
        self.assertEqual(p["stage_desc"], "", "stage_desc 默认是空串而不是 None")

    def test_side_used_verbatim_in_key(self):
        """`side` 不做规范化 —— 大写 `LONG` 的键必须是 `..._LONG`。"""
        trackers = {"BTC-USDT-SWAP_LONG": {"trailingStopPx": "77"}}
        out = collect_okx_position_payloads(
            [self._f(position={"side": "LONG"})], trackers)
        self.assertEqual(out[0]["trailingStopPx"], "77")

    def test_side_absent_yields_trailing_underscore(self):
        trackers = {"BTC-USDT-SWAP_": {"trailingStopPx": "88"}}
        out = collect_okx_position_payloads(
            [self._f(position={"pos": "1"})], trackers)
        self.assertEqual(out[0]["trailingStopPx"], "88", "缺 side → 键以 _ 结尾")

    def test_atr_from_factor_level(self):
        out = collect_okx_position_payloads([self._f(atr=9.9)], {})
        self.assertEqual(out[0]["atr"], 9.9)

    def test_atr_default_zero(self):
        out = collect_okx_position_payloads([self._f(atr=None)], {})
        self.assertIsNone(out[0]["atr"], "显式 None 保留 None（get 只在缺键时用默认）")

    def test_atr_missing_key_gives_zero(self):
        f = self._f()
        del f["atr"]
        out = collect_okx_position_payloads([f], {})
        self.assertEqual(out[0]["atr"], 0.0)

    def test_position_dict_is_copied_not_aliased(self):
        src = {"side": "long", "pos": "1"}
        out = collect_okx_position_payloads([self._f(position=src)], {})
        out[0]["injected"] = True
        self.assertNotIn("injected", src, "不得改到原 position dict")

    def test_multiple_positions_order_preserved(self):
        """顺序必须与 `all_factors` 一致。

        ⚠️ 注意 `instId` **不在**载荷里 —— 载荷是 `dict(position)` 加若干追踪器字段，
        而 `instId` 在**因子项**那一层。我第一版断言 `p["instId"]` → KeyError。
        这里改用一个真正被搬进来的字段（`atr`）来验顺序。
        """
        fs = [{"instId": "A-USDT-SWAP", "name": "A", "atr": 1.0,
               "position": {"side": "long"}},
              {"instId": "B-USDT-SWAP", "name": "B", "atr": 2.0,
               "position": {"side": "short"}}]
        out = collect_okx_position_payloads(fs, {})
        self.assertEqual([p["atr"] for p in out], [1.0, 2.0])
        self.assertEqual([p["side"] for p in out], ["long", "short"])
        self.assertNotIn("instId", out[0],
                         "既有行为：载荷不含 instId（它在因子项层）")

    def test_payload_does_not_carry_instid(self):
        """钉住上面那条既有行为，防止后人"顺手"补上 instId 而改变载荷形状。"""
        out = collect_okx_position_payloads([self._f()], {})
        self.assertNotIn("instId", out[0])
        self.assertIn("side", out[0])

    def test_empty_input(self):
        self.assertEqual(collect_okx_position_payloads([], {}), [])


class RandomParityTest(unittest.TestCase):
    def test_collect_parity(self):
        rng = random.Random(31001)
        for i in range(12000):
            factors = []
            for _ in range(rng.randint(0, 3)):
                pos = rng.choice([None, {}, {"side": rng.choice(["long", "short", "LONG", ""]),
                                             "venue": rng.choice(["okx", "gate", None])},
                                  {"side": "long"}])
                f = {"instId": rng.choice(["B-USDT-SWAP", "E-USDT-SWAP"]),
                     "name": rng.choice(["BTC", "ETH"]),
                     "atr": rng.choice([1.5, None, "x"])}
                if pos is not None or rng.random() < 0.5:
                    f["position"] = pos
                factors.append(f)
            trackers = {}
            for f in factors:
                if isinstance(f.get("position"), dict):
                    trackers[rng.choice([f"{f['instId']}_long", f["instId"],
                                         f"{f['instId']}_"])] = rng.choice(
                        [{}, {"trailingStopPx": "9"}, {"stage_desc": "s"}])
            got = collect_okx_position_payloads(copy.deepcopy(factors), copy.deepcopy(trackers))
            want = _legacy_collect(copy.deepcopy(factors), copy.deepcopy(trackers))
            self.assertEqual(got, want, f"第{i}组分叉")


class WiringTest(unittest.TestCase):
    def test_impl_in_submodule_not_facade(self):
        facade_src = FACADE.read_text(encoding="utf-8")
        mod_src = MODULE.read_text(encoding="utf-8")
        self.assertIn("def collect_okx_position_payloads(", mod_src)
        self.assertNotIn("def collect_okx_position_payloads(", facade_src)

    def test_facade_calls_the_assembly(self):
        """装配调用必须在**主执行路径**上（第九十三刀后住 cycle_stages）。"""
        facade_src = FACADE.read_text(encoding="utf-8")
        stages_src = (ROOT / "scripts" / "trader" / "cycle_stages.py").read_text(encoding="utf-8")
        self.assertIn("_collect_okx_position_payloads(all_factors, trackers)", stages_src,
                      "持仓载荷装配的调用点应随相位 4 前段迁入 cycle_stages")
        # 门面仍须把实现注入阶段函数（调用期解析 ⇒ patch 面有效）
        self.assertIn("_collect_okx_position_payloads=_collect_okx_position_payloads", facade_src)
        self.assertIn("from scripts.trader.position_universe import (", facade_src)

    def test_facade_no_longer_contains_inline_bodies(self):
        facade_src = FACADE.read_text(encoding="utf-8")
        for gone in ("position_payload.setdefault",):
            self.assertNotIn(gone, facade_src, f"门面仍残留 {gone!r}")

    def test_module_has_no_io_imports(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        top = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top |= {a.asname or a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                top |= {a.asname or a.name for a in node.names}
        for forbidden in ("requests", "urllib", "okx_rest", "subprocess", "os"):
            self.assertNotIn(forbidden, top, f"纯装配模块不应 import {forbidden}")

    def test_module_level_has_no_side_effects(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        body = list(tree.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        for node in body:
            self.assertNotIsInstance(node, ast.Expr, f"模块级裸表达式 L{node.lineno}")


if __name__ == "__main__":
    unittest.main()
