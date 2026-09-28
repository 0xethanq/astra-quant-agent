"""OKX 直签边界从**保证金**换算张数（2026-09-28 用户拍板「交易全改成保证金和杠杆」）。

## 这个测试守什么

**旧路径（缺陷）**：调用方按【保证金闸门夹取**之前**】的张数发单，而闸门结果
`venue_ctx["margin_usdt"]` 只被多所路径消费 ⇒ **同一把闸门对 OKX 形同虚设**：
AI 计划额 / 权益占比 / 单标的封顶任一小于"张数隐含额"时，币安与 Gate 按更小的
保证金下单，**OKX 却仍按夹取前的大张数下单**。

**新路径**：OKX 也在场所边界从钱反推张数 —— 三所共用同一条规则
「意图是钱，原生数量只在场所边界出现一次」。

## 本门用网格对拍钉住两件事

1. **闸门未夹取时量级不变**：浮点往返可能让张数少**一个最小步长**（只会向下，
   见下面 `NoClampIsBitIdenticalTest` 的说明），绝不放大 ⇒ 正常情况下的下单量
   实质不变；
2. **闸门夹取时只会更小、绝不放大**，且换算后的名义额与夹取后的保证金一致。

第 3 组用例直接扫源码，防止有人把边界换算删掉而门不自知。
"""

from __future__ import annotations

import random
import unittest
from pathlib import Path

from astra_backend.execution.sizing import quantize_size

ROOT = Path(__file__).resolve().parents[2]
ORDER_SUBMIT = ROOT / "scripts" / "trader" / "order_submit.py"
ORDER_INTENT = ROOT / "scripts" / "trader" / "order_intent.py"

#: 真实池子口径（`scripts/instrument_pool.py`）
SPECS = (
    ("BTC", 0.01, 0.01),
    ("ETH", 0.1, 0.01),
    ("SOL", 1.0, 0.01),
    ("XRP", 100.0, 0.01),
    ("DOGE", 1000.0, 0.01),
    ("ARB", 10.0, 0.1),
    ("SUI", 1.0, 1.0),
)


def _size_implied_margin(sz: float, ct_val: float, px: float, lever: float) -> float:
    """张数隐含的保证金 —— 与 `gates.order_margin_gate` 同式。"""
    return sz * ct_val * px / lever


def _gate(planned_margin: float, sz: float, ct_val: float, px: float, lever: float,
          *, equity_cap: float = 0.0, single_cap: float = 0.0) -> float:
    """`order_margin_gate` 的等价式：min(AI计划额, 张数隐含额, 权益×占比, 单标的封顶)。"""
    caps = [planned_margin, _size_implied_margin(sz, ct_val, px, lever)]
    caps += [c for c in (equity_cap, single_cap) if c and c > 0]
    return min(caps)


def _derived_size(margin: float, lever: float, ct_val: float, px: float,
                  step: float) -> float:
    """场所边界「保证金 → 原生张数」—— `order_submit` 的新式。"""
    return quantize_size(margin * lever / (ct_val * px), step or 1.0)


