"""B3（交易员侧第十五块）`scripts/trader/order_intent.py` 的抽取回归。

## 这个测试在守什么

`execute_portfolio` 里开多/开空各有一段 `if allow_entry:` 下单块（约 27 / 24 行），
其中**三价定价**与**下单载荷装配**两段完全同构。本块把这两段抽成
`resolve_entry_prices` / `build_order_intent`。

## 为什么这两段特别值得抽

三价定价里方向差异只有两处（盘口取 `bidPx` / `askPx`，兜底取 `±`），载荷装配里
方向差异只有三处（`buy`/`sell`、`long`/`short`、`BUY_LONG`/`SELL_SHORT`）。
**差异小、代码长，正是"改了一边忘了另一边"最容易发生的地方**：
漏改盘口方向会让空单盯着买一价下单；漏改 `side` 会让策略对做空发 `buy` ——
后者不是"少赚"，是**反向开仓**。

## 三价定价的差分必须覆盖"AI 给了价"与"AI 没给价"两种路径

`ai_decision` 可能是 `None`、可能是空 dict、三个价可能各自为 0（视为未给）。
原实现里 `tp_px` / `sl_px` 在赋值前**并不存在**，兜底基准是刚算出的 `limit_px`。
这类"多分支 + 变量时序"的逻辑，只测一条happy path 等于没测。
"""

from __future__ import annotations

import ast
import random
import unittest
from pathlib import Path

from scripts.trader import order_intent

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "ai_factor_trader.py"
SUBMODULE = ROOT / "scripts" / "trader" / "order_intent.py"
ENTRY = ROOT / "scripts" / "trader" / "entry_execution.py"   # 第九十刀：开多/开空两支现住此


def _legacy_prices(*, is_long, ai_decision, f, prec, tp_dist, sl_dist):
    """搬走前 facade 长/空 `if allow_entry:` 块开头的三价定价（逐字原样）。"""
    if is_long:
        limit_px = round(ai_decision.get("entry_price") if (ai_decision and ai_decision.get("entry_price", 0) > 0) else (f.get("bidPx") or f["price"]), prec)
        tp_px = round(ai_decision.get("take_profit_price") if (ai_decision and ai_decision.get("take_profit_price", 0) > 0) else (limit_px + tp_dist), prec)
        sl_px = round(ai_decision.get("stop_loss_price") if (ai_decision and ai_decision.get("stop_loss_price", 0) > 0) else (limit_px - sl_dist), prec)
    else:
        limit_px = round(ai_decision.get("entry_price") if (ai_decision and ai_decision.get("entry_price", 0) > 0) else (f.get("askPx") or f["price"]), prec)
        tp_px = round(ai_decision.get("take_profit_price") if (ai_decision and ai_decision.get("take_profit_price", 0) > 0) else (limit_px - tp_dist), prec)
        sl_px = round(ai_decision.get("stop_loss_price") if (ai_decision and ai_decision.get("stop_loss_price", 0) > 0) else (limit_px + sl_dist), prec)
    return limit_px, tp_px, sl_px


def _legacy_intent(*, is_long, inst_id, actual_sz, ct_val, min_sz, limit_px, ai_lever,
                   margin_usdt, max_margin_usdt, inst_lever_cap, ai_conf, ai_info):
    """`venue_ctx` 装配的**约定契约**（2026-09-28 口径统一后）。

    ⚠️ 原基线是"搬走前逐字原样"。用户拍板「交易全改成保证金和杠杆」后：
    - 名义额改为 **保证金 × 杠杆**（钱）—— 旧式 `actual_sz × ct_val × limit_px`
      用的是保证金闸门**夹取之前**的张数，夹取时账实不符；
    - 新增 `ct_val` / `min_sz`，供 OKX 直签边界做**唯一一次**「钱 → 张」换算。
    故这里的基线即**新契约本身**。
    """
    _notional = round(float(margin_usdt or 0.0) * float(ai_lever or 0.0), 2)
    if is_long:
        venue_ctx = {"notional_usdt": _notional,
                     "margin_usdt": margin_usdt,
                     "max_margin_usdt": max_margin_usdt,
                     "leverage": ai_lever,
                     # 审计 P2-5：池内单标的杠杆上限一并透传（router 取更严者）
                     "max_leverage": inst_lever_cap,
                     # 审计 P1-7：per-venue min_confidence 闸门需要原始置信度（决策载荷里本没有）
                     "confidence": ai_conf,
                     "ct_val": ct_val,
                     "min_sz": min_sz,
                     "intent_id": f"{inst_id}:BUY_LONG:{int(ai_info.get('timestamp') or __import__('time').time())}"}
        side, pos_side = "buy", "long"
    else:
        venue_ctx = {"notional_usdt": _notional,
                     "margin_usdt": margin_usdt,
                     "max_margin_usdt": max_margin_usdt,
                     "leverage": ai_lever,
                     "max_leverage": inst_lever_cap,   # 审计 P2-5：池内单标的杠杆上限
                     "confidence": ai_conf,   # 审计 P1-7：per-venue 置信度门禁
                     "ct_val": ct_val,
                     "min_sz": min_sz,
                     "intent_id": f"{inst_id}:SELL_SHORT:{int(ai_info.get('timestamp') or __import__('time').time())}"}
        side, pos_side = "sell", "short"
    return side, pos_side, venue_ctx


