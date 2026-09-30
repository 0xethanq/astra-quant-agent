"""`apply_module_layout` 的**兼容退路**（第二百一十四刀）。

编辑器档案有两种形态：新版是 `profile["pipelines"][pipeline]` 里的**模块列表**，
旧版是**一整段文本**。函数开头就判：**只要拿不到「含 base 源模块的列表」**，就走兼容退路 ——
把 base 模板与旧文本转出的模块拼起来，再交给**同一个**渲染器（并**带上 context**）。

本刀只钉这条退路（主路径分支很多，留待后续按需覆盖）：

| 输入 | 行为 |
|---|---|
| `pipelines` 不是字典 / `pipeline` 项不是列表 | 旧文本经 `text_to_modules` 转模块，与 base 模板合并后渲染 |
| 列表（**任何**列表） | **不走**退路：先做基座归一，再按模块编排渲染 |
| `pipelines` 是列表但 profile 另有旧文本 | 以**列表**为准（旧文本不再被并进来）|

⚖️ 2026-09-30 契约变更：旧判据是「列表里**一个 base 源模块都没有** ⇒ 算旧式」。
基座归一落地后该判据必须改 —— 归一本身就会把 base 源模块**补进**列表，若还按旧判据，
同一个列表会一会儿算旧式一会儿算新式（自相矛盾）。现判据只看**形状**（是不是列表），
于是一个只有 custom 项的列表走模块编排：基座按规范顺序回插、custom 项原位保留。
**结果正文与旧退路等价**（都是 base + custom，且 base 在前）—— 见
`test_a_custom_only_list_is_module_shaped_and_still_renders_base_first`。

★ 退路也必须**带上 context**：否则旧档案的变量会退回成字面量（正是席位提示词那次事故的形态）。
"""

import unittest
from unittest.mock import MagicMock, patch

from scripts import prompt_library as PL


class CompatPathTest(unittest.TestCase):
    def setUp(self):
        self.compile = patch.object(PL, "compile_modules",
                                    side_effect=lambda mods: "编译:" + repr(mods))
        self.compile_mock = self.compile.start()
        self.addCleanup(self.compile.stop)
        self.text_to_modules = patch.object(PL, "text_to_modules",
                                            return_value=[{"title": "旧模块",
                                                           "source": "custom",
                                                           "content": "旧文本"}])
        self.ttm = self.text_to_modules.start()
        self.addCleanup(self.text_to_modules.stop)
        # ⚠️ 替身必须**带 content**：生产里基座模块来自 `text_to_modules`，一定含 content。
        # 早先这里给的是没有 content 的裸 dict，基座归一接手后会在 `live["content"]` 上炸
        # KeyError —— 那是替身不真实，不是实现缺陷（实测踩过）。
        self.base = patch.object(PL, "base_template_modules",
                                 return_value=[{"title": "base-1", "source": "base",
                                                "content": "base 原文"}])
        self.base_mock = self.base.start()
        self.addCleanup(self.base.stop)
        self.render = patch.object(PL, "render_variables", return_value="渲染结果")
        self.render_mock = self.render.start()
        self.addCleanup(self.render.stop)
        self.ctx = {"k": 1}

    def test_non_dict_pipelines_uses_the_legacy_text(self):
        out = PL.apply_module_layout("BASE", {"pipelines": "旧档案"}, "trading_main", "标签",
                                     self.ctx)
        self.assertEqual(out, "渲染结果")
        self.assertIs(self.render_mock.call_args.args[1], self.ctx, "退路也必须带上 context")
        self.assertTrue(self.ttm.called, "旧文本必须经 text_to_modules 转换")

    def test_pipeline_entry_that_is_not_a_list_uses_the_legacy_text(self):
        PL.apply_module_layout("BASE", {"pipelines": {"trading_main": "旧文本"}},
                               "trading_main", "标签", self.ctx)
        self.assertTrue(self.ttm.called)

    def test_a_custom_only_list_is_module_shaped_and_still_renders_base_first(self):
        """★ 新判据：**是不是列表**（不是"有没有 base 源模块"）。

        只有 custom 项的列表也走模块编排 —— 基座归一按规范顺序把 `base-1` 回插到最前，
        custom 项原位保留。**结果与旧退路等价**（base + custom，且 base 在前），
        区别只在"由谁保证顺序"：以前靠 `base_modules + custom` 拼接，现在靠归一。
        """
        out = PL.apply_module_layout("BASE", {"pipelines": {"trading_main": [
            {"title": "自定义", "source": "custom", "content": "x"}]}},
            "trading_main", "标签", self.ctx)
        self.assertEqual(out, "渲染结果")
        self.assertFalse(self.ttm.called,
                         "已经是列表 ⇒ 直接用它，不该再去解析旧文本")
        compiled = self.compile_mock.call_args.args[0]
        self.assertEqual([m["title"] for m in compiled], ["base-1", "自定义"],
                         "基座必须排在 custom 之前（顺序与旧退路一致）")

    def test_a_base_source_module_does_not_take_the_legacy_path(self):
        """有 base 源模块 ⇒ 走模块编排，**完全不需要**解析旧文本。

        旧实现靠"这条分支里恰好没调用 `text_to_modules`"来间接证明；基座归一接手后
        更直接：整条模块路径**根本不碰**它，故把 `text_to_modules` 换成会爆炸的替身，
        正常返回即可证明没走退路（比原来"允许后续分支出错"的钉法更严）。
        """
        with patch.object(PL, "text_to_modules", side_effect=AssertionError("不该走退路")):
            out = PL.apply_module_layout("BASE", {"pipelines": {"trading_main": [
                {"title": "base-1", "source": "base", "enabled": True}]}},
                "trading_main", "标签", self.ctx)
        self.assertEqual(out, "渲染结果")
        self.assertFalse(self.ttm.called, "模块路径不得解析旧文本")

    def test_legacy_path_without_profile_pipeline_text(self):
        """旧档案里连这一段文本都没有 ⇒ 只编 base 模板（不炸）。"""
        out = PL.apply_module_layout("BASE", {}, "trading_main", "标签", self.ctx)
        self.assertEqual(out, "渲染结果")
        self.assertTrue(self.ttm.called, "空文本同样经转换函数（由它决定给不给模块）")


if __name__ == "__main__":
    unittest.main()
