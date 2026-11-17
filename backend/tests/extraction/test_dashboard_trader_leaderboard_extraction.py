"""`astra_backend/dashboard_payload/trader_leaderboard.py`（B3 第二十六刀）回归。

## 这个测试在守什么

`build_inst_leaderboard` 把 `by_inst` 转成前端表格行。三处口径容易"顺手改坏"：

1. **胜率分母是 `trades`，不是 `wins + losses`**。`by_inst["trades"]` **包含**
   被尘埃过滤掉的单子（`trade_stats` 里过滤发生在记账之后），而 `wins`/`losses`
   **不含**。所以分母**大于** `wins + losses`。这是刻意的口径差异 ——
   改成 `wins/(wins+losses)` 会让分币种胜率与既有数字不一致。
2. **排序只按 `pnl` 降序**，相等时保持 `by_inst` 插入顺序（Python `sort` 稳定）。
   加二级排序键会改变同分组内的行序。
3. **`round(...,2)` 只作用于 `pnl`**，笔数是整数直出。

## 附带发现（如实记录）

`leaderboard` 这个键**当前没有消费方**：`frontend/src` 全仓搜不到 `leaderboard`
（只有 `.archive/trading.html` 那份旧静态页读 `perf.inst_leaderboard`）。
也就是它随旧面板一起退役了。**但接口要保持不变**（目标明确要求），
故保留键与形状，并借本轮抽离给它补上此前**完全没有的**测试覆盖。
"""

from __future__ import annotations

import ast
import random
import unittest
from pathlib import Path

from astra_backend.dashboard_payload.trader_leaderboard import build_inst_leaderboard

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "astra_backend" / "dashboard_cache.py"
MODULE = ROOT / "astra_backend" / "dashboard_payload" / "trader_leaderboard.py"
STATS = ROOT / "astra_backend" / "dashboard_payload" / "trade_stats.py"   # 第九十五刀：调用点现住此


def _legacy(by_inst):
    """搬走前 update_cache_cycle 里的内联实现（逐字原样）。"""
    inst_leaderboard = []
    for inst, s in by_inst.items():
        w_r = round((s["wins"] / s["trades"]) * 100, 1) if s["trades"] > 0 else 0.0
        inst_leaderboard.append({
            "inst": inst,
            "trades": s["trades"],
            "wins": s["wins"],
            "losses": s["losses"],
            "win_rate": w_r,
            "pnl": round(s["pnl"], 2)
        })
    inst_leaderboard.sort(key=lambda x: x["pnl"], reverse=True)
    return inst_leaderboard


def _s(trades=0, wins=0, losses=0, pnl=0.0):
    return {"trades": trades, "wins": wins, "losses": losses, "pnl": pnl}


def _bound_names(fn: ast.FunctionDef) -> set[str]:
    """函数体里**被绑定**的名字：赋值目标、for 目标、with/as、except/as、
    推导式与生成器的目标、lambda 形参、嵌套函数的形参。"""
    bound: set[str] = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    if fn.args.vararg:
        bound.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        bound.add(fn.args.kwarg.arg)

    class _B(ast.NodeVisitor):
        def visit_Name(self, node):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                bound.add(node.id)

        def visit_arg(self, node):
            bound.add(node.arg)

        def visit_Lambda(self, node):
            for a in node.args.args + node.args.kwonlyargs:
                bound.add(a.arg)
            if node.args.vararg:
                bound.add(node.args.vararg.arg)
            if node.args.kwarg:
                bound.add(node.args.kwarg.arg)
            self.generic_visit(node)

        def visit_comprehension(self, node):
            for n in ast.walk(node.target):
                if isinstance(n, ast.Name):
                    bound.add(n.id)
            self.generic_visit(node)

        def visit_Import(self, node):
            for a in node.names:
                bound.add(a.asname or a.name.split(".")[0])

        def visit_ImportFrom(self, node):
            for a in node.names:
                bound.add(a.asname or a.name)

        def visit_FunctionDef(self, node):
            bound.add(node.name)
            for a in node.args.args + node.args.kwonlyargs:
                bound.add(a.arg)
            self.generic_visit(node)

    for stmt in fn.body:
        _B().visit(stmt)
    return bound


