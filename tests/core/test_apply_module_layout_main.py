"""`apply_module_layout` **主路径**的关键分支（第二百一十五刀；2026-09-30 按新契约改钉）。

## ★ 契约变更（2026-09-30，用户批准）

起因是用户报障：「提示词工坊的提示词怎么和决策透视的提示词不一样，是不是有什么 bug」。
实测根因：出厂方案在 `trading_system` / `evolution_system` 上**一个 base 模块都没登记** ——
工坊只列出覆盖层（**1356 字符 vs 实发 9700 字符**），排序/启停对那几条管线全都无效；
运行期则靠"无 base ⇒ 基座整段前置"的兜底静默注入。

故 `apply_module_layout` 现在**先做基座归一**（`normalize_base_modules`），契约随之变化：

| 语义 | 旧口径 | **新口径** |
|---|---|---|
| 缺登记的 base 分节 | 不补回（`trading_user` 例外，fail-closed 补回）| **所有 pipeline 都按基座规范顺序回插** —— 基座分节不得因档案遗漏而消失 |
| base 项的 `content` | 三态：`None`⇒模板、`""`⇒空、其它⇒档案内容 | **恒取现网基座**（基座只读，"代码升级后自动同步"才成立）；三态只适用于 `custom`/`legacy` |
| 改写 base 项 | 直接生效（等于冻结该节，代码升级到不了它）| 由**保存路径** `demote_edited_base_modules` 降级为 `legacy` 覆盖层后生效（实发 = 基座 + 覆盖层）|
| 删掉 base 项 | 该节不再输出 | **会被回插**（删 ≠ 移除；要移除请用 `enabled=False`）|
| ★ 禁用 ≠ 缺失 | 显式禁用不输出、也不补回 | **不变**（最重要的安全属性之一）|
| ★ 锁定节强制模板原文 | 强行用 base 原文 | **不变**（现在恒成立，仍显式钉住）|
| ★ `trading_user` fail-closed | 补回被编组漏掉的前置模块 | **不变** |
| 标题对不上的 base 项 | 有内容才输出 | **降级 `legacy` 原位保留**（不再静默丢弃；空内容的仍会被后续判空过滤）|
| 其它 pipeline 严格 | 不补回 | **已取消**（见第一行）|

最后统一走 `render_variables(compile_modules(...), context)` —— **context 一定带上**。
"""

import unittest
from unittest.mock import patch

from scripts import prompt_library as PL

BASE = [{"title": "实时一览", "source": "base", "content": "模板A"},
        {"title": "三重滤网裁决协议", "source": "base", "content": "锁定原文"},
        {"title": "没被档案提到的节", "source": "base", "content": "模板C"}]


