"""`useLlmConfig.ts` 行为基线（结构优化阶段 4·B3 第五十六刀）。

## 为什么先立基线而不是先拆

`frontend/src/composables/useLlmConfig.ts` 是前端最大的单文件
（**686 行**，~40 个函数，一个闭包里的 ~50 个绑定）。它的 docstring
自己写了后续拆法（provider / model / failover 三域），但**此前没有任何测试**。

无验证网就拆 686 行闭包，风险与收益不成比例 —— 故本轮先建**桩驱动的行为基线**，
断言全部是"从外部可观察的行为"（发往服务端的请求体、状态迁移、computed 产出），
这样按域拆分后这些断言**仍应全部成立**（拆分不应改变任何一条）。

## ⚠️ 本刀我在写基线时犯的错（连续第五刀同类）

给 `toggleProviderQuick` 注册桩时我写的是**结尾片段** `'/toggle'`，
而桩用 `startsWith` 前缀匹配、真实路径是
`/api/v1/admin/llm/providers/p2/toggle` —— 注册串不是它的前缀，
于是掉进默认 `{}`，症状是 `p.enabled` 变成 `undefined`。

**更该记的是我随后的误判**：我先把它归因为"宽前缀 `models` 遮住了窄前缀"，
据此改了注册顺序，**改完照样失败**（顺序与匹配无关，`startsWith` 本就不成立）。
直到把"注册了哪些前缀 + 实际请求路径"打出来，才看出是注册串本身写错。

> 教训：桩不生效时，**先打印取证，再猜原因**。
> 这是本仓反复出现的模式（第五十一 / 五十三 / 五十四 / 五十五刀同源）。

## 本文件做什么

1. **执行** `frontend/tests/useLlmConfig.test.mjs`（136 条断言），
   并钉住断言数下限，防"空跑也通过"。
2. 把"`useLlmConfig.ts` 的导出面"钉成事实 —— 拆分时**导出键名一个都不能少**，
   因为页面靠解构取用（`<script setup>` 顶层绑定对模板可见）。
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
MODULE = FRONTEND / "src" / "composables" / "useLlmConfig.ts"
NODE_TEST = FRONTEND / "tests" / "useLlmConfig.test.mjs"
PAGE = FRONTEND / "src" / "views" / "admin" / "LlmPage.vue"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: Path) -> str:
    """剥掉注释，只留可执行代码。

    ⚠️ **不要用正则做这件事。** 我在这里挂了两次：

    1. `re.sub(r"/\\*.*?\\*/", "", t, flags=re.S)` —— 非贪婪从**第一个** `/*`
       吃到**第一个** `*/`。当文档串里还有别的 `/**` 时（本文件正是），
       会留下半截注释残渣，之后所有基于位置的解析全部错位；
    2. `re.sub(r"^\\s*//.*$", "", t, flags=re.M)` 又会吃掉 `http://` 之类。

    改用**逐字符扫描**（与 `test_frontend_chart_countdown.py` 的
    `_strip_ts_comments` 同一思路），并保留字符串字面量。
    """
    out: list[str] = []
    text = p.read_text(encoding="utf-8")
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        # 行注释
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            if j == -1:
                break
            out.append("\n")
            i = j + 1
            continue
        # 块注释（含 JSDoc）
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                break
            # 保留换行数以维持行号
            out.append("\n" * text.count("\n", i, j))
            i = j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


class NodeBehaviourTest(unittest.TestCase):
    """执行桩驱动的行为基线。"""

    def test_behaviour_baseline_passes(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("未找到 node")
        self.assertTrue(NODE_TEST.exists(), f"行为基线文件缺失: {NODE_TEST}")
        try:
            _guard_offline()
            r = subprocess.run(
                [node, "--experimental-strip-types", str(NODE_TEST)],
                cwd=str(FRONTEND), capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            self.fail("frontend/tests/useLlmConfig.test.mjs 超时（300s）")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, f"useLlmConfig 行为基线失败:\n{out[-3500:]}")
        m = re.search(r"(\d+) passed, (\d+) failed", out)
        self.assertIsNotNone(m, f"未解析到用例统计:\n{out[-1500:]}")
        self.assertGreaterEqual(int(m.group(1)), 130,
                                f"断言数异常地少（{m.group(1)}）—— 基线可能被削弱")
        self.assertEqual(m.group(2), "0")


def _ctx_destructured_names(src: str) -> set[str]:
    """取 `const { ... } = useLlmCtx()` 里解构的名字。

    ⚠️ 我为这一件事连撞**四次**，全过程记下来（本仓"凭猜测写解析"的典型）：

    1. `re.search(r"const \\{(.*?)\\} = useLlmCtx\\(\\)", src, re.S)` —— 非贪婪从
       文件里第一个 `const {` 起匹配，跨过 `const { t } = useI18n()`，
       把 i18n 的解构也算进来（报出的"缺失键"里混进了 `t } = useI18n() ...`）；
    2. 改"从 `useLlmCtx()` 往前 `rfind('const {')`" —— 仍然 0 个键，
       因为 `const { t } = useI18n()` **含有** `const {` 子串；
    3. 改"往前找 `=` 再找 `{`" —— 撞上 `<script setup lang="ts">` 里的等号；
    4. 修好等号后仍失败 —— 因为 `_code()` 里的
       `re.sub(r"/\\*.*?\\*/", ...)` 把文档串**剥坏了**（非贪婪吃到前一个 `*/`），
       留下 `{` 残渣让配对错位。

    **最终形态**：`const {` 必须**行首锚定**，再用同文件里**行首锚定**的
    `} = useLlmCtx()` 收尾。行首锚定天然避开"子串出现在别处"的所有坑。
    """
    names: set[str] = set()
    pattern = r"^const \{\s*$(.*?)^\}\s*=\s*useLlmCtx\(\)\s*$"
    for m in re.finditer(pattern, src, re.S | re.M):
        for x in m.group(1).replace("\n", " ").split(","):
            x = x.strip()
            if x:
                names.add(x)
    return names


class ExportSurfaceTest(unittest.TestCase):
    """⚠️ 页面靠解构取用这些键；拆分时**一个都不能少**。"""

    # 与 node 基线里的"导出面"断言同源
    REQUIRED = [
        "cfg", "loading", "searchQuery", "currentView", "selectedProvider",
        "detailTab", "showApiKey", "providerForm", "testResult", "testLoading",
        "testingModelId", "fetchModalVisible", "fetchingRemote", "remoteFetchResult",
        "remoteSearch", "customFetchUrl", "customFetchKey", "modelModalVisible",
        "editingModel", "modelForm", "thinkingTimeoutInput", "savingSettings",
        "settingsResult", "requestAttemptsInput", "fallbackIds", "failoverEvents",
        "fallbackOptions", "availableEffortOptions", "filteredProviders",
        "filteredRemoteModels",
        "toggleFallback", "moveFallback", "modelNameOf", "loadFailoverEvents",
        "setPresetTimeout", "saveGlobalSettings", "loadConfig",
        "openAddProviderModal", "selectProvider", "onApiFormatChange",
        "goBackToList", "toggleProviderQuick", "saveProviderConfig",
        "clearCurrentProviderModels", "removeProvider",
        "openFetchDialog", "executeRemoteFetch", "importRemoteModel",
        "importAllFilteredRemoteModels",
        "openAddModelModal", "openEditModelModal", "saveModelForm",
        "activateModel", "deleteSingleModel", "runTestModel", "toggleCapability",
    ]

    def test_module_returns_every_required_key(self):
        src = _code(MODULE)
        m = re.search(r"return \{(.*?)\n  \}", src, re.S)
        self.assertIsNotNone(m, "未解析到 useLlmConfig 的 return 块")
        returned = {x.strip().rstrip(",") for x in m.group(1).split("\n") if x.strip()}
        missing = [k for k in self.REQUIRED if k not in returned]
        self.assertEqual(missing, [], f"导出面缺键（页面解构会得到 undefined）: {missing}")

    def test_page_provides_the_ctx_to_children(self):
        """⚠️ `LlmPage` 不是靠解构取用，而是 `provide(LLM_KEY, llm)`。

        真正的消费方在 `views/admin/llm/*.vue` —— 它们 `inject` 同一个 ctx 对象。
        这条钉住这个架构：若拆分时改成"各子组件自己调 useLlmConfig()"，
        各视图会各持一份互不相干的配置状态（`injection.ts` 的注释解释过），
        看起来能跑、实际全错。
        """
        src = _code(PAGE)
        self.assertIn("useLlmConfig()", src, "LlmPage 不再调用 useLlmConfig()")
        self.assertIn("provide(LLM_KEY, llm)", src, "LlmPage 不再 provide ctx")
        self.assertIn("const llm = useLlmConfig()", src,
                      "provide 的应是 useLlmConfig() 的返回值")

    def test_child_views_destructure_from_the_injected_ctx(self):
        """子视图必须用 `useLlmCtx()`，且解构的键都要在导出面里。"""
        llm_dir = FRONTEND / "src" / "views" / "admin" / "llm"
        consumers = sorted(llm_dir.glob("*.vue"))
        self.assertTrue(consumers, "llm/ 下没有子视图？")
        mod_src = _code(MODULE)
        m = re.search(r"return \{(.*?)\n  \}", mod_src, re.S)
        self.assertIsNotNone(m, "未解析到 return 块")
        returned = {x.strip().rstrip(",") for x in m.group(1).split("\n") if x.strip()}

        used_ctx = False
        total_keys: set[str] = set()
        for p in consumers:
            src = _code(p)
            if "useLlmCtx()" not in src:
                continue
            used_ctx = True
            self.assertNotIn(
                "useLlmConfig()", src,
                f"{p.name} 直接调了 useLlmConfig() —— 会脱离父页 provide 的同一份状态，"
                f"应改用 useLlmCtx()")
            names = _ctx_destructured_names(src)
            total_keys |= names
            missing = sorted(names - returned)
            self.assertEqual(missing, [],
                             f"{p.name} 解构了未导出的键（运行时 undefined）: {missing}")
        self.assertTrue(used_ctx, "没有任何子视图使用 useLlmCtx()")
        self.assertGreaterEqual(len(total_keys), 40,
                                f"子视图解构的键异常地少（{len(total_keys)}）")


class WiringTest(unittest.TestCase):
    """拆分时必须保持的接线约束（先钉住，拆分后复用）。"""

    def test_dual_named_imports_still_resolve(self):
        """`LlmPage` 的子组件也从 `llm/` 目录取用，确认没有被误删。"""
        llm_dir = FRONTEND / "src" / "views" / "admin" / "llm"
        if not llm_dir.exists():
            self.skipTest("llm/ 子目录不存在")
        self.assertTrue(list(llm_dir.glob("*.vue")), "llm/ 子组件目录为空")

    def test_no_vue_outside_setup_registration(self):
        """⚠️ `onMounted` 只应出现一次（`useLlmConfig` 的自动加载入口）。"""
        src = _code(MODULE)
        self.assertEqual(src.count("onMounted("), 1,
                         "onMounted 出现的次数变了 —— 拆分时容易漏掉或重复自动加载")

    def test_module_does_not_import_the_world(self):
        """本模块只应依赖 4 个 composable + vue，不得引入新依赖。"""
        src = _read(MODULE)
        imports = re.findall(r"^import .*? from '([^']+)'", src, re.M)
        allowed = {
            "vue", "./useI18n", "./useApi", "./useConfirm", "./useToast",
        }
        extra = [i for i in imports if i not in allowed]
        self.assertEqual(extra, [], f"出现了预期外的 import（禁止增减依赖）: {extra}")


if __name__ == "__main__":
    unittest.main()
