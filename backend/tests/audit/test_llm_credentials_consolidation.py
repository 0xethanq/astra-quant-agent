"""`scripts/llm_credentials.py` 孪生漂移消除（阶段 4·B3 第四十六刀）回归。

## 修了什么

跨文件重复扫描发现 `get_cpa_client_config()` 在**两个独立脚本**里**逐字相同**
地存在（各 15 行，可执行体 `== True`）：

| 文件 | 原行 |
|---|---|
| `scripts/ai_brain_trader.py` | 239 |
| `scripts/self_improvement_engine.py` | 125 |

两份此刻**完全相同**，所以不是当下的 bug；但它是一条**必然漂移**的复制：
两处都从 `astra_backend.llm_manager` 取「当前激活模型」再回落到环境变量，
任何一处改了回落顺序或加了新环境变量，另一处不会跟着改 ——
两个进程就会用**不同的凭据**说话。

本仓已有同类教训与修法（`scripts/ai_factor_trader.py:714` 的
「孪生漂移…等于闸装了死副本。现从模块导入同一实现，双进程单一事实源」），
本刀按同一思路消除这一处。

## ⚠️ 为什么落在 `scripts/` 而不是 `astra_backend/llm/`

我第一版写成 `astra_backend/llm/credentials.py`，被
`tests/test_llm_seam_discipline.py::test_core_modules_do_not_import_facade`
**当场拒绝**：

    credentials.py:67 from astra_backend.llm_manager import ...

该闸的铁律是「`astra_backend/llm/` 下的核心模块不得反向 import 门面
`llm_manager`（会成环；应为薄壳注入）」。而本函数的**业务本身**就是
「先问 `llm_manager.get_active_llm_runtime()`」—— 天然违反该铁律。

既然两个调用方都是 `scripts/` 下的脚本，正确位置就是 `scripts/` 同层。
**闸抓对了，是我的落点错了。** 本文件据此记录，并把该约束钉成测试。
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

MODULE = SCRIPTS / "llm_credentials.py"
FACADES = (SCRIPTS / "ai_brain_trader.py", SCRIPTS / "self_improvement_engine.py")

from llm_credentials import get_cpa_client_config  # noqa: E402


class _Settings:
    llm_base_url = "https://standalone/v1"
    llm_api_key = "STANDALONE_KEY"


class FallbackOrderTest(unittest.TestCase):
    """⚠️ 三条回落分支的顺序是**业务语义**。"""

    def test_runtime_active_model_wins(self):
        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   return_value={"base_url": "https://runtime/v1", "api_key": "RT"}):
            self.assertEqual(get_cpa_client_config(_Settings()),
                             ("https://runtime/v1", "RT"))

    def test_runtime_exception_falls_back_to_standalone(self):
        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   side_effect=RuntimeError("config store down")):
            self.assertEqual(get_cpa_client_config(_Settings()),
                             ("https://standalone/v1", "STANDALONE_KEY"))

    def test_runtime_without_base_url_falls_back(self):
        """⚠️ 激活模型存在但 `base_url` 为空 → 必须继续回落，不能返回空地址。"""
        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   return_value={"base_url": "", "api_key": "RT"}):
            self.assertEqual(get_cpa_client_config(_Settings()),
                             ("https://standalone/v1", "STANDALONE_KEY"))

    def test_env_fallback_when_nothing_else(self):
        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   side_effect=RuntimeError("x")), \
             patch.dict(os.environ, {"LLM_BASE_URL": "https://env/v1",
                                     "LLM_API_KEY": "ENVKEY"}, clear=False):
            self.assertEqual(get_cpa_client_config(None),
                             ("https://env/v1", "ENVKEY"))

    def test_openai_aliases_are_second_choice(self):
        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   side_effect=RuntimeError("x")), \
             patch.dict(os.environ, {"OPENAI_BASE_URL": "https://openai/v1",
                                     "OPENAI_API_KEY": "OK"}, clear=False), \
             patch.dict(os.environ, {}, clear=True):
            # 清空后只剩 OPENAI_*
            with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://openai/v1",
                                         "OPENAI_API_KEY": "OK"}, clear=True):
                self.assertEqual(get_cpa_client_config(None),
                                 ("https://openai/v1", "OK"))

    def test_llm_env_beats_openai_env(self):
        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   side_effect=RuntimeError("x")), \
             patch.dict(os.environ, {"LLM_BASE_URL": "https://llm/v1",
                                     "OPENAI_BASE_URL": "https://openai/v1",
                                     "LLM_API_KEY": "A",
                                     "OPENAI_API_KEY": "B"}, clear=True):
            self.assertEqual(get_cpa_client_config(None), ("https://llm/v1", "A"))

    def test_hardcoded_openai_default_is_last_resort(self):
        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   side_effect=RuntimeError("x")), \
             patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_cpa_client_config(None),
                             ("https://api.openai.com/v1", ""))

    def test_missing_api_key_yields_empty_string_not_none(self):
        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   return_value={"base_url": "https://runtime/v1"}):
            _, key = get_cpa_client_config(None)
            self.assertEqual(key, "")

    def test_returns_tuple_of_two_str(self):
        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   return_value={"base_url": "https://runtime/v1", "api_key": "K"}):
            out = get_cpa_client_config(None)
        self.assertIsInstance(out, tuple)
        self.assertEqual(len(out), 2)
        for v in out:
            self.assertIsInstance(v, str)

    def test_exception_is_swallowed_by_design(self):
        """⚠️ 异常被静默吞掉是**有意**的：后台配置库不可用不应让交易进程起不来。"""
        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   side_effect=RuntimeError("boom")), \
             patch.dict(os.environ, {"LLM_BASE_URL": "https://env/v1",
                                     "LLM_API_KEY": "K"}, clear=True):
            self.assertEqual(get_cpa_client_config(None), ("https://env/v1", "K"))


class FacadeInjectionTest(unittest.TestCase):
    """⚠️ 两个门面必须在**调用时**把自己模块的 `standalone_settings` 传进去。"""

    def test_both_facades_are_thin_shells(self):
        for path in FACADES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            fn = next(n for n in tree.body
                      if isinstance(n, ast.FunctionDef)
                      and n.name == "get_cpa_client_config")
            self.assertLessEqual(fn.end_lineno - fn.lineno + 1, 12,
                                 f"{path.name} 的壳太厚（{fn.end_lineno - fn.lineno + 1} 行）")
            body = ast.unparse(ast.Module(body=fn.body, type_ignores=[]))
            self.assertIn("_get_cpa_client_config(standalone_settings)", body,
                          f"{path.name} 的壳没有做调用时注入")

    def test_facade_global_injection_reaches_shared_impl(self):
        """patch 门面全局 → 薄壳读到新值（证明**不是** import 期绑定的副本）。"""
        import ai_brain_trader as abt
        import self_improvement_engine as sie

        class S:
            llm_base_url = "https://patched/v1"
            llm_api_key = "PATCHED"

        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   side_effect=RuntimeError("x")):
            with patch.object(abt, "standalone_settings", S()):
                self.assertEqual(abt.get_cpa_client_config(), ("https://patched/v1", "PATCHED"))
            with patch.object(sie, "standalone_settings", S()):
                self.assertEqual(sie.get_cpa_client_config(), ("https://patched/v1", "PATCHED"))

    def test_two_facades_agree_given_same_inputs(self):
        """⚠️ 本刀的**目的**：同输入必须给出同输出（消除孪生漂移）。"""
        import ai_brain_trader as abt
        import self_improvement_engine as sie

        with patch("astra_backend.llm_manager.get_active_llm_runtime",
                   side_effect=RuntimeError("x")), \
             patch.dict(os.environ, {"LLM_BASE_URL": "https://env/v1",
                                     "LLM_API_KEY": "K"}, clear=True):
            with patch.object(abt, "standalone_settings", None), \
                 patch.object(sie, "standalone_settings", None):
                self.assertEqual(abt.get_cpa_client_config(),
                                 sie.get_cpa_client_config())

    def test_facade_wrappers_are_distinct_functions(self):
        """门面保留的必须是**自己的**壳（不是子模块函数的别名赋值）。"""
        import ai_brain_trader as abt
        import self_improvement_engine as sie
        self.assertIsNot(abt.get_cpa_client_config, get_cpa_client_config)
        self.assertIsNot(sie.get_cpa_client_config, get_cpa_client_config)


class PlacementTest(unittest.TestCase):
    """⚠️ 本刀踩过的坑：共享模块**不能**放进 `astra_backend/llm/`。"""

    def test_shared_module_lives_in_scripts(self):
        self.assertTrue(MODULE.exists())
        self.assertFalse((ROOT / "astra_backend" / "llm" / "credentials.py").exists(),
                         "共享模块不得放回 astra_backend/llm/（会违反接缝铁律）")

    # 「该模块单独跑也绿」这条判据**已合并**到
    # `tests/audit/test_standalone_modules_stay_green.py`（一次子进程跑完所有这类模块）。
    # 原用例名：test_seam_gate_still_green。

    def test_shared_module_has_no_top_level_llm_manager_import(self):
        """`llm_manager` 的 import 必须在**函数内**（延迟到调用时）。

        模块顶层 import 会在 `scripts/` 与 `astra_backend/` 之间制造
        import 期耦合 —— 本仓大量脚本正是靠延迟导入才可独立运行。
        """
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertNotIn("llm_manager", node.module,
                                 "llm_manager 必须在函数内延迟导入")
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn("llm_manager", a.name)

    def test_module_has_no_module_level_side_effects(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        bare = [n for n in tree.body
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
        self.assertEqual(bare, [], "模块层不应有裸调用")


class DuplicationGoneTest(unittest.TestCase):
    def test_no_facade_still_contains_the_original_body(self):
        """两个门面里都**不该**再有原来的实现体（只看可执行语句，不看 docstring）。"""
        for path in FACADES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            fn = next(n for n in tree.body
                      if isinstance(n, ast.FunctionDef)
                      and n.name == "get_cpa_client_config")
            body = ast.unparse(ast.Module(body=fn.body, type_ignores=[]))
            self.assertNotIn("OPENAI_BASE_URL", body,
                             f"{path.name} 里仍内联着原实现")
            self.assertNotIn("llm_base_url,", body,
                             f"{path.name} 里仍内联着原实现")

    def test_only_one_definition_across_the_repo(self):
        """全仓（非测试/非归档）只应有一处**实现**。"""
        offenders = []
        for p in ROOT.rglob("*.py"):
            if any(x in p.parts for x in (".venv", "plan_local", "__pycache__",
                                          "node_modules", ".git", ".archive", "tests")):
                continue
            if p == MODULE:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for n in tree.body:
                if isinstance(n, ast.FunctionDef) and n.name == "get_cpa_client_config":
                    body = ast.unparse(ast.Module(body=n.body, type_ignores=[]))
                    if "OPENAI_BASE_URL" in body:
                        offenders.append(str(p))
        self.assertEqual(offenders, [], f"这些文件仍有内联实现: {offenders}")


if __name__ == "__main__":
    unittest.main()
