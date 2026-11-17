r"""抽取调用点的**名字可解析性**总审计门（第九十八刀）。

## 为什么需要这条门

"抽取"这类重构的门通常有两条：①段体 AST 逐字 ②调用点与签名逐项同名一致。
**两条都看不见下面这个真 bug**：

第九十八刀首版把 `content` 当成了门面全局 —— 真因是抽取分析器用 `ast.walk`
（**BFS，不是源码序**）判断"首个 Store/Load"，于是段内解包目标
`content, _, usage_dict, _ = execute_llm_request(...)` 被判成"晚于"它后面的 Load，
归类成"需要从门面注入的全局名"。结果调用点写成 `content=content`，
而门面命名空间里**没有**这个名字 ⇒ 潜伏 NameError。
签名一致 ✓、段体逐字 ✓、自由名可解析 ✓ —— 全绿。

## 本门怎么做

**动态发现**：扫描门面文件里的所有调用，凡"实参全是 `name=name` 同形"的即视为
抽取调用点（这正是本仓抽取的既定形态），然后断言每个名字在**调用处**可解析：

- 门面模块属性（真全局），或
- 该函数的**形参**，或
- 调用点**之前**在函数内被赋值/导入/except-as 的局部名。

动态发现意味着**未来的抽取自动被覆盖**，无需登记。
"""
from __future__ import annotations

import ast
import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

FACADES = (
    "scripts/ai_factor_trader.py",
    "scripts/ai_brain_trader.py",
    "scripts/sync_full_ledger.py",
    "scripts/self_improvement_engine.py",
    "astra_backend/dashboard_cache.py",
    "astra_backend/llm/store.py",
    "astra_backend/llm_manager.py",
    "astra_backend/council_manager.py",
    "astra_backend/policy_snapshot.py",
)
PKG_HINT = ("scripts.trader.", "scripts.brain.", "astra_backend.dashboard_payload.",
            "scripts.")


def _resolvable_names(fn: ast.FunctionDef, call: ast.Call, facade) -> set:
    got = set()
    # 形参（含 kw-only 与 *args/**kwargs）
    a = fn.args
    for arg in list(a.args) + list(a.kwonlyargs) + list(a.posonlyargs):
        got.add(arg.arg)
    if a.vararg:
        got.add(a.vararg.arg)
    if a.kwarg:
        got.add(a.kwarg.arg)
    # 调用点之前的局部绑定
    for st in fn.body:
        if st.lineno >= call.lineno:
            break
        for n in ast.walk(st):
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                got.add(n.id)
            if isinstance(n, ast.ExceptHandler) and n.name:
                got.add(n.name)
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for al in n.names:
                    got.add(al.asname or al.name.split(".")[0])
    # try 内 import（晚于 break 的语句里也可能有）
    for n in ast.walk(fn):
        if isinstance(n, (ast.Import, ast.ImportFrom)) and n.lineno < call.lineno:
            for al in n.names:
                got.add(al.asname or al.name.split(".")[0])
    # 模块属性（**含 dunder**：`__version__` 就是被注入的真全局名之一）
    got |= set(dir(facade))
    return got


def _extraction_calls(path: str):
    """产出 (owner_fn, call) —— 只挑"实参全为 name=name 同形"的调用。"""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            if not call.keywords or call.args:
                continue
            if not all(k.arg == ast.unparse(k.value) for k in call.keywords):
                continue
            if not isinstance(call.func, ast.Name):
                continue
            yield fn, call


def _module_level_names(tree: ast.Module) -> set:
    """门面模块级可解析的名字（def / import / 赋值目标）。"""
    got = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            got.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                got.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.Assign):
            for tg in n.targets:
                if isinstance(tg, ast.Name):
                    got.add(tg.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            got.add(n.target.id)
    return got


def _names_bound_before(fn: ast.AST, call: ast.Call) -> set:
    got = set()
    a = getattr(fn, "args", None)
    if a is not None:
        for arg in list(a.args) + list(a.kwonlyargs):
            got.add(arg.arg)
        if a.vararg:
            got.add(a.vararg.arg)
        if a.kwarg:
            got.add(a.kwarg.arg)
    for st in fn.body:
        if st.lineno >= call.lineno:
            break
        for n in ast.walk(st):
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                got.add(n.id)
            if isinstance(n, ast.ExceptHandler) and n.name:
                got.add(n.name)
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for al in n.names:
                    got.add(al.asname or al.name.split(".")[0])
    return got


class ExtractionCallSiteNamesTest(unittest.TestCase):
    def test_every_injected_name_resolves_at_the_call_site(self):
        checked_calls = checked_names = 0
        problems = []
        for rel in FACADES:
            facade = importlib.import_module(rel[:-3].replace("/", "."))
            for fn, call in _extraction_calls(rel):
                ok = _resolvable_names(fn, call, facade)
                bad = []
                for k in call.keywords:
                    name = ast.unparse(k.value)
                    checked_names += 1
                    if name not in ok:
                        bad.append(name)
                checked_calls += 1
                if bad:
                    problems.append(f"{rel}::{fn.name} → {call.func.id}() L{call.lineno}: {bad}")
        self.assertGreater(checked_calls, 10,
                           f"只发现 {checked_calls} 处抽取调用点，发现逻辑可疑")
        self.assertEqual(problems, [],
                         "抽取调用点引用了**调用处不存在**的名字（潜伏 NameError）：\n  "
                         + "\n  ".join(problems))
        # 防空：确认确实检查了足量名字
        self.assertGreater(checked_names, 100)

    def test_every_extraction_callee_name_is_resolvable(self):
        """**被调用名**也必须可解析。

        这条是第一百零八刀的教训换来的：那次抽完两段后忘了把新函数 import 进门面，
        调用点 `normalize_providers_into_result(...)` 直接 NameError。
        上面那条"kwarg 值可解析"看不见它 —— 因为被调用名**不是** kwarg。
        """
        problems = []
        for rel in FACADES:
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
            mod_names = _module_level_names(tree)
            for fn, call in _extraction_calls(rel):
                callee = call.func.id
                if callee in mod_names or callee in _names_bound_before(fn, call):
                    continue
                problems.append(f"{rel}::{fn.name} → {callee}() L{call.lineno}")
        self.assertEqual(problems, [],
                         "抽取调用点的**被调用名**在门面/函数内在调用处不可解析：\n  "
                         + "\n  ".join(problems))


if __name__ == "__main__":
    unittest.main()
