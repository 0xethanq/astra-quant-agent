"""B3（交易员侧第十一块）`scripts/trader/gates.py` 的抽取回归。

## 这个测试在守什么

`order_margin_gate` / `equity_margin_cap` / `is_tradfi_market_liquid`（共 59 行）
从 `scripts/ai_factor_trader.py` 搬进 `scripts/trader/gates.py`。

`order_margin_gate` 是**真金白银的闸门** —— 审计 P0-1 记录过它的失效后果：
多所路径把 AI 原始 `margin_usdt` 直接透传，实盘出现 `margin=3011.1U`（≈权益 60%），
而配置硬顶是 20%（≈997U）、单标的绝对封顶 600U。因此本文件重点守**口径**：

1. 四种约束各取 min，任一条都不能漏（`生效口径 = min(计划额, 张数隐含额, 权益×占比, 绝对封顶)`）；
2. **权益不可得（缺失≠0）时不臆造占比上限** —— 这条最容易被"顺手补个默认值"破坏；
3. 风控常量必须**调用期**从门面读取（`risk_constants` 的 .env 改参由门面重载刷新）；
4. 门面的**计数锚点**（`order_margin_gate(` 出现 3 次）不得被壳或注释破坏。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.ai_factor_trader as aft
from scripts.trader import gates

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "ai_factor_trader.py"
SUBMODULE = ROOT / "scripts" / "trader" / "gates.py"
ENTRY = ROOT / "scripts" / "trader" / "entry_execution.py"   # 第九十刀：开多/开空两支现住此

_IMPL_ONLY_MARKERS = (
    "OKX 下单保证金闸门",
    "Strict US Regular Trading Window",
)


class ImplementationMovedTest(unittest.TestCase):
    def test_impl_lives_in_submodule_not_facade(self):
        facade = FACADE.read_text(encoding="utf-8")
        sub = SUBMODULE.read_text(encoding="utf-8")
        for marker in _IMPL_ONLY_MARKERS:
            self.assertIn(marker, sub, f"实现体未搬入子模块: {marker!r}")
            self.assertNotIn(marker, facade, f"门面仍留有实现体: {marker!r}")

    def test_facade_shells_delegate_with_call_time_constants(self):
        facade = FACADE.read_text(encoding="utf-8")
        self.assertIn("_order_margin_gate_impl(", facade)
        self.assertIn("_equity_margin_cap_impl(", facade)
        self.assertIn("_is_tradfi_market_liquid_impl(", facade)
        self.assertIn("max_single_asset_margin=MAX_SINGLE_ASSET_MARGIN,", facade)
        self.assertIn("max_margin_equity_ratio=MAX_MARGIN_EQUITY_RATIO,", facade)

    def test_count_anchor_still_sees_definition_plus_two_call_sites(self):
        """计数锚点是"反漂移"设计：1 定义 + 开多 + 开空 = 3。

        本测试**复刻**那条锚点的口径，但把失败信息说得更清楚 —— 它一旦翻红，
        要么是壳被改成别名赋值，要么是有注释写出了带左括号的函数名（两种都发生过）。

        ⚠️ 第九十刀：开多/开空两支随入场循环搬入 `scripts/trader/entry_execution.py`
        ⇒ "1 定义 + 2 调用 = 3"的算术**原样保留**，只是分别定位（定义=门面壳、
        两处调用=入场执行模块），并加反证防"门面注释里写个带括号的函数名"虚 Hits。
        """
        facade = FACADE.read_text(encoding="utf-8")
        entry = ENTRY.read_text(encoding="utf-8")
        def_hits = [i + 1 for i, line in enumerate(facade.splitlines())
                    if "order_margin_gate(" in line]
        call_hits = [i + 1 for i, line in enumerate(entry.splitlines())
                     if "order_margin_gate(" in line]
        self.assertEqual(len(def_hits), 1,
                         f"门面应恰有 1 处（定义壳），实际在行 {def_hits}")
        self.assertEqual(len(call_hits), 2,
                         f"开多/开空应各调用一次（共 2），实际在行 {call_hits}")


def _outcome(fn, kw, sam, mer):
    """返回 ('ok', value) 或 ('raise', ExceptionTypeName) —— 让差分把异常也纳入比较。"""
    try:
        if fn.__name__ == "_legacy":
            return ("ok", fn(**kw, MAX_SINGLE_ASSET_MARGIN=sam, MAX_MARGIN_EQUITY_RATIO=mer))
        return ("ok", fn(**kw, max_single_asset_margin=sam, max_margin_equity_ratio=mer))
    except Exception as exc:  # noqa: BLE001 - 故意捕获以比较异常类型
        return ("raise", type(exc).__name__)


class OrderMarginGateParityTest(unittest.TestCase):
    """与搬走前的门面实现做差分对拍。"""

    @staticmethod
    def _legacy(planned_margin, *, size, price, ct_val, leverage, usdt_available,
                MAX_SINGLE_ASSET_MARGIN, MAX_MARGIN_EQUITY_RATIO):
        """搬走前门面里的实现（逐字原样，常量改为入参以便参数化）。"""
        lev = max(1.0, float(leverage or 1.0))
        try:
            size_implied = max(0.0, float(size) * float(ct_val) * float(price)) / lev
        except (TypeError, ValueError):
            size_implied = 0.0
        try:
            planned = max(0.0, float(planned_margin or 0.0))
        except (TypeError, ValueError):
            planned = 0.0
        caps = [c for c in (planned if planned > 0 else size_implied, size_implied,
                            float(MAX_SINGLE_ASSET_MARGIN or 0.0)) if c > 0]
        try:
            equity = float(usdt_available or 0.0)
        except (TypeError, ValueError):
            equity = 0.0
        if equity > 0:
            caps.append(equity * MAX_MARGIN_EQUITY_RATIO)
        return round(min(caps), 4) if caps else 0.0

    def test_random_parity(self):
        import random
        rng = random.Random(20260920)
        vals = [None, 0, 0.0, -1, 5, 100.0, 3011.1, 1e9, "12", "abc"]
        for _ in range(4000):
            kw = {k: rng.choice(vals) for k in
                  ("planned_margin", "size", "price", "ct_val", "leverage", "usdt_available")}
            sam = rng.choice([0.0, 600.0, 1234.5])
            mer = rng.choice([0.0, 0.2, 0.31])
            # 注意：`float(leverage or 1.0)` 在 leverage 为非数字字符串时**会抛**
            # ValueError（原始实现就是这样，不在 try 保护内）。差分测试必须把
            # "两边都抛"也算作一致，否则会把我自己的随机输入误报成回归。
            got = _outcome(gates.order_margin_gate, kw, sam, mer)
            exp = _outcome(self._legacy, kw, sam, mer)
            self.assertEqual(got, exp, f"分叉: {kw} sam={sam} mer={mer}")

    def test_equity_unavailable_does_not_invent_a_cap(self):
        """权益不可得（None/0）时**不得**臆造占比上限，但仍受绝对封顶约束。

        这是审计 P0-1 的核心口径：缺失 ≠ 0。
        """
        with patch.object(aft, "MAX_SINGLE_ASSET_MARGIN", 600.0), \
             patch.object(aft, "MAX_MARGIN_EQUITY_RATIO", 0.20):
            for unavailable in (None, 0, 0.0):
                got = aft.order_margin_gate(9999.0, size=0.0, price=0.0, ct_val=0.0,
                                            leverage=1.0, usdt_available=unavailable)
                self.assertEqual(got, 600.0,
                                 f"权益={unavailable!r} 时应收敛到绝对封顶，而非臆造 0 或占比额")

    def test_every_cap_is_applied(self):
        with patch.object(aft, "MAX_SINGLE_ASSET_MARGIN", 600.0), \
             patch.object(aft, "MAX_MARGIN_EQUITY_RATIO", 0.20):
            common = dict(price=10.0, ct_val=1.0, leverage=2.0, usdt_available=1000.0)
            # 权益占比 = 200 → 最小
            self.assertEqual(aft.order_margin_gate(9999.0, size=0.0, **common), 200.0)
            # 张数隐含额 = 30*1*10/2 = 150 → 最小
            self.assertEqual(aft.order_margin_gate(9999.0, size=30.0, **common), 150.0)
            # AI 计划额 = 80 → 最小
            self.assertEqual(aft.order_margin_gate(80.0, size=30.0, **common), 80.0)


class GateConstantsAreCallTimeTest(unittest.TestCase):
    def test_margin_cap_constants_are_read_at_call_time(self):
        with patch.object(aft, "MAX_MARGIN_EQUITY_RATIO", 0.50):
            self.assertEqual(aft.equity_margin_cap(1000.0), 500.0)
        with patch.object(aft, "MAX_SINGLE_ASSET_MARGIN", 777.0), \
             patch.object(aft, "MAX_MARGIN_EQUITY_RATIO", 0.0):
            self.assertEqual(
                aft.order_margin_gate(9999.0, size=0.0, price=0.0, ct_val=0.0,
                                      leverage=1.0, usdt_available=None),
                777.0, "绝对封顶未读到补丁值 → 常量被 import 期烘焙")

    def test_equity_margin_cap_zero_when_equity_unavailable(self):
        self.assertEqual(aft.equity_margin_cap(0.0), 0.0)
        self.assertEqual(aft.equity_margin_cap(None), 0.0)


class TradfiWindowTest(unittest.TestCase):
    def test_crypto_and_commodity_always_liquid(self):
        for asset in ("crypto", "commodity"):
            self.assertTrue(aft.is_tradfi_market_liquid(asset))

    def test_stock_follows_us_session_window(self):
        """直接对拍子模块实现（时间相关，用固定时刻）。"""
        import datetime as _dt

        def legacy(asset_type, now_bj):
            if asset_type in ["crypto", "commodity"]:
                return True
            weekday, hour, minute = now_bj.weekday(), now_bj.hour, now_bj.minute
            if weekday == 5 and hour >= 5:
                return False
            if weekday == 6:
                return False
            if weekday == 0 and (hour < 21 or (hour == 21 and minute < 30)):
                return False
            if (hour == 21 and minute >= 30) or (hour >= 22) or (hour < 4):
                return True
            return False

        # 2026-09-14 是周一；遍历一周内全部小时/半点
        base = _dt.datetime(2026, 9, 14, tzinfo=_dt.timezone(_dt.timedelta(hours=8)))
        for day in range(7):
            for hour in range(24):
                for minute in (0, 30):
                    now = base + _dt.timedelta(days=day, hours=hour, minutes=minute)
                    with patch.object(gates.datetime, "datetime",
                                      _FrozenDatetime(now)):
                        got = gates.is_tradfi_market_liquid("stock")
                    self.assertEqual(got, legacy("stock", now),
                                     f"分叉于 {now.isoformat()}")


class _FrozenDatetime:
    """让 `datetime.datetime.now(tz)` 返回固定时刻，其余属性透传真实类。"""

    def __init__(self, fixed):
        self._fixed = fixed

    def now(self, tz=None):
        return self._fixed.astimezone(tz) if tz else self._fixed

    def __getattr__(self, name):
        import datetime as _dt
        return getattr(_dt.datetime, name)


class FacadeShellShapeTest(unittest.TestCase):
    def test_shells_are_functions_not_aliases(self):
        """门面必须是 `def name(...)` 薄壳，不能是 `name = impl` 别名。

        别名会让计数锚点从 3 掉到 2，也会让 `inspect.getsource(trader.order_margin_gate)`
        取到子包实现 —— 破坏"门面单文件可审计"的既有约定。
        """
        facade = FACADE.read_text(encoding="utf-8")
        for name, impl in (("order_margin_gate", "_order_margin_gate_impl"),
                           ("equity_margin_cap", "_equity_margin_cap_impl"),
                           ("is_tradfi_market_liquid", "_is_tradfi_market_liquid_impl")):
            self.assertIsNotNone(
                re.search(rf"^def {name}\(", facade, re.M),
                f"{name} 必须是 def 薄壳（行首）")
            self.assertIsNone(re.search(rf"^{name}\s*=\s*{impl}", facade, re.M),
                              f"{name} 被写成了别名赋值")


if __name__ == "__main__":
    unittest.main()
