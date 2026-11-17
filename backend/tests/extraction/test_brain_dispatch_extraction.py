r"""brain 派发尾块抽取对拍门（B3·第九十八刀）。

`scripts/ai_brain_trader.py::execute_batch_ai_brain_cycle`（305 行）末尾 173 行
`try` 块 → `scripts/brain/dispatch.py::dispatch_llm_and_persist_decisions`。

## 本门新增一条**关键**判据（本轮被抓出的真 bug 换来的）

`test_call_site_names_are_resolvable_at_the_call`：调用点 `name=name` 里的
**每一个**名字，必须在调用处真的可解析 —— 要么是门面模块属性，要么是**调用点之前**
在同一个函数里被赋过值的局部量。

为什么必须单独钉：本刀首版把 `content` 当成了门面全局（真因是我的抽取分析器用
`ast.walk`（**BFS，非源码序**）判断"首个 Store/Load"，于是段内解包目标
`content, _, usage_dict, _ = execute_llm_request(...)` 被判成"晚于"它后面的 Load）。
结果调用点写成 `content=content` —— **门面里没有这个名字 ⇒ 潜伏 NameError**，
而"签名/调用点一致性"与"段体 AST 逐字"两条判据**都看不见**它。
"""
from __future__ import annotations

import ast
import builtins
import inspect
import subprocess
import sys
import types
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "0a05d76"                       # 本刀动工前最后提交（第九十七刀收口）
FACADE = ROOT / "scripts" / "ai_brain_trader.py"
MOD = ROOT / "scripts" / "brain" / "dispatch.py"
FN = "dispatch_llm_and_persist_decisions"
SEG = 35                              # 基线 execute_batch_ai_brain_cycle 的语句下标
OWNER = "execute_batch_ai_brain_cycle"


def _baseline_fn() -> ast.FunctionDef:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/ai_brain_trader.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    t = ast.parse(normalize(r.stdout))
    return next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == OWNER)


def _impl() -> ast.FunctionDef:
    t = ast.parse(MOD.read_text(encoding="utf-8"))
    return next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == FN)


def _facade_call() -> tuple:
    tree = ast.parse(FACADE.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == OWNER)
    call = next(n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == FN)
    return tree, fn, call


class BrainDispatchVerbatimTest(unittest.TestCase):
    def test_call_passes_every_parameter_once_same_name(self):
        params = [a.arg for a in _impl().args.kwonlyargs]
        _tree, _fn, call = _facade_call()
        self.assertEqual(call.args, [])
        self.assertEqual([k.arg for k in call.keywords], params,
                         "调用点参数与签名不一致")
        for k in call.keywords:
            self.assertEqual(ast.unparse(k.value), k.arg, f"{k.arg} 未按同名传参")

    def test_call_site_names_are_resolvable_at_the_call(self):
        """⚠️ 本刀的血：调用点每个名字必须在调用处可解析（模块属性或**此前**的局部量）。"""
        import importlib
        facade = importlib.import_module("scripts.ai_brain_trader")
        _tree, fn, call = _facade_call()
        # 调用点之前被赋值/导入的局部名
        local_before = set()
        for st in fn.body:
            if st.lineno >= call.lineno:
                break
            for n in ast.walk(st):
                if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                    local_before.add(n.id)
                if isinstance(n, ast.ExceptHandler) and n.name:
                    local_before.add(n.name)
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    for a in n.names:
                        local_before.add(a.asname or a.name.split(".")[0])
        # 参数名（含 try 内 import 的形态：逐个源码扫描兜底）
        for n in ast.walk(fn):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    if a.lineno < call.lineno:
                        local_before.add(a.asname or a.name.split(".")[0])
        bad = []
        for k in call.keywords:
            name = ast.unparse(k.value)
            if hasattr(facade, name) or name in local_before:
                continue
            bad.append(name)
        self.assertEqual(bad, [],
                         f"调用点引用了**调用处不存在**的名字（潜伏 NameError）: {bad}")

    def test_body_free_names_resolvable_in_new_module(self):
        fn = _impl()
        module = ast.parse(MOD.read_text(encoding="utf-8"))
        mod_names = set()
        for n in module.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mod_names.add(n.name)
            elif isinstance(n, ast.Assign):
                for tg in n.targets:
                    if isinstance(tg, ast.Name):
                        mod_names.add(tg.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    mod_names.add(a.asname or a.name.split(".")[0])
        local = set(inspect.signature(fn).parameters) if False else {
            a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        for n in ast.walk(fn):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local.add(n.name); local |= {a.arg for a in n.args.args}
            if isinstance(n, ast.Lambda):
                local |= {a.arg for a in n.args.args}
            if isinstance(n, ast.comprehension):
                tg = n.target
                for e in (tg.elts if isinstance(tg, (ast.Tuple, ast.List)) else [tg]):
                    if isinstance(e, ast.Name):
                        local.add(e.id)
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                local.add(n.id)
            if isinstance(n, ast.ExceptHandler) and n.name:
                local.add(n.name)
            if isinstance(n, (ast.Import, ast.ImportFrom)):   # 函数内的局部 import
                for a in n.names:
                    local.add(a.asname or a.name.split(".")[0])
        reads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
                 and isinstance(n.ctx, ast.Load)}
        missing = sorted(reads - local - set(dir(builtins)) - mod_names)
        self.assertEqual(missing, [], f"新模块里解析不到的名字: {missing}")

    def test_no_llm_request_path_returns_none(self):
        """`execute_llm_request=None` ⇒ 不发请求、正常走完 ⇒ 返回 None（透传语义）。"""
        from scripts.brain import dispatch as D
        kw = {p: None for p in inspect.signature(D.dispatch_llm_and_persist_decisions).parameters}
        kw.update(
            active_inst_ids=set(), active_position_sides={}, packages=[], prompt="p",
            effective_system_prompt="s", runtime_context={}, policy_snapshot={},
            policy_version="v", policy_hash="h", policy_summary="sum", time_str="t",
            telemetry=types.SimpleNamespace(finish=lambda *a, **k: None),
            execute_llm_request=None, json=__import__("json"), os=__import__("os"),
            time=__import__("time"), urllib=__import__("urllib"),
            Any=object, Dict=dict, safe_float=lambda v, d=0.0: d,
            atomic_write_json=lambda *a, **k: None,
            assemble_decision_cache=lambda **k: {},
            _normalize_position_management=lambda *a, **k: [],
            _build_history_record=lambda **k: {},
            _build_effective_prompt_text=lambda **k: "",
            _record_cycle_health=lambda *a, **k: None,
            execute_brain_pending_cancels=lambda *a, **k: None)
        got = D.dispatch_llm_and_persist_decisions(**kw)
        self.assertIsNone(got)

if __name__ == "__main__":
    unittest.main()