def _loaded_names(fn: ast.FunctionDef) -> set[str]:
    """函数体里被读取的名字（**不含任何注解**）。

    ⚠️ 注解有**两处**，两处都要排除 —— 我只想到第一处就误报了一轮：

    1. 函数签名 `def f(x) -> List[Dict[str, Any]]`；
    2. **函数体内的带注解赋值** `rows: List[Dict[str, Any]] = []`
       （`AnnAssign.annotation` 也是 `Name(Load)`）。

    注解是**类型层**的东西，不是运行时依赖。判断"函数是否读外部状态"时
    必须把它们排除，否则任何用了 `typing` 泛型的模块都会被误判为"不纯"。
    """
    loaded: set[str] = set()

    def _skip_annotation(stmt):
        if isinstance(stmt, ast.AnnAssign) and stmt.annotation is not None:
            # 只走 value，不走 annotation
            if stmt.value is not None:
                for n in ast.walk(stmt.value):
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                        loaded.add(n.id)
            return True
        return False

    for stmt in fn.body:
        if _skip_annotation(stmt):
            continue
        for n in ast.walk(stmt):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                loaded.add(n.id)
    return loaded


class BasicTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(build_inst_leaderboard({}), [])

    def test_row_shape(self):
        out = build_inst_leaderboard({"BTC": _s(3, 2, 1, 12.5)})
        self.assertEqual(len(out), 1)
        self.assertEqual(sorted(out[0]),
                         ["inst", "losses", "pnl", "trades", "win_rate", "wins"])

    def test_win_rate_rounded_to_one_decimal(self):
        out = build_inst_leaderboard({"BTC": _s(3, 1, 1, 0.0)})
        self.assertEqual(out[0]["win_rate"], 33.3)

    def test_win_rate_zero_trades_is_zero_not_divide_error(self):
        out = build_inst_leaderboard({"BTC": _s(0, 0, 0, 0.0)})
        self.assertEqual(out[0]["win_rate"], 0.0, "trades==0 时给 0.0（不是除零）")

    def test_pnl_rounded_to_two(self):
        out = build_inst_leaderboard({"BTC": _s(1, 1, 0, 12.345678)})
        self.assertEqual(out[0]["pnl"], 12.35)

    def test_counts_are_ints_unchanged(self):
        out = build_inst_leaderboard({"BTC": _s(3, 2, 1, 0.0)})
        for k in ("trades", "wins", "losses"):
            self.assertIsInstance(out[0][k], int, k)

    def test_ordering_is_pnl_desc(self):
        out = build_inst_leaderboard({
            "A": _s(1, 0, 1, -5.0),
            "B": _s(1, 1, 0, 20.0),
            "C": _s(1, 1, 0, 7.0),
        })
        self.assertEqual([r["inst"] for r in out], ["B", "C", "A"])

    def test_negative_pnl_sorts_last(self):
        out = build_inst_leaderboard({
            "X": _s(1, 0, 1, 0.0),
            "Y": _s(1, 0, 1, -1.0),
        })
        self.assertEqual([r["inst"] for r in out], ["X", "Y"])


class WinRateDenominatorTest(unittest.TestCase):
    """**核心口径**：分母是 `trades`（含尘埃单），不是 `wins + losses`。"""

    def test_denominator_includes_dust_trades(self):
        """5 笔里 2 盈 1 亏、另 2 笔是尘埃（不计盈亏）→ 胜率 40%，不是 66.7%。

        `trade_stats` 的口径是：尘埃单**计入** `trades` 但**不计入** `wins`/`losses`。
        故 `wins + losses = 3` 而 `trades = 5`。用错分母会得到 66.7%。
        """
        out = build_inst_leaderboard({"BTC": _s(5, 2, 1, 3.0)})
        self.assertEqual(out[0]["win_rate"], 40.0,
                         "分母必须是 trades(5)：2/5=40%")
        self.assertNotEqual(out[0]["win_rate"], 66.7,
                            "若得到 66.7% 说明分母被改成了 wins+losses")

    def test_dust_only_instrument_has_zero_win_rate(self):
        out = build_inst_leaderboard({"DOGE": _s(3, 0, 0, 0.001)})
        self.assertEqual(out[0]["win_rate"], 0.0)
        self.assertEqual(out[0]["trades"], 3, "尘埃单仍计入 trades")

    def test_full_win_rate(self):
        out = build_inst_leaderboard({"BTC": _s(4, 4, 0, 10.0)})
        self.assertEqual(out[0]["win_rate"], 100.0)