class PricesParityTest(unittest.TestCase):
    def test_ai_prices_override_venue_fallback(self):
        dec = {"entry_price": 101.5, "take_profit_price": 110.0, "stop_loss_price": 95.0}
        for is_long in (True, False):
            got = order_intent.resolve_entry_prices(
                is_long=is_long, ai_decision=dec, f={"bidPx": 100.0, "askPx": 100.5, "price": 100.0},
                prec=2, tp_dist=5.0, sl_dist=3.0)
            exp = _legacy_prices(is_long=is_long, ai_decision=dec,
                                 f={"bidPx": 100.0, "askPx": 100.5, "price": 100.0},
                                 prec=2, tp_dist=5.0, sl_dist=3.0)
            self.assertEqual(got, exp, f"is_long={is_long} 与搬走前分叉")
            self.assertEqual(got, (101.5, 110.0, 95.0))

    def test_venue_side_of_book_differs_by_direction(self):
        """盘口价：做多取 bidPx，做空取 askPx —— 漏改会让空单盯着买一价下单。"""
        f = {"bidPx": 100.0, "askPx": 100.5, "price": 99.0}
        lp_long, _, _ = order_intent.resolve_entry_prices(
            is_long=True, ai_decision={}, f=f, prec=2, tp_dist=5.0, sl_dist=3.0)
        lp_short, _, _ = order_intent.resolve_entry_prices(
            is_long=False, ai_decision={}, f=f, prec=2, tp_dist=5.0, sl_dist=3.0)
        self.assertEqual(lp_long, 100.0, "做多应用 bidPx")
        self.assertEqual(lp_short, 100.5, "做空应用 askPx")

    def test_distances_are_mirrored_by_direction(self):
        f = {"bidPx": 100.0, "askPx": 100.0, "price": 100.0}
        lp_l, tp_l, sl_l = order_intent.resolve_entry_prices(
            is_long=True, ai_decision={}, f=f, prec=2, tp_dist=5.0, sl_dist=3.0)
        lp_s, tp_s, sl_s = order_intent.resolve_entry_prices(
            is_long=False, ai_decision={}, f=f, prec=2, tp_dist=5.0, sl_dist=3.0)
        self.assertEqual((tp_l, sl_l), (lp_l + 5.0, lp_l - 3.0), "做多止盈在上、止损在下")
        self.assertEqual((tp_s, sl_s), (lp_s - 5.0, lp_s + 3.0), "做空反向")

    def test_missing_venue_price_falls_back_to_last(self):
        f = {"price": 42.0}
        for is_long in (True, False):
            got = order_intent.resolve_entry_prices(
                is_long=is_long, ai_decision={}, f=f, prec=2, tp_dist=5.0, sl_dist=3.0)
            exp = _legacy_prices(is_long=is_long, ai_decision={}, f=f,
                                 prec=2, tp_dist=5.0, sl_dist=3.0)
            self.assertEqual(got, exp)
            self.assertEqual(got[0], 42.0)

    def test_zero_or_missing_ai_prices_use_fallback(self):
        """AI 三价各自为 0 / 缺失时都必须走兜底（原实现逐个 `> 0` 判定）。"""
        f = {"bidPx": 100.0, "askPx": 101.0, "price": 99.0}
        cases = [
            {"entry_price": 0, "take_profit_price": 0, "stop_loss_price": 0},
            {"entry_price": 100.0, "take_profit_price": 0, "stop_loss_price": 0},
            {"entry_price": 0, "take_profit_price": 110.0, "stop_loss_price": 0},
            {"entry_price": 0, "take_profit_price": 0, "stop_loss_price": 95.0},
            {"take_profit_price": -1.0},
        ]
        for dec in cases:
            for is_long in (True, False):
                got = order_intent.resolve_entry_prices(
                    is_long=is_long, ai_decision=dec, f=f, prec=2, tp_dist=5.0, sl_dist=3.0)
                exp = _legacy_prices(is_long=is_long, ai_decision=dec, f=f,
                                     prec=2, tp_dist=5.0, sl_dist=3.0)
                self.assertEqual(got, exp, f"{dec} is_long={is_long} 分叉")

    def test_none_and_empty_ai_decision(self):
        f = {"bidPx": 100.0, "askPx": 101.0, "price": 99.0}
        for dec in (None, {}):
            for is_long in (True, False):
                got = order_intent.resolve_entry_prices(
                    is_long=is_long, ai_decision=dec, f=f, prec=2, tp_dist=5.0, sl_dist=3.0)
                exp = _legacy_prices(is_long=is_long, ai_decision=dec, f=f,
                                     prec=2, tp_dist=5.0, sl_dist=3.0)
                self.assertEqual(got, exp, f"ai_decision={dec!r} is_long={is_long} 分叉")

    def test_random_price_parity(self):
        rng = random.Random(20260923)
        for _ in range(6000):
            is_long = rng.random() < 0.5
            f = {}
            if rng.random() < 0.8:
                f["bidPx"] = rng.choice([0.0, 1.0, 100.0, 79000.5])
            if rng.random() < 0.8:
                f["askPx"] = rng.choice([0.0, 1.0, 100.5, 79001.0])
            f["price"] = rng.choice([0.5, 1.0, 99.0, 79000.0, 1e5])
            dec = {}
            if rng.random() < 0.7:
                dec["entry_price"] = rng.choice([0, -1.0, 100.0, 79000.0])
            if rng.random() < 0.7:
                dec["take_profit_price"] = rng.choice([0, 110.0, 80000.0])
            if rng.random() < 0.7:
                dec["stop_loss_price"] = rng.choice([0, 95.0, 78000.0])
            if rng.random() < 0.15:
                dec = None
            kw = dict(is_long=is_long, ai_decision=dec, f=f,
                      prec=rng.choice([0, 2, 4]), tp_dist=rng.choice([0.0, 5.0, 500.0]),
                      sl_dist=rng.choice([0.0, 3.0, 300.0]))
            try:
                got = order_intent.resolve_entry_prices(**kw)
            except Exception as exc:                       # noqa: BLE001
                got = ("raise", type(exc).__name__)
            try:
                exp = _legacy_prices(**kw)
            except Exception as exc:                       # noqa: BLE001
                exp = ("raise", type(exc).__name__)
            self.assertEqual(got, exp, f"分叉: {kw}")


