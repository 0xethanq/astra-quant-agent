r"""brain 前置解析抽取对拍门（B3·第一百刀）。

`execute_batch_ai_brain_cycle` 的两段前置解析 → `scripts/brain/runtime.py`：
`capture_policy_snapshot`（策略快照冻结 + 派生 version/hash/summary）、
`resolve_llm_runtime`（环境变量 → 运行时覆盖；失败置 `execute_llm_request=None`）。

## 本门把一条**规则**钉成判据

`test_non_definite_outputs_are_passed_in`：凡"段内**非必然绑定**"的输出，
**必须**同时出现在入参里（in-out）。理由是第九十二刀那次的真 bug：
段内条件赋值 + 上游曾无条件赋值 ⇒ 搬出函数边界后未命中分支就 `UnboundLocalError`。
本例两处正是如此：`policy_snapshot`（调用方可能已给值）与
`api_key`/`base_url`（段内 `... or base_url` 会读旧值）。
"""
from __future__ import annotations

import ast
import builtins
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "14477ff"                  # 本刀动工前最后提交（第九十九刀收口）
FACADE = ROOT / "scripts" / "ai_brain_trader.py"
MOD = ROOT / "scripts" / "brain" / "runtime.py"
OWNER = "execute_batch_ai_brain_cycle"
SPECS = {"capture_policy_snapshot": (6, 9), "resolve_llm_runtime": (29, 33)}


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
    out = {}
    for n in ast.walk(ast.parse(FACADE.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in SPECS:
            out.setdefault(n.func.id, n)
    return out


def _definite(stmts) -> set:
    """保守的"必然绑定"分析（与抽取工具同款规则）。"""
    got = set()
    for st in stmts:
        if isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            tgts = st.targets if isinstance(st, ast.Assign) else [st.target]
            for tg in tgts:
                if isinstance(tg, ast.Name):
                    got.add(tg.id)
                elif isinstance(tg, (ast.Tuple, ast.List)):
                    for e in tg.elts:
                        if isinstance(e, ast.Name):
                            got.add(e.id)
        elif isinstance(st, ast.With):
            for it in st.items:
                if isinstance(it.optional_vars, ast.Name):
                    got.add(it.optional_vars.id)
            got |= _definite(st.body)
        elif isinstance(st, (ast.Import, ast.ImportFrom)):
            for a in st.names:
                got.add(a.asname or a.name.split(".")[0])
        elif isinstance(st, ast.If):
            a, b = _definite(st.body), _definite(st.orelse)
            got |= (a & b) if st.orelse else set()
        elif isinstance(st, ast.Try):
            if st.handlers:
                got |= _definite(st.body) & set().union(*[_definite(h.body) for h in st.handlers])
    return got


class BrainRuntimeVerbatimTest(unittest.TestCase):
    def test_calls_pass_every_parameter_once_same_name(self):
        calls = _facade_calls()
        for name in SPECS:
            with self.subTest(fn=name):
                params = [a.arg for a in _impl(name).args.kwonlyargs]
                call = calls[name]
                self.assertEqual(call.args, [])
                self.assertEqual([k.arg for k in call.keywords], params)
                for k in call.keywords:
                    self.assertEqual(ast.unparse(k.value), k.arg)

    def test_non_definite_outputs_are_passed_in(self):
        """⚠️ 规则判据：非必然绑定的输出必须在入参里（否则 UnboundLocalError）。"""
        # ⚠️ 历史对拍已退役（2026-09-27）：原先"必然绑定"集合取自**抽取前的段体**。
        #    现改为对**当前实现**求必然绑定集合。判据依然有效：入参是参数、不是赋值，
        #    本就不在 definite 里，所以"返回了却不必然绑定、又没入参"照样被下面抓住。
        for name in SPECS:
            with self.subTest(fn=name):
                definite = _definite(_impl(name).body)
                returned = [e.id for e in _impl(name).body[-1].value.elts]
                params = {a.arg for a in _impl(name).args.kwonlyargs}
                risky = [n for n in returned if n not in definite]
                self.assertTrue(risky, f"{name} 预期存在 in-out 语义（本例应有）")
                missing = [n for n in risky if n not in params]
                self.assertEqual(missing, [],
                                 f"{name}: 非必然绑定却未入参 ⇒ 未命中分支会 UnboundLocalError: {missing}")

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

    # ---------- 行为例 ----------

    def test_capture_policy_snapshot_reuses_given_snapshot(self):
        from scripts.brain import runtime as R
        given = {"policy_version": "v9", "policy_hash": "h9", "summary": "s9"}
        ph, snap, psum, pv = R.capture_policy_snapshot(
            policy_snapshot=given, _get_system_version_tag=lambda: "tag")
        self.assertIs(snap, given, "已给快照必须**原样复用**（不多跑一次生成）")
        self.assertEqual((pv, ph, psum), ("v9", "h9", "s9"))

    def test_capture_policy_snapshot_falls_back_when_both_imports_fail(self):
        from scripts.brain import runtime as R
        fake = type(sys)("policy_snapshot_fake")
        real_import = builtins.__import__

        def _bad_import(name, *a, **k):
            if name in ("policy_snapshot", "astra_backend.policy_snapshot"):
                raise ImportError("boom")
            return real_import(name, *a, **k)

        with mock.patch.object(builtins, "__import__", side_effect=_bad_import):
            ph, snap, psum, pv = R.capture_policy_snapshot(
                policy_snapshot=None, _get_system_version_tag=lambda: "tag")
        self.assertEqual(pv, "tag@unknown", "两级 import 都失败 ⇒ 退化为 unknown 快照")
        self.assertEqual(ph, "unknown")
        self.assertEqual(psum, "policy_snapshot_fallback")
        self.assertEqual(snap.get("units"), {})

    def test_resolve_llm_runtime_applies_runtime_overrides(self):
        """清空 LLM_* 环境变量后，运行时配置必须生效（并钉住 env 优先级）。"""
        from scripts.brain import runtime as R
        keys = ("LLM_MODEL", "LLM_REASONING_EFFORT", "LLM_THINKING_TIMEOUT", "LLM_TIMEOUT_SECONDS")
        clean = {k: v for k, v in os.environ.items() if k not in keys}
        runtime_cfg = {"model": "m1", "reasoning_effort": "low", "api_format": "anthropic",
                       "base_url": "https://x", "api_key": "k1", "thinking_timeout": 33}
        with mock.patch.dict(os.environ, clean, clear=True), \
             mock.patch("astra_backend.llm_manager.get_active_llm_runtime",
                        return_value=runtime_cfg):
            api_format, api_key, base_url, effort, fn, model_name, timeout = \
                R.resolve_llm_runtime(api_key="old", base_url="https://old", os=os)
        self.assertEqual((model_name, effort, api_format), ("m1", "low", "anthropic"))
        self.assertEqual((base_url, api_key), ("https://x", "k1"))
        self.assertEqual(timeout, 33.0)
        self.assertIsNotNone(fn, "成功路径必须拿到真实的 execute_llm_request")
        # 环境变量优先（`os.environ.get(...) or 运行时值`）—— 这是既有优先级，钉住它
        with mock.patch.dict(os.environ, {**clean, "LLM_MODEL": "env-model",
                                          "LLM_REASONING_EFFORT": "medium"}, clear=True), \
             mock.patch("astra_backend.llm_manager.get_active_llm_runtime",
                        return_value=runtime_cfg):
            _f, _e, _af, effort2, _fn, model2, _t = \
                R.resolve_llm_runtime(api_key="old", base_url="https://old", os=os)
        self.assertEqual((model2, effort2), ("env-model", "medium"),
                         "环境变量必须压过运行时配置（既有优先级）")

    def test_resolve_llm_runtime_failure_keeps_defaults_and_nulls_requester(self):
        from scripts.brain import runtime as R
        with mock.patch("astra_backend.llm_manager.get_active_llm_runtime",
                        side_effect=RuntimeError("boom")):
            api_format, api_key, base_url, effort, fn, model_name, timeout = \
                R.resolve_llm_runtime(api_key="keepme", base_url="https://keep", os=os)
        self.assertEqual((api_key, base_url), ("keepme", "https://keep"),
                         "失败时 in-out 必须把调用方原值带回来")
        self.assertEqual(api_format, "openai_chat")
        self.assertIsNone(fn, "解析失败 ⇒ 请求器置 None（不裸奔）")

if __name__ == "__main__":
    unittest.main()
