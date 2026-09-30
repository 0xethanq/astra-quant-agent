"""`components/admin/README.md` 的"引用者数"必须与实测一致
（结构优化阶段 4·B3 第五十五刀）。

## 为什么要立这个测试

该 README 原先有一段"顺带发现"，声称 `components/base/` 与
`components/dashboard/` 里 **10 个组件实测 0 个引用者**，并按仓库纪律
"未动，记录在此供后续决策"。

**这个结论是错的，而且危险**：这 10 个全部有消费者（`BaseDrawer` 甚至有 4 个）。
它是**误读台账 F7** 的产物 —— F7 讲的是 `components/admin/` 自己那 5 个组件里
有 4 个单用，不是 `base/`/`dashboard/` 里的组件有 0 个消费者。
把"单用（1 个消费者）"读成"0 个引用者"，顺手列成了另外两个目录的清单。

若有人照原结论清理，会**删掉 10 个正在使用的组件**。
更糟的是：这份 README **不被任何测试检查**，所以错误可以静默存活。

故本测试把 README 里的两张表都钉成"必须与实测一致"：

1. **顶层表**（`DataTable` / `PageHeader` 的引用者数）；
2. **更正表**（那 10 个组件的引用者数与消费者）。

## 判定口径（与 README 一致）

"消费者" = 在 `src/**` 的 `.ts`/`.vue` 里**真的 import 了它**
**或**在模板里用了 `<Name ...>` 标签的文件数，**排除它自己的定义文件**。
`*.md` 一律不参与统计（否则 README 提到自己就会互相计数 ——
这正是原结论没有暴露出来的原因之一）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "frontend" / "src"
README = SRC / "components" / "admin" / "README.md"


def _sources() -> list[Path]:
    return [p for p in SRC.rglob("*")
            if p.suffix in (".ts", ".vue") and p.is_file()]


def consumers_of(name: str) -> list[str]:
    """返回相对 `src/` 的消费者路径列表（排除自身定义文件）。

    ⚠️ 三种引入形态都要认（第一版只认 `import X from`，于是 6 个纯逻辑
    `.ts` 模块全被误判成"无消费者"）：

      1. `import X from './X.vue'`  —— 默认导入（`.vue` 组件）
      2. `import { a, b } from './x'` —— 命名导入（`.ts` 模块，路径是小写文件名）
      3. `<X ... />`               —— 模板标签（`.vue` 组件）
    """
    imp_default = re.compile(r"import\s+" + re.escape(name) + r"\s+from")
    tag = re.compile(r"<" + re.escape(name) + r"[\s/>]")
    # 命名导入：`from './name'` 或 `from './name.ts'`（大小写按文件实际名）
    imp_named = re.compile(r"from\s+'[^']*/" + re.escape(name) + r"(?:\.ts)?'")
    self_pat = re.compile(r"/" + re.escape(name) + r"\.(vue|ts)$")
    out = []
    for p in _sources():
        if self_pat.search(p.as_posix()):
            continue
        text = p.read_text(encoding="utf-8")
        if imp_default.search(text) or tag.search(text) or imp_named.search(text):
            out.append(p.relative_to(SRC).as_posix())
    return out


class ReadmeClaimTest(unittest.TestCase):
    def setUp(self):
        self.doc = README.read_text(encoding="utf-8")

    def test_readme_no_longer_claims_zero_consumers(self):
        """⚠️ 核心断言：那句错误结论不得**作为有效断言**复活。

        更正段落里用删除线**引用**了原句（那是刻意保留的历史），
        故只在"非删除线"的正文里禁止出现。判据：该行不以 `> ~~` 开头。
        """
        live = [ln for ln in self.doc.splitlines()
                if "实测 0 个引用者" in ln and not ln.lstrip().startswith("> ~~")]
        self.assertEqual(live, [],
                         "README 又出现了『实测 0 个引用者』的有效断言 —— "
                         "该结论已被证伪，请改为逐个取证")
        self.assertIn("它是错的", self.doc,
                      "README 应保留对原错误结论的更正说明（便于接手人理解历史）")

    def test_the_ten_components_all_have_real_consumers(self):
        """现存组件全部有消费者 —— 逐个实测。"""
        components = ["BaseSwitch", "BaseDrawer", "BaseDialog",
                      "BaseTabs", "CopyButton",
                      "DataStatus", "SettingsPopover", "FactorDrawer"]
        for name in components:
            with self.subTest(component=name):
                got = consumers_of(name)
                self.assertTrue(got, f"{name} 实测 0 个消费者 —— README 的更正表需更新")

    # ---------------------------------------------------------------- 表解析

    def _table_count(self, label: str) -> int:
        """从 README 表格里解析 `| <label> | <n> | ...` 的 `n`。

        ⚠️ 第一版我把期望值**硬编码在断言里**，于是"改 README 里的数字"
        根本不会翻红 —— 负向验证（把 8 改成 5）判定为 OK，暴露了盲区。
        改为**从文档本身解析**，文档一改数字就与实测不符 → 翻红。
        """
        # 匹配：| `DataTable.vue` | **8** |     或   | `base/BaseDrawer` | 4 | ...
        pat = re.compile(
            r"^\|\s*`?" + re.escape(label) + r"`?\s*\|\s*\*{0,2}(\d+)\*{0,2}\s*\|",
            re.M)
        m = pat.search(self.doc)
        self.assertIsNotNone(
            m, f"README 表格里找不到 {label} 的引用者数 —— 文档结构变了？")
        return int(m.group(1))

    def test_top_level_table_counts_match_reality(self):
        """顶层表（`DataTable` / `PageHeader`）的引用者数必须与实测一致。"""
        for label in ("DataTable.vue", "PageHeader.vue"):
            name = label[:-len(".vue")]
            with self.subTest(component=name):
                got = len(consumers_of(name))
                self.assertEqual(got, self._table_count(label),
                                 f"{name} 实测 {got} 个消费者，README 表格写的不是这个数")

    def test_correction_table_counts_match_reality(self):
        """README 更正表里写的消费者数必须与实测一致（**从文档解析**）。"""
        components = ["BaseSwitch", "BaseDrawer", "BaseDialog",
                      "BaseTabs", "CopyButton",
                      "DataStatus", "SettingsPopover", "FactorDrawer"]
        for name in components:
            with self.subTest(component=name):
                got = len(consumers_of(name))
                for label in (f"base/{name}", f"dashboard/{name}", name):
                    if re.search(r"^\|\s*`?" + re.escape(label) + r"`?\s*\|", self.doc, re.M):
                        self.assertEqual(
                            got, self._table_count(label),
                            f"{name} 实测 {got} 个消费者，README 表格写的不是这个数")
                        break
                else:
                    self.fail(f"README 更正表里找不到 {name} 的行")

    def test_readme_lists_the_dashboard_pure_logic_modules(self):
        """`components/dashboard/` 的纯逻辑 `.ts` 必须在导航里点名（现 7 个）。

        它们与同目录 `.vue` 混放，是接手人最容易看漏的一类文件。
        """
        dash = SRC / "components" / "dashboard"
        ts_modules = sorted(p.name for p in dash.glob("*.ts"))
        self.assertEqual(ts_modules, [
            "chartCandles.ts", "chartCountdown.ts", "chartIndicators.ts",
            "chartLiveLevels.ts", "chartMath.ts", "chartOverlays.ts", "chartStyles.ts",
        ], "dashboard 的纯逻辑模块清单变了 —— 请同步 README 导航")
        for m in ts_modules:
            with self.subTest(module=m):
                self.assertIn(m, self.doc, f"README 导航未提到 {m}")

    def test_every_ts_module_in_dashboard_has_at_least_one_consumer(self):
        """顺带守住"纯逻辑模块确实被用着"——防止外提后变成孤儿。"""
        dash = SRC / "components" / "dashboard"
        for p in sorted(dash.glob("*.ts")):
            with self.subTest(module=p.name):
                self.assertTrue(consumers_of(p.stem),
                                f"{p.name} 无消费者 —— 可能是外提后忘记接线")


if __name__ == "__main__":
    unittest.main()
