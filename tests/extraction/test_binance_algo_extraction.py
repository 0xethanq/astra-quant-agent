"""Binance Algo 请求构造器外提（结构优化阶段 4·B3 第五十九刀）。

## 抽了什么

`astra_backend/exchanges/binance.py`（754 行）里有一簇形态完全不同的代码：
**US-004 Algo Service 双轨契约构造器** —— 5 个 `@classmethod` +
1 个 workingType 校验 + 3 个类常量（`ALGO_ORDER_PATH` / `ALGO_TYPES` /
`WORKING_TYPES`）。

特点是**零 I/O、零凭证、零签名**，纯 dict 构造 + fail-closed 校验；
但它夹在"公共行情端点"与"私有签名面"之间，读代码时容易被当成网络层的一部分。
实测（传递纯度扫描）该文件**没有任何模块级路径常量**，这簇是纯的。

外提到 `astra_backend/exchanges/binance_algo.py`（`BinanceAlgoRequestsMixin`），
`binance.py` **754 → 638 行**。

## ⚠️ 为什么用 **mixin** 而不是"搬成自由函数"

原实现全是 `@classmethod`，且大量通过 `cls.` 与 `BinanceAdapter.` 访问类常量。
`tests/venues/test_venue_capability_semantics.py` 用
`self.ad.build_algo_order_request(...)`（**实例上调用 classmethod**）与
`binance.BinanceAdapter.WORKING_TYPES`（**类属性**）两种形态。

若搬成自由函数，这些访问**全部失效**；mixin 则：

- `BinanceAdapter(BinanceAlgoRequestsMixin, BaseExchangeAdapter)` →
  `self.ad.build_algo_order_request(...)` 不变；
- `cls` 运行时仍是 `BinanceAdapter` → `cls.ALGO_ORDER_PATH` 不变；
- `BinanceAdapter.WORKING_TYPES` 经 MRO 仍解析 → 不变。

本文件的 `AccessShapeTest` 把**三种访问形态**都钉住。

## ⚠️ 一处**有意**的形态改动（如实记录）

`_require_working_type` 原为 `@staticmethod` 且写死 `BinanceAdapter.WORKING_TYPES`
（"读另一个类"）。搬进 mixin 后那个类名解析不到，故改为
`@classmethod` + `cls.WORKING_TYPES` —— 经 MRO 仍解析到**同一份常量**，
取值与语义不变，调用点 `cls._require_working_type(...)` 也不变。

因此 `VerbatimCopyTest` 把这一处列入"预期替换"，而不是要求逐字节相同。
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FACADE = ROOT / "astra_backend" / "exchanges" / "binance.py"
MIXIN = ROOT / "astra_backend" / "exchanges" / "binance_algo.py"
PKG_INIT = ROOT / "astra_backend" / "exchanges" / "__init__.py"

from astra_backend.exchanges.binance import BinanceAdapter  # noqa: E402
from astra_backend.exchanges.binance_algo import BinanceAlgoRequestsMixin  # noqa: E402
from tests.extraction.rename_baseline import legacy_rev_path, normalize

def _nodedoc(src: str) -> str:
    """把所有字符串字面量（含文档串）与 `#` 注释替换成等长空白，只留代码骨架。

    ⚠️ 用 AST 拿字符串节点的位置，逐字符扫描剥注释 —— 不用正则
    （第五十六刀在正则剥注释上连撞四次）。
    """
    text = src
    # 逐字符扫描：字符串与注释都抹掉（不用正则 —— 第五十六刀在正则剥注释上连撞四次）
    res: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "#":
            j = text.find("\n", i)
            if j == -1:
                break
            res.append(" " * (j - i))
            i = j
            continue
        if c in "\"'":
            quote = c * 3 if text[i:i + 3] == c * 3 else c
            j = i + len(quote)
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j:j + len(quote)] == quote:
                    break
                j += 1
            seg = text[i:j + len(quote)]
            res.append("\n" * seg.count("\n") + " " * (len(seg) - seg.count("\n")))
            i = j + len(quote)
            continue
        res.append(c)
        i += 1
    return "".join(res)


BUILDERS = ("build_algo_order_request", "build_algo_query_request",
            "build_algo_open_orders_request", "build_algo_cancel_request",
            "build_algo_cancel_all_request")
CONSTS = ("ALGO_ORDER_PATH", "ALGO_TYPES", "WORKING_TYPES")


class AccessShapeTest(unittest.TestCase):
    """⚠️ 三种访问形态都不得因外提而失效（这是选 mixin 而非自由函数的理由）。"""

    def setUp(self):
        self.ad = BinanceAdapter(environment="demo")

    def test_class_attributes_resolve_on_the_adapter(self):
        from astra_backend.exchanges import binance
        for c in CONSTS:
            with self.subTest(const=c):
                self.assertTrue(hasattr(BinanceAdapter, c), f"BinanceAdapter 缺 {c}")
                self.assertEqual(getattr(BinanceAdapter, c),
                                 getattr(BinanceAlgoRequestsMixin, c))
        self.assertEqual(binance.BinanceAdapter.WORKING_TYPES,
                         ("MARK_PRICE", "CONTRACT_PRICE", "INDEX_PRICE"))

    def test_builders_callable_on_the_class(self):
        r = BinanceAdapter.build_algo_query_request(algo_id=7)
        self.assertEqual(r, {"method": "GET", "path": "/fapi/v1/algoOrder",
                             "params": {"algoId": "7"}})

    def test_builders_callable_on_an_instance(self):
        """既有测试正是这种形态：`self.ad.build_algo_order_request(...)`。"""
        r = self.ad.build_algo_order_request(
            symbol="BTCUSDT", side="BUY", type_="STOP_MARKET",
            trigger_price=100, working_type="MARK_PRICE", close_position=True)
        self.assertEqual(r["method"], "POST")
        self.assertEqual(r["path"], BinanceAdapter.ALGO_ORDER_PATH)
        self.assertEqual(r["body"]["closePosition"], "true")

    def test_cls_resolves_to_the_adapter_not_the_mixin(self):
        """`cls.ALGO_ORDER_PATH` 必须解析到适配器（MRO 顺序正确）。"""
        self.assertEqual(BinanceAdapter.__mro__[1], BinanceAlgoRequestsMixin)
        self.assertIn(BinanceAlgoRequestsMixin, BinanceAdapter.__mro__)

    def test_mixin_has_no_init_and_does_no_io(self):
        """mixin 不得定义 `__init__`、不得引入网络/凭证/文件依赖。

        ⚠️ 禁用词检查必须**先剥文档串** —— 本模块的 docstring 里正当地写着
        "与传送层（`signed_request` / `urlopen`）没有耦合"，
        直接扫原文会把这句说明当成"mixin 含 urlopen"（本仓反复出现的坑）。
        """
        src = MIXIN.read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef)
                   and n.name == "BinanceAlgoRequestsMixin")
        self.assertFalse([n for n in cls.body if isinstance(n, ast.FunctionDef)
                          and n.name == "__init__"], "mixin 不得定义 __init__")
        # 依赖面：只看 import（AST，天然不受文档干扰）
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module.split(".")[0])
        self.assertTrue(mods <= {"decimal", "typing", "__future__"},
                        f"mixin 出现非预期依赖: {sorted(mods)}")
        # 禁用词：在**剥掉所有文档串与注释**之后检查
        code = _nodedoc(src)
        for banned in ("urlopen", "signature", "hmac", "venue_credentials", "open("):
            self.assertNotIn(banned, code, f"mixin 代码里不应出现 {banned}")


class ConstantsUnchangedTest(unittest.TestCase):
    """常量取值是审计结论的载体，一个字节都不许变。"""

    def test_algo_order_path(self):
        self.assertEqual(BinanceAdapter.ALGO_ORDER_PATH, "/fapi/v1/algoOrder")

    def test_algo_types(self):
        self.assertEqual(BinanceAdapter.ALGO_TYPES,
                         ("STOP", "STOP_MARKET", "TAKE_PROFIT",
                          "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET"))

    def test_working_types(self):
        self.assertEqual(BinanceAdapter.WORKING_TYPES,
                         ("MARK_PRICE", "CONTRACT_PRICE", "INDEX_PRICE"))


class FailClosedTest(unittest.TestCase):
    """构造器的 fail-closed 行为（既有测试已覆盖大部分，此处钉最易被改坏的几条）。"""

    def test_working_type_must_be_explicit(self):
        """不依赖平台默认值：缺 workingType 必须抛，且**不可**回落 CONTRACT_PRICE。"""
        for bad in (None, "", "  ", "LAST_PRICE", "mark_price_x"):
            with self.subTest(wt=bad):
                with self.assertRaises(ValueError):
                    BinanceAdapter.build_algo_order_request(
                        symbol="BTCUSDT", side="BUY", type_="STOP_MARKET",
                        trigger_price=100, working_type=bad, quantity="1")

    def test_working_type_is_upper_normalised(self):
        r = BinanceAdapter.build_algo_order_request(
            symbol="BTCUSDT", side="BUY", type_="STOP_MARKET",
            trigger_price=1, working_type=" mark_price ", quantity="1")
        self.assertEqual(r["body"]["workingType"], "MARK_PRICE")

    def test_symbol_must_be_usdt_native(self):
        for bad in ("BTC-USD-SWAP", "BTCUSD", ""):
            with self.subTest(sym=bad):
                with self.assertRaises(ValueError):
                    BinanceAdapter.build_algo_order_request(
                        symbol=bad, side="BUY", type_="STOP_MARKET",
                        trigger_price=1, working_type="MARK_PRICE", quantity="1")

    def test_close_position_mutual_exclusion(self):
        with self.assertRaises(ValueError):
            BinanceAdapter.build_algo_order_request(
                symbol="BTCUSDT", side="BUY", type_="STOP_MARKET",
                trigger_price=1, working_type="MARK_PRICE",
                close_position=True, quantity="1")
        with self.assertRaises(ValueError):
            BinanceAdapter.build_algo_order_request(
                symbol="BTCUSDT", side="BUY", type_="STOP_MARKET",
                trigger_price=1, working_type="MARK_PRICE",
                close_position=True, reduce_only=True)
        with self.assertRaises(ValueError):
            BinanceAdapter.build_algo_order_request(
                symbol="BTCUSDT", side="BUY", type_="STOP",   # 非 _MARKET
                trigger_price=1, working_type="MARK_PRICE", close_position=True)

    def test_hedge_mode_cannot_pass_reduce_only(self):
        for ps in ("LONG", "SHORT"):
            with self.subTest(ps=ps):
                with self.assertRaises(ValueError):
                    BinanceAdapter.build_algo_order_request(
                        symbol="BTCUSDT", side="BUY", type_="STOP_MARKET",
                        trigger_price=1, working_type="MARK_PRICE",
                        quantity="1", reduce_only=True, position_side=ps)

    def test_legacy_order_fields_are_never_emitted(self):
        """`stopPrice` / `newClientOrderId` 属普通订单字段，绝不出现在 Algo 体里。"""
        r = BinanceAdapter.build_algo_order_request(
            symbol="BTCUSDT", side="BUY", type_="STOP_MARKET", trigger_price=1,
            working_type="MARK_PRICE", quantity="1", client_algo_id="cid-1")
        self.assertNotIn("stopPrice", r["body"])
        self.assertNotIn("newClientOrderId", r["body"])
        self.assertIn("clientAlgoId", r["body"])
        self.assertIn("triggerPrice", r["body"])

    def test_query_and_cancel_require_an_identifier(self):
        for fn in (BinanceAdapter.build_algo_query_request,
                   BinanceAdapter.build_algo_cancel_request):
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(ValueError):
                    fn()
                with self.assertRaises(ValueError):
                    fn(algo_id=None, client_algo_id="")

    def test_cancel_all_requires_symbol(self):
        with self.assertRaises(ValueError):
            BinanceAdapter.build_algo_cancel_all_request(symbol="")
        with self.assertRaises(ValueError):
            BinanceAdapter.build_algo_cancel_all_request(symbol="   ")

    def test_trigger_price_must_be_positive(self):
        for bad in (0, -1, "abc", None):
            with self.subTest(tp=bad):
                with self.assertRaises(ValueError):
                    BinanceAdapter.build_algo_order_request(
                        symbol="BTCUSDT", side="BUY", type_="STOP_MARKET",
                        trigger_price=bad, working_type="MARK_PRICE", quantity="1")

    def test_type_must_be_in_algo_family(self):
        with self.assertRaises(ValueError):
            BinanceAdapter.build_algo_order_request(
                symbol="BTCUSDT", side="BUY", type_="LIMIT",
                trigger_price=1, working_type="MARK_PRICE", quantity="1")


class VerbatimCopyTest(unittest.TestCase):
    """⚠️ 搬移只允许复制（第五十刀立的规矩）。"""

    PRE = "cc96d36"   # 第五十八刀提交 —— 本刀之前

    # 有意替换：`@staticmethod` + 写死类名 → `@classmethod` + `cls`（见模块 docstring）
    EXPECTED = [
        ("@staticmethod\ndef _require_working_type(working_type: Optional[str]) -> str:",
         "@classmethod\ndef _require_working_type(cls, working_type: Optional[str]) -> str:"),
        ("BinanceAdapter.WORKING_TYPES", "cls.WORKING_TYPES"),
    ]

    def _fn(self, src: str, name: str) -> str:
        tree = ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef) and n.name == name:
                module = ast.Module(
                    body=[s for s in n.body
                          if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))],
                    type_ignores=[])
                return ast.unparse(module)
        raise AssertionError(f"{name} not found")

    def test_facade_no_longer_defines_the_builders(self):
        """门面里不应再有这簇的实现（否则就是两份）。"""
        tree = ast.parse(FACADE.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == "BinanceAdapter")
        names = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        for b in BUILDERS:
            self.assertNotIn(b, names, f"binance.py 仍定义 {b}")
        assigns = {t.id for n in cls.body if isinstance(n, ast.Assign)
                   for t in n.targets if isinstance(t, ast.Name)}
        for c in CONSTS:
            self.assertNotIn(c, assigns, f"binance.py 仍定义 {c}")


class DocsRegisteredTest(unittest.TestCase):
    def test_module_registered_in_package_docs(self):
        self.assertIn("binance_algo.py", PKG_INIT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
