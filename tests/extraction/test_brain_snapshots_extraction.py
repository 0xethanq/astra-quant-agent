r"""brain 本地快照落盘抽取对拍门（B3·第九十九刀）。

`scripts/ai_brain_trader.py::execute_batch_ai_brain_cycle` 里三处"写本地快照"
→ `scripts/brain/snapshots.py`（因子库自更新 / 演算快照 / 提示词快照）。

判据：段体 **AST 逐字**（基线 `8002d5c` 的语句下标 21/23/28）、调用点逐个同名恰好一次、
自由名可解析；另加**三个真实落盘行为例**（文件内容 + 无 `.tmp` 残留），
全部指向 `tempfile` 目录（离线套件要求零生产写入）。
"""
from __future__ import annotations

import ast
import builtins
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "8002d5c"                  # 本刀动工前最后提交（第九十八刀收口）
FACADE = ROOT / "scripts" / "ai_brain_trader.py"
MOD = ROOT / "scripts" / "brain" / "snapshots.py"
OWNER = "execute_batch_ai_brain_cycle"
SPECS = {                        # 函数名 -> 基线语句下标
    "update_factor_library_snapshot": 21,
    "write_calculus_snapshot": 23,
    "write_prompt_snapshot": 28,
}


def _baseline_fn() -> ast.FunctionDef:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/ai_brain_trader.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return next(n for n in ast.parse(normalize(r.stdout)).body
                if isinstance(n, ast.FunctionDef) and n.name == OWNER)


def _impl(name: str) -> ast.FunctionDef:
    t = ast.parse(MOD.read_text(encoding="utf-8"))
    return next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _facade_calls() -> dict:
    tree = ast.parse(FACADE.read_text(encoding="utf-8"))
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in SPECS:
            out.setdefault(n.func.id, n)
    return out


class BrainSnapshotsVerbatimTest(unittest.TestCase):
    def test_calls_pass_every_parameter_once_same_name(self):
        calls = _facade_calls()
        for name in SPECS:
            with self.subTest(fn=name):
                params = [a.arg for a in _impl(name).args.kwonlyargs]
                call = calls[name]
                self.assertEqual(call.args, [])
                self.assertEqual([k.arg for k in call.keywords], params)
                for k in call.keywords:
                    self.assertEqual(ast.unparse(k.value), k.arg, f"{name}.{k.arg} 非同形传参")

    def test_no_undeclared_free_names(self):
        module = ast.parse(MOD.read_text(encoding="utf-8"))
        mod_names = {n.name for n in module.body if isinstance(n, ast.FunctionDef)}
        for name in SPECS:
            with self.subTest(fn=name):
                fn = _impl(name)
                local = {a.arg for a in fn.args.kwonlyargs}
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
                    if isinstance(n, (ast.Import, ast.ImportFrom)):
                        for a in n.names:
                            local.add(a.asname or a.name.split(".")[0])
                reads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
                         and isinstance(n.ctx, ast.Load)}
                missing = sorted(reads - local - set(dir(builtins)) - mod_names)
                self.assertEqual(missing, [], f"{name} 解析不到: {missing}")

    # ---------- 行为例：三个落盘（全部指向临时目录） ----------

    def test_write_calculus_snapshot_writes_json_and_leaves_no_tmp(self):
        from scripts.brain import snapshots as S
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "calculus.json")
            S.write_calculus_snapshot(
                packages=[{"name": "BTC", "instId": "BTC-USDT-SWAP", "calculus": {"x": 1}}],
                time_str="2026-09-15 11:00:00", CALCULUS_SNAPSHOT_FILE=target,
                json=json, os=os)
            self.assertTrue(os.path.exists(target), "演算快照必须落盘")
            self.assertFalse(os.path.exists(target + ".tmp"), "不得残留 .tmp")
            got = json.loads(Path(target).read_text(encoding="utf-8"))
            self.assertEqual(got["engine"], "causal-calculus-v1")
            self.assertEqual(got["timestamp"], "2026-09-15 11:00:00")
            self.assertEqual(got["instruments"][0]["instId"], "BTC-USDT-SWAP")

    def test_write_prompt_snapshot_writes_rendered_text(self):
        from scripts.brain import snapshots as S
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "prompt.txt")
            S.write_prompt_snapshot(
                effective_system_prompt="SYS", prompt="USER", time_str="t",
                AI_LAST_PROMPT_FILE=target,
                _build_effective_prompt_text=lambda **k: f"[{k['effective_system_prompt']}|{k['prompt']}]",
                os=os)
            self.assertEqual(Path(target).read_text(encoding="utf-8"), "[SYS|USER]")
            self.assertFalse(os.path.exists(target + ".tmp"))

    def test_update_factor_library_calls_the_module_and_swallows_failure(self):
        """注入**假模块**（不依赖 sys.path 顺序/已导入状态）验证真的调用了自更新。"""
        import types as _types
        from scripts.brain import snapshots as S
        fake = _types.ModuleType("factor_library")
        fake.CALLS = []
        fake.update_factor_library = lambda: fake.CALLS.append(1)
        with tempfile.TemporaryDirectory() as td:
            old_path = list(sys.path)
            old_mod = sys.modules.get("factor_library")
            sys.modules["factor_library"] = fake          # 段内 `import factor_library` 命中它
            try:
                S.update_factor_library_snapshot(WORKSPACE_DIR=td, os=os, sys=sys)
            finally:
                sys.path[:] = old_path
                if old_mod is None:
                    sys.modules.pop("factor_library", None)
                else:
                    sys.modules["factor_library"] = old_mod
        self.assertEqual(fake.CALLS, [1], "必须真的调用因子库自更新")
        # 失败路径：**同样走替身**（让它抛错）⇒ 只告警不抛。
        # ⚠️ 首版这里传了一个不存在的目录，于是段内 `import factor_library` 落到**真实**
        # 模块并触发自更新 → 真的写了 `data/factor_library_snapshot.json.tmp`，
        # 被离线守卫 `CONFIG_WRITE_ATTEMPTS` 当场抓到。测试的失败路径也必须封闭。
        def _boom():
            raise RuntimeError("boom")
        fake.update_factor_library = _boom
        old_mod = sys.modules.get("factor_library")
        sys.modules["factor_library"] = fake
        try:
            S.update_factor_library_snapshot(WORKSPACE_DIR="/nonexistent-dir-xyz",
                                             os=os, sys=sys)   # 不得抛出
        finally:
            if old_mod is None:
                sys.modules.pop("factor_library", None)
            else:
                sys.modules["factor_library"] = old_mod

if __name__ == "__main__":
    unittest.main()
