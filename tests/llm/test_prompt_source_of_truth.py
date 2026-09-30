"""提示词体系的**单一事实源**与**只读契约**门禁（2026-09-30 重构）。

## 这次重构解决了什么

重构前，同一段提示词正文存在**三份**副本：代码常量
（`SYSTEM_PROMPT` 的 8 节军规 / `EVOLUTION_SYSTEM_PROMPT` / `PRESETS`）、
出厂基线 `data/prompt_library.json`、以及工坊编辑出的本地库。改一处另两处不动，
表现就是**「在工坊里改了、实发却没变」**——一个把人骗到实盘才发现的静默故障。

现在：**正文只存 JSON**；代码里只剩输出 JSON Schema（只读）。

## 本文件守住的不变量

| 不变量 | 为什么它值得一条会红的门 |
|---|---|
| 代码里不得再出现提示词正文 | 副本一旦回来，"改了没生效"就回来了，且没人会立刻发现 |
| 唯一代码基座 = 只读 Schema，且只有它 | 别让人"顺手"把军规塞回常量；也防止基座悄悄变成两份 |
| 只读契约不可改内容 / 不可禁用 | 它是机器契约，改字段名会让整轮决策解析失败 |
| 只读契约**缺失会被回插** | 让"删掉它"不等于"生效"，fail-safe 而非 fail-open |
| 正文不得为空 | 空提示词会让模型瞎猜，且对空串的 `assertNotIn` 会**真空通过** |
| 提示词口径与执行层常量同源 | 模型按不存在的空间规划 = 直接亏钱 |
"""
from __future__ import annotations

import copy
import re
import unittest
from pathlib import Path

import scripts.prompt_library as pl

ROOT = Path(__file__).resolve().parents[2]

#: 代码里**允许**存在的提示词相关常量：只有只读契约与它的标题。
#: 任何其它"整段正文"型常量都应视为副本回流。
_PROSE_FREE_FILES = (
    ROOT / "scripts" / "ai_brain_trader.py",
    ROOT / "scripts" / "self_improvement_engine.py",
    ROOT / "scripts" / "brain" / "prompt.py",
    ROOT / "astra_backend" / "prompt_views.py",
)

#: 已删除的正文常量名 —— 它们回来就是副本回流。
_RETIRED_CONSTANTS = ("_SYSTEM_CORE", "_PYRAMID")

#: 旧正文的特征短语（属于被迁走的军规/角色正文，不属于 JSON Schema）。
#: 命中即说明有人把正文抄回了 py。
_RETIRED_PHRASES = (
    "反割肉",
    "严禁无差别照抄",
    "核心军规",
    "三阶利润棘轮",
)

SCHEMA_TITLE = "严格 JSON 规范契约与完整输出骨架 (JSON Schema)"


class NoPromptProseInCodeTests(unittest.TestCase):
    """代码里不得再出现提示词正文（只允许只读 JSON Schema）。"""

    def test_retired_prose_constants_stay_deleted(self):
        import scripts.ai_brain_trader as abt
        for name in _RETIRED_CONSTANTS:
            self.assertFalse(hasattr(abt, name),
                             f"{name} 回来了 —— 提示词正文又变成代码副本了（那是"
                             f"「工坊改了没生效」的根因，见本文件 docstring）")

    def test_no_file_carries_retired_prose(self):
        hits = []
        for path in _PROSE_FREE_FILES:
            text = path.read_text(encoding="utf-8")
            for phrase in _RETIRED_PHRASES:
                if phrase in text:
                    hits.append(f"{path.relative_to(ROOT)}: {phrase}")
        self.assertEqual(hits, [],
                         "这些文件里又出现了被迁走的提示词正文（正文只应存 "
                         "data/prompt_library.json）:\n  " + "\n  ".join(hits))

    def test_the_only_code_base_is_the_readonly_schema(self):
        with_base = [k for k in pl.TEMPLATE_KEYS if pl.base_template_text(k).strip()]
        self.assertEqual(with_base, ["trading_system"],
                         f"只有 trading_system 应有代码基座（只读 Schema），实际 {with_base}")
        base = pl.base_template_text("trading_system")
        self.assertIn("macro_assessment", base)
        # 基座只能是**一节**（Schema）；多于一节说明有人把别的正文并了进来
        titles = re.findall(r"==== 【([^】]+)】 ====", base)
        self.assertEqual(len(titles), 1, f"代码基座不止一节: {titles}")

    def test_the_evolution_prose_constant_is_empty(self):
        import scripts.self_improvement_engine as sie
        self.assertEqual(sie.EVOLUTION_SYSTEM_PROMPT, "",
                         "复盘正文常量必须为空（正文在 JSON；代码只留宿主宪章）")

    def test_presets_carry_no_prose(self):
        for pid, preset in pl.PRESETS.items():
            for key in pl.TEMPLATE_KEYS:
                self.assertFalse(str(preset.get(key) or "").strip(),
                                 f"PRESETS[{pid}][{key}] 又有正文了 —— 这是第三份副本")
            for key, mods in (preset.get("pipelines") or {}).items():
                self.assertEqual(list(mods or []), [],
                                 f"PRESETS[{pid}].pipelines[{key}] 又有模块了")