class IntentParityTest(unittest.TestCase):
    def _mk(self, **over):
        kw = dict(is_long=True, inst_id="BTC-USDT-SWAP", actual_sz=3.0, ct_val=0.01,
                  min_sz=0.01,
                  limit_px=79000.0, ai_lever=5.0,
                  margin_usdt=150.0, max_margin_usdt=200.0,
                  inst_lever_cap=10.0, ai_conf=88.0,
                  ai_info={"timestamp": 1757850000})
        kw.update(over)
        return kw

    def test_side_labels_flip_with_direction(self):
        """漏改 side 会让做空发 buy —— 不是少赚，是**反向开仓**。"""
        for is_long, side, pos_side, tag in ((True, "buy", "long", "BUY_LONG"),
                                             (False, "sell", "short", "SELL_SHORT")):
            got = order_intent.build_order_intent(**self._mk(is_long=is_long))
            exp = _legacy_intent(**self._mk(is_long=is_long))
            self.assertEqual(got, exp, f"is_long={is_long} 分叉")
            self.assertEqual(got[0], side)
            self.assertEqual(got[1], pos_side)
            self.assertIn(tag, got[2]["intent_id"])

    def test_notional_and_margin_fields(self):
        got = order_intent.build_order_intent(**self._mk(actual_sz=3.0, ct_val=0.01,
                                                         limit_px=79000.0))
        _side, _pos, ctx = got
        # 名义额 = **保证金 × 杠杆**（钱）。旧式 `张数 × 面值 × 价` 用的是闸门
        # 夹取**之前**的张数 —— 夹取时被高估，而真正下的单按夹取后的保证金走。
        self.assertEqual(ctx["notional_usdt"], round(150.0 * 5.0, 2))
        self.assertEqual(ctx["margin_usdt"], 150.0)
        self.assertEqual(ctx["max_margin_usdt"], 200.0)
        self.assertEqual(ctx["leverage"], 5.0)
        self.assertEqual(ctx["max_leverage"], 10.0)
        self.assertEqual(ctx["confidence"], 88.0)
        # 边界换算所需的合约规格随上下文下传
        self.assertEqual(ctx["ct_val"], 0.01)
        self.assertEqual(ctx["min_sz"], 0.01)

    def test_intent_id_is_idempotent_for_same_timestamp(self):
        """同一 AI 决策重投必须得到同一个意图号（幂等，不重复占预算）。"""
        a = order_intent.build_order_intent(**self._mk(ai_info={"timestamp": 1757850000}))[2]
        b = order_intent.build_order_intent(**self._mk(ai_info={"timestamp": 1757850000}))[2]
        self.assertEqual(a["intent_id"], b["intent_id"])
        self.assertEqual(a["intent_id"], "BTC-USDT-SWAP:BUY_LONG:1757850000")

    def test_intent_id_falls_back_to_now_when_timestamp_missing(self):
        ctx = order_intent.build_order_intent(**self._mk(ai_info={}))[2]
        suffix = ctx["intent_id"].rsplit(":", 1)[1]
        self.assertTrue(suffix.isdigit(), f"意图号尾部应为秒级时间戳，实际 {ctx['intent_id']}")
        self.assertGreater(int(suffix), 1_600_000_000)

    def test_none_timestamp_falls_back(self):
        ctx = order_intent.build_order_intent(**self._mk(ai_info={"timestamp": None}))[2]
        self.assertTrue(ctx["intent_id"].rsplit(":", 1)[1].isdigit())


