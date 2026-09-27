r"""Binance 下单参数构建抽取对拍门（第一百一十二刀）。

`astra_backend/exchanges/binance.py` 里两段 → `astra_backend/exchanges/binance_orders.py`：
- `build_order_params(...)`：`place_order` 中段的参数归一化（数量/价格按 `step`/`tick`
  **向下取整**、`LIMIT`/`MARKET` 选择、`newClientOrderId`/`positionSide`/`reduceOnly`）；
- `apply_protective_qty_policy(...)`：保护单（TP/SL）**数量策略**，两处逐字重复的 6 行合并。

## 本门钉两条安全契约

1. **`reduceOnly` 与 `positionSide` 互斥**（审计 §2 契约）：两者同时给 ⇒ 主动抛
   `ValueError`，**不得**把矛盾参数发到交易所（对冲模式下交易所会拒单且语义不清）。
   原先该判断埋在下单方法中段、外包一层 `signed_request`，很难单独验证。
2. 数量策略决定"平多少"：给了数量 ⇒ `quantity` + `reduce_only=True` + `close_position=False`；
   没给 ⇒ `close_position=True`（**整仓平**）。TP/SL 两处必须**共用同一个函数**
   （本门断言两处调用点都是它），否则日后会各自漂移。

基线：`7658a99`（本刀动工前最后提交）。
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "7658a99"
FACADE = ROOT / "astra_backend" / "exchanges" / "binance.py"
MOD = ROOT / "astra_backend" / "exchanges" / "binance_orders.py"


def _baseline_cls() -> ast.ClassDef:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:astra_backend/exchanges/binance.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return next(n for n in ast.parse(normalize(r.stdout)).body
                if isinstance(n, ast.ClassDef) and n.name == "BinanceAdapter")


def _baseline_method(name: str) -> ast.FunctionDef:
    return next(n for n in _baseline_cls().body
                if isinstance(n, ast.FunctionDef) and n.name == name)


def _impl(name: str) -> ast.FunctionDef:
    t = ast.parse(MOD.read_text(encoding="utf-8"))
    return next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _facade_calls(name: str) -> list:
    return [n for n in ast.walk(ast.parse(FACADE.read_text(encoding="utf-8")))
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == name]


def _spec(step="0.001", tick="0.1"):
    return SimpleNamespace(step_size=Decimal(step), tick_size=Decimal(tick))


def _base_kwargs(**over):
    kw = dict(inst="BTCUSDT", position_side="", price=None, qty=2, reduce_only=False,
              s="BUY", spec=_spec(), text="", tif="gtc")
    kw.update(over)
    return kw


class BinanceOrdersExtractionTest(unittest.TestCase):
    def test_call_sites_pass_every_parameter_once_same_name(self):
        """**第一百一十六刀后**：门面只直接调用 `build_order_params`；
        `apply_protective_qty_policy` 的调用点移到了同模块的 `send_protective_order` 内部
        （仍是"同名注入"形态），故这里分两处校验，意图不变：**没有位置参数、没有漏传、没有改名**。
        """
        params = [a.arg for a in _impl("build_order_params").args.kwonlyargs]
        for call in _facade_calls("build_order_params"):
            self.assertEqual(call.args, [])
            self.assertEqual([k.arg for k in call.keywords], params)
            for k in call.keywords:
                self.assertEqual(ast.unparse(k.value), k.arg)
        # 模块内调用点：`send_protective_order` 调 `apply_protective_qty_policy`
        inner = [n for n in ast.walk(_impl("send_protective_order"))
                 if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "apply_protective_qty_policy"]
        self.assertEqual(len(inner), 1)
        self.assertEqual([k.arg for k in inner[0].keywords], ["req_kwargs", "qty_str"])
        for k in inner[0].keywords:
            self.assertEqual(ast.unparse(k.value), k.arg)
        self.assertEqual(_facade_calls("apply_protective_qty_policy"), [],
                         "门面不应再直接调用它（调用点已下沉到 send_protective_order）")

    def test_both_protective_branches_share_one_helper(self):
        """TP/SL 必须都走**同一个**发单函数 —— 否则又会各自漂移。

        第一百一十六刀把两段近乎逐字重复的代码（只差 type_/触发价/结果键）合并成
        `send_protective_order`；本判据的**意图不变**，只是从"两处都调数量策略"
        升级为"两处都调发单助手，且各自传对了 type_ 与结果键"。
        """
        calls = _facade_calls("send_protective_order")
        self.assertEqual(len(calls), 2, "止盈/止损两处都必须调用该助手")
        seen = {}
        for call in calls:
            kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
            seen[kw["type_"]] = kw
        self.assertEqual(sorted(seen), ["'STOP_MARKET'", "'TAKE_PROFIT_MARKET'"],
                         "ast.unparse 输出单引号字符串常量")
        self.assertEqual(seen["'TAKE_PROFIT_MARKET'"]["trigger_price"], "tp_px")
        self.assertEqual(seen["'STOP_MARKET'"]["trigger_price"], "sl_px")

    def test_no_undeclared_free_names(self):
        module = ast.parse(MOD.read_text(encoding="utf-8"))
        # 模块级可解析名：函数/类定义 + **import** + 赋值目标
        # （漏掉 import 是我第一版就踩的坑：子模块自己 import 标准库类型后，
        #  这一条会误报成"自由名解析不到"——与审计门当初同一处缺口。）
        mod_names = set()
        for n in module.body:
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                mod_names.add(n.name)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    mod_names.add(a.asname or a.name.split(".")[0])
            elif isinstance(n, ast.Assign):
                for tg in n.targets:
                    if isinstance(tg, ast.Name):
                        mod_names.add(tg.id)
        for name in ("build_order_params", "apply_protective_qty_policy"):
            with self.subTest(fn=name):
                fn = _impl(name)
                local = {a.arg for a in fn.args.kwonlyargs}
                for n in ast.walk(fn):
                    if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                        local.add(n.id)
                    if isinstance(n, ast.ExceptHandler) and n.name:
                        local.add(n.name)
                    if isinstance(n, (ast.Import, ast.ImportFrom)):
                        for a in n.names:
                            local.add(a.asname or a.name.split(".")[0])
                reads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
                         and isinstance(n.ctx, ast.Load)}
                missing = sorted(reads - local - set(dir(builtins)) - mod_names)
                self.assertEqual(missing, [], f"{name} 解析不到: {missing}")

    # ---------- 行为例：参数构建 ----------

    def _build(self, **over):
        from astra_backend.exchanges.binance_orders import build_order_params
        return build_order_params(**_base_kwargs(**over))

    def test_market_order_when_no_price(self):
        p = self._build(price=None)
        self.assertEqual(p["type"], "MARKET")
        self.assertNotIn("price", p)
        self.assertNotIn("timeInForce", p)
        self.assertEqual(p["symbol"], "BTCUSDT")
        self.assertEqual(p["side"], "BUY")
        self.assertNotIn("newClientOrderId", p, "空 text 不落该键")
        self.assertNotIn("positionSide", p)
        self.assertNotIn("reduceOnly", p)

    def test_limit_order_rounds_down_price_to_tick(self):
        p = self._build(price="60123.4567", tif="gtc")
        self.assertEqual(p["type"], "LIMIT")
        self.assertEqual(p["timeInForce"], "GTC", "tif 必须大写")
        self.assertEqual(p["price"], "60123.4", "按 tick=0.1 向下取整，且不留尾零")

    def test_zero_price_is_market(self):
        self.assertEqual(self._build(price=0)["type"], "MARKET")

    def test_quantity_rounded_down_to_step(self):
        self.assertEqual(self._build(qty=1.23456)["quantity"], "1.234")
        self.assertEqual(self._build(qty=2)["quantity"], "2", "整值不留尾零")

    def test_spec_none_uses_fallbacks(self):
        self.assertEqual(self._build(qty=1.5, spec=None)["quantity"], "1.5")
        self.assertEqual(self._build(price="10.04", spec=None)["price"], "10",
                         "无 spec 时 tick 兜底 0.1")

    def test_client_id_and_position_side(self):
        p = self._build(text="  tg-1  ", position_side="long")
        self.assertEqual(p["newClientOrderId"], "tg-1", "必须 strip")
        self.assertEqual(p["positionSide"], "LONG", "必须大写")

    def test_reduce_only_requires_hedge_flag_absent(self):
        p = self._build(reduce_only=True, position_side="")
        self.assertEqual(p["reduceOnly"], "true")

    def test_reduce_only_and_position_side_are_mutually_exclusive(self):
        """审计 §2 契约：矛盾参数必须在本地下单前就炸掉。"""
        with self.assertRaises(ValueError) as cm:
            self._build(reduce_only=True, position_side="long")
        self.assertIn("互斥", str(cm.exception))

    # ---------- 行为例：保护单数量策略 ----------

    def test_qty_policy_with_quantity(self):
        from astra_backend.exchanges.binance_orders import apply_protective_qty_policy
        kw = {"symbol": "BTCUSDT"}
        self.assertIsNone(apply_protective_qty_policy(req_kwargs=kw, qty_str="0.5"))
        self.assertEqual(kw["quantity"], "0.5")
        self.assertTrue(kw["reduce_only"])
        self.assertFalse(kw["close_position"])
        self.assertEqual(kw["symbol"], "BTCUSDT", "只加策略键，不动其他")

    def test_qty_policy_without_quantity_closes_whole_position(self):
        from astra_backend.exchanges.binance_orders import apply_protective_qty_policy
        kw = {}
        apply_protective_qty_policy(req_kwargs=kw, qty_str=None)
        self.assertTrue(kw["close_position"], "未给数量 ⇒ 整仓平")
        self.assertNotIn("quantity", kw)
        self.assertNotIn("reduce_only", kw, "整仓平模式不落 reduce_only")

class SendProtectiveOrderTest(unittest.TestCase):
    """第一百一十六刀：TP/SL 两段重复代码合并成 `send_protective_order`。

    本类钉住合并后**必须保持**的行为：触发价无效 ⇒ 不发单、返回 `""`；
    有效 ⇒ 用正确的 `type_`/触发价/仓位方向构造请求并发出；返回 `algoId`，
    缺则 `orderId`，都不是则 `""`；数量策略照旧生效。

    另一条同样重要（写在 docstring 里但值得被断言）：**无条件赋值等价于原实现** ——
    `res` 初值为 `""`、返回值恒为 `str`，故 `res[key] = helper(...)` 与原
    `if isinstance(data, dict): res[key] = ...` 的最终结果完全一致。
    """

    def _send(self, trigger, type_="TAKE_PROFIT_MARKET", data=None, qty_str=None):
        from astra_backend.exchanges.binance_orders import send_protective_order
        sent = []

        def build(**kw):
            sent.append(kw)
            return {"built": kw}

        def priv(req):
            return data

        out = send_protective_order(build_algo_order_request=build, inst="BTCUSDT",
                                    opp_side="SELL", position_side=None, private_algo_send=priv,
                                    qty_str=qty_str, trigger_price=trigger, type_=type_, wt="CONTRACT_PRICE")
        return out, sent

    def test_invalid_trigger_sends_nothing(self):
        for bad in (None, 0, 0.0, -5):
            with self.subTest(bad=bad):
                out, sent = self._send(bad)
                self.assertEqual(out, "")
                self.assertEqual(sent, [], "触发价无效时**不得**发单")

    def test_valid_trigger_builds_expected_kwargs(self):
        out, sent = self._send(65000.0, data={"algoId": 701})
        self.assertEqual(out, "701")
        self.assertEqual(len(sent), 1)
        assert sent[0] == {"symbol": "BTCUSDT", "side": "SELL", "type_": "TAKE_PROFIT_MARKET",
                           "trigger_price": 65000.0, "working_type": "CONTRACT_PRICE",
                           "position_side": None, "close_position": True}
        self.assertNotIn("quantity", sent[0])

    def test_qty_policy_is_applied(self):
        _out, sent = self._send(65000.0, data={"algoId": 1}, qty_str="0.5")
        self.assertEqual(sent[0]["quantity"], "0.5")
        self.assertTrue(sent[0]["reduce_only"])
        self.assertFalse(sent[0]["close_position"])

    def test_id_fallback_order_and_empty(self):
        # 两键同时存在时必须**优先 algoId**（只喂单键的断言没有牙：负向实测发现 B 例抓不住顺序颠倒）
        self.assertEqual(self._send(65000.0, data={"algoId": 701, "orderId": 88})[0], "701",
                         "algoId 优先于 orderId")
        self.assertEqual(self._send(65000.0, data={"orderId": 88})[0], "88", "缺 algoId 时用 orderId")
        self.assertEqual(self._send(65000.0, data={"algoId": None, "orderId": 88})[0], "88",
                         "algoId 为 None ⇒ 回退 orderId")
        self.assertEqual(self._send(65000.0, data={"algoId": "", "orderId": ""})[0], "")
        self.assertEqual(self._send(65000.0, data={})[0], "")
        self.assertEqual(self._send(65000.0, data="not-a-dict")[0], "", "响应非 dict ⇒ 空串")

    def test_sl_type_and_value_are_forwarded(self):
        out, sent = self._send(58000.0, type_="STOP_MARKET", data={"algoId": 702})
        self.assertEqual(out, "702")
        self.assertEqual(sent[0]["type_"], "STOP_MARKET")
        self.assertEqual(sent[0]["trigger_price"], 58000.0)


if __name__ == "__main__":
    unittest.main()
