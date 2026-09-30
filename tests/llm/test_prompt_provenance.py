"""提示词方案库的**来源判定**回归（审计批5 新发现；2026-09-30 按新契约改钉）。

## ⚖️ 本文件在 2026-09-30 提示词体系重构后的口径

旧口径：每条管线都有一个"整段代码基座"（`trading_system` = 8 节 / 8341 字符）。
**新口径**：代码基座**只剩输出 JSON Schema 一条**（`trading_system`，1712 字符 / 1 节）；
另外三条管线**刻意没有代码基座**，正文全部来自 `data/prompt_library.json`。

因此本文件里"多条基座模块"的用例改为用 `_BASE_TEMPLATE_CACHE` 注入一份**合成的**
多节基座来考 `align_pipeline_sources` 的**逐模块**语义 —— 那个缝本来就是门面自带的
（`register_base_template` 写的就是这个缓存），不必依赖"代码里真有 8 节"。

原始事故链（仍然有效、仍须守住）：`update_profile` 走扁平文本路径时无条件
`text_to_modules(text, "legacy")`——即使提交的文本与代码基座**逐字相同**，模块也会
全部变成 `legacy`；下一轮 `apply_module_layout` 判定「无 base 模块」就把基座整段前置，
于是线上交易提示词从 6454 字符变成 12910 字符（×2.00）。

背景（实测事故链）：`update_profile` 走扁平文本路径时无条件
`text_to_modules(text, "legacy")`——即使提交的文本与代码基座**逐字相同**，八个模块也会
全部变成 `legacy`；下一轮 `apply_module_layout` 判定「无 base 模块」就把基座整段前置，
于是线上交易提示词从 6454 字符变成 12910 字符（×2.00，军规/JSON 契约各出现两遍）。
这条链与 P1-2（只提交一条管线把其他管线降级）同族，只是触发路径在扁平文本上。

修复：`scripts/prompt_library.py` 增加「管线 → 代码基座文本」注册表 +
`align_pipeline_sources()`，只按**逐字相同**恢复 `source="base"`（连同基座 id/locked），
真正被改写的模块才留在 legacy；注册表取不到基座时退化为"不改来源"，绝不臆造。
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.prompt_library as pl

# 线上真实方案库路径：测试若指向它，说明沙箱没生效，必须立刻失败
REAL_LIBRARY = (Path(__file__).resolve().parents[2] / "data" / "prompt_library.json").resolve()
#: 新契约下唯一的代码基座模块标题（= 输出 JSON Schema）。
BASE_TITLE = "严格 JSON 规范契约与完整输出骨架 (JSON Schema)"
#: 合成的多节基座：只用于考 `align_pipeline_sources` 的**逐模块**来源判定。
SYNTHETIC_BASE = ("==== 【甲节】 ====\n甲节正文\n\n"
                  "==== 【乙节】 ====\n乙节正文\n\n"
                  "==== 【丙节】 ====\n丙节正文")


_READ_SCOPE = None


def setUpModule():
    """显式声明生产读（第二百三十六刀）：
    本文件把**线上**提示词库快照抄进沙箱后断言其 provenance 属性 —— 它的存在目的
    就是「线上那份库是否健康」（含绝对金额/来源标注等），属**有意的线上守卫**。

    只读、不改；声明在此是为了把「依赖线上配置内容」从**静默**变成**可审计**
    （守卫见 `tests/__init__.py`；`ASTRA_TESTS_STRICT_READS=1` 下未声明的读会报错）。
    """
    global _READ_SCOPE
    from tests import allow_real_data_reads
    _READ_SCOPE = allow_real_data_reads()
    _READ_SCOPE.__enter__()


def tearDownModule():
    global _READ_SCOPE
    if _READ_SCOPE is not None:
        _READ_SCOPE.__exit__(None, None, None)
        _READ_SCOPE = None


class _PromptLibraryCase(unittest.TestCase):
    """每个用例都把方案库指到临时副本。

    注意：全局沙箱（tests.config_sandbox.isolate_config）只重定向**导入时已存在**的模块，
    而本文件是懒加载 `prompt_library` 的——所以这里必须显式 patch；万一漏了，
    `tests/__init__.py` 的运维配置写保护也会把写 `data/prompt_library.json` 拦下来。
    """

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="astra-promptlib-"))
        self.addCleanup(shutil.rmtree, self._tmp, True)
        target = self._tmp / "prompt_library.json"
        target.write_text(REAL_LIBRARY.read_text(encoding="utf-8"), encoding="utf-8")
        # 双文件模型（2026-09）：`target` 是**出厂基线**（读侧），写入侧另钉一个。
        for _attr, _val in (("BASELINE_FILE", target),
                            ("LOCAL_FILE", self._tmp / "prompt_library.local.json")):
            patcher = mock.patch.object(pl, _attr, _val)
            patcher.start()
            self.addCleanup(patcher.stop)
        for _attr in ("BASELINE_FILE", "LOCAL_FILE"):
            self.assertNotEqual(Path(getattr(pl, _attr)).resolve(), REAL_LIBRARY,
                                f"{_attr} 没有被沙箱化——测试会改写生产配置")

    def _profile(self, pid: str = "allpattern_swing") -> dict:
        return pl.load_library()["profiles"][pid]


class BaseTemplateRegistryTests(unittest.TestCase):
    def test_only_the_readonly_schema_pipeline_has_a_code_base(self):
        """★ 新契约：**只有** `trading_system` 有代码基座（只读 JSON Schema）。

        另外三条管线刻意没有基座 —— 它们的正文只存 JSON。留空的后果必须被显式记录：
        不能有人后来"顺手"又把正文塞回代码常量（那就退回了三方副本的老问题）。
        """
        with_base = [key for key in pl.TEMPLATE_KEYS if pl.base_template_text(key).strip()]
        self.assertEqual(with_base, ["trading_system"],
                         f"只有 trading_system 应有代码基座，实际: {with_base}")
        self.assertIn("严格 JSON 规范契约", pl.base_template_text("trading_system"))

    def test_base_text_matches_the_code_prompt_it_claims(self):
        import scripts.ai_brain_trader as abt
        self.assertEqual(pl.base_template_text("trading_system"), abt.SYSTEM_PROMPT)

    def test_unknown_pipeline_is_fail_safe(self):
        # 取不到基座 → 原样返回，绝不把模块误标成 base
        modules = pl.text_to_modules("==== 【未知节】 ====\n内容", "legacy")
        self.assertEqual(pl.base_template_text("not_a_pipeline"), "")
        self.assertEqual(pl.align_pipeline_sources(modules, "not_a_pipeline"), modules)


class SourceAlignmentTests(unittest.TestCase):
    def test_verbatim_base_text_stays_base(self):
        text = pl.base_template_text("trading_system")
        aligned = pl.align_pipeline_sources(pl.text_to_modules(text, "legacy"), "trading_system")
        self.assertEqual({m["source"] for m in aligned}, {"base"})
        # id 必须回到基座 id，否则布局匹配又会退化成"整段前置"
        base_ids = {m["id"] for m in pl.text_to_modules(text, "base")}
        self.assertEqual({m["id"] for m in aligned}, base_ids)

    def _align_against(self, base_text: str, modules):
        """在**合成的**多节基座下考逐模块来源判定（用门面自带的缓存缝）。"""
        with mock.patch.dict(pl._BASE_TEMPLATE_CACHE, {"trading_system": base_text}):
            return pl.align_pipeline_sources(modules, "trading_system")

    def test_only_edited_modules_become_legacy(self):
        modules = pl.text_to_modules(SYNTHETIC_BASE, "legacy")
        modules[1]["content"] = modules[1]["content"] + "\n- 临时补充规则"
        aligned = self._align_against(SYNTHETIC_BASE, modules)
        self.assertEqual([m["source"] for m in aligned],
                         ["base", "legacy", "base"],
                         "只有被改的那一节变 legacy，其余仍认亲为 base")

    def test_same_title_but_different_content_is_not_adopted(self):
        modules = pl.text_to_modules(SYNTHETIC_BASE, "legacy")
        modules[0]["content"] = "==== 【甲节】 ====\n完全改写的正文"
        aligned = self._align_against(SYNTHETIC_BASE, modules)
        self.assertEqual(aligned[0]["source"], "legacy", "同标题但内容不同不得认亲为 base")

    def test_the_real_readonly_schema_base_is_a_single_module(self):
        """新契约的形状断言：唯一代码基座就是 1 节（谁把它拆成多节都会在这里被看见）。"""
        modules = pl.text_to_modules(pl.base_template_text("trading_system"), "legacy")
        self.assertEqual(len(modules), 1)
        self.assertEqual(modules[0]["title"], BASE_TITLE)
        aligned = pl.align_pipeline_sources(modules, "trading_system")
        self.assertEqual([m["source"] for m in aligned], ["base"])


class FlatUpdateProvenanceTests(_PromptLibraryCase):
    def test_flat_update_with_verbatim_base_keeps_single_copy(self):
        """回归：把基座原文存回去，线上渲染不得翻倍（**这条是本文件的核心价值**）。"""
        base = pl.base_template_text("trading_system")
        pl.update_profile("allpattern_swing", {"trading_system": base}, note="回归：逐字回存基座")
        profile = self._profile()
        self.assertIn("base", {m["source"] for m in profile["pipelines"]["trading_system"]},
                      "逐字回存必须仍认亲为 base（否则下一轮会把基座整段前置而翻倍）")
        import scripts.ai_brain_trader as abt
        rendered = pl.apply_module_layout(
            abt.SYSTEM_PROMPT, profile, "trading_system", "交易 System")
        self.assertEqual(rendered.count("严格 JSON 规范契约与完整输出骨架"), 1,
                         "基座被前置了两次——提示词翻倍回归")
        self.assertLessEqual(len(rendered), len(abt.SYSTEM_PROMPT) + 16)

    def test_flat_update_with_one_edit_keeps_other_modules_base(self):
        """只改一节 ⇒ 只有那一节降级，其余仍认亲为 base（用合成多节基座考逐模块语义）。"""
        edited = SYNTHETIC_BASE.replace("乙节正文", "乙节正文（自定义：手续费敏感度加倍）")
        self.assertNotEqual(edited, SYNTHETIC_BASE)
        with mock.patch.dict(pl._BASE_TEMPLATE_CACHE, {"trading_system": SYNTHETIC_BASE}):
            aligned = pl.align_pipeline_sources(pl.text_to_modules(edited, "legacy"), "trading_system")
        sources = [m["source"] for m in aligned]
        self.assertIn("base", sources, "未改动的模块不该丢掉 base 来源")
        self.assertEqual(sources.count("legacy"), 1, f"只应有一个模块变 legacy: {sources}")

    def test_flat_update_does_not_touch_other_pipelines(self):
        """用 `evolution_system`（无代码基座）考"单管线隔离" —— 它不会被只读契约挡住。"""
        before = {key: pl.compile_modules(pl.load_library()["profiles"]["allpattern_swing"]["pipelines"][key])
                  for key in pl.TEMPLATE_KEYS if key != "evolution_system"}
        pl.update_profile("allpattern_swing",
                          {"evolution_system": "==== 【只改这条管线】 ====\n正文"}, note="回归：单管线")
        after = {key: pl.compile_modules(self._profile()["pipelines"][key]) for key in before}
        self.assertEqual(before, after, "保存一条管线不得改写其他管线")

    def test_revision_rollback_restores_previous_state(self):
        pl.update_profile("allpattern_swing",
                          {"evolution_system": "==== 【会被回滚的一段】 ====\n正文"},
                          note="回归：待回滚")
        target = pl.load_library()["revisions"][-1]["snapshot"]["evolution_system"]
        pl.update_profile("allpattern_swing", {"evolution_system": target}, note="回归：回滚")
        self.assertIn("会被回滚的一段",
                      pl.load_library()["profiles"]["allpattern_swing"]["evolution_system"])

    def test_a_flat_text_append_to_the_locked_schema_is_refused(self):
        """★ 只读契约必须**连扁平文本路径一起挡**（否则"追加一句"就能改掉输出契约）。

        这是很容易漏的一条：模块路径被前端禁用了控件，但工坊/导入/API 都能提交**扁平
        文本**；扁平文本经 `text_to_modules` 解析后，追加的内容会并进同名那一节 ⇒
        等于改了只读模块。必须 fail-closed 拒绝。
        """
        base = pl.base_template_text("trading_system")
        with self.assertRaises(ValueError) as ctx:
            pl.update_profile("allpattern_swing",
                              {"trading_system": base + "\n- 偷偷追加的一行"}, note="不该成功")
        self.assertIn("只读", str(ctx.exception))

    def test_clean_pipelines_fallback_also_aligns(self):
        """_clean_pipelines 的兜底重建路径也必须恢复 base 来源。"""
        base = pl.base_template_text("trading_system")
        cleaned = pl._clean_pipelines({}, {"pipelines": {}, "trading_system": base})
        self.assertEqual({m["source"] for m in cleaned["trading_system"]}, {"base"})


if __name__ == "__main__":
    unittest.main()
