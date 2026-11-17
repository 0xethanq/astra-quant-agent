r"""`load_llm_config` 两段归一化抽取对拍门（第一百零八刀）。

`astra_backend/llm/store.py::load_llm_config`（94 行）里两段纯循环 →
`astra_backend/llm/store_normalize.py`（与第一百零二刀同域，故并入该模块）：
`normalize_providers_into_result`（供应商 + 其下模型的响应形状归一）、
`flatten_models_into_result`（顶层扁平模型，向后兼容）。

两者都是 **0 输出**：结果按引用写进调用方传入的 `res`（门里用 `assertIs` 钉住"原地写"）。

## 本门钉的**规则**（不只是搬家）

1. 供应商列表**只**含显式登记在该供应商下的模型（不在顶层扁平列表里"顺带捞"）；
2. **主脑徽标归属**：同名模型挂多家供应商时 `is_active` 只打给归属供应商那一份；
   归属无法判定（`active_pid` 为空）时保留全打，避免误判成"没启用"；
3. `mask_keys` 决定输出 `api_key_masked` 还是原始 `api_key`（**二选一，不得都写**）。

基线：`def9d18`（本刀动工前最后提交）。
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

PRE = "def9d18"
FACADE = ROOT / "astra_backend" / "llm" / "store.py"
MOD = ROOT / "astra_backend" / "llm" / "store_normalize.py"
OWNER = "load_llm_config"
SPECS = {"normalize_providers_into_result": (6, 6), "flatten_models_into_result": (7, 7)}


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


def _real_helpers():
    from astra_backend.llm.capabilities import _detect_capabilities, _detect_reasoning_type
    from astra_backend.llm.util import mask_secret
    return _detect_capabilities, _detect_reasoning_type, mask_secret


class LlmLoadConfigExtractionTest(unittest.TestCase):
    def test_call_sites_are_plain_statements_with_all_kwargs(self):
        calls = _facade_calls()
        for name in SPECS:
            with self.subTest(fn=name):
                params = [a.arg for a in _impl(name).args.kwonlyargs]
                call = calls[name]
                self.assertEqual(call.args, [])
                self.assertEqual([k.arg for k in call.keywords], params)
                for k in call.keywords:
                    self.assertEqual(ast.unparse(k.value), k.arg)
        # 0 输出 ⇒ 调用点必须是**表达式语句**（不得写 `x = f(...)`）
        tree = ast.parse(FACADE.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == OWNER)
        for st in fn.body:
            if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) \
                    and getattr(st.value.func, "id", "") in SPECS:
                continue
        self.assertFalse([st for st in fn.body if isinstance(st, ast.Assign)
                          and isinstance(st.value, ast.Call)
                          and getattr(st.value.func, "id", "") in SPECS],
                         "0 输出的抽取调用点不得被赋值")

    def test_no_undeclared_free_names(self):
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

    # ---------- 行为例：供应商归一 ----------

    def _providers(self, res, providers, *, active_mid="m1", active_pid="p1", mask_keys=True,
                   caps=None, rtypes=None, masker=None):
        from astra_backend.llm.store_normalize import normalize_providers_into_result
        dc, dr, dm = _real_helpers()
        normalize_providers_into_result(
            _detect_capabilities=caps or dc, _detect_reasoning_type=rtypes or dr,
            active_mid=active_mid, active_pid=active_pid, mask_keys=mask_keys,
            mask_secret=masker or dm, providers_list=providers, res=res)
        return res

    def test_provider_only_lists_its_own_registered_models(self):
        res = {"providers": []}
        same = res["providers"]
        self._providers(res, [{"id": "p1", "name": "P1", "models": [{"id": "m1"}]}])
        self.assertIs(res["providers"], same, "必须原地写调用方容器")
        self.assertEqual([m["id"] for m in res["providers"][0]["models"]], ["m1"],
                         "只含显式登记在该供应商下的模型")
        self.assertEqual(res["providers"][0]["models_count"], 1)

    def test_active_badge_only_on_owning_provider(self):
        res = {"providers": []}
        providers = [{"id": "p1", "models": [{"id": "m1"}]}, {"id": "p2", "models": [{"id": "m1"}]}]
        self._providers(res, providers, active_mid="m1", active_pid="p2")
        flags = {p["id"]: p["models"][0]["is_active"] for p in res["providers"]}
        self.assertEqual(flags, {"p1": False, "p2": True},
                         "同名模型只给归属供应商打主脑徽标")

    def test_active_badge_all_when_ownership_unknown(self):
        res = {"providers": []}
        providers = [{"id": "p1", "models": [{"id": "m1"}]}, {"id": "p2", "models": [{"id": "m1"}]}]
        self._providers(res, providers, active_mid="m1", active_pid="")
        self.assertTrue(all(p["models"][0]["is_active"] for p in res["providers"]),
                        "归属不可判定时保留全打（否则会被误读成'没启用'）")

    def test_mask_keys_is_exclusive(self):
        res = {"providers": []}
        self._providers(res, [{"id": "p1", "api_key": "sk-secret", "models": []}], mask_keys=True)
        p = res["providers"][0]
        self.assertIn("api_key_masked", p)
        self.assertNotIn("api_key", p, "掩码模式下**不得**带出原始密钥")
        self.assertTrue(p["has_key"], "has_key 只看有无密钥，与掩码无关")
        res2 = {"providers": []}
        self._providers(res2, [{"id": "p1", "api_key": "sk-secret", "models": []}], mask_keys=False)
        self.assertEqual(res2["providers"][0]["api_key"], "sk-secret")
        self.assertNotIn("api_key_masked", res2["providers"][0])

    def test_model_field_defaults_and_detector_fallback(self):
        res = {"providers": []}
        seen = []
        self._providers(res, [{"id": "p1", "models": [{"id": "m1"}]}],
                        caps=lambda mid: seen.append(mid) or {"chat": True},
                        rtypes=lambda mid: "reasoning")
        m = res["providers"][0]["models"][0]
        self.assertEqual(m["name"], "m1", "缺 name 时回退成 id")
        self.assertEqual(m["capabilities"], {"chat": True})
        self.assertEqual(m["reasoning_type"], "reasoning")
        self.assertEqual(m["reasoning_effort"], "high")
        self.assertEqual(seen, ["m1"], "能力探测必须被调用（缺字段时）")

    # ---------- 行为例：扁平模型 ----------

    def test_flat_models_has_key_and_is_active(self):
        from astra_backend.llm.store_normalize import flatten_models_into_result
        dc, dr, dm = _real_helpers()
        res = {"models": []}
        same = res["models"]
        flatten_models_into_result(
            _detect_capabilities=dc, active_mid="m1", config={"models": [
                {"id": "m1", "provider_id": "p1"},
                {"id": "m2", "provider_id": "p1"},
            ]}, mask_keys=True, mask_secret=dm,
            providers_list=[{"id": "p1", "api_key": "prov-key"}], res=res)
        self.assertIs(res["models"], same, "必须原地写调用方容器")
        by_id = {m["id"]: m for m in res["models"]}
        self.assertTrue(by_id["m1"]["is_active"])
        self.assertFalse(by_id["m2"]["is_active"])
        self.assertTrue(by_id["m1"]["has_key"], "模型无密钥但归属供应商有 ⇒ has_key=True")
        self.assertNotIn("api_key", by_id["m1"], "掩码模式不带原始密钥")

    def test_flat_models_raw_key_when_not_masking(self):
        from astra_backend.llm.store_normalize import flatten_models_into_result
        dc, _dr, _dm = _real_helpers()
        res = {"models": []}
        flatten_models_into_result(
            _detect_capabilities=dc, active_mid="", config={"models": [{"id": "m9", "api_key": "k9"}]},
            mask_keys=False, mask_secret=lambda v: "MASKED",
            providers_list=[], res=res)
        self.assertEqual(res["models"][0]["api_key"], "k9")
        self.assertFalse(res["models"][0]["is_active"], "active_mid 为空 ⇒ 无激活项")

if __name__ == "__main__":
    unittest.main()