class WiringTest(unittest.TestCase):
    def test_impl_lives_in_submodule_not_facade(self):
        facade = FACADE.read_text(encoding="utf-8")
        sub = SUBMODULE.read_text(encoding="utf-8")
        self.assertIn("def resolve_entry_prices(", sub)
        self.assertIn("def build_order_intent(", sub)
        self.assertNotIn("def resolve_entry_prices(", facade)
        self.assertNotIn("def build_order_intent(", facade)

    def test_both_directions_call_helpers(self):
        entry = ENTRY.read_text(encoding="utf-8")
        self.assertEqual(entry.count("resolve_entry_prices("), 2,
                         "开多/开空都必须走同一套定价实现")
        self.assertEqual(entry.count("build_order_intent("), 2,
                         "开多/开空都必须走同一套载荷装配")
        self.assertIn("is_long=True,", entry)
        self.assertIn("is_long=False,", entry)

    def test_both_call_sites_define_every_name_they_pass(self):
        """调用点必须在自己**这一支**里备好传给 helper 的每个名字。

        判据（与 `test_trader_pyramiding_extraction` 同一套）：只沿**到达该调用的
        唯一路径**收集定义，绝不下钻进兄弟分支 —— 否则开多分支的同名局部量会
        把开空分支的缺口盖住。

        这块尤其需要：`resolve_entry_prices` / `build_order_intent` 的实参里有
        `tp_dist` / `sl_dist` / `ai_margin` / `_inst_lever_cap` / `ai_info` 等
        **只在所属分支里才算得出**的量。
        """
        tree = ast.parse(ENTRY.read_text(encoding="utf-8"))
        func = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "execute_entry_scan")

        from tests.source_scan import names_defined_at_call

        checked = 0
        for node in ast.walk(func):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("resolve_entry_prices", "build_order_intent")):
                continue
            passed = set()
            for arg in node.args:
                for nm in ast.walk(arg):
                    if isinstance(nm, ast.Name):
                        passed.add(nm.id)
            for kw in node.keywords:
                for nm in ast.walk(kw.value):
                    if isinstance(nm, ast.Name):
                        passed.add(nm.id)
            available = names_defined_at_call(func, node, module_tree=tree)
            # 被调用函数自身的形参名不算（is_long 等只以关键字名出现，不在 value 树里）
            missing = sorted(n for n in passed if n not in available)
            self.assertEqual(missing, [],
                             f"{node.func.id} 调用（L{node.lineno}）所在分支引用了"
                             f"未定义的名字 {missing}；实盘走到该分支时会 NameError")
            checked += 1
        self.assertEqual(checked, 4,
                         f"应有 2 处定价 + 2 处载荷装配调用，实际 {checked}")

    def test_facade_keeps_the_two_anchor_lines(self):
        """入场执行模块必须保留保证金闸门与权益顶两行 —— 它们是计数锚点的载体。

        这是**刻意**保留在调用点的部分（cut 15 的设计：把两行留在调用点，
        以便锚点证明"两条路径都过闸"）。⚠️ 第九十刀：`execute_portfolio`
        的入场循环整体搬入 `scripts/trader/entry_execution.py`，两行载体随之迁移
        —— 计数与语义一字不变；门面侧改为**反证**（残留即搬家不彻底）。
        """
        entry = ENTRY.read_text(encoding="utf-8")
        self.assertEqual(entry.count("_order_margin = order_margin_gate("), 2)
        self.assertNotIn("_order_margin = order_margin_gate(",
                         FACADE.read_text(encoding="utf-8"),
                         "门面残留该行 ⇒ 载体迁移不彻底（或出现孪生）")
        from tests.source_scan import count_keyword_argument
        self.assertEqual(
            count_keyword_argument("scripts/ai_factor_trader.py", "build_order_intent",
                                   "max_margin_usdt",
                                   value_must_contain="equity_margin_cap(usdt_available)",
                                   pkg_name="trader"),
            2, "两处调用必须各自携带权益顶（域定位：载体已入子包）")


if __name__ == "__main__":
    unittest.main()