class NoClampIsBitIdenticalTest(unittest.TestCase):
    """闸门未夹取（正常情形）⇒ 新旧张数一致：**逐位相同，或最多少一个最小步长**。

    ⚠️ 为什么不是"绝对逐位相同"（如实记录，不粉饰）：
    「张 → 保证金 → 张」是一次浮点往返。`ctVal` 很小的标的（BTC 0.01）在同样的
    保证金下张数可达 ~2.9e7，`margin × 杠杆 ÷ (ctVal × px)` 的浮点误差量级
    ~3e-9 会刚好把 `raw/step` 压到整数边界下方，`quantize_size` 的 `+1e-9`
    吸收不掉 ⇒ 向下少**一个最小步长**。

    方向是**永远向下**（本文件 `ClampOnlyShrinksTest` 用 2000 组随机网格钉住"绝不放大"），
    所以这个偏差只会**少下单、不会超买** —— 可接受，且与 `quote_qty_to_native`
    的既有取整方向一致（第一百五十三刀：一律向下取整，换算出的名义永不超出目标）。
    """

    def test_grid_equivalence_when_the_gate_does_not_bind(self):
        checked = 0
        for _name, ct_val, step in SPECS:
            for px in (0.0950, 1.5004, 9.605, 0.2237, 79000.0, 103.55):
                for lever in (2, 3, 5, 6, 8, 10, 12):
                    for planned_margin in (12.0, 50.0, 120.0, 420.0, 900.0):
                        # 构造「张数隐含额 <= AI 计划额」⇒ 闸门不会夹取
                        raw_sz = quantize_size(
                            planned_margin * lever / (ct_val * px) * 0.8, step)
                        if raw_sz <= 0:
                            continue
                        clamp_margin = _gate(planned_margin, raw_sz, ct_val, px, lever)
                        if clamp_margin < _size_implied_margin(raw_sz, ct_val, px, lever):
                            continue        # 夹取了，交给下一组用例
                        got = _derived_size(clamp_margin, lever, ct_val, px, step)
                        self.assertLessEqual(
                            got, raw_sz,
                            f"未夹取却放大了: {_name} ctVal={ct_val} px={px} "
                            f"lever={lever} planned={planned_margin} "
                            f"旧={raw_sz} 新={got}")
                        self.assertLessEqual(
                            raw_sz - got, step + 1e-9,
                            f"未夹取却偏差超过一个步长: {_name} 旧={raw_sz} 新={got}")
                        checked += 1
        self.assertGreater(checked, 200, "网格覆盖太窄 ⇒ 本门失去意义")

    def test_the_drift_is_almost_always_zero(self):
        """绝大多数情形**逐位相同**；偏差只出现在张数极大的极端标的。"""
        same = diff = 0
        for _name, ct_val, step in SPECS:
            for px in (1.5004, 9.605, 103.55):
                for lever in (3, 6, 12):
                    for planned_margin in (50.0, 420.0):
                        raw_sz = quantize_size(planned_margin * lever / (ct_val * px) * 0.8, step)
                        if raw_sz <= 0:
                            continue
                        margin = _gate(planned_margin, raw_sz, ct_val, px, lever)
                        if margin < _size_implied_margin(raw_sz, ct_val, px, lever):
                            continue
                        if _derived_size(margin, lever, ct_val, px, step) == raw_sz:
                            same += 1
                        else:
                            diff += 1
        self.assertGreater(same, 0)
        self.assertGreater(same / (same + diff), 0.5,
                           f"逐位相同占比过低（{same}/{same + diff}）⇒ 往返精度有问题")

    def test_randomised_equivalence(self):
        rnd = random.Random(20260928)
        checked = 0
        for _ in range(3000):
            _name, ct_val, step = rnd.choice(SPECS)
            px = rnd.uniform(0.05, 90000)
            lever = rnd.choice([1, 2, 3, 5, 6, 8, 10, 12, 20])
            planned = rnd.uniform(5, 2000)
            raw_sz = quantize_size(planned * lever / (ct_val * px) * rnd.uniform(0.5, 1.0), step)
            if raw_sz <= 0:
                continue
            margin = _gate(planned, raw_sz, ct_val, px, lever)
            if margin < _size_implied_margin(raw_sz, ct_val, px, lever):
                continue
            got = _derived_size(margin, lever, ct_val, px, step)
            self.assertLessEqual(got, raw_sz, "未夹取却放大")
            self.assertLessEqual(raw_sz - got, step + 1e-9, "未夹取却偏差超一个步长")
            checked += 1
        self.assertGreater(checked, 500, "随机覆盖太窄")


