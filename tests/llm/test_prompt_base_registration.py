r"""出厂基线的**基座显式登记**门（2026-09-30）。

## 为什么要有这条门

用户报障原话：「提示词工坊的提示词怎么和决策透视的提示词不一样，是不是有什么 bug」。
根因实测有三层，前两层都在**基座登记**上：

1. 出厂方案在 `trading_system` / `evolution_system` 上**一个 base 模块都没登记** ⇒
   提示词工坊只列出方案自己那几段覆盖层（实测 **1356 字符 vs 实发 9700 字符**）——
   用户在工坊里既看不到、也排不了、也启停不了真正的系统军规与严格 JSON 契约；
   运行期靠 `apply_module_layout` 里"无 base ⇒ 基座整段前置"的兜底静默注入。
2. `trading_user` 的 `推演与决策任务` 被标 `source:"base"` 却存着 **2085 字符陈旧快照**
   （实发那一节是 2944 字符的按周期注入正文）⇒ 工坊显示存档、实发用现网，两边都偏离。
3. 工坊预览只编译方案自己的模块（`compileWorkingModules`），结构上不可能等于决策透视。

本门把「每条管线的现网基座都显式登记、且正文与现网逐字相同」从"我核实过一次"
变成"每次提交都核实"。它同时带**牙齿自检**：故意删一段 / 改脏一段，归一必须救回来——
否则它只是"读一遍自己的实现"，挡不住回归。

## 与邻近门的分工

| 门 | 守什么 |
|---|---|
| `test_rename_keeps_prompt_module_ids_safe.py` | 出厂基线**不持久化** `module-base-*` id（种子改名安全） |
| 本门 | 出厂基线**显式登记**每条管线的现网基座，正文逐字相同 |
| `test_prompt_provenance.py` | `source` 标注与"基座整段前置"兜底的历史事故记录 |
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import scripts.prompt_library as library

#: 语义变量插槽语法（与 `scripts/prompt_templates.py::_PLACEHOLDER_RE` 同形）
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

#: 统一走**门面**（`MAX_TEMPLATE_CHARS` / `_base_text_resolver` 由门面在调用时注入；
#: 直接取 `scripts.prompt_templates` 里的纯函数会缺这两个必需的关键字实参）。
base_template_modules = library.base_template_modules
compile_modules = library.compile_modules
normalize_base_modules = library.normalize_base_modules

BASELINE_JSON = Path(__file__).resolve().parents[2] / "data" / "prompt_library.json"

#: 管线 → 现网基座文本（`None` = 与 `_BASE_TEMPLATE_SOURCES` 同款解析）
PIPELINES = ("trading_system", "trading_user", "evolution_system", "evolution_user")


def _live_base(pipeline: str) -> str:
    return library._base_text_resolver(pipeline)


class FactoryBaselineRegistersLiveBaseTest(unittest.TestCase):
    """基石：出厂基线的每条管线都显式登记了现网基座的**每一条**分节。"""

    def setUp(self):
        self.assertTrue(BASELINE_JSON.is_file(), "出厂方案库不见了")
        self.raw = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))

    def _profile_raw(self) -> dict:
        active = str(self.raw.get("active_profile_id") or "")
        self.assertIn(active, self.raw.get("profiles") or {}, "出厂方案库缺当前启用方案")
        return self.raw["profiles"][active]

    def test_every_live_base_section_is_registered_exactly_once_as_base(self):
        """★ 主断言：现网基座的分节标题 == 方案里 `source:"base"` 的标题，且不重不漏。

        ★ 2026-09-30 提示词体系重构后重钉：`_BASE_TEMPLATE_SOURCES` 只剩
        `trading_system → READONLY_OUTPUT_SCHEMA`，另外三条管线**刻意没有代码基座**
        （正文全部搬进 `data/prompt_library.json`）。旧写法对这三条空基座断言
        "解析必须非空"，钉的其实是"每条管线都有代码基座"这条已废弃的旧契约。
        新判据：有代码基座的管线仍须不重不漏地登记；没有代码基座的管线则**不得**
        在方案里冒充 `source:"base"`（无基座而自称基座 = 工坊显示与实发再次分叉）。
        """
        profile = self._profile_raw()
        for pipeline in PIPELINES:
            with self.subTest(pipeline=pipeline):
                live_titles = [m["title"] for m in base_template_modules(_live_base(pipeline), pipeline)]
                stored = (profile.get("pipelines") or {}).get(pipeline) or []
                base_titles = [m["title"] for m in stored if m.get("source") == "base"]
                if not live_titles:
                    self.assertEqual(
                        base_titles, [],
                        f"{pipeline}: 本管线没有代码基座，方案里不得登记 source=base 模块"
                        f"（否则工坊会把存档当真基座、与实发分叉）：{base_titles}")
                    continue
                self.assertEqual(sorted(base_titles), sorted(live_titles),
                                 f"{pipeline}: 出厂基线没有把现网基座全部登记为 source=base"
                                 f"（缺失={sorted(set(live_titles) - set(base_titles))}，"
                                 f"多余={sorted(set(base_titles) - set(live_titles))}）—— "
                                 "这会让工坊看不到整段基座、且排序/启停对它无效")

    def test_registered_base_content_is_byte_identical_to_live(self):
        """★ 主断言：登记的正文必须与现网基座逐字相同（否则工坊显示存档、实发用现网）。"""
        profile = self._profile_raw()
        for pipeline in PIPELINES:
            live = {m["title"]: m["content"] for m in base_template_modules(_live_base(pipeline), pipeline)}
            stored = {m["title"]: m.get("content") for m in
                      ((profile.get("pipelines") or {}).get(pipeline) or [])
                      if m.get("source") == "base"}
            for title, expected in live.items():
                with self.subTest(pipeline=pipeline, title=title):
                    self.assertIn(title, stored)
                    actual = str(stored[title] or "")
                    if "{{" in str(expected) or "{{" in actual:
                        # 插槽载体：`trading_user` 的 7 条基座里有 **6 条**是 `{{变量}}` 载体
                        # （trading_memory / news_intelligence / account_positions /
                        # pending_orders / market_matrix / decision_timestamp +
                        # account_balance + risk_budget），而 `TRADING_USER_TEMPLATE`
                        # 那份是**给编辑器看的说明版**。两者本就不同，归一会刻意保留存档正文 ——
                        # 覆盖它等于**关掉全部实时数据注入**（见 `_carries_unique_slot` 注释）。
                        continue
                    self.assertEqual(actual, str(expected),
                                     f"{pipeline} / {title}: 基线正文与现网基座不一致")

    def test_baseline_does_not_persist_the_stale_task_snapshot(self):
        """回归防线：`trading_user` 的 `推演与决策任务` 不许再是那份 2085 字符陈旧快照。

        实发那一节由 `scripts/brain/prompt.py` 按周期注入（实测 2944 字符），
        库里再存一份 = 用户改了工坊却不生效 + 两处漂移。
        """
        profile = self._profile_raw()
        stored = ((profile.get("pipelines") or {}).get("trading_user") or [])
        task = [m for m in stored if m.get("title") == "推演与决策任务"]
        self.assertEqual(len(task), 1, "推演与决策任务 应恰好一条")
        self.assertLess(len(str(task[0].get("content") or "")), 1000,
                        "推演与决策任务 又变成整份 JSON 快照了 —— 契约应只由代码基座供给")

    def test_all_eight_semantic_slots_are_carried_by_registered_base_modules(self):
        """★ 差点没被发现的那条：8 个实时语义插槽必须**全部**由 trading_user 管线携带。

        ★ 2026-09-30 提示词体系重构后重钉：这些插槽原先住在 `source:"base"` 模块里，
        现在全部由 JSON 的 `source:"custom"` 模块承载（`custom-tu-time / pos / pending /
        matrix / news / memory`）。旧写法只遍历 `source=="base"` 的模块 ⇒ 集合恒为空，
        必然响亮失败；但若"顺手"改成遍历却漏掉渲染断言，又会在别处真空通过。
        新判据（同一意图、更强）：不管 source 是什么，`trading_user` 管线必须覆盖全部
        8 个插槽，**并且**每个插槽在带真实 context 渲染时都真的被替换出值
        （而不是留着占位符 ⇒ 模型收不到实时账户/行情数据）。

        为什么值得单独钉：这 8 个插槽曾被"治愈成说明版文本"的归一静默换掉，
        长度变化**净额只有 +12 字符**（有增有减互相抵消），按长度或文本相似度
        做归一/去重的人不会察觉。
        """
        expected = {"decision_timestamp", "account_balance", "risk_budget", "account_positions",
                    "pending_orders", "market_matrix", "news_intelligence", "trading_memory"}
        profile = self._profile_raw()
        modules = ((profile.get("pipelines") or {}).get("trading_user") or [])
        self.assertTrue(modules, "trading_user 管线为空 —— 定位错了对象")
        carried = set()
        for module in modules:
            carried |= set(_PLACEHOLDER_RE.findall(str(module.get("content") or "")))
        missing = sorted(expected - carried)
        self.assertEqual(missing, [],
                         f"trading_user 管线没携带这些实时插槽: {missing} —— "
                         "它们被说明版文本覆盖了，模型将收不到对应实时数据")
        # 逐个渲染确认"插槽真的接通了实时数据"（不是留着 {{...}} 占位符）。
        context = {slot: f"<RENDERED:{slot}>" for slot in expected}
        rendered = library.apply_module_layout("", profile, "trading_user", "slots", context=context)
        for slot in sorted(expected):
            with self.subTest(slot=slot):
                self.assertIn(f"<RENDERED:{slot}>", rendered,
                              f"插槽 {slot} 未被替换 —— 该实时数据接不到模型")


class NormalizationHasTeethTest(unittest.TestCase):
    """★ 牙齿：归一必须**救得回来**，否则本门只是"读一遍自己的实现"。"""

    def setUp(self):
        self.base = "【A】\none\n\n【B】\ntwo\n\n【C】\nthree"
        self.modules = base_template_modules(self.base, "trading_system")

    def _normalize(self, modules):
        return normalize_base_modules(modules, self.base, "trading_system")

    def test_deleted_base_section_is_reinserted_at_its_canonical_position(self):
        """删掉中间一段 ⇒ 必须按规范顺序回插，而不是追加到末尾。"""
        stripped = [m for m in self.modules if m["title"] != "B"]
        stripped.append({"id": "custom-1", "title": "自定义", "content": "mine",
                         "enabled": True, "source": "custom"})
        out = self._normalize(stripped)
        self.assertEqual([m["title"] for m in out], ["A", "B", "C", "自定义"],
                         "回插没有落在规范位置（追加到末尾会把覆盖层挤到基座前面）")

    def test_dirty_base_snapshot_is_healed_to_live(self):
        """改脏 `source:"base"` 的正文 ⇒ 必须被治愈成现网基座（跟随发版）。"""
        dirty = [dict(m) for m in self.modules]
        dirty[0]["content"] = "【A】\n被改脏了"
        out = self._normalize(dirty)
        self.assertEqual(out[0]["content"], self.modules[0]["content"],
                         "陈旧基座快照没有被治愈 —— source=base 的承诺（跟随代码发版）失效了")

    def test_variable_slot_carrier_is_never_overwritten(self):
        """**反向牙齿**：带独有插槽的基座项不得被"说明版"基座文本覆盖。

        真实事故（本次改动自身引入，实测只差 12 字符）：`trading_user` 的代码基座登记在
        `astra_backend/prompt_views.TRADING_USER_TEMPLATE`，那是**给编辑器看的说明版**；
        真正实发的用户消息基座是 `scripts/brain/prompt.py` 逐周期生成的 f-string。
        `{{trading_memory}}` 一旦被换成说明文本，**长期记忆从此不再注入模型**。
        """
        modules = [
            {"title": "A", "content": "【A】\n{{news_intelligence}}", "enabled": True, "source": "base"},
        ]
        out = normalize_base_modules(
            modules,
            "【A】\n实时插槽：宏观环境与最新可验证资讯。",
            "trading_user",
        )
        self.assertEqual(out[0]["content"], "【A】\n{{news_intelligence}}",
                         "插槽载体被说明版基座文本覆盖了 —— 该变量将不再注入模型")

    def test_no_base_text_means_no_fabrication(self):
        """取不到基座文本 ⇒ 原样返回，绝不臆造（与 `align_pipeline_sources` 同纪律）。"""
        modules = [dict(m) for m in self.modules]
        self.assertEqual(normalize_base_modules(modules, "", "trading_system"), modules)

    def test_idempotent(self):
        once = self._normalize([dict(m) for m in self.modules])
        twice = self._normalize(once)
        self.assertEqual(compile_modules(once), compile_modules(twice))
        self.assertEqual([m["title"] for m in once], [m["title"] for m in twice])


class StudioViewMatchesRuntimeTest(unittest.TestCase):
    """工坊预览（`pipeline_view`）与实发（`apply_module_layout`）必须同源同量级。"""

    def test_studio_view_lists_all_base_sections_and_matches_runtime_length(self):
        profile = library.active_profile()
        for pipeline in PIPELINES:
            base = _live_base(pipeline)
            with self.subTest(pipeline=pipeline):
                view = library.pipeline_view(base, profile, pipeline)
                base_titles = [m["title"] for m in base_template_modules(base, pipeline)]
                view_base_titles = [m["title"] for m in view if m.get("source") == "base"]
                self.assertEqual(sorted(view_base_titles), sorted(base_titles),
                                 f"{pipeline}: 工坊视图漏了基座分节（这正是用户报障的形态）")
                studio_chars = sum(len(str(m.get("content") or "")) for m in view if m.get("enabled", True))
                runtime_chars = len(library.apply_module_layout(base, profile, pipeline, pipeline))
                # 两者只应差模块之间的 "\n\n" 连接符（每个 2 字符）⇒ 用宽松但有意义的档位卡死
                self.assertGreaterEqual(runtime_chars, studio_chars,
                                        "实发比工坊视图还短 —— 说明有内容只在实发侧存在")
                self.assertLessEqual(runtime_chars - studio_chars, 2 * len(view) + 8,
                                     f"{pipeline}: 工坊视图与实发相差 {runtime_chars - studio_chars} 字符，"
                                     "超出连接符量级 ⇒ 又出现了「工坊看不到、实发却有」的静默内容")


if __name__ == "__main__":
    unittest.main()
