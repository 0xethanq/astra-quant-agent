"""`useLlmConfig.ts` 纯逻辑外提（结构优化阶段 4·B3 第五十七刀）。

## 抽了什么

`frontend/src/composables/useLlmConfig.ts` 原先 686 行。它的 docstring 提过
"按 provider / model / failover 三域再拆"，但实测后判断**不能那样拆**：
那三域的动作函数都直接读写同一批 `ref`（`cfg`/`providerForm`/`modelForm`/
`selectedProvider` …），拆成独立 composable 会各建一份新状态 ——
`views/admin/llm/injection.ts` 的注释已解释过这个陷阱（"看起来能跑、实际全错"）。

故本刀只抽**真正无状态**的部分到 `frontend/src/composables/llmLogic.ts`：
输入进、值出，不碰任何 `ref`。门面 `useLlmConfig.ts` **686 → 617 行**。

## 最大收益：消掉一处**逐字重复**

`importRemoteModel` 与 `importAllFilteredRemoteModels` 里各写了一份
**完全相同**的模型 payload 字面量（11 个字段的回落链，实测字节一致）。
现统一到 `buildRemoteModelPayload()`。

## ⚠️ 抽离阶段我主动改回的一处"改进"

写 `filterProviders` 时我顺手给 `p.name` 加了存在性守卫
（`(p.name && p.name.toLowerCase()...)`），原实现是**直接** `p.name.toLowerCase()`。
那是**行为变更**（无 name 的供应商原本会抛错），与"保持业务逻辑完全不变"冲突 ——
已改回与原实现逐字等价，并有
`test_filter_providers_has_no_name_guard` 钉住这个决定。

## ⚠️ 拆分的正确性证据

本刀**没有改任何一条基线断言**，而 `frontend/tests/useLlmConfig.test.mjs`
的 **136 条**在拆分后仍然全绿 —— 那正是"接口与业务逻辑完全不变"的证据。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path
import os


def _guard_offline() -> None:
    """离线套件下跳过（**必须在 spawn 之前调用**）。

    ⚠️ 这是第六十一刀补的**回归修复**：`tests/offline_suite.py::main` 会装
    audit hook 阻止一切未白名单的外部子进程，而 `node` / `vite` / `vue-tsc`
    **都不在白名单**。§44.4 早已立此规矩并核实过
    "离线套件里 `external child process: node` 计数 = 0"，
    但第五十六～六十刀新增的 node 套件**漏了这道守卫**，使该计数重新变成 5。

    判据是套件在装 hook **之前**显式设的 `OFFLINE_SUITE_RUNNING`，
    所以这里一定来得及。**必须 `raise` 而不是 `case.skipTest(...)`**
    —— 后者在 `setUpClass` 收到类时会 `TypeError`（§44.4 的教训）。

    ⚠️ 守卫直接贴在 `subprocess.run(...)` **上一行**（而不是各 `test_` 方法里）：
    这样模块级/`setUpClass` 里的 spawn 也覆盖得到，且加新用例时不会漏。
    """
    if os.environ.get("OFFLINE_SUITE_RUNNING"):
        raise unittest.SkipTest(
            "离线套件禁用外部子进程（node/vite/vue-tsc 不在白名单）—— 见 tests/offline_suite.py"
        )

# 仓库根（frontend/ 与 backend/ 的父目录）；测试已随后端收进 backend/tests。
ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "frontend"
FACADE = FRONTEND / "src" / "composables" / "useLlmConfig.ts"
PURE = FRONTEND / "src" / "composables" / "llmLogic.ts"
BASELINE = FRONTEND / "tests" / "useLlmConfig.test.mjs"
PURE_TEST = FRONTEND / "tests" / "llmLogic.test.mjs"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: Path) -> str:
    """剥掉块注释 / 行注释（逐字符扫描，不用正则 —— 见第五十六刀的教训）。"""
    text = _read(p)
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                break
            out.append("\n")
            i = j + 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                break
            out.append("\n" * text.count("\n", i, j))
            i = j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _run_node(test_file: Path, timeout: int = 300):
    node = shutil.which("node")
    if node is None:
        raise unittest.SkipTest("未找到 node")
    _guard_offline()
    return subprocess.run([node, "--experimental-strip-types", str(test_file)],
                          cwd=str(FRONTEND), capture_output=True, text=True,
                          timeout=timeout)


class NodeBehaviourTest(unittest.TestCase):
    def test_pure_module_behaviour_passes(self):
        self.assertTrue(PURE_TEST.exists(), f"缺失: {PURE_TEST}")
        try:
            r = _run_node(PURE_TEST)
        except subprocess.TimeoutExpired:
            self.fail("llmLogic.test.mjs 超时")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, f"llmLogic 行为测试失败:\n{out[-3000:]}")
        m = re.search(r"(\d+) passed, (\d+) failed", out)
        self.assertIsNotNone(m, f"未解析到统计:\n{out[-1500:]}")
        self.assertGreaterEqual(int(m.group(1)), 90, f"断言数异常地少: {m.group(1)}")
        self.assertEqual(m.group(2), "0")

    def test_baseline_still_passes_unchanged(self):
        """⚠️ 本刀的核心证据：拆分后基线断言**一条未改**仍然全绿。"""
        self.assertTrue(BASELINE.exists())
        try:
            r = _run_node(BASELINE)
        except subprocess.TimeoutExpired:
            self.fail("useLlmConfig.test.mjs 超时")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0,
                         f"拆分后基线翻红 —— 说明接口/行为被改动了:\n{out[-3500:]}")
        m = re.search(r"(\d+) passed, (\d+) failed", out)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 130,
                                f"基线断言数变少了（{m.group(1)}）—— 是否删了断言？")


class NoDuplicationTest(unittest.TestCase):
    """⚠️ 本刀消掉的重复不得长回来。"""

    def test_payload_literal_only_in_pure_module(self):
        """模型 payload 的 11 字段回落链只应在 llmLogic.ts 一处。"""
        for p in (FACADE, PURE):
            src = _code(p)
            hits = src.count("从远端一键自动收录") + src.count("admin.llm.remoteAutoCollected")
            if p == PURE:
                self.assertEqual(hits, 1, "纯模块应恰好定义一次回落文案")
            else:
                self.assertEqual(hits, 0,
                                 "门面又内联了模型 payload —— 应用 buildRemoteModelPayload")

    def test_facade_calls_the_builder_twice(self):
        """两条收录路径（单个 / 批量）都必须走同一个 builder。"""
        src = _code(FACADE)
        self.assertEqual(src.count("buildRemoteModelPayload("), 2,
                         f"应有 2 处调用，实际 {src.count('buildRemoteModelPayload(')}")

    def test_activate_payload_is_shared_in_the_import_path(self):
        """⚠️ **收录**路径的 activate body 必须走 `buildActivatePayload`。

        注意 `activateModel()` 有它**自己**的 activate body（`provider_id` 带
        `|| 'custom'` 回落、`reasoning_effort || 'high'`），与收录路径**不同**，
        故刻意未统一 —— 第一版我把断言写成"门面不得出现 `model_id: m.id`"，
        结果被 `activateModel` 正当命中而误报。断言要窄到具体路径。
        """
        src = _code(FACADE)
        self.assertEqual(src.count("buildActivatePayload("), 1)
        # 收录路径的 body 应已被替换掉：不应再出现"紧跟 buildRemoteModelPayload
        # 的三字段内联对象"这一形态
        body = src[src.index("async function importRemoteModel"):src.index("async function importAll")]
        self.assertIn("buildActivatePayload(", body)
        self.assertNotIn("reasoning_effort: payload.reasoning_effort", body,
                         "收录路径又内联了 activate payload")

    def test_provider_id_derivation_is_shared(self):
        src = _code(FACADE)
        self.assertIn("providerIdFromName(", src)
        self.assertNotIn("[^a-z0-9_-]", src,
                         "门面又内联了 id 净化正则 —— 应走 providerIdFromName")

    def test_cascade_hint_is_shared(self):
        src = _code(FACADE)
        self.assertIn("providerDeleteCascadeHint(", src)
        self.assertNotIn("个模型将一并删除", src,
                         "门面又内联了级联提示文案")


class BehaviourPreservedTest(unittest.TestCase):
    """⚠️ 抽离阶段刻意保持与原实现逐字等价的几处（不得被"顺手改进"）。"""

    def test_filter_providers_has_no_name_guard(self):
        """原实现是**直接** `p.name.toLowerCase()`，没有存在性守卫。

        我第一版顺手加了 `(p.name && ...)` —— 那是行为变更（无 name 的供应商
        原本会抛错），与"保持业务逻辑完全不变"冲突，已改回。
        """
        src = _code(PURE)
        self.assertIn("p.name.toLowerCase().includes(q)", src)
        self.assertNotIn("(p.name && p.name.toLowerCase()", src,
                         "filterProviders 被加了守卫 —— 抽离阶段不应夹带行为变更")

    def test_filter_error_returns_original_reference(self):
        """无关键词时返回原数组引用（不是拷贝）—— 与原实现一致。"""
        src = _code(PURE)
        self.assertIn("if (!q) return providers", src)
        self.assertIn("if (!q) return models", src)

    def test_api_format_effect_keeps_custom_path(self):
        src = _code(PURE)
        self.assertIn("isStandardOrEmpty", src)

    def test_no_vue_or_network_dependency_in_pure_module(self):
        """纯逻辑模块不得依赖 vue / fetch / 任何 composable。"""
        src = _code(PURE)
        for banned in ("from 'vue'", "fetch(", "useApi", "useI18n", "useToast",
                       "ref(", "computed("):
            self.assertNotIn(banned, src, f"纯模块不应出现 {banned!r}")


class FacadeStillIntactTest(unittest.TestCase):
    def test_facade_still_returns_every_key(self):
        """导出面不得因为外提而少键（页面靠解构取用）。"""
        src = _code(FACADE)
        m = re.search(r"return \{(.*?)\n  \}", src, re.S)
        self.assertIsNotNone(m, "未解析到 return 块")
        returned = {x.strip().rstrip(",") for x in m.group(1).split("\n") if x.strip()}
        for k in ("cfg", "providerForm", "modelForm", "fallbackIds", "fallbackOptions",
                  "availableEffortOptions", "filteredProviders", "filteredRemoteModels",
                  "modelNameOf", "toggleFallback", "moveFallback", "onApiFormatChange",
                  "importRemoteModel", "importAllFilteredRemoteModels", "removeProvider",
                  "saveProviderConfig", "loadConfig"):
            self.assertIn(k, returned, f"导出面缺 {k}")

    def test_no_new_dependencies(self):
        """只允许原有 4 个 composable + vue + 新的本地纯模块。"""
        src = _read(FACADE)
        imports = re.findall(r"^import .*? from '([^']+)'", src, re.M)
        allowed = {"vue", "./useI18n", "./useApi", "./useConfirm", "./useToast",
                   "./llmLogic"}
        extra = [i for i in imports if i not in allowed]
        self.assertEqual(extra, [], f"出现预期外 import（禁止增减依赖）: {extra}")

    def test_pure_module_has_no_new_dependencies(self):
        src = _read(PURE)
        imports = re.findall(r"^import .*? from '([^']+)'", src, re.M)
        self.assertEqual(imports, [], f"纯模块不应 import 任何东西: {imports}")


if __name__ == "__main__":
    unittest.main()
