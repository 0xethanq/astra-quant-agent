r"""LLM 生效模型 → `.env` 装配抽取对拍门（第一百零六刀）。

`astra_backend/llm/store.py::activate_provider_model`（143 行）里两段 →
`astra_backend/llm/env_sync.py`：`resolve_effective_endpoint`（优先级链）、
`build_env_values`（env 值组装 + 超时夹取 + 条件写密钥）。

## 本门钉的是**判定规则**，不是搬家动作

优先级链与夹取规则原先夹在 143 行函数中段、前后都是 IO，几乎无法单测。
现在每条优先级、每个边界值都有断言；`os` 是**注入**的 ⇒ 用假 `os` 测 env 回退，
**不碰真实环境变量**（离线套件要求零外部影响）。

基线：`c7fc135`（本刀动工前最后提交）。
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import sys
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "c7fc135"
FACADE = ROOT / "astra_backend" / "llm" / "store.py"
MOD = ROOT / "astra_backend" / "llm" / "env_sync.py"
OWNER = "activate_provider_model"
SPECS = {"resolve_effective_endpoint": (20, 24), "build_env_values": (25, 27)}


class FakeOS:
    """只实现被用到的 `getenv`，避免测试改动真实环境。"""

    def __init__(self, **env):
        self.env = env

    def getenv(self, key, default=None):
        return self.env.get(key, default)


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


class LlmEnvSyncTest(unittest.TestCase):
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

    def test_free_names_resolvable(self):
        module = ast.parse(MOD.read_text(encoding="utf-8"))
        mod_names = {n.name for n in module.body if isinstance(n, ast.FunctionDef)}
        for name in SPECS:
            with self.subTest(fn=name):
                fn = _impl(name)
                local = {a.arg for a in fn.args.kwonlyargs}
                for n in ast.walk(fn):
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

    # ---------- 行为例：优先级链 ----------

    def _resolve(self, target_model, providers=(), **env):
        from astra_backend.llm.env_sync import resolve_effective_endpoint
        return resolve_effective_endpoint(
            config={"providers": list(providers)}, os=FakeOS(**env), target_model=target_model)

    def test_model_own_values_win(self):
        base_url, api_key = self._resolve(
            {"base_url": "https://own/", "api_key": "k-own", "provider_id": "p1"},
            [{"id": "p1", "base_url": "https://prov", "api_key": "k-prov"}],
            LLM_BASE_URL="https://env")
        self.assertEqual(api_key, "k-own", "模型自身 api_key 优先")
        self.assertEqual(base_url, "https://own", "自身 base_url 优先且去掉尾部斜杠")

    def test_falls_back_to_its_provider(self):
        base_url, api_key = self._resolve(
            {"provider_id": "p1"},
            [{"id": "p1", "base_url": "https://prov/", "api_key": "k-prov"}],
            LLM_BASE_URL="https://env")
        self.assertEqual((base_url, api_key), ("https://prov", "k-prov"),
                         "模型缺值 ⇒ 用其供应商的（provider_id 命中）")

    def test_provider_missing_falls_back_to_env_then_default(self):
        self.assertEqual(self._resolve({}, [{"id": "px"}], LLM_BASE_URL="https://env/")[0], "https://env")
        self.assertEqual(self._resolve({}, [], OPENAI_BASE_URL="https://oa/")[0], "https://oa")
        self.assertEqual(self._resolve({}, [])[0], "https://api.openai.com/v1",
                         "全空 ⇒ OpenAI 默认值")

    def test_api_key_stays_empty_without_any_source(self):
        base_url, api_key = self._resolve({}, [])
        self.assertEqual(api_key, "")
        self.assertEqual(base_url, "https://api.openai.com/v1")

    # ---------- 行为例：env 值组装 ----------

    def _build(self, **over):
        from astra_backend.llm.env_sync import build_env_values
        seen = []
        kw = dict(api_key="", base_url="https://api.example/v1", effort="high", model_id="m1",
                  save_secrets=lambda d: seen.append(d), thinking_timeout=None)
        kw.update(over)
        return build_env_values(**kw), seen

    def test_env_values_baseline(self):
        values, saved = self._build()
        self.assertEqual(values, {"LLM_BASE_URL": "https://api.example/v1", "LLM_MODEL": "m1",
                                  "LLM_REASONING_EFFORT": "high"})
        self.assertEqual(saved, [], "无 api_key ⇒ 不写密钥存储")
        self.assertNotIn("LLM_THINKING_TIMEOUT", values, "未给超时 ⇒ 不写该键")

    def test_timeout_clamped_and_formatted(self):
        self.assertEqual(self._build(thinking_timeout=1.0)[0]["LLM_THINKING_TIMEOUT"], "5",
                         "低于下限夹到 5s")
        self.assertEqual(self._build(thinking_timeout=99999)[0]["LLM_THINKING_TIMEOUT"], "1800",
                         "高于上限夹到 1800s")
        self.assertEqual(self._build(thinking_timeout=120.0)[0]["LLM_THINKING_TIMEOUT"], "120",
                         "整数值不写成 120.0")
        self.assertEqual(self._build(thinking_timeout=12.5)[0]["LLM_THINKING_TIMEOUT"], "12.5")

    def test_secret_written_only_when_allowed(self):
        values, saved = self._build(api_key="k1")
        self.assertEqual(values["LLM_API_KEY"], "k1")
        self.assertEqual(saved, [{"LLM_API_KEY": "k1"}])
        values2, saved2 = self._build(api_key="k1", save_secrets=None)
        self.assertEqual(values2["LLM_API_KEY"], "k1")
        self.assertEqual(saved2, [], "save_secrets 缺省时不得写盘（也不得报错）")

if __name__ == "__main__":
    unittest.main()