class OrderingStabilityTest(unittest.TestCase):
    """相等 pnl 时保持 `by_inst` 插入顺序（不得加二级排序键）。"""

    def test_equal_pnl_keeps_insertion_order(self):
        by_inst = {"AAA": _s(1, 1, 0, 5.0),
                   "BBB": _s(1, 1, 0, 5.0),
                   "CCC": _s(1, 1, 0, 5.0)}
        out = build_inst_leaderboard(by_inst)
        self.assertEqual([r["inst"] for r in out], ["AAA", "BBB", "CCC"],
                         "相等 pnl 应按 by_inst 插入顺序（Python sort 稳定）")

    def test_equal_pnl_preserves_a_different_insertion_order(self):
        by_inst = {"CCC": _s(1, 1, 0, 5.0),
                   "AAA": _s(1, 1, 0, 5.0)}
        out = build_inst_leaderboard(by_inst)
        self.assertEqual([r["inst"] for r in out], ["CCC", "AAA"])


class MutationTest(unittest.TestCase):
    def test_input_not_mutated(self):
        by_inst = {"BTC": _s(2, 1, 1, 3.0)}
        before = {k: dict(v) for k, v in by_inst.items()}
        build_inst_leaderboard(by_inst)
        self.assertEqual(by_inst, before, "不得修改入参")

    def test_returns_fresh_rows(self):
        by_inst = {"BTC": _s(2, 1, 1, 3.0)}
        a = build_inst_leaderboard(by_inst)
        b = build_inst_leaderboard(by_inst)
        self.assertIsNot(a, b)
        self.assertIsNot(a[0], b[0])

    def test_row_does_not_alias_input_dict(self):
        by_inst = {"BTC": _s(2, 1, 1, 3.0)}
        out = build_inst_leaderboard(by_inst)
        out[0]["wins"] = 999
        self.assertEqual(by_inst["BTC"]["wins"], 1)


class RandomParityTest(unittest.TestCase):
    def test_random_parity(self):
        rng = random.Random(20261003)
        names = ["BTC", "ETH", "SOL", "DOGE", "PEPE"]
        for _ in range(4000):
            by_inst = {}
            for n in rng.sample(names, rng.randint(0, len(names))):
                tr = rng.randint(0, 12)
                w = rng.randint(0, tr)
                l = rng.randint(0, tr - w)
                by_inst[n] = _s(tr, w, l, rng.choice([-9.99, -0.005, 0.0, 12.345, 1e3]))
            self.assertEqual(build_inst_leaderboard(by_inst), _legacy(by_inst),
                             f"分叉: {by_inst}")


