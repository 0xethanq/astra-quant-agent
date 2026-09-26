"""前端 HTTP 层收敛为单一实现（结构优化阶段 4·B3 第五十四刀）。

## 修了什么

`frontend/src/composables/useApi.ts` 原先**内联复刻**了
`frontend/src/api/http.ts` 里的整个 fetch 流程（拼 `X-Astra-Session` 会话头 →
解析响应 → 401 登出 → FastAPI `detail` 归一）。两份拷贝**已经漂移**：

| 行为 | `api/http.ts` | 旧 `useApi` |
|---|---|---|
| 网络层失败（DNS/断网/CORS） | `HttpError('网络错误，请稍后重试', 0)` | **原样抛出** `TypeError: Failed to fetch` 等浏览器原文 |
| 错误类型 | `HttpError`（带 `status`） | 裸 `Error` |

网络失败那条影响**所有后台页面**的报错文案 —— 用户看到浏览器英文原文。
现 `useApi` 委托 `http.ts` 的 `http()`，删除本地复刻。

同时删掉 `http.ts` 里**零引用**的 `useHttp()`（19 行）—— 它是同一段逻辑的
第三个副本，且全仓无人使用（实测 `useHttp` 仅出现在它自己的定义处）。

## ⚠️ 为什么是"委托"而不是"合并到 useApi"

`useResource.ts` 的注释解释过：`useApi()` 的 `loading`/`error` 是**实例共享**的，
多请求互相覆盖，所以各页才自己再写一份 —— 这两个 ref **按设计不该被消费**。
实测确认：全仓 20 处调用**无一例外**都是 `const { api } = useApi()`，
**没有任何地方解构或读取 `loading` / `error`**。

故只统一"真正在被使用的那部分"（`api`）。
`loading`/`error` 保留为兼容形状（避免破坏任何可能的动态访问），
但已标注"勿用"。

## ⚠️ 本刀暴露的一个基础设施缺口

前端**没有任何自动化验证**：`frontend/package.json` 只有 `dev`/`build`/`preview`，
**没有 `typecheck` 脚本**，`frontend/tests/` 只有 2 个 `.mjs` 且无人执行；
后端 `tests/` 对前端只是**源码字符串扫描**。

本刀实测确认 `vue-tsc --noEmit` 与 `vite build` 都是干净通过的（退出码 0），
故 `FrontendGateTest` 把它们**跑进后端测试套件**（各限时 300 秒，
工具或 tsconfig 缺失时跳过而不是失败）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
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

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HTTP_TS = FRONTEND / "src" / "api" / "http.ts"
USE_API_TS = FRONTEND / "src" / "composables" / "useApi.ts"
# 批 76：HTTP 层的用户可见文案迁到 i18n 词条（英文界面此前只显示中文）。
# 契约从"字面量写在 http.ts 里"变为"经 i18n 键取到同一条文案"。
ZH_COMMON_TS = FRONTEND / "src" / "locales" / "zh" / "common.ts"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: Path) -> str:
    """只保留**可执行代码**：去掉块注释、行注释与文档字符串。

    ⚠️ 本刀第一版直接扫原文，于是：
      ① `useApi.ts` 的**文档**里解释了"原先自己拼 `X-Astra-Session`" →
         被 `assertNotIn` 当成"仍在拼会话头"；
      ② `http.ts` 的**头部注释**写着"迁移自旧 useApi()" →
         被"不得 import useApi"的断言命中。
    这是本仓的老毛病：**文档里提到代码会让文本断言误命中**（第五十一刀同理）。
    故所有"不得存在"类断言一律扫 `_code()`。
    """
    text = _read(p)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)      # 块注释（含 JSDoc）
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)        # 整行注释
    text = re.sub(r"//[^\n]*$", "", text, flags=re.M)        # 行尾注释
    return text


class SingleImplementationTest(unittest.TestCase):
    def test_use_api_delegates_instead_of_reimplementing(self):
        """⚠️ `useApi` 不得再有内联 `fetch(` —— 那正是本刀删掉的重复实现。"""
        src = _read(USE_API_TS)
        self.assertNotIn("await fetch(", _code(USE_API_TS),
                         "useApi 又内联了 fetch —— 请改回委托 http.ts")
        self.assertIn("from '../api/http'", src)
        self.assertIn("await http<T>(path, options)", src)

    def test_use_api_does_not_build_session_header_itself(self):
        """会话头只应由 `http.ts` 拼一次。"""
        self.assertNotIn("X-Astra-Session", _code(USE_API_TS),
                         "useApi 自己拼了会话头 —— 会话逻辑应只有 http.ts 一处")

    def test_use_api_does_not_duplicate_detail_normalisation(self):
        """FastAPI `detail` 归一（422 数组→中文）只应由 `normalizeDetail` 一处实现。"""
        src = _read(USE_API_TS)
        self.assertNotIn("x.loc", src, "useApi 复刻了 detail 归一逻辑")
        self.assertNotIn("HTTP ${resp.status}", src)

    def test_unused_use_http_stays_removed(self):
        """`http.ts` 的 `useHttp()` 是零引用的第三个副本，已删。

        若将来要恢复，必须先有**消费方**，并说明它相对 `useResource` 的价值。
        """
        self.assertNotIn("useHttp", _code(HTTP_TS))

    def test_http_ts_no_longer_imports_vue(self):
        """删掉 `useHttp` 后 `http.ts` 不再需要 vue —— 纯 TS 更容易被独立检查。"""
        self.assertNotIn("from 'vue'", _code(HTTP_TS))

    def test_no_reverse_dependency(self):
        """`http.ts` 不得 import `useApi`（否则成环）。"""
        self.assertNotIn("useApi", _code(HTTP_TS))


class ErrorContractTest(unittest.TestCase):
    """⚠️ 委托后抛出的仍是 `Error` 子类，且非网络失败的文案逐字不变。"""

    def test_http_error_extends_error(self):
        src = _read(HTTP_TS)
        self.assertIn("class HttpError extends Error", src)

    def test_session_expired_message_unchanged(self):
        """各页 `catch (e) { toast(e.message) }` 直接展示这个文案。

        批 76：文案本身**逐字不变**，只是从 `http.ts` 的字面量搬到 zh 词条，
        由 `t('common.sessionExpired')` 取。故这里同时断言
        「http.ts 经该键取值」+「zh 词条仍是这条文案」。
        """
        self.assertIn("'common.sessionExpired'", _read(HTTP_TS))
        self.assertIn("sessionExpired: '会话已过期，请重新登录'", _read(ZH_COMMON_TS))

    def test_network_failure_message_is_the_friendly_one(self):
        """⚠️ 本刀修的漂移：网络层失败必须是中文友好文案，

        而不是旧 `useApi` 里原样冒出的 `TypeError: Failed to fetch`。
        批 76 同上：改断言"键 + zh 词条"，文案逐字不变。
        """
        self.assertIn("'common.networkRetry'", _read(HTTP_TS))
        self.assertIn("networkRetry: '网络错误，请稍后重试'", _read(ZH_COMMON_TS))

    def test_normalize_detail_handles_fastapi_422_array(self):
        """422 数组仍要拼成「字段：原因；字段：原因」。

        批 76：连接符改为 `t('common.punct.colon')` / `t('common.punct.semicolon')`
        （英文界面下不该混进中文标点），故断言键 + zh 词条里的连接符。
        """
        src = _read(HTTP_TS)
        self.assertIn("Array.isArray(detail)", src)
        # 断言**键**而非 `t(...)` 调用形状 —— 局部变量名（此处为 `tr`）不该被钉死
        self.assertIn("'common.punct.colon'", src)
        self.assertIn("'common.punct.semicolon'", src)
        zh = _read(ZH_COMMON_TS)
        self.assertIn("colon: '：'", zh)
        self.assertIn("semicolon: '；'", zh)


class ConsumersKeepWorkingTest(unittest.TestCase):
    """⚠️ 20 个消费方都写 `const { api } = useApi()` —— 这个形状必须保持。"""

    def test_all_consumers_still_destructure_api(self):
        hits = []
        for p in (FRONTEND / "src").rglob("*"):
            if p.suffix not in (".ts", ".vue"):
                continue
            if p == USE_API_TS:
                continue
            if "useApi()" in _read(p):
                hits.append(p)
        self.assertGreaterEqual(len(hits), 15, f"useApi 消费方异常地少: {len(hits)}")
        for p in hits:
            src = _read(p)
            for m in re.finditer(r"const \{([^}]*)\} = useApi\(\)", src):
                self.assertIn("api", m.group(1), f"{p} 未解构 api")

    def test_use_api_still_returns_api(self):
        src = _read(USE_API_TS)
        self.assertIn("return { loading, error, api }", src)


class FrontendGateTest(unittest.TestCase):
    """⚠️ 前端此前**没有任何自动化验证**（无 typecheck 脚本、无执行的测试）。

    本刀实测 `vue-tsc --noEmit` 与 `vite build` 都干净通过，
    故把它们跑进后端套件。工具缺失时**跳过而不是失败**
    （后端测试不应因前端依赖未安装而翻红）。
    """

    @staticmethod
    def _run(cmd, timeout=300):
        exe = FRONTEND / "node_modules" / ".bin" / cmd[0]
        if not exe.exists():
            raise unittest.SkipTest(f"{exe} 不存在（前端依赖未安装）")
        _guard_offline()
        return subprocess.run([str(exe), *cmd[1:]], cwd=str(FRONTEND),
                              capture_output=True, text=True, timeout=timeout)

    def test_vue_tsc_typecheck_passes(self):
        if not (FRONTEND / "tsconfig.app.json").exists():
            self.skipTest("tsconfig.app.json 不存在")
        r = self._run(["vue-tsc", "--noEmit", "-p", "tsconfig.app.json"])
        self.assertEqual(r.returncode, 0,
                         f"vue-tsc 类型检查失败:\n{(r.stdout + r.stderr)[-2500:]}")

    def test_vite_build_passes(self):
        r = self._run(["vite", "build"], timeout=600)
        self.assertEqual(r.returncode, 0,
                         f"vite build 失败:\n{(r.stdout + r.stderr)[-2500:]}")

    def test_package_json_has_no_typecheck_script(self):
        """如实记录基础设施缺口：`package.json` 没有 `typecheck` 脚本。

        本条**不是**要求它存在，而是把现状钉成事实 ——
        若将来补上脚本，此断言会翻红并提醒同步更新本文件的说明。
        """
        pkg = json.loads(_read(FRONTEND / "package.json"))
        scripts = pkg.get("scripts", {})
        self.assertEqual(sorted(scripts), ["build", "dev", "preview"],
                         f"package.json scripts 变化了: {sorted(scripts)} —— "
                         f"请同步更新 FrontendGateTest 的说明")


class NodeBehaviourTest(unittest.TestCase):
    """跑 `frontend/tests/http.test.mjs` —— 用**受控 fetch 桩**真跑一遍 HTTP 层。

    ⚠️ 本仓此前从无**被执行的**前端测试（`frontend/tests/` 里两个 `.mjs` 无人运行）。
    本类把它接进后端套件，避免又变成"没人跑的测试"。
    纯源码字符串扫描（上面的类）挡不住"委托后行为变了"，本类能。

    需要 Node ≥ 22.6（`--experimental-strip-types`）；不满足则**跳过**。
    """

    TEST = FRONTEND / "tests" / "http.test.mjs"

    def test_behaviour_suite_passes(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("未找到 node")
        if not self.TEST.exists():
            self.fail(f"行为测试文件缺失: {self.TEST}")
        try:
            _guard_offline()
            r = subprocess.run(
                [node, "--experimental-strip-types", str(self.TEST)],
                cwd=str(FRONTEND), capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            self.fail("frontend/tests/http.test.mjs 超时（300s）")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, f"前端 HTTP 行为测试失败:\n{out[-3000:]}")
        # 顺带钉住用例数量：防止文件被改成"空跑也通过"
        m = re.search(r"(\d+) passed, (\d+) failed", out)
        self.assertIsNotNone(m, f"未解析到用例统计:\n{out[-1500:]}")
        self.assertGreaterEqual(int(m.group(1)), 25,
                                f"行为用例数异常地少: {m.group(1)}")
        self.assertEqual(m.group(2), "0")


if __name__ == "__main__":
    unittest.main()
