"""`CouncilPage.vue` 无状态逻辑外提（结构优化阶段 4·B3 第六十刀）。

## 为什么挑这个文件

`views/admin/CouncilPage.vue`（873 行，script 302 行）此前**没有任何行为测试**。
唯一的既有断言是
`tests/audit/test_audit_config_p1b_guards.py::test_ui_slots_are_real_variables`
—— 它只对 `{ k: '…' }` 字面量做正则扫描。也就是说这个页面里
"槽位是不是合法变量"有护栏，而**其余纯逻辑一条断言都没有**。

本刀把无状态部分搬进 `views/admin/council/councilLogic.ts`（与既有
`views/admin/llm/injection.ts` 同一惯例），使其可被 node 直接执行测试。

## ⚠️ 为什么不搬有状态的动作

`addNewCustomTrader` / `removeRole` / `saveConfig` / `runDebateTest` 读写的是
同一批 `ref`（`councilConfig` / `availableModels` / `expandedRole` …）。
搬成独立模块会各建一份新状态 —— `views/admin/llm/injection.ts` 的注释已解释过
这个陷阱（"看起来能跑、实际全错"）。故只搬**输入进、值出**的部分。

## ⚠️ 本刀顺手收掉 7 处重复判据

`role.is_arbitrator || roleId === 'cio'`（及其取反）在脚本与模板里**重复了 7 处**，
是典型的"改一处漏一处"结构。现收成 `isCioSeat()` 单一来源。

同处还消掉一处**跨文件漂移源**：模板里手写的
`['trader_trend','trader_momentum','trader_quant']` 与新增的
`BUILTIN_TRADER_IDS` 是同一份知识的两份拷贝，已改为引用后者。

## ⚠️ 我改了一处既有护栏（如实记录）

`test_ui_slots_are_real_variables` 原本正则扫 `CouncilPage.vue`，
`dataSlots` 搬走后它**再也扫不到**（`assertTrue(keys)` 失败）——
这正说明该护栏是"跟随数据位置"的。已改为扫**两个文件**。

**刻意没有**改成"import 那个 ts 模块再读 `DATA_SLOTS`"：那样做，
用例就**不再强制任何源文件里存在槽位定义** —— 把定义删掉、只在测试里留一份，
用例照样绿。扫源文件虽然粗糙，但它保证"真值在源码里"。
另加了 `len(keys) >= 8` 下限，防止"删剩一个"也蒙混过关。

## ⚠️ 我刻意**没有**改的一处

模板里插入槽位的表达式：

```
@click="role.prompt = role.prompt ? `${role.prompt.trim()}\\n${t(...)}{{${slot.k}}}` : `{{${slot.k}}}`"
```

看起来可以调 `slotSnippet(slot.k)`，但该三元**两次求值 `role.prompt`**，
改成函数调用后求值次数会变（对本例是纯读，但语义已变）。
按"重构不改行为"的约束，**保持原样**，`slotSnippet` 也就没有存在理由，已删除。
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
PAGE = FRONTEND / "src" / "views" / "admin" / "CouncilPage.vue"
LOGIC = FRONTEND / "src" / "views" / "admin" / "council" / "councilLogic.ts"
NODE_TEST = FRONTEND / "tests" / "councilLogic.test.mjs"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: Path) -> str:
    """剥掉块注释 / 行注释 / 文档串（逐字符扫描，不用正则）。"""
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
    def test_logic_behaviour_passes(self):
        self.assertTrue(NODE_TEST.exists(), f"缺失: {NODE_TEST}")
        try:
            r = _run_node(NODE_TEST)
        except subprocess.TimeoutExpired:
            self.fail("councilLogic.test.mjs 超时")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, f"行为测试失败:\n{out[-3000:]}")
        m = re.search(r"(\d+) passed, (\d+) failed", out)
        self.assertIsNotNone(m, f"未解析到统计:\n{out[-1500:]}")
        self.assertGreaterEqual(int(m.group(1)), 90, f"断言数异常地少: {m.group(1)}")
        self.assertEqual(m.group(2), "0")


class DuplicationRemovedTest(unittest.TestCase):
    """⚠️ 本刀消掉的重复不得长回来。"""

    def test_cio_judgement_is_single_source(self):
        """`is_arbitrator || roleId === 'cio'` 的重复从 7 处收成 1 处。"""
        page = _code(PAGE)
        hits = page.count("is_arbitrator")
        # 只允许在 addNewCustomTrader 的对象字面量里出现一次（is_arbitrator: false）
        self.assertLessEqual(hits, 1,
                             f"页面里仍有 {hits} 处 is_arbitrator —— 应走 isCioSeat()")
        self.assertNotIn("roleId === 'cio'", page,
                         "页面里仍有裸的 roleId === 'cio' 判据")
        self.assertGreaterEqual(page.count("isCioSeat("), 4,
                                "模板里的 CIO 判据应已全部改为 isCioSeat()")
        logic = _code(LOGIC)
        # 收成单一来源：判据本体只应出现一次，并引用 CIO_ROLE_ID 常量
        self.assertEqual(logic.count("is_arbitrator"), 1,
                         "isCioSeat 里应只有一处 is_arbitrator")
        self.assertIn("roleId === CIO_ROLE_ID", logic)

    def test_builtin_trader_list_is_single_source(self):
        """内置交易员 id 列表不得在页面里手写第二份。"""
        page = _code(PAGE)
        self.assertNotIn("'trader_momentum'", page,
                         "页面里又手写了内置交易员列表 —— 应走 isBuiltinTrader()")
        self.assertIn("BUILTIN_TRADER_IDS", _code(LOGIC))
        self.assertIn("isBuiltinTrader(", page)

    def test_consensus_modes_and_slots_live_in_logic(self):
        """⚠️ 断言必须**窄到定义形态**。

        我第一版写 `assertNotIn("cross_examination", page)` —— 立刻误报：
        模板里有 `testResult.transcript?.cross_examinations`，
        那是**后端返回的字段名**，与"议事模式定义"是两回事
        （本仓第 N 次"断言过宽 → 误报"）。
        """
        page = _code(PAGE)
        self.assertNotIn("{ k: '", page, "槽位定义应只在 councilLogic.ts")
        # 议事模式的**定义形态**不得出现在页面里
        self.assertNotIn("{ id: '", page, "议事模式定义应只在 councilLogic.ts")
        # ⚠️ 我原本还想断言 `assertNotIn("标准提案模式", page)` —— 又误报：
        #    当时页面把 `'标准提案模式'` 当作 `consensusModeName(mode, fallback)`
        #    的**回落实参**传进去，那是正当用法。
        #
        # 🔁 2026-09-16（批 40）重钉：模式卡此前直接渲染 `CONSENSUS_MODES` 里的
        #    中文 name/tag/desc，英文界面显示中文；locale 里 `modeStandard*` /
        #    `modeCross*` 六个键只有 `modeStandardName` 被当回落用到，且文案与常量
        #    已分叉（如 tag：常量 `Standard` vs locale `高效终审`）——两份真源。
        #    修法是把展示文案改走 locale 查表（`MODE_TEXT_KEY` 存**完整键路径**），
        #    常量退回"id 登记 + 回落"。**原意照旧但来源变了**，故断言改为：
        #    页面出现的是键路径，而 zh locale 的该键必须与逻辑模块里的模式名一致。
        page = _code(PAGE)
        logic_src = _code(LOGIC)
        self.assertIn("admin.council.modeStandardName", page,
                      "模式展示文案必须走 locale 键路径")
        self.assertNotIn("mode.name }}", page,
                         "模式卡不得再直接渲染常量里的 name")
        self.assertIn("name: '标准提案模式'", logic_src,
                      "逻辑模块里的模式名应保持不变（作为回落实参）")
        zh_council = (ROOT / "frontend" / "src" / "locales" / "zh" / "admin"
                      / "council.ts").read_text(encoding="utf-8")
        self.assertIn("modeStandardName: '标准提案模式'", zh_council,
                      "zh locale 的模式名必须与逻辑模块里的模式名一致")
        logic = _code(LOGIC)
        self.assertIn("{ k: 'market_matrix'", logic)
        # ⚠️ 用 `id: 'x'` 而不是 `{ id: 'x'` —— 我第一版写成后者，
        #    但 prettier 把每个模式对象折成多行（`{\n    id: 'x',`），
        #    字符串层面根本不匹配。**又一次"凭印象写格式"**。
        for mode_id in ('standard', 'cross_examination', 'debate'):
            self.assertIn(f"id: '{mode_id}'", logic)
        # 后端字段名在模板里是正当的
        self.assertIn("cross_examinations", page)

    def test_icon_table_keys_are_derived_not_guessed(self):
        """图标表键必须经 roleIconKeyOf() 取，不得再写 `roleIcons[roleId] || ...`。

        2026-09-16 重钉：改版**刻意弃用** `councilLogic.roleColorOf / ROLE_COLORS`
        的五色轮盘（页面 docstring 写明："与「单一强调色 + 语义色」的工作台语言冲突"，
        新设计改中性席位牌 + CIO 走品牌强调色；该模块与其 mjs 契约测试未被改动）。
        故原断言"页面必须出现 `roleColorOf(`"已不成立——**原意照旧**：
        键要经函数推导、不许手写查表；顺手把"颜色轮盘不得复活"反向钉住。
        """
        page = _code(PAGE)
        self.assertIn("roleIcons[roleIconKeyOf(", page)
        self.assertNotIn("roleColors[roleId]", page)
        self.assertNotIn("roleColorOf(", page, "五色轮盘已弃用，不得复活")
        self.assertIn("seatTone(", page, "席位着色必须走单一来源 seatTone()")


class ChainIntactTest(unittest.TestCase):
    """页面仍须保留接收这些值的接线（外提不等于断开）。"""

    def test_page_imports_the_logic_module(self):
        src = _read(PAGE)
        self.assertIn("from './council/councilLogic'", src)

    def test_page_still_holds_the_stateful_actions(self):
        """有状态的动作**必须**留在页面里（搬走会各建一份新状态）。"""
        src = _read(PAGE)
        for fn in ("async function loadData", "async function saveConfig",
                   "async function exportConfig", "async function doImportConfig",
                   "async function applySuite", "function addNewCustomTrader",
                   "async function removeRole", "async function resetRole",
                   "async function runDebateTest"):
            self.assertIn(fn, src, f"有状态动作 {fn} 不应被搬走")

    def test_page_still_renders_roles_and_slots(self):
        """2026-09-16 重钉：席位列改由派生值 `seatEntries` 驱动（改版把逐个席位大卡
        手风琴换成「席位列 / 席位编辑器」主从双栏），模板里不再出现字面量
        `councilConfig.roles`。**原意不变**：共识模式、数据槽位、席位（roles）、
        模型库四样都必须仍在渲染，且 roles 仍取自接口载荷。
        """
        src = _read(PAGE)
        for anchor in ('v-for="mode in CONSENSUS_MODES"',
                       'v-for="[roleId, role] in seatEntries"',
                       'v-for="slot in DATA_SLOTS"',
                       "councilConfig.value.roles",
                       "availableModels"):
            self.assertIn(anchor, src, f"页面模板缺少 {anchor}")

    def test_logic_module_is_pure(self):
        """逻辑模块不得 import 任何东西（连 vue 都不 import）。"""
        src = _read(LOGIC)
        imports = re.findall(r"^\s*import\s", src, re.M)
        self.assertEqual(imports, [], f"逻辑模块不应有 import: {len(imports)} 处")
        for banned in ("from 'vue'", "fetch(", "useApi", "useI18n", "useToast",
                       "ref(", "computed("):
            self.assertNotIn(banned, src, f"逻辑模块不应出现 {banned!r}")

    def test_timeout_fallback_matches_page_initial_value(self):
        """⚠️ 两处超时回落值必须一致，否则用户不改超时也会被静默改值。"""
        logic = _code(LOGIC)
        page = _code(PAGE)
        m_logic = re.search(r"Number\(cfg\?\.timeout_seconds\) \|\| ([\d.]+)", logic)
        m_page = re.search(r"timeout_seconds: ([\d.]+)", page)
        self.assertIsNotNone(m_logic, "逻辑模块里找不到超时回落值")
        self.assertIsNotNone(m_page, "页面里找不到超时初始值")
        a, b = float(m_logic.group(1)), float(m_page.group(1))
        self.assertEqual(a, b,
                         f"超时回落值不一致：逻辑模块 {a} vs 页面初值 {b}")


class NoNewDependenciesTest(unittest.TestCase):
    def test_page_imports_unchanged_plus_logic(self):
        """页面 import 白名单（禁止无端增减依赖）。

        2026-09-16 重钉：改版把「页内展开的导入面板」改成 `BaseDialog`、总开关改用
        `BaseSwitch`（页面 docstring 写明"对话框化"），故白名单增两项**本仓内部组件**。
        原意（不许引入新的**第三方依赖**）不但保留，还补了一条更直接的断言：
        非相对路径的 import 只许 `vue` / `lucide-vue-next`。
        """
        src = _read(PAGE)
        imports = re.findall(r"^import .*? from '([^']+)'", src, re.M)
        allowed = {"vue", "../../utils/format", "../../composables/useToast",
                   "../../composables/useConfirm", "../../components/admin/PageHeader.vue",
                   "../../composables/useI18n", "../../composables/useApi",
                   "../../stores/auth", "lucide-vue-next",
                   "../../components/base/BaseSwitch.vue",
                   "../../components/base/BaseDialog.vue",
                   "../../components/base/BaseLoadingAnnounce.vue",
                   "./council/councilLogic"}
        extra = [i for i in imports if i not in allowed]
        self.assertEqual(extra, [], f"出现预期外 import（禁止增减依赖）: {extra}")
        # ⚠️ 上面那条 `^import .*? from` 只扫**单行** import（lucide 是多行 import，
        # 历来扫不到）。第三方依赖另用不锚行首的匹配来钉，覆盖多行写法。
        all_from = re.findall(r"from '([^']+)'", src)
        third_party = sorted({i for i in all_from if not i.startswith(".")})
        self.assertEqual(third_party, ["lucide-vue-next", "vue"],
                         f"第三方依赖只许 vue / lucide-vue-next（内部相对路径不算依赖）: {third_party}")


if __name__ == "__main__":
    unittest.main()
