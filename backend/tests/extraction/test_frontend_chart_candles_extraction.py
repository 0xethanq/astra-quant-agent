"""`ChartWorkstation.vue` 取蜡烛路径收敛（结构优化阶段 4·B3 第五十五刀）。

## 修了什么

`ChartWorkstation.vue` 原先有**两条逐字重复**的取蜡烛路径：

| 位置 | 用途 | 失败时 |
|---|---|---|
| `setDataLoader({ getBars })` | KLineChart 内部驱动取数 | `console.warn` 后 `callback([], false)` |
| `loadCandles()` | 定时静默刷新 | `console.warn` 后保持原图不动 |

两条各自内联了同一套 "拼 URL → `fetch` → 查 `res.ok` → 取 `data.candles`
→ 转 `KLineData`"，URL 拼法与字段映射**逐字相同**，只有错误处理不同 ——
这正是"想改一处却漏掉另一处"的典型结构。现抽到
`frontend/src/components/dashboard/chartCandles.ts`。

## ⚠️ 抽离阶段刻意**不夹带行为变更**

第一版我给 `lastClose` 加了 `Number.isFinite` 守卫（原实现没有），
会被 `NaN` 变成 `null`。虽然更"安全"，但那是**行为变更**，与"保持业务逻辑
完全不变"冲突 —— 已改回与原实现逐字等价的 `Number(last.close)`，
并在注释里记下"要不要挡 NaN"是需另行取证的独立决策。

## ⚠️ 本刀我又犯的错

在 `chartCandles.ts` 里**手写了一份 `KLineData` 接口**，`vue-tsc` 立刻报
`Index signature for type 'string' is missing` —— 两份形状看似相同、实际不兼容，
调用处 `callback(klineList)` 编译失败。已改为
`import type { KLineData } from 'klinecharts'`，类型定义只留一处。

## ⚠️ 这个测试**不是**独立的正确性证明（如实记录）

本文件是**源码结构断言** + **执行 node 行为套件**。前者挡"重复实现又长回来"，
后者挡"抽出来的逻辑行为不对"。至于"蜡烛字段的业务口径对不对"，
由**重构时的等价性**保证（原样搬运）并由
`frontend/tests/chartCandles.test.mjs` 的 41 条钉住。
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
DASH = ROOT / "frontend" / "src" / "components" / "dashboard"
COMPONENT = DASH / "ChartWorkstation.vue"
MODULE = DASH / "chartCandles.ts"
NODE_TEST = ROOT / "frontend" / "tests" / "chartCandles.test.mjs"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: Path) -> str:
    """只保留可执行代码：剥掉 `//`、`/* */` 与文档内容。

    ⚠️ 本仓老毛病：文档里提到代码会让文本断言误命中（第五十一 / 五十四刀）。
    所有"不得存在"类断言一律扫本函数的结果。
    只剥注释与模板/脚本外的说明，**保留字符串字面量**（断言要用到 URL 片段）。
    """
    text = _read(p)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    text = re.sub(r"//[^\n]*$", "", text, flags=re.M)
    return text


class ComponentNoLongerDuplicatesTest(unittest.TestCase):
    def test_component_has_no_direct_candle_fetch(self):
        """⚠️ 本刀的**核心断言**：组件里不得再有内联的蜡烛取数。

        旧实现两处都是 `await fetch(\`/api/v1/market/...\`)`。
        """
        code = _code(COMPONENT)
        self.assertNotIn("await fetch(", code,
                         "组件又内联了 fetch —— 取数应走 chartCandles.fetchCandles")
        self.assertNotIn("/api/v1/market/", code,
                         "组件又自己拼了行情 URL —— 应走 chartCandles.candlesUrl")

    def test_component_does_not_reimplement_field_mapping(self):
        """字段映射（`timestamp`/`volume`/`turnover`）只应在 chartCandles.ts 一处。"""
        code = _code(COMPONENT)
        self.assertNotIn("turnover: c.vol * c.close", code,
                         "组件里又出现了蜡烛字段映射 —— 应走 chartCandles.toKlineData")
        self.assertNotIn("volume: c.vol", code)

    def test_component_uses_the_shared_helper_twice(self):
        """两条路径都改用共享实现。"""
        code = _code(COMPONENT)
        self.assertEqual(code.count("fetchCandles("), 2,
                         f"应有 2 处调用 fetchCandles，实际 {code.count('fetchCandles(')}")
        self.assertIn("from './chartCandles'", code)

    def test_component_keeps_both_error_handlings(self):
        """两条路径的**错误处理刻意保留不同**（这是它们唯一的真实差异）。"""
        code = _code(COMPONENT)
        self.assertIn("'DataLoader getBars error:'", code)
        self.assertIn("'Candles fetch fallback:'", code)
        self.assertIn("callback([], false)", code)


class SharedModuleShapeTest(unittest.TestCase):
    def test_module_defines_the_three_entry_points(self):
        src = _code(MODULE)
        for fn in ("export function candlesUrl(", "export function toKlineData(",
                   "export async function fetchCandles("):
            self.assertIn(fn, src, f"chartCandles.ts 缺少 {fn}")

    def test_module_reuses_klinecharts_type_instead_of_redeclaring(self):
        """⚠️ 本刀我手写了一份 `KLineData` 接口 → `vue-tsc` 报
        `Index signature for type 'string' is missing`（两份形状不兼容）。

        类型定义只应有一处。
        """
        src = _code(MODULE)
        self.assertIn("import type { KLineData } from 'klinecharts'", src,
                      "应复用 klinecharts 的 KLineData")
        self.assertNotIn("export interface KLineData {", src,
                         "又自己声明了一份 KLineData —— 会与 klinecharts 的不兼容")

    def test_module_keeps_limit_and_cache_buster(self):
        src = _code(MODULE)
        self.assertIn("limit=150", src)
        self.assertIn("_t=${Date.now()}", src)
        self.assertIn("cache: 'no-store'", src)

    def test_module_does_not_swallow_errors(self):
        """`fetchCandles` **不吞异常** —— 由调用方按各自既有方式记日志。"""
        src = _code(MODULE)
        body = src[src.index("export async function fetchCandles("):]
        self.assertNotIn("catch", body, "fetchCandles 不应自己 catch（会改变两条路径的行为）")

    def test_last_close_has_no_finite_guard(self):
        """⚠️ 抽离阶段刻意与原实现逐字等价：不加 `Number.isFinite` 守卫。

        加了守卫会让 `NaN` 变 `null` —— 那是行为变更，与
        "保持业务逻辑完全不变"冲突。若将来要挡 NaN，是一个**独立**决策。
        """
        src = _code(MODULE)
        self.assertIn("Number(last.close)", src)
        self.assertNotIn("Number.isFinite(Number(last.close))", src,
                         "lastClose 被加了守卫 —— 抽离阶段不应夹带行为变更")


class NodeBehaviourTest(unittest.TestCase):
    """执行 `frontend/tests/chartCandles.test.mjs`（受控 fetch 桩真跑一遍）。"""

    @staticmethod
    def _run(cmd, timeout=300):
        node = shutil.which("node")
        if node is None:
            raise unittest.SkipTest("未找到 node")
        _guard_offline()
        return subprocess.run([node, "--experimental-strip-types", *cmd],
                              cwd=str(ROOT / "frontend"),
                              capture_output=True, text=True, timeout=timeout)

    def test_behaviour_suite_passes(self):
        if not NODE_TEST.exists():
            self.fail(f"行为测试文件缺失: {NODE_TEST}")
        try:
            r = self._run([str(NODE_TEST)])
        except subprocess.TimeoutExpired:
            self.fail("frontend/tests/chartCandles.test.mjs 超时（300s）")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, f"chartCandles 行为测试失败:\n{out[-3000:]}")
        m = re.search(r"(\d+) passed, (\d+) failed", out)
        self.assertIsNotNone(m, f"未解析到用例统计:\n{out[-1500:]}")
        self.assertGreaterEqual(int(m.group(1)), 35, f"用例数异常地少: {m.group(1)}")
        self.assertEqual(m.group(2), "0")


class LiveContractTest(unittest.TestCase):
    """⚠️ 桩里的响应形状必须与**真实网关**一致，否则测试是自说自话。

    这里把"网关实际返回什么"钉成事实（字段名与 `ts` 是毫秒）。
    网关不可用时跳过 —— 离线套件不应依赖实盘。
    """

    def _fetch(self):
        import json
        import urllib.request
        url = ("http://127.0.0.1:8080/api/v1/market/BTC-USDT-SWAP/candles"
               "?bar=1H&limit=150")
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status != 200:
                    self.skipTest(f"网关返回 {resp.status}")
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 - 网关不可用即跳过
            self.skipTest(f"网关不可用: {e}")

    def test_gateway_candle_shape_matches_the_stub(self):
        data = self._fetch()
        self.assertIn("candles", data)
        candles = data["candles"]
        self.assertIsInstance(candles, list)
        self.assertTrue(candles, "网关返回空蜡烛，无法核对形状")
        first = candles[0]
        for key in ("ts", "open", "high", "low", "close", "vol"):
            self.assertIn(key, first, f"网关蜡烛缺少 {key}（与测试桩不符）")
        self.assertGreater(first["ts"], 1e12, "`ts` 应是毫秒时间戳")

    def test_field_mapping_is_exercised_by_real_data(self):
        """用真实网关数据跑一遍归一，确认没有非有限值。"""
        data = self._fetch()
        node = shutil.which("node")
        if node is None:
            self.skipTest("未找到 node")
        import json
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"candles": data["candles"]}, fh)
            tmp = fh.name
        self.addCleanup(lambda: Path(tmp).unlink(missing_ok=True))
        script = (
            "import { pathToFileURL } from 'node:url';"
            "import fs from 'node:fs';"
            f"const d=JSON.parse(fs.readFileSync({tmp!r},'utf8'));"
            "const m=await import(pathToFileURL("
            "'src/components/dashboard/chartCandles.ts').href);"
            "const k=m.toKlineData(d.candles);"
            "const bad=k.filter(x=>!Number.isFinite(x.timestamp)"
            "||!Number.isFinite(x.close)||!Number.isFinite(x.turnover));"
            "console.log(JSON.stringify({n:k.length,bad:bad.length}));"
        )
        _guard_offline()
        r = subprocess.run([node, "--experimental-strip-types", "--input-type=module",
                            "-e", script],
                           cwd=str(ROOT / "frontend"), capture_output=True,
                           text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        payload = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(payload["n"], len(data["candles"]))
        self.assertEqual(payload["bad"], 0, "真实数据归一后出现非有限值")


if __name__ == "__main__":
    unittest.main()