class JsonProseIsRealTests(unittest.TestCase):
    """正文真的在 JSON 里、真的非空、且四个管线都能渲染出东西。"""

    def test_every_pipeline_renders_a_non_trivial_prompt(self):
        prof = pl.active_profile()
        for key in pl.TEMPLATE_KEYS:
            modules = prof["pipelines"].get(key) or []
            self.assertTrue(modules, f"{key} 管线没有任何模块 —— 模型会收到空提示词")
            rendered = pl.apply_module_layout(pl.base_template_text(key), prof, key, "门禁")
            self.assertGreater(len(rendered), 400,
                               f"{key} 渲染结果过短（{len(rendered)}）—— 正文可能丢了")
            self.assertNotIn("[MISSING_CONTEXT", rendered,
                             f"{key} 渲染出占位符（插槽没接上）")

    def test_the_trading_system_prompt_carries_the_fast_rhythm_doctrine(self):
        """出厂口径必须真的是「快节奏·高胜率」而不是残留的旧文案。"""
        import scripts.ai_brain_trader as abt
        effective = abt.get_effective_system_prompt(pl.active_profile())
        for anchor in ("胜率优先",
                       "资金周转优先",
                       "失效即离场",
                       "时间止损",
                       "分批止盈",
                       "结构位"):
            self.assertIn(anchor, effective, f"新口径锚点缺失: {anchor}")
        # 反例：旧口径里"死等远端目标"的取向不该作为主基调出现
        self.assertNotIn("让利润奔跑是唯一目标", effective)


class LockedContractIsEnforcedTests(unittest.TestCase):
    """只读契约：改内容 / 禁用 → 拒绝；缺失 → 渲染时回插（fail-safe）。"""

    def _mutate(self, mutate):
        prof = copy.deepcopy(pl.active_profile())
        mutate(prof)
        return pl.validate_profile(pl._clean_profile(prof, "allpattern_swing"))

    @staticmethod
    def _schema_module(prof):
        return next(m for m in prof["pipelines"]["trading_system"]
                    if m["title"] == SCHEMA_TITLE)

    def test_editing_the_contract_is_refused(self):
        report = self._mutate(lambda p: self._schema_module(p).__setitem__("content", "改过了"))
        self.assertFalse(report["valid"], "改动只读契约必须被拒绝")
        self.assertTrue(any("只读" in e for e in report["errors"]), report["errors"])

    def test_disabling_the_contract_is_refused(self):
        report = self._mutate(lambda p: self._schema_module(p).__setitem__("enabled", False))
        self.assertFalse(report["valid"], "禁用只读契约必须被拒绝")

    def test_a_flat_text_append_to_the_contract_is_refused(self):
        """★ 扁平文本路径也必须挡：追加一句就会并进同名那一节 ⇒ 等于改了只读契约。

        这条很容易漏 —— 模块路径有前端禁用控件，但工坊/导入/API 都能提交**扁平文本**。
        """
        base = pl.base_template_text("trading_system")
        with self.assertRaises(ValueError) as ctx:
            pl.update_profile("allpattern_swing",
                              {"trading_system": base + "\n- 偷偷追加的一行"},
                              note="门禁：不该成功")
        self.assertIn("只读", str(ctx.exception))

    def test_a_native_profile_passes(self):
        report = self._mutate(lambda p: None)
        self.assertTrue(report["valid"], report["errors"])

    def test_deleting_the_contract_still_renders_it(self):
        """★ fail-safe：删掉 ≠ 生效。渲染边界必须把只读契约回插。"""
        prof = copy.deepcopy(pl.active_profile())
        prof["pipelines"]["trading_system"] = [
            m for m in prof["pipelines"]["trading_system"] if m["title"] != SCHEMA_TITLE
        ]
        rendered = pl.apply_module_layout(pl.base_template_text("trading_system"),
                                          prof, "trading_system", "门禁")
        self.assertIn("macro_assessment", rendered,
                      "删掉只读契约后模型收不到 JSON 契约 —— fail-open 了")
        self.assertEqual(rendered.count(SCHEMA_TITLE), 1, "只读契约被回插了多次")


class PromptMatchesExecutorConstantsTests(unittest.TestCase):
    """提示词口径必须与执行层常量同源（模型不能按不存在的空间规划）。"""

    def test_the_risk_budget_section_is_rendered_from_live_constants(self):
        import scripts.ai_brain_trader as abt
        text = abt.build_risk_budget_text(1000.0)
        self.assertNotIn("[MISSING_CONTEXT", text)
        for anchor in ("单笔杠杆区间", "盈亏比 R:R 硬底线", "新开仓最低置信度门禁"):
            self.assertIn(anchor, text, f"风险预算缺少口径项: {anchor}")

    def test_the_prompt_points_at_the_runtime_budget_instead_of_hardcoding(self):
        """提示词不得写死具体风控数字，必须指向【本周期风险预算】。"""
        import scripts.ai_brain_trader as abt
        effective = abt.get_effective_system_prompt(pl.active_profile())
        self.assertIn("【本周期风险预算】", effective,
                      "提示词必须指向运行期风险预算小节")
        # 反例：具体门禁数值写死进正文（会导致与后台可配风控漂移）
        for forbidden in ("同向持仓上限 3 笔", "杠杆不超过 5x", "目标 R:R ≥ 2.2"):
            self.assertNotIn(forbidden, effective, f"正文写死了动态风控值: {forbidden}")

    def test_the_prompt_does_not_hardcode_absolute_money(self):
        import scripts.ai_brain_trader as abt
        effective = abt.get_effective_system_prompt(pl.active_profile())
        offenders = re.findall(r"\b\d{3,}(?:\.\d+)?\s*(?:USDT|U\b)", effective)
        self.assertEqual(offenders, [], f"提示词出现绝对金额: {offenders}")


if __name__ == "__main__":
    unittest.main()