class ClampOnlyShrinksTest(unittest.TestCase):
    """闸门夹取时**只会更小**（绝不放大），且名义额与夹取后的保证金一致。"""

    def test_a_binding_cap_shrinks_okx_too(self):
        ct_val, step, px, lever = 100.0, 0.01, 1.5004, 6
        # AI 计划 420U、张数隐含 671.9U；权益占比顶压到 49.9U ⇒ 闸门夹取
        raw_sz = quantize_size(420.0 * lever / (ct_val * px), step)
        self.assertGreater(raw_sz, 0)
        margin = _gate(420.0, raw_sz, ct_val, px, lever, equity_cap=49.9)
        self.assertAlmostEqual(margin, 49.9, places=4, msg="闸门应被权益顶夹住")

        new_sz = _derived_size(margin, lever, ct_val, px, step)
        self.assertLess(new_sz, raw_sz,
                        "闸门夹取后 OKX 仍按夹取前的张数下单 ⇒ 本修法失效")
        # 换算后的名义额 ≈ 夹取后的保证金 × 杠杆（允许一个步长的向下取整）
        notional = new_sz * ct_val * px
        self.assertLessEqual(notional, margin * lever + 1e-6)
        self.assertGreater(notional, margin * lever - step * ct_val * px - 1e-6)

    def test_every_binding_cap_shrinks_okx_too(self):
        """三把**独立**上限各自压住时，OKX 都必须跟着缩小。

        （「张数隐含额」不作此列：它就是上界参照本身，等于它即"未夹取"，
        由 `NoClampIsBitIdenticalTest` 覆盖。）
        """
        ct_val, step, px, lever = 1.0, 0.01, 103.55, 5
        raw_sz = quantize_size(200.0 * lever / (ct_val * px), step)
        cases = {
            "AI 计划额": (40.0, 0.0, 0.0),
            "权益占比": (500.0, 80.0, 0.0),
            "单标的封顶": (500.0, 0.0, 30.0),
        }
        for label, (planned, equity_cap, single_cap) in cases.items():
            with self.subTest(cap=label):
                margin = _gate(planned, raw_sz, ct_val, px, lever,
                               equity_cap=equity_cap, single_cap=single_cap)
                self.assertLess(margin, _size_implied_margin(raw_sz, ct_val, px, lever),
                                f"{label} 本应夹住却没夹住 ⇒ 用例失去意义")
                got = _derived_size(margin, lever, ct_val, px, step)
                self.assertLessEqual(got, raw_sz, f"{label} 夹取后反而放大了仓位")
                self.assertLess(got, raw_sz, f"{label} 夹取后 OKX 未跟着缩小 ⇒ 本修法失效")

    def test_never_larger_over_a_random_grid(self):
        rnd = random.Random(7)
        for _ in range(2000):
            _name, ct_val, step = rnd.choice(SPECS)
            px = rnd.uniform(0.05, 90000)
            lever = rnd.choice([1, 2, 3, 5, 6, 8, 10, 12, 20])
            planned = rnd.uniform(5, 2000)
            raw_sz = quantize_size(planned * lever / (ct_val * px), step)
            if raw_sz <= 0:
                continue
            margin = _gate(planned, raw_sz, ct_val, px, lever,
                           equity_cap=rnd.uniform(0, 1500),
                           single_cap=rnd.choice([0.0, 50.0, 600.0]))
            got = _derived_size(margin, lever, ct_val, px, step)
            self.assertLessEqual(got, raw_sz,
                                 f"{_name} 网格放大: 旧={raw_sz} 新={got}")


class SourceContractTest(unittest.TestCase):
    """源码契约：边界换算必须真的在 `order_submit` 里，且算不出就拒单。"""

    def _src(self) -> str:
        return ORDER_SUBMIT.read_text(encoding="utf-8")

    def test_the_okx_boundary_derives_size_from_margin(self):
        src = self._src()
        self.assertIn('"margin_usdt"', src)
        self.assertIn("quantize_size(", src,
                      "OKX 边界不见了「钱 → 张」换算 ⇒ 闸门又对 OKX 失效")
        self.assertIn("_okx_size_from_margin", src)

    def test_it_fails_closed_when_the_derived_size_is_below_the_minimum(self):
        src = self._src()
        self.assertIn("低于交易所最小下单量", src,
                      "换算出的张数 <= 0 时必须拒单，不能带着 0 张去发单")
        self.assertIn("return False", src)

    def test_intent_carries_the_money_not_the_contract_count(self):
        src = ORDER_INTENT.read_text(encoding="utf-8")
        self.assertIn('"margin_usdt": margin_usdt', src)
        self.assertIn('"ct_val": ct_val', src)
        self.assertIn('"min_sz": min_sz', src)
        # 名义额必须是钱（保证金 × 杠杆），不得再张数乘面值
        self.assertIn('float(margin_usdt or 0.0) * float(ai_lever or 0.0)', src)
        self.assertNotIn("actual_sz * ct_val * limit_px", src,
                         "名义额又由张数反推 ⇒ 闸门夹取时账实不符")


if __name__ == "__main__":
    unittest.main(verbosity=2)
