"""适配器**能力差异**调用必须带守卫（第一百九十二刀；多所拆除后收口为单所口径）。

## 为什么

适配器实现之间的能力**并不一致**。真机踩到的那次是：`cancel_orphan_attributed_legs`
直接 `ad.cancel_price_order(leg_id)`，而只有某一个实现有这个方法 ⇒ 对另一个实现恒
`AttributeError` ⇒ 腿撤不掉（而它恰是孤儿腿最多的那一所）。这类调用的失败往往是
**被 except 吞掉**的（"读不到/做不到"静默变成"没有"），所以必须靠门钉住。

多所执行面（含 `execution_router` / `venue_protection` 的跨所清理）已随 OKX 专用化
移除，**能力差异的来源也随之变了**：不再是"三家适配器的差异"，而是
"`OKXAdapter` / `OKXPublicAdapter` / `SandboxExchangeAdapter` 这几个**实现**之间的差异"。
本门因此把矩阵改成**从实现集合动态推导**（不写死任何场所名单）：
凡"至少一个实现有、至少一个实现没有"的公共方法，调用它就必须带守卫。

## 判据

在 `scripts/`、`astra_backend/`、`astra_gateway/` 里，对上述方法的调用，
必须能在其所在函数里找到下列**任一**守卫：

1. `hasattr(同一接收者, "方法")` / `getattr(同一接收者, "方法", …)` —— 能力探针；
2. **按实现分流**：形如 `_v == "okx"` 的字符串比较（结构化识别）；
3. **接收者本身绑定到某个实现**：`ad = get_adapter("okx", …)`，或名字里含实现名
   （`okx_rest` / `sandbox_sb` …）且该实现确有这个方法；
4. `self.方法(...)` —— 适配器**自身内部**调用（只有它自己有这个方法）；
5. 显式允许清单（附理由）。

另附非空自检与牙齿（合成的无守卫 `ad.cancel_price_order(x)` 必被抓）。
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# 2026-10：`plugins/` 随策略插件系统整套裁撤 ⇒ 不再是代码根（`test_scan_scope_is_explicit`
# 会动态推导代码根并要求本门扫全，多数一个不存在的根同样是范围错误）。
SCAN_DIRS = ("scripts", "astra_backend", "astra_gateway")

#: 需要比对能力差异的**实现**集合（基类不参与：基类声明的是契约，不是差异来源）。
#: ⚠️ 只收 `astra_backend/exchanges/` 里的**交易所适配器实现**；
#: `sandbox/adapter.py` 是测试替身（`reset`/`step` 之类是它自己的回放契约），
#: 把它算进来会把回放实现自己的调用点误判成"无守卫"。
IMPL_NAMES = ("okx", "okx_public")
#: 接收者名字里出现即视为"绑定到某实现"的词。
IMPL_WORDS = set(IMPL_NAMES)
#: 形如 `v` / `venue` / `_v` 的"场所名变量"（用于结构化识别按所分流）
VENUEISH_NAMES = {"v", "venue", "_v", "_gv", "target_venue", "venue_key", "name", "self_venue"}
#: 显式放行（附理由）。当前为空 —— 守卫都能结构化识别。
ALLOWLIST: dict[tuple[str, str, int], str] = {}


def adapter_classes() -> dict:
    """所有**具体交易所适配器实现**（差异来源）。"""
    from astra_backend.exchanges import OKXAdapter, OKXPublicAdapter
    return {"okx": OKXAdapter, "okx_public": OKXPublicAdapter}


def capability_gap_methods(classes) -> dict:
    """**基类契约之外**的公共能力 ⇒ 调用它们就得带守卫。

    单所口径下"各所有没有"这个差异源消失了，但**契约差异**仍在：
    凡 `BaseExchangeAdapter` 没有声明、只在某个具体实现上存在的公共方法，
    调用方都不能假定"任何适配器都有它"—— 这正是那次真事故的形状
    （`ad.cancel_price_order(leg_id)` 对没有该方法的实现恒 `AttributeError`）。
    """
    from astra_backend.exchanges.base import BaseExchangeAdapter
    base = {m for m in dir(BaseExchangeAdapter)
            if not m.startswith("_") and callable(getattr(BaseExchangeAdapter, m, None))}
    out = {}
    for m in sorted({m for c in classes.values() for m in dir(c)
                     if not m.startswith("_") and callable(getattr(c, m, None))}):
        if m in base:
            continue
        have = [v for v, c in classes.items() if hasattr(c, m)]
        if 0 < len(have) < len(classes):
            out[m] = have
        elif have:
            # 所有具体实现都有、但基类没有声明 ⇒ 同样不能假定"任何适配器都有"
            out[m] = sorted(classes)
    return out


def _enclosing(tree: ast.AST, lineno: int):
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= lineno <= (node.end_lineno or node.lineno):
                if best is None or node.lineno >= best.lineno:
                    best = node
    return best


def impl_bound_by_binding(tree, fn, recv: str, method: str, gaps: dict):
    """③ 接收者是否**由 `get_adapter("<impl>", …)` 绑定**，且该实现有这个方法。"""
    scopes = [n for n in (fn, tree) if n is not None]
    for scope in scopes:
        for node in ast.walk(scope):
            if not isinstance(node, ast.Assign):
                continue
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if recv not in targets:
                continue
            value = node.value
            if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id == "get_adapter"):
                continue
            impl = None
            for arg in value.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    impl = arg.value.lower()
                    break
            if impl and method in gaps and impl in gaps[method]:
                return f"bound-to-{impl}"
    return None


def guard_kind(fn, recv: str, method: str, *, tree=None, gaps=None):
    """返回守卫类型名，或 None（无守卫）。"""
    if recv == "self":
        return "self-internal"                                   # ④
    named = [w for w in IMPL_WORDS if w in recv.lower()]
    if named and gaps is not None:
        # ③a 名字里带实现 ⇒ 只在该实现**确实有这个方法**时才算守卫；
        # 若带的是"没有该方法的实现"⇒ **不豁免**，这正是危险。
        if any(w in gaps.get(method, []) for w in named):
            return f"impl-bound-name:{'/'.join(sorted(named))}"
    if tree is not None and gaps is not None:
        bound = impl_bound_by_binding(tree, fn, recv, method, gaps)   # ③b
        if bound:
            return bound
    if fn is None:
        return None
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("hasattr", "getattr"):       # ①
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                    and node.args[1].value == method and ast.unparse(node.args[0]) == recv:
                return f"{node.func.id}-probe"
        if isinstance(node, ast.Compare):                         # ②
            ops = [ast.unparse(o) for o in [node.left] + list(node.comparators)]
            lits = {n.value for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            if (lits & IMPL_WORDS) and any(o in VENUEISH_NAMES for o in ops):
                return "impl-branch"
    return None


def find_unguarded_calls(source: str, rel_path: str, gaps: dict):
    out = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        if method not in gaps:
            continue
        recv = ast.unparse(node.func.value)
        fn = _enclosing(tree, node.lineno)
        if guard_kind(fn, recv, method, tree=tree, gaps=gaps):
            continue
        if (rel_path, method, node.lineno) in ALLOWLIST:
            continue
        out.append((node.lineno, method, recv, fn.name if fn else "<module>", gaps[method]))
    return out


def _iter_py():
    for root in SCAN_DIRS:
        for path in sorted((ROOT / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


class AdapterCapabilityCallsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gaps = capability_gap_methods(adapter_classes())

    def test_every_capability_gap_call_has_a_guard(self):
        problems = []
        for path in _iter_py():
            rel = str(path.relative_to(ROOT))
            for line, method, recv, fname, have in find_unguarded_calls(
                    path.read_text(encoding="utf-8"), rel, self.gaps):
                problems.append(f"{rel}:{line} ({fname}) {recv}.{method}(…) 仅 {have} 有该方法")
        self.assertEqual(problems, [], "适配器能力差异调用没有守卫（另一实现会 AttributeError，"
                                       "且常被 except 吞掉）：\n" + "\n".join(problems))

    def test_matrix_is_not_vacuous(self):
        self.assertGreaterEqual(len(self.gaps), 3,
                                f"实现间的能力差异只推出 {len(self.gaps)} 个 ⇒ 门可能已与实现脱节")
        for must in ("detect_position_mode", "open_orders"):
            self.assertIn(must, self.gaps,
                          f"{must} 应被识别为「并非所有实现都有」的能力（矩阵与实现脱节）")

    def test_call_sites_are_actually_scanned(self):
        """扫描器必须**真的看见**调用点（防路径写错导致空转）。

        ⚠️ 单所口径下调用点数量大幅下降：原先 15+ 处大多是跨所分支（已随多所执行面
        删除）。判据因此改成**点名**：至少要在 `scripts/` 侧看见一个真实调用点 ——
        只看适配器实现内部（`self.`）不算，那证明不了调用侧被扫到。
        """
        seen = []
        for path in _iter_py():
            rel = str(path.relative_to(ROOT))
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr in self.gaps:
                    seen.append((rel, node.func.attr))
        self.assertTrue(seen, "一个相关调用点都没扫到 ⇒ 门与实现脱节")
        self.assertTrue(any(rel.startswith("scripts/") for rel, _ in seen),
                        f"只在适配器定义内部看见调用点（{seen}）⇒ 调用侧可能漏扫")

    def test_teeth_on_unguarded_call(self):
        # ⚠️ 这张表必须覆盖下面每个用例用到的方法 —— 否则 `find_unguarded_calls` 根本不看它，
        # 断言 `== []` 就成了**空转**（本刀自己踩到过一次，见提交信息）。
        gaps = {"cancel_price_order": ["okx"], "cancel_algo_order": ["sandbox"]}
        unguarded = ("def f(ad, oid):\n"
                     "    return ad.cancel_price_order(oid)\n")
        self.assertTrue(find_unguarded_calls(unguarded, "scripts/x.py", gaps),
                        "无守卫的能力差异调用没被抓到 ⇒ 门没有牙齿")
        for guarded in (
            "def f(ad, oid):\n"
            "    if hasattr(ad, 'cancel_price_order'):\n"
            "        return ad.cancel_price_order(oid)\n",
            "def f(_v, ad, oid):\n"
            "    return ad.cancel_price_order(oid) if _v == 'okx' else None\n",
            "def f(okx_ad, oid):\n"
            "    return okx_ad.cancel_price_order(oid)\n",
            # ③b：接收者由 get_adapter("sandbox") 绑定 ⇒ 该实现确有 cancel_algo_order ⇒ 合规
            "def f(oid):\n"
            "    ad_sb = get_adapter('sandbox', environment='demo')\n"
            "    return ad_sb.cancel_algo_order(algo_id=oid)\n",
            "class A:\n"
            "    def f(self, oid):\n"
            "        return self.cancel_price_order(oid)\n",
        ):
            self.assertEqual(find_unguarded_calls(guarded, "scripts/x.py", gaps), [],
                             f"合规写法被误判：{guarded[:40]!r}")
        # 反例：**绑错实现**必须被抓（okx 没有 cancel_algo_order）
        wrong_impl = ("def f(oid):\n"
                      "    ad_okx = get_adapter('okx', environment='demo')\n"
                      "    return ad_okx.cancel_algo_order(algo_id=oid)\n")
        self.assertTrue(find_unguarded_calls(wrong_impl, "scripts/x.py", gaps),
                        "把某实现专有方法调到**绑错实现**的接收者上没被抓到 ⇒ 门漏掉真实危险")

    def test_allowlist_entries_have_reasons(self):
        for key, reason in ALLOWLIST.items():
            self.assertTrue(str(reason).strip(), f"{key} 的放行理由不能为空")


if __name__ == "__main__":
    unittest.main()
