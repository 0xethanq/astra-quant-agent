r"""`r20 → astra` 改名对**提示词基座模块 id** 的影响面判据（2026-09-27）。

## 背景：这里差点成为一次静默的数据丢失

`scripts/prompt_templates.py::stable_base_module_id()` 用
`sha1(f"{种子}{title}")[:10]` 派生基座模块的**确定性 id**，种子原本是
`r20-base-module::`，全量改名时变成了 `astra-base-module::` ⇒ 所有基座模块 id 换了一批。

id 换了本身不可怕，可怕的是"换了一批"这件事**不会报错** ——
如果用户在本地方案库里按旧 id 存过自定义，而合并逻辑按 id 匹配，
那些自定义就会**静默消失**（表现为"我改的提示词怎么又回到默认了"）。

## 本门钉住的性质（把"我核实过一次"变成"每次提交都核实"）

1. **出厂基线不持久化这类 id**：`data/prompt_library.json` 里 `module-base-*` 条目数为 0。
   这是"改名安全"的第一块基石：没有存量 id 被写进仓库。
2. **合并按标题匹配，而不是按 id**：所以旧 id 只是被**重新派生**一次，
   仍然落在同一个标题上，不会产生重复模块、也不会丢掉用户覆盖。
   这是第二块基石，也是本门真正要守住的那条 —— 一旦有人把合并改成按 id 匹配，
   这条用例会立刻翻红并说明后果。
3. **id 与标题是 1:1 的确定性映射**：同标题恒等、异标题恒异。
"""
from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TEMPLATES = ROOT / "scripts" / "prompt_templates.py"
LIBRARY = ROOT / "scripts" / "prompt_library.py"
BASELINE_JSON = ROOT / "data" / "prompt_library.json"

#: 改名前的种子（**必须**在这里写出来才能断言"它派生的 id 不再出现"）
LEGACY_SEED = "r20-base-module::"
CURRENT_SEED = "astra-base-module::"


def _module_text() -> str:
    return TEMPLATES.read_text(encoding="utf-8")


class SeedIsNoLongerTheLegacyOneTest(unittest.TestCase):
    def test_the_live_seed_is_the_renamed_one(self):
        self.assertIn(CURRENT_SEED, _module_text(),
                      "种子应已随改名更新；若有意改回，请连同本文件一起重新论证")
        self.assertNotIn(f'f"{LEGACY_SEED}{{title}}"', _module_text(),
                         "活代码里不该再拿旧种子派生 id")

    def test_the_change_is_documented_in_place(self):
        """⚠️ 这条最重要：改种子必须**就地写明为什么安全**。

        本类存在的意义就是让下一个人看到 `astra-base-module::` 时，
        不会以为"这串是历史遗留，顺手改掉没关系"。
        """
        src = _module_text()
        # ⚠️ 必须锚在**代码里那次使用**，不能锚在注释中提到种子的地方 ——
        #    论证注释本身就会写出 `astra-base-module::`，锚错了取到的是注释之前的文本。
        usage = f'f"{CURRENT_SEED}{{title}}"'
        self.assertIn(usage, src, "找不到种子的实际使用点（本用例的锚点失效）")
        idx = src.index(usage)
        window = src[max(0, idx - 1400):idx]
        for frag in ("出厂基线", "按标题", "哈希输入"):
            self.assertIn(frag, window,
                          f"种子附近缺少安全论证的关键一条：{frag}")


class FactoryBaselinePersistsNoBaseIdsTest(unittest.TestCase):
    """基石一：出厂方案库里没有 `module-base-*` id ⇒ 改名没有存量 id 可破坏。"""

    def test_baseline_has_no_module_base_ids(self):
        self.assertTrue(BASELINE_JSON.is_file(), "出厂方案库不见了")
        found = []

        def walk(node):
            if isinstance(node, dict):
                mid = node.get("id")
                if isinstance(mid, str) and mid.startswith("module-base-"):
                    found.append((mid, node.get("title")))
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(json.loads(BASELINE_JSON.read_text(encoding="utf-8")))
        self.assertEqual(found, [],
                         "出厂基线开始持久化 module-base-* id 了 —— "
                         "此后改种子就会真正破坏存量数据，必须重新评估改名策略")


class MergeMatchesByTitleNotByIdTest(unittest.TestCase):
    """基石二（**真正要守的那条**）：合并按标题匹配，旧 id 只是被重新派生。"""

    def _apply_module_layout_src(self) -> str:
        src = LIBRARY.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "apply_module_layout":
                return ast.get_source_segment(src, node) or ""
        self.fail("prompt_library.apply_module_layout 不见了")

    def test_the_merge_keys_on_title(self):
        body = self._apply_module_layout_src()
        self.assertIn("base_by_title", body,
                      "合并逻辑不再按标题建索引 —— 若改成按 id 匹配，"
                      "改名后用户按旧 id 存的自定义会**静默丢失**")
        self.assertRegex(body, r"base_by_title\.get\(\s*title\s*\)",
                         "合并必须以**标题**为键查活模块")

    def test_orphan_base_modules_are_appended_by_title(self):
        body = self._apply_module_layout_src()
        m = re.search(r"output\.extend\(.*?base_modules.*?\)", body, re.S)
        self.assertIsNotNone(m, "找不到「未被匹配的基座模块」那一步")
        self.assertIn("title", m.group(0), "残留基座模块必须按标题去重，否则会产生重复预设")

    def test_ids_are_a_pure_function_of_the_title(self):
        """基石三：同标题恒等、异标题恒异 —— 所以"重新派生"是安全的。"""
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location("pt_seed_probe", TEMPLATES)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["pt_seed_probe"] = mod
        spec.loader.exec_module(mod)

        a1 = mod.stable_base_module_id("三重滤网裁决协议")
        a2 = mod.stable_base_module_id("三重滤网裁决协议")
        b = mod.stable_base_module_id("开仓与价格几何")
        self.assertEqual(a1, a2, "同标题必须得到同一个 id")
        self.assertNotEqual(a1, b, "不同标题必须得到不同 id")
        self.assertTrue(a1.startswith("module-base-"), f"id 前缀变了：{a1}")
        self.assertEqual(len(a1.split("-")[-1]), 10, "摘要长度是 id 形态的一部分")


if __name__ == "__main__":
    unittest.main()
