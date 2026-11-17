"""前缀缓存契约门（2026-09-29 事故后的防复发闸）。

## 这一刀守的是什么

`astra_gateway/cache_warmer.py` 的旧实现每 4.5 分钟发一次"缓存保活"，但它发的是
`scripts.ai_brain_trader.SYSTEM_PROMPT`（**base** 版），而生产真正发送的是
`get_effective_system_prompt()`（profile 模块布局之后的版本）—— 两者在**第 4460 个字符**
处就分歧。前缀缓存要求逐字节相同的前缀，而上游按 ~4092 token（≈6500 字符）分块上报，
第一块整块落在分歧点之后 ⇒ **永久 0 命中**，且没有任何测试会红。

本门把三件"看不见的契约"钉住：

1. **System Prompt 必须是逐字节静态的**：无 `{{占位符}}`、无日期/时间戳；
2. **动态段必须排在静态头之后**：live 提示词布局里，凡逐轮必变的小节都不得插到
   `推演与决策任务` 前面（否则后面全都不成前缀）；
3. **预热前缀必须与生产提示词同源**：用**真实的** `build_effective_prompt_text`
   造一份快照，`load_snapshot_prefix()` 取出的 `system` 必须逐字等于现网
   effective prompt，`user` 必须是快照正文的字面前缀 —— 这一条若早存在，
   旧实现当天就会红。
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: 逐轮必变的运行时小节标题（与 cache_warmer.DYNAMIC_MARKERS 同源语义）。
DYNAMIC_TITLES = (
    "全网实时重大快讯与宏观情报",
    "账户当前持仓与风险敞口全景",
    "在途未成交限价挂单",
    "全标的池原生行情、技术指标与筹码矩阵",
    "当前决策时间戳与市场时效",
    "全市场宏观体制自适应识别",
)

#: 静态头的锚点：它之前的一切都是可缓存前缀。
STATIC_ANCHOR = "推演与决策任务"


class SystemPromptIsStaticTests(unittest.TestCase):
    def _effective(self) -> str:
        from scripts.ai_brain_trader import get_effective_system_prompt
        return get_effective_system_prompt()

    def test_no_template_placeholders_survive(self):
        text = self._effective()
        leftovers = re.findall(r"\{\{[^}]*\}\}", text)
        self.assertEqual(leftovers, [], f"System Prompt 里残留占位符 ⇒ 前缀逐轮变：{leftovers[:3]}")

    def test_no_volatile_timestamps(self):
        text = self._effective()
        for pattern, label in ((r"20\d\d-\d\d-\d\d", "日期"), (r"\d{1,2}:\d{2}:\d{2}", "时间")):
            self.assertIsNone(re.search(pattern, text),
                              f"System Prompt 出现{label}字面量 ⇒ 每轮前缀都不同，缓存永不命中")

    def test_two_renders_are_byte_identical(self):
        self.assertEqual(self._effective(), self._effective(),
                         "同一份配置两次渲染必须逐字节一致（前缀缓存的前提）")

    def test_base_prompt_is_not_the_production_prefix(self):
        """把旧事故的根因写成断言：base SYSTEM_PROMPT ≠（也不是）生产前缀。

        旧预热发的正是 base 版；这里确认它与 effective 版**不同**，
        免得有人日后又把 base 当成"生产前缀"用。
        """
        from scripts.ai_brain_trader import SYSTEM_PROMPT
        self.assertNotEqual(SYSTEM_PROMPT, self._effective())
        self.assertFalse(self._effective().startswith(SYSTEM_PROMPT),
                         "effective 若真是以 base 开头，旧实现就不会 0 命中了 —— 事实相反")


class LayoutKeepsDynamicSectionsAtTheTailTests(unittest.TestCase):
    def _live_layout(self) -> list:
        library = json.loads((ROOT / "data" / "prompt_library.json").read_text(encoding="utf-8"))
        active = library.get("active_profile_id")
        profile = (library.get("profiles") or {}).get(active) or {}
        layout = ((profile.get("pipelines") or {}).get("trading_user"))
        self.assertIsInstance(layout, list, "active profile 的 trading_user 布局必须是列表")
        return layout

    def test_every_dynamic_section_sits_after_the_static_task_block(self):
        layout = self._live_layout()
        titles = [str(item.get("title") or "") for item in layout if item.get("enabled", True)]
        anchor = next((i for i, title in enumerate(titles) if STATIC_ANCHOR in title), None)
        self.assertIsNotNone(anchor, f"布局里找不到静态锚点「{STATIC_ANCHOR}」")
        offenders = [
            title for index, title in enumerate(titles)
            if index < anchor and any(marker in title for marker in DYNAMIC_TITLES)
        ]
        self.assertEqual(offenders, [],
                         "这些逐轮必变的小节被排到了静态任务块之前 ⇒ 其后内容全部不成前缀："
                         f"{offenders}")


class SnapshotPrefixMatchesProductionTests(unittest.TestCase):
    """用**真实的**快照构造函数造样本，验证预热前缀与生产提示词同源。"""

    def _build_snapshot_text(self) -> tuple[str, str, str]:
        from scripts.ai_brain_trader import get_effective_system_prompt
        from scripts.brain.cycle_parts import build_effective_prompt_text

        system = get_effective_system_prompt()
        # 稳定头（≥ 实测的缓存最小前缀）＋ 一个动态小节
        user = "【长期记忆】静态教训若干。\n" * 600 + (
            "\n======================= 【全网实时重大快讯与宏观情报】 =======================\n"
            "本轮快讯随时变。\n"
        )
        text = build_effective_prompt_text(
            effective_system_prompt=system, policy_version="",
            time_str="2026-09-29 15:15:22", prompt=user,
        )
        return text, system, user

    def test_warmer_prefix_equals_the_live_effective_system_prompt(self):
        import astra_gateway.cache_warmer as cw

        text, system, user = self._build_snapshot_text()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ai_brain_last_prompt.txt"
            path.write_text(text, encoding="utf-8")
            prefix = cw.load_snapshot_prefix(path=path)
        self.assertIsNotNone(prefix, "真实格式的快照必须能解析出前缀")
        self.assertEqual(prefix["system"], system.strip(),
                         "预热 SYSTEM 与现网 effective prompt 必须逐字相同（旧实现在此分歧）")
        self.assertTrue(user.startswith(prefix["user"]), "预热 USER 必须是生产 user 的字面前缀")
        self.assertNotIn("快讯", prefix["user"], "动态小节不得进前缀")

    # ⚠️ 这里**故意没有**"拿生产 data/ai_brain_last_prompt.txt 去断言内容"的用例：
    # 那是运行时产物、平台一变就红（`tests/__init__.py` 的读生产数据提示就是为本类写法发的），
    # 而且测试沙箱里的提示词库与生产库不同源，断言必然假红。契约由上面这份**同源合成快照**守。


if __name__ == "__main__":
    unittest.main()
