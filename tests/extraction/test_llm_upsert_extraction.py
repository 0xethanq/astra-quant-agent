r"""`upsert_model` 两条写入路径抽取对拍门（第一百零九刀）。

`astra_backend/llm/store.py::upsert_model`（111 行）里两个大 `if` →
`astra_backend/llm/store_upsert.py`：`write_model_into_top_level_list`（顶层
`config["models"]` 更新/追加）、`write_model_into_providers_local_list`
（同一模型登记进其供应商本地 `models` 数组）。两者 **0 输出**（按引用改 `models` / `prov`）。

## 本门钉的规则

1. **空 `api_key` 不得抹掉已存密钥**：更新分支里 `api_key` 是**条件赋值**
   （`if api_key:`）—— 调用方没给密钥时，存量密钥必须保持原样（安全相关）；
2. `provider_id` / `provider_name` 为空时**回退到条目已有值**（不是重置成默认）；
3. 供应商本地条目**永不**携带 `api_key`（密钥唯一存放处是供应商本体）；
4. `prov.setdefault("models", [])`：供应商尚无 `models` 数组时要能建出来。

基线：`1b060ba`（本刀动工前最后提交）。
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

PRE = "1b060ba"
FACADE = ROOT / "astra_backend" / "llm" / "store.py"
MOD = ROOT / "astra_backend" / "llm" / "store_upsert.py"
OWNER = "upsert_model"
SPECS = {"write_model_into_top_level_list": (26, 26),
         "write_model_into_providers_local_list": (27, 27)}


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


def _top_kwargs(**over):
    kw = dict(api_format="openai_chat", api_key="", base_url="https://x/v1", caps={"chat": True},
              ctx_len=128000, default_effort="high", desc="d", mid="m1", name="M1",
              provider_id="p1", provider_name="P1", reasoning_type="reasoning")
    kw.update(over)
    return kw


class LlmUpsertExtractionTest(unittest.TestCase):
    def test_call_sites_plain_and_all_kwargs_same_name(self):
        calls = _facade_calls()
        for name in SPECS:
            with self.subTest(fn=name):
                params = [a.arg for a in _impl(name).args.kwonlyargs]
                call = calls[name]
                self.assertEqual(call.args, [])
                self.assertEqual([k.arg for k in call.keywords], params)
                for k in call.keywords:
                    self.assertEqual(ast.unparse(k.value), k.arg)

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

    # ---------- 行为例：顶层列表 ----------

    def _top(self, models, existing, **over):
        from astra_backend.llm.store_upsert import write_model_into_top_level_list
        write_model_into_top_level_list(existing=existing, models=models, **_top_kwargs(**over))
        return models

    def test_updates_existing_in_place(self):
        entry = {"id": "m1", "name": "OLD", "api_key": "kept-key"}
        models = [entry]
        self._top(models, entry, name="NEW")
        self.assertIs(models[0], entry, "必须原地更新，不得换新对象")
        self.assertEqual(entry["name"], "NEW")
        self.assertEqual(entry["capabilities"], {"chat": True})
        self.assertEqual(len(models), 1, "不得重复追加")

    def test_empty_api_key_must_not_wipe_stored_key(self):
        """安全规则：调用方未提供密钥时，存量密钥保持原样。"""
        entry = {"id": "m1", "api_key": "kept-key"}
        self._top([entry], entry, api_key="")
        self.assertEqual(entry["api_key"], "kept-key", "空 api_key 不得抹掉已存密钥")
        self._top([entry], entry, api_key="new-key")
        self.assertEqual(entry["api_key"], "new-key", "给了新密钥则覆盖")

    def test_empty_provider_fields_fall_back_to_existing(self):
        entry = {"id": "m1", "provider_id": "orig-p", "provider_name": "原始供应商"}
        self._top([entry], entry, provider_id="", provider_name="")
        self.assertEqual(entry["provider_id"], "orig-p")
        self.assertEqual(entry["provider_name"], "原始供应商")

    def test_appends_when_absent_with_defaults(self):
        models = []
        self._top(models, None, provider_id="", provider_name="")
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["id"], "m1")
        self.assertEqual(models[0]["provider_id"], "openai", "新建时为空 ⇒ 默认 openai")
        self.assertEqual(models[0]["provider_name"], "自定义")

    # ---------- 行为例：供应商本地列表 ----------

    def _prov(self, prov, **over):
        from astra_backend.llm.store_upsert import write_model_into_providers_local_list
        write_model_into_providers_local_list(
            prov=prov, **{k: v for k, v in _top_kwargs(**over).items()
                          if k in ("caps", "ctx_len", "default_effort", "desc", "mid", "name",
                                   "reasoning_type")})
        return prov

    def test_none_provider_is_a_noop(self):
        self.assertIsNone(self._prov(None), "无供应商时不得抛错（原实现即空操作）")

    def test_creates_models_array_and_appends(self):
        prov = {"id": "p1"}
        self._prov(prov, name="M1")
        self.assertEqual([m["id"] for m in prov["models"]], ["m1"])
        self.assertEqual(prov["models"][0]["name"], "M1")
        self.assertNotIn("api_key", prov["models"][0], "供应商本地条目不得携带密钥")

    def test_updates_local_entry_in_place(self):
        local = {"id": "m1", "name": "OLD", "api_key": "should-stay-untouched"}
        prov = {"id": "p1", "models": [local]}
        self._prov(prov, name="NEW")
        self.assertIs(prov["models"][0], local, "原地更新")
        self.assertEqual(local["name"], "NEW")
        self.assertEqual(local["api_key"], "should-stay-untouched",
                         "本函数只管那 7 个字段，不得动其他键")
        self.assertEqual(len(prov["models"]), 1)

if __name__ == "__main__":
    unittest.main()