class MainPathTest(unittest.TestCase):
    def setUp(self):
        self.base = patch.object(PL, "base_template_modules", return_value=list(BASE))
        self.base_mock = self.base.start()
        self.addCleanup(self.base.stop)
        self.compile = patch.object(PL, "compile_modules",
                                    side_effect=lambda mods: "编译:" + "|".join(
                                        m["content"] for m in mods))
        self.compile_mock = self.compile.start()
        self.addCleanup(self.compile.stop)
        self.render = patch.object(PL, "render_variables", return_value="输出")
        self.render_mock = self.render.start()
        self.addCleanup(self.render.stop)

    def _profile(self, pipeline, items):
        return {"pipelines": {pipeline: items}}

    def _all_base(self, pipeline, extra=()):
        """写出**全部**基座标题再附加 extra —— 让用例只考它自己要考的那条语义。"""
        items = [{"title": m["title"], "source": "base"} for m in BASE]
        return self._profile(pipeline, items + list(extra))

    def test_a_missing_base_section_is_reinserted_in_canonical_order(self):
        """★ 新契约（本次变更的核心）：档案只写了一段 ⇒ 其余基座分节按**规范顺序**回插。"""
        PL.apply_module_layout("BASE",
                               self._profile("trading_main", [
                                   {"source": "base", "title": "实时一览", "content": "档案A"}]),
                               "trading_main", "标签", {"k": 1})
        got = self.compile_mock.call_args.args[0]
        self.assertEqual([m["title"] for m in got],
                         ["实时一览", "三重滤网裁决协议", "没被档案提到的节"],
                         "缺登记的基座分节必须按基座规范顺序回插（不得追加到末尾打乱顺序）")
        self.assertEqual([m["content"] for m in got], ["模板A", "锁定原文", "模板C"],
                         "回插的分节带现网基座正文；档案里那段 base 的正文被治愈为基座原文")

    def test_base_content_is_code_owned_whatever_the_profile_says(self):
        """★ 基座只读：`None` / 空串 / 自定义内容**一律**取现网基座。

        旧口径是"三态"（`None`⇒模板、`""`⇒空、其它⇒档案内容）。新口径下 `source=="base"`
        的内容由代码所有 —— 这正是前端 `source.baseTip`（"代码升级后会自动同步到本方案"）
        能成立的前提；想让自定义内容生效，保存路径会把它降级成 `legacy` 覆盖层。
        """
        for content in (None, "", "档案A"):
            with self.subTest(content=content):
                PL.apply_module_layout("BASE",
                                       self._profile("trading_main", [
                                           {"title": "实时一览", "source": "base",
                                            "content": content},
                                           {"title": "三重滤网裁决协议", "source": "base"},
                                           {"title": "没被档案提到的节", "source": "base"}]),
                                       "trading_main", "标签", {"k": 1})
                got = self.compile_mock.call_args.args[0]
                self.assertEqual(got[0]["content"], "模板A",
                                 f"base 项 content={content!r} 应被治愈为现网基座正文")

    def test_custom_module_keeps_its_own_content(self):
        """§ 三态语义仍在 —— 但只对 `custom`/`legacy` 这类**非基座**项。"""
        PL.apply_module_layout("BASE",
                               self._all_base("trading_main", [
                                   {"title": "我的自定义", "source": "custom", "content": "自定义正文"}]),
                               "trading_main", "标签", {"k": 1})
        got = self.compile_mock.call_args.args[0]
        self.assertEqual(got[3]["content"], "自定义正文", "自定义项用自己的正文")

    def test_a_disabled_base_item_is_dropped_and_not_readded(self):
        """★ **禁用 ≠ 缺失**（不变的安全属性）：显式关掉的分节真的不出现，也不会被回插。"""
        PL.apply_module_layout("BASE",
                               self._profile("trading_user", [
                                   {"source": "base", "title": "实时一览", "enabled": False},
                                   {"source": "base", "title": "没被档案提到的节",
                                    "enabled": False}]),
                               "trading_user", "标签", {"k": 1})
        got = self.compile_mock.call_args.args[0]
        self.assertEqual([m["title"] for m in got], ["三重滤网裁决协议"],
                         "两个显式禁用的分节都不输出；未禁用的那节照常回插（删≠移除，禁用才移除）")
        self.assertNotIn("实时一览", [m["title"] for m in got])
        self.assertNotIn("没被档案提到的节", [m["title"] for m in got])

    def test_locked_sections_force_the_base_text(self):
        """★ 锁定节强制用模板原文（档案里的自定义内容对它无效）—— 新契约下恒成立，仍显式钉住。"""
        PL.apply_module_layout("BASE",
                               self._profile("trading_main", [
                                   {"source": "base", "title": "实时一览"},
                                   {"source": "base", "title": "三重滤网裁决协议",
                                    "content": "被篡改的内容"},
                                   {"source": "base", "title": "没被档案提到的节"}]),
                               "trading_main", "标签", {"k": 1})
        got = self.compile_mock.call_args.args[0]
        locked = [m for m in got if m["title"] == "三重滤网裁决协议"]
        self.assertEqual(len(locked), 1, "锁定节应恰好一条")
        self.assertEqual(locked[0]["content"], "锁定原文", "锁定节不得被档案内容覆盖")

    def test_fail_closed_readds_pre_title_modules_in_trading_user(self):
        """★ **Fail closed 真正起作用的地方**：`trading_user` 编组只把「第一个标题之后」的模块
        收进父节；**第一个标题之前**的模块不进任何组 ⇒ 本来会被漏掉 ⇒ 由 fail-closed **补回末尾**。

        2026-09-30 补记：基座归一现在会先把缺登记的分节按规范顺序回插，于是"前置节"通常
        在归一阶段就回到了输出里；fail-closed 仍然是**最后一道**保险（它接住的是"归一回插
        之后仍不在任何组里"的模块）。故本用例改为钉**最终输出集合**，并保留原意：
        第一个标题之前的模块绝不允许消失。
        """
        base = [{"title": "前置节", "source": "base", "content": "模板P"},
                {"title": "实时一览", "source": "base", "content": "模板A"},
                {"title": "没被档案提到的节", "source": "base", "content": "模板C"}]
        with patch.object(PL, "base_template_modules", return_value=base):
            PL.apply_module_layout("BASE",
                                   self._profile("trading_user", [
                                       {"source": "base", "title": "实时一览",
                                        "content": "档案A"}]),
                                   "trading_user", "标签", {"k": 1})
        got = self.compile_mock.call_args.args[0]
        self.assertEqual([m["title"] for m in got], ["前置节", "实时一览", "没被档案提到的节"],
                         "第一个标题之前的「前置节」必须出现在输出里（不得静默丢弃）")

    def test_trading_user_keeps_a_profile_content_that_holds_variables(self):
        """★ `trading_user` 下：档案内容**含变量** ⇒ **原样保留**，不编译。

        理由：它本身就是一块模板（变量留给渲染器统一替换）；若此处编译，变量会被当正文固化 ——
        正是席位提示词那次事故（提示词里出现字面量花括号）的形态。

        这类"插槽载体"由 `_carries_unique_slot` 识别，**不得**被基座说明文本治愈掉
        （`trading_user` 的现网基座是给编辑器看的说明版，覆盖它等于关掉实时数据注入）。
        """
        PL.apply_module_layout("BASE",
                               self._profile("trading_user", [
                                   {"title": "实时一览", "source": "base",
                                    "content": "实时:{{macro_4h}} 结束"},
                                   {"title": "三重滤网裁决协议", "source": "base"},
                                   {"title": "没被档案提到的节", "source": "base"}]),
                               "trading_user", "标签", {"k": 1})
        got = self.compile_mock.call_args.args[0]
        self.assertEqual(got[0]["content"], "实时:{{macro_4h}} 结束",
                         "含变量的档案内容不得被编译（否则变量变成字面量）")

    def test_trading_user_without_variables_uses_the_live_section_not_the_stored_text(self):
        """★ `trading_user` 下：档案内容**不含变量** ⇒ 用**现网基座**那一份，而不是存档正文。

        为什么不直接钉"整组编译含嵌套小节"：2026-09-30 的基座归一之后，**每个规范分节都会
        被登记为父节**，于是 `_trading_user_parent_groups` 再也不会把规范标题吸收进别的组
        —— 那个场景在新契约下已不可达（`tests/core/test_prompt_library_groups.py` 仍单独钉住
        编组函数自身的三条语义）。这里改钉**仍然可达且真正重要**的那条：
        存档正文与现网基座不同时，`trading_user` 用的是**现网那一份**。
        """
        with patch.object(PL, "base_template_modules",
                          return_value=[{"title": "实时一览", "source": "base",
                                         "content": "现网实时正文"}]):
            PL.apply_module_layout("BASE",
                                   self._profile("trading_user", [
                                       {"title": "实时一览", "source": "base",
                                        "content": "存档里写死的旧正文"}]),
                                   "trading_user", "标签", {"k": 1})
        got = self.compile_mock.call_args.args[0]
        self.assertEqual(len(got), 1)
        self.assertIn("现网实时正文", got[0]["content"],
                      "不含变量时不得采用存档正文（否则实时分节会被写死成旧文本）")
        self.assertNotIn("存档里写死的旧正文", got[0]["content"],
                         "存档正文不得进入结果")

    def test_unknown_base_title_is_kept_as_a_legacy_overlay(self):
        """档案里写了 base 源但标题对不上模板 ⇒ **不得静默丢弃**，降级为 `legacy` 保留内容。"""
        PL.apply_module_layout("BASE",
                               self._all_base("trading_main", [
                                   {"title": "对不上的标题", "source": "base", "content": "内容"}]),
                               "trading_main", "标签", {"k": 1})
        got = self.compile_mock.call_args.args[0]
        self.assertEqual([m["title"] for m in got],
                         ["实时一览", "三重滤网裁决协议", "没被档案提到的节", "对不上的标题"],
                         "对不上的标题降级 legacy 后原位保留（不丢内容、也不重复）")
        self.assertEqual(got[-1]["source"], "legacy", "对不上的 base 项必须降级为 legacy")
        self.assertEqual(got[-1]["content"], "内容", "降级后内容原样保留")

    def test_a_matched_module_takes_its_identity_from_the_template(self):
        """★ 模块身份以**模板**为准：档案项只提供 `content`，其余字段不参与合并。"""
        PL.apply_module_layout("BASE",
                               self._profile("trading_main", [
                                   {"source": "base", "title": "实时一览",
                                    "content": "档案A", "自定义字段": "应被忽略"},
                                   {"source": "base", "title": "三重滤网裁决协议"},
                                   {"source": "base", "title": "没被档案提到的节"}]),
                               "trading_main", "标签", {"k": 1})
        got = self.compile_mock.call_args.args[0]
        self.assertEqual(got[0]["source"], "base", "身份字段来自模板")
        self.assertNotIn("自定义字段", got[0], "档案里的额外字段不进入输出模块")

    def test_context_is_always_passed_to_the_renderer(self):
        ctx = {"k": 2}
        PL.apply_module_layout("BASE", self._profile("trading_main", []), "trading_main",
                               "标签", ctx)
        self.assertIs(self.render_mock.call_args.args[1], ctx,
                      "主路径同样必须带上 context（否则变量退回字面量）")


if __name__ == "__main__":
    unittest.main()
