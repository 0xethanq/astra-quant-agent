r"""LLM 配置库归一化抽取对拍门（B4 收尾·第一百零二刀）。

`astra_backend/llm/store.py::init_llm_config`（202 行）里两块 → `llm/store_normalize.py`：
`resolve_brain_provider_attribution`（主脑条目钉回其供应商）、
`finalize_config_document`（韧性配置解析 + 组装 + 原子写盘，尾部返回透传）。

判据：段体 **AST 逐字**（基线 `3503466` 的语句下标 26..28 / 29..40）、调用点逐个同名恰好一次、
非必然绑定必须入参、自由名可解析；行为例 + **`assertIs` 副作用断言**
（`resolve_brain_provider_attribution` 设计上**原地改** `flat_models` 里的 dict ——
若有人改成"返回新列表"，语义就变了，本门必须翻红）。
"""
from __future__ import annotations

import ast
import builtins
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "3503466"                  # 本刀动工前最后提交（第一百刀收口）
FACADE = ROOT / "astra_backend" / "llm" / "store.py"
MOD = ROOT / "astra_backend" / "llm" / "store_normalize.py"
OWNER = "init_llm_config"
SPECS = {"resolve_brain_provider_attribution": (26, 28), "finalize_config_document": (29, 40)}


def _baseline_fn() -> ast.FunctionDef:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:astra_backend/llm/store.py")],
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


class LlmStoreNormalizeVerbatimTest(unittest.TestCase):
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

    def test_finalize_call_site_is_a_bare_return_passthrough(self):
        """尾块段内的 `return config` 就是 `init_llm_config` 的终返 ⇒ 调用点必须 `return f(...)`。"""
        fn = next(n for n in ast.parse(FACADE.read_text(encoding="utf-8")).body
                  if isinstance(n, ast.FunctionDef) and n.name == OWNER)
        last = fn.body[-1]
        self.assertIsInstance(last, ast.Return)
        self.assertIsInstance(last.value, ast.Call)
        self.assertEqual(last.value.func.id, "finalize_config_document")

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

    # ---------- 行为例 ----------

    def test_attribution_pins_model_to_its_provider_in_place(self):
        from astra_backend.llm.store_normalize import resolve_brain_provider_attribution
        models = [{"id": "m-active", "provider_id": "p-b", "base_url": "https://stale"}]
        providers = [
            {"id": "p-a", "name": "A", "base_url": "https://a", "api_key": "ka"},
            {"id": "p-b", "name": "B", "base_url": "https://b", "api_key": "kb"},
        ]
        first_entry = models[0]
        active_pid = resolve_brain_provider_attribution(
            active_m_id="m-active", data={"active_provider_id": "p-b"},
            flat_models=models, merged_providers=providers,
            _resolve_active_provider_id=lambda info: info["active_provider_id"])
        self.assertEqual(active_pid, "p-b")
        # ⚠️ 副作用断言（有牙）：必须**原地**改同一个 list 里的**同一个 dict**
        # —— 若实现改成"复制列表/重建 dict"，下面两条立刻翻红（那是行为变更）。
        self.assertIs(models[0], first_entry, "不得替换为新 dict")
        self.assertEqual(len(models), 1, "不得重建列表")
        self.assertEqual(models[0]["provider_name"], "B")
        self.assertEqual(models[0]["base_url"], "https://b")
        self.assertEqual(models[0]["api_key"], "kb")
        self.assertEqual(models[0]["api_format"], "openai_chat")

    def test_finalize_clamps_attempts_and_sanitizes_fallback_chain(self):
        from astra_backend.llm import policy
        from astra_backend.llm.store_normalize import finalize_config_document
        flat = [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "llm_models.json"
            cfg = finalize_config_document(
                active_effort="high", active_m_id="m1", active_pid="p1", config_file=target,
                data={"request_attempts": 999,
                      "fallback_model_ids": ["m2", "m2", "ghost", "m1", "", "m3"]},
                flat_models=flat, merged_providers=[{"id": "p1"}], thinking_timeout=120,
                DEFAULT_REQUEST_ATTEMPTS=policy.DEFAULT_REQUEST_ATTEMPTS,
                List=list, MAX_FALLBACK_MODELS=policy.MAX_FALLBACK_MODELS,
                MAX_REQUEST_ATTEMPTS=policy.MAX_REQUEST_ATTEMPTS,
                MIN_REQUEST_ATTEMPTS=policy.MIN_REQUEST_ATTEMPTS,
                _atomic_write_json=lambda p, d: Path(p).write_text(
                    json.dumps(d, ensure_ascii=False), encoding="utf-8"),
                os=__import__("os"))
            self.assertEqual(cfg["request_attempts"], policy.MAX_REQUEST_ATTEMPTS,
                             "越界请求次数必须夹取到上限")
            self.assertEqual(cfg["fallback_model_ids"], ["m2", "m3"],
                             "回退链必须去重、剔除自身与未知 id、保序")
            self.assertEqual(cfg["active_provider_id"], "p1")
            self.assertTrue(target.exists(), "定稿必须落盘")
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["active_model_id"], "m1")

    def test_finalize_self_heals_dirty_attempts(self):
        from astra_backend.llm import policy
        from astra_backend.llm.store_normalize import finalize_config_document
        with tempfile.TemporaryDirectory() as td:
            cfg = finalize_config_document(
                active_effort="low", active_m_id="m1", active_pid="", config_file=Path(td) / "x.json",
                data={"request_attempts": "not-a-number", "fallback_model_ids": "not-a-list"},
                flat_models=[{"id": "m1"}], merged_providers=[], thinking_timeout=1,
                DEFAULT_REQUEST_ATTEMPTS=policy.DEFAULT_REQUEST_ATTEMPTS, List=list,
                MAX_FALLBACK_MODELS=policy.MAX_FALLBACK_MODELS,
                MAX_REQUEST_ATTEMPTS=policy.MAX_REQUEST_ATTEMPTS,
                MIN_REQUEST_ATTEMPTS=policy.MIN_REQUEST_ATTEMPTS,
                _atomic_write_json=lambda p, d: None, os=__import__("os"))
            self.assertEqual(cfg["request_attempts"], policy.DEFAULT_REQUEST_ATTEMPTS)
            self.assertEqual(cfg["fallback_model_ids"], [], "脏数据必须自愈为空链，不得抛错")

if __name__ == "__main__":
    unittest.main()