class WiringTest(unittest.TestCase):
    def test_impl_in_submodule_not_facade(self):
        app_src = APP.read_text(encoding="utf-8")
        mod_src = MODULE.read_text(encoding="utf-8")
        self.assertIn("def build_inst_leaderboard(", mod_src)
        self.assertNotIn("def build_inst_leaderboard(", app_src)
        # 第九十五刀：调用点随相位 4 聚合段迁入 trade_stats.aggregate_bills_and_metrics
        stats_src = STATS.read_text(encoding="utf-8")
        self.assertIn("_core_build_inst_leaderboard(by_inst)", stats_src)
        self.assertIn("_core_build_inst_leaderboard=_core_build_inst_leaderboard", app_src,
                      "门面仍须注入实现（调用期解析 ⇒ patch 面有效）")

    def test_facade_no_longer_contains_the_inline_loop(self):
        app_src = APP.read_text(encoding="utf-8")
        for gone in ('inst_leaderboard.append', 'inst_leaderboard.sort'):
            self.assertNotIn(gone, app_src, f"门面仍残留内联片段 {gone!r}")

    def test_payload_key_still_present(self):
        """接口不变：载荷里仍要有 `leaderboard` 键。

        ⚠️ 这段字面量**已经没有**在 `astra_backend/dashboard_cache.py` 里了 ——
        阶段 4·B3 第三十六刀把整个 `CACHE_DATA` 字面量（92 行）搬进了
        `astra_backend/dashboard_payload/cache_payload.py`。
        故断言必须**同时**接受"在载荷装配模块里"这个位置，
        否则测试会把一次**等价搬迁**误报成接口变更。

        改这条时我保留了原意（键仍在、且仍取自 `inst_leaderboard`），
        只是承认它的**位置**变了。
        """
        sources = {
            "门面": APP.read_text(encoding="utf-8"),
            "载荷装配模块": (ROOT / "astra_backend" / "dashboard_payload"
                             / "cache_payload.py").read_text(encoding="utf-8"),
        }
        hits = [name for name, src in sources.items()
                if '"leaderboard": inst_leaderboard' in src]
        self.assertEqual(hits, ["载荷装配模块"],
                         "`leaderboard` 键应恰好出现在载荷装配模块里一处")

    def test_module_is_pure(self):
        """函数体只读入参，不读模块级/全局。

        ⚠️ 这条我连误报两轮，都是为了同一件事：**"未绑定的名字"不等于"外部依赖"**。

        - 第一版把**注解**算进去了：`-> List[Dict[str, Any]]` 里的
          `List`/`Dict`/`Any` 在 AST 里也是 `Name(Load)`；
        - 第二版排除了注解，却仍把 `lambda x: x["pnl"]` 的 **lambda 形参** `x`
          当成外部名。

        故改用**作用域感知**的绑定集合：赋值目标、for/with/except 目标、
        **推导式与生成器的目标**、**lambda 与嵌套函数的形参**都算已绑定。
        这样"自由名"才真的是"自由"。
        """
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        bound = _bound_names(fn)
        loaded = _loaded_names(fn)
        import builtins
        free = loaded - bound - set(dir(builtins))
        self.assertEqual(free, set(), f"存在未绑定的外部名: {sorted(free)}")

    def test_annassign_annotation_is_not_a_dependency(self):
        """带注解的局部赋值不得把 `List`/`Dict` 算成外部依赖。"""
        src = ("def f(rows):\n"
               "    out: List[Dict[str, Any]] = []\n"
               "    return out\n")
        fn = ast.parse(src).body[0]
        import builtins
        free = _loaded_names(fn) - _bound_names(fn) - set(dir(builtins))
        self.assertEqual(free, set(), f"注解被误算成依赖: {sorted(free)}")

    def test_free_name_check_actually_works(self):
        """反向验证：真加一个外部名必须被抓到（防这条闸空转）。"""
        src = ("def build_inst_leaderboard(by_inst):\n"
               "    return [{**s, 'x': OUTSIDE_GLOBAL} for s in by_inst]\n")
        tree = ast.parse(src)
        fn = tree.body[0]
        bound = _bound_names(fn)
        loaded = _loaded_names(fn)
        import builtins
        free = loaded - bound - set(dir(builtins))
        self.assertIn("OUTSIDE_GLOBAL", free)

    def test_binder_handles_lambda_and_comprehension(self):
        """lambda 形参与推导式目标不得算作自由名。"""
        src = ("def f(items):\n"
               "    rows = [x for x in items]\n"
               "    rows.sort(key=lambda r: r['pnl'], reverse=True)\n"
               "    return rows\n")
        fn = ast.parse(src).body[0]
        bound = _bound_names(fn)
        self.assertIn("x", bound)
        self.assertIn("r", bound)

    def test_module_does_not_import_dashboard(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertFalse(a.name.startswith("astra_backend.dashboard_cache"))
            elif isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith("astra_backend.dashboard_cache"))


if __name__ == "__main__":
    unittest.main()
