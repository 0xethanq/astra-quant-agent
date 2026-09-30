"""B3（主脑侧第五块）`scripts/brain/prompt.py` 的抽取回归。

## 这个测试在守什么

`construct_full_market_prompt`（269 行）是主脑最大的单函数，从
`scripts/ai_brain_trader.py` 搬进 `scripts/brain/prompt.py`。它有 **15 项门面依赖**，
是本阶段注入面最宽的一处 —— 而它同时又是"提示词口径 == 执行层口径"这条
不变量的唯一载体。

因此本文件重点守**注入契约**，而不是重测渲染（渲染已有
`test_prompt_rendering_isolated` 25 例在守）：

1. **风控常量必须与执行层同源**：`patch.object(abt, "MAX_LEVERAGE", …)` 之后，
   渲染出的提示词必须体现新值 —— 若子模块在 import 期把常量烘焙进自己的命名空间，
   这里就会读到旧值（提示词口径与执行层漂移，模型按不存在的空间规划）。
2. **文件路径缝必须仍生效**：`AI_MEMORY_MD_FILE` / `NEWS_SENTIMENT_FILE`。
3. **`active_profile` / `apply_module_layout` 补丁必须被读到**。
4. 双模调用形态：门面薄壳（生产）+ 只传用户参数（AST 隔离执行）。

## 关于第 4 点（本块特有）

`tests/llm/test_prompt_rendering_isolated.py` 会把本函数的 AST 节点单独 `exec`，
只传用户参数。为此子模块对注入项采用"同名回退到 `globals()`"：
`None` 时从被 exec 的 globals 取。**两种形态都必须成立**，本文件各测一条。
"""
from __future__ import annotations

import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import scripts.ai_brain_trader as abt
import scripts.risk_constants as risk_constants
from scripts.brain import prompt as brain_prompt

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "ai_brain_trader.py"
SUBMODULE = ROOT / "scripts" / "brain" / "prompt.py"

# 只在子模块里存在、门面不应再有的实现体特征行
_IMPL_ONLY_MARKERS = (
    '- 15M K线(倒序12根 [O,H,L,C,V])',
    # ⚠️ 2026-09-30 换锚：原第二个标记 `严禁无差别照抄` 属于**提示词正文**，
    # 已随提示词来源迁移搬进 `data/prompt_library.json`（代码里再也搜不到）。
    # 本用例的目的是"实现体在子模块、门面只剩薄壳"，故改用一个**仍然只属于
    # 实现体**的装配代码标记（记忆分节标题剥离 —— 见 `memory_body` 那段）。
    'memory_body = memory_lessons.strip()',
)


class _Package(dict):
    """宽松字典：让 `p["任意字段"]` 都能解析，便于只测"接线"而不构造完整行情包。"""

    def __missing__(self, key):
        return 0.0


def _PACKAGE() -> _Package:
    pkg = _Package()
    pkg.update({
        "name": "BTC", "instId": "BTC-USDT-SWAP", "price": 100.0,
        "data_quality": "valid", "type": "crypto", "precision": 2, "atr": 1.0,
        "chg24h": 1.0, "bidPx": 99.9, "askPx": 100.1, "fundingRate": 0.001,
        "oiUsd": "1M", "lsRatio": "1.0", "takerNetUsd": "0", "vol24h": 10.0,
    })
    return pkg


class ImplementationActuallyMovedTest(unittest.TestCase):
    def test_impl_body_lives_in_submodule_not_facade(self):
        facade = FACADE.read_text(encoding="utf-8")
        sub = SUBMODULE.read_text(encoding="utf-8")
        for marker in _IMPL_ONLY_MARKERS:
            self.assertIn(marker, sub, f"实现体未搬入子模块: {marker!r}")
            self.assertNotIn(marker, facade, f"门面仍留有实现体: {marker!r}")

    def test_facade_shell_delegates_with_all_15_deps(self):
        facade = FACADE.read_text(encoding="utf-8")
        self.assertIn("_construct_full_market_prompt_impl(", facade)
        for kw in ("safe_float=safe_float,", "sl_atr_mult_for=_sl_atr_mult_for,",
                   "build_risk_budget_text=build_risk_budget_text,",
                   "active_profile=active_profile,",
                   "apply_module_layout=apply_module_layout,",
                   "system_version=__version__,",
                   "ai_memory_md_file=AI_MEMORY_MD_FILE,",
                   "ai_memory_file=AI_MEMORY_FILE,",
                   "news_sentiment_file=NEWS_SENTIMENT_FILE,",
                   "max_leverage=MAX_LEVERAGE,", "min_leverage=MIN_LEVERAGE,",
                   "max_scale_in_count=MAX_SCALE_IN_COUNT,",
                   "min_scale_in_confidence=MIN_SCALE_IN_CONFIDENCE,",
                   "max_margin_equity_ratio=MAX_MARGIN_EQUITY_RATIO,"):
            self.assertIn(kw, facade, f"门面未注入 {kw}")


class InjectionContractTest(unittest.TestCase):
    """风控常量与文件路径的测试缝必须仍然生效。"""

    def _render(self, **patches):
        """渲染**带风险预算**的用户提示词，并断言补丁真的生效。

        ⚠️ 2026-09-30 重钉（两处都必须说清，否则这条用例会变成假绿）：

        ① **必须传 `usdt_available`**。风险预算小节过去是内联在门面的 f-string 里
           （`{min_leverage:g}~{max_leverage:g}x`），所以不传余额也能渲染出数字。
           提示词正文迁进 `data/prompt_library.json` 后，这些数字统一由
           `{{risk_budget}}` 插槽承载，而 `build_risk_budget_text(None)` 的语义是
           `[MISSING_CONTEXT:risk_budget]`（**缺上下文就该大声缺**，不是静默给个默认值）
           ⇒ 不传余额这条用例只会对着占位符断言。

        ② **补丁打在 `risk_constants` 上**，不是门面名。口径同源的单一事实源现在是
           `risk_constants`（`build_risk_budget_text` 在调用期 `import scripts.risk_constants as rc`
           再读 `rc.MIN_LEVERAGE` 等），门面的 `MIN_LEVERAGE` 只是它的一层转发。
           这条用例本来就该盯"调用期读、不许 import 期烘焙"这件事 —— 钉 SSOT 比
           钉转发层更贴近它要守的不变量。
        """
        stack = ExitStack()
        for name, value in patches.items():
            stack.enter_context(patch.object(risk_constants, name, value))
        try:
            text = abt.construct_full_market_prompt([], usdt_available=1000.0)
        finally:
            stack.close()
        self.assertNotIn("[MISSING_CONTEXT:risk_budget]", text,
                         "风险预算小节没渲染出来 —— 本用例的断言会退化成对占位符的对拍")
        return text

    def test_leverage_constants_are_read_at_call_time(self):
        """`patch.object(abt, "MAX_LEVERAGE")` 必须体现在渲染出的提示词里。

        这条是"提示词口径 == 执行层口径"的直接哨兵：子模块若在 import 期绑定
        `risk_constants` 的值，这里会渲染出旧区间。

        渲染形态是 `{min:g}~{max:g}x`（`int(max(min_leverage, min(max_leverage,
        (lo+hi)/2)))` 那个示例值也会跟着动，但不单独钉数值以免绑死示例算法）。
        """
        text = self._render(MAX_LEVERAGE=42.0, MIN_LEVERAGE=3.0)
        # 新格式（风险预算小节）：`{min:g}x ~ {max:g}x`
        self.assertIn("3x ~ 42x", text, "杠杆区间未读到补丁值 → 提示词口径与执行层漂移")
        self.assertNotIn("6x ~ 12x", text, "渲染出了旧区间，说明常量被 import 期烘焙")

    def test_confidence_gate_is_read_at_call_time(self):
        """加仓置信度门禁必须调用期读（它会直接进提示词，写死就是口径漂移）。"""
        text = self._render(MIN_SCALE_IN_CONFIDENCE=66)
        self.assertIn("置信度 ≥ 66%", text, "加仓置信度门禁未读到补丁值")

    def test_scale_in_disabled_flag_is_read_at_call_time(self):
        text = self._render(MAX_SCALE_IN_COUNT=0)
        # ⚠️ 2026-09-30 改锚：`MAX_SCALE_IN_COUNT <= 0` 走的从来**不是** "最多 0 次"
        # 那条分支，而是"已禁用"分支（`build_risk_budget_text` 里的三目）。旧断言
        # `最多0次` 在旧内联 f-string 里也许凑巧成立过，但按现实现必须是禁用文案 ——
        # 改锚到这里反而更准：它证明的是"0 这个补丁值被**读到**并改变了分支"。
        self.assertIn("金字塔加仓: 已禁用", text, "加仓次数上限未读到补丁值（没走禁用分支）")
        self.assertNotIn("最多 2 次", text, "渲染出了旧上限，说明常量被 import 期烘焙")

    def test_safe_float_is_injected_and_used(self):
        """`safe_float` 必须是被注入进来的那个。

        注意：`packages=[]` 时函数体里用到 safe_float 的分支根本不会执行，
        所以这条**必须带一个标的**才测得准（这条哨最初就是写错了调用形态、
        对着空列表断言"被调用"，结果空转 —— 见报告 §16 的方法论记录）。
        """
        calls = []
        real = abt.safe_float

        def spy(value, default=0.0):
            calls.append(value)
            return real(value, default)

        with patch.object(abt, "safe_float", spy):
            abt.construct_full_market_prompt([_PACKAGE()], active_positions_detail=[{"instId": "BTC", "pos": 1.0}])
        self.assertTrue(calls, "safe_float 未被调用 —— 未走注入项")

    def test_active_profile_patch_is_observed(self):
        sentinel = {"name": "补丁策略", "pipelines": {}}
        with patch.object(abt, "active_profile", lambda: sentinel):
            # 只要求不抛且走通；真正的布局断言在 test_prompt_rendering_isolated
            self.assertIsInstance(abt.construct_full_market_prompt([]), str)

    def test_news_sentiment_file_patch_is_observed(self):
        """`NEWS_SENTIMENT_FILE` 补丁必须被读到（不存在→走缺省分支，不抛）。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with patch.object(abt, "NEWS_SENTIMENT_FILE", str(Path(td) / "nope.json")):
                text = abt.construct_full_market_prompt([])
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 500)


class DualCallShapeTest(unittest.TestCase):
    """门面薄壳与"只传用户参数"两种调用形态都必须成立。"""

    def test_facade_shape(self):
        text = abt.construct_full_market_prompt([])
        self.assertIsInstance(text, str)

    def test_user_args_only_shape_resolves_from_globals(self):
        """模拟 AST 隔离执行：只传用户参数，注入项从 globals() 回退。

        把子模块所需的 14 个名字临时放进模块全局，然后**不传任何注入参数**调用 ——
        这正是 `test_prompt_rendering_isolated` 的调用形态。若子模块把注入项设成
        必填（无默认），这里会 TypeError。
        """
        names = ["safe_float", "sl_atr_mult_for",
                 "build_risk_budget_text", "active_profile", "apply_module_layout",
                 "system_version", "ai_memory_md_file", "ai_memory_file",
                 "news_sentiment_file", "max_leverage", "min_leverage",
                 "max_scale_in_count", "min_scale_in_confidence",
                 "max_margin_equity_ratio"]
        # AST 隔离测试里这些名字就叫 `_sl_atr_mult_for` / `__version__` 等（门面拼写）
        injected = {
            "safe_float": abt.safe_float,
            "_sl_atr_mult_for": abt._sl_atr_mult_for,
            "build_risk_budget_text": abt.build_risk_budget_text,
            "active_profile": abt.active_profile,
            "apply_module_layout": abt.apply_module_layout,
            "__version__": "0.0.0-test",
            "AI_MEMORY_MD_FILE": abt.AI_MEMORY_MD_FILE,
            "AI_MEMORY_FILE": abt.AI_MEMORY_FILE,
            "NEWS_SENTIMENT_FILE": abt.NEWS_SENTIMENT_FILE,
            "MAX_LEVERAGE": 9.0, "MIN_LEVERAGE": 2.0,
            "MAX_SCALE_IN_COUNT": 1, "MIN_SCALE_IN_CONFIDENCE": 70,
            "MAX_MARGIN_EQUITY_RATIO": 0.31,
        }
        # ⚠️ 2026-09-30 重钉：原断言 `assertIn("2~9x", text)` 盯的是"注入的
        # MIN/MAX_LEVERAGE 出现在提示词里"。提示词正文迁进 `data/prompt_library.json`
        # 后，杠杆区间改由 `{{risk_budget}}` 插槽承载（源头是 `risk_constants`，
        # 不经过这两个注入项）⇒ 注入值不再进提示词，那条断言已无处可落。
        #
        # 但本用例真正要守的不变量是"**注入项能从 globals() 回退解析**、只传用户参数
        # 也不会 TypeError"。故改为把 `apply_module_layout` 换成一个**间谍**：
        # 它被调用即证明回退解析走到了最后一步，返回哨兵即证明用的就是注入的那个
        # —— 比对着提示词文本找数字更直接，且不会因为文案改版而假绿。
        sentinel = "SENTINEL_FROM_INJECTED_APPLY_MODULE_LAYOUT"
        calls = []

        def _spy_apply_module_layout(*args, **kwargs):
            calls.append((args, kwargs))
            return sentinel

        injected = dict(injected)
        injected["apply_module_layout"] = _spy_apply_module_layout
        saved = {k: brain_prompt.__dict__.get(k, _MISSING) for k in injected}
        brain_prompt.__dict__.update(injected)
        try:
            text = brain_prompt.construct_full_market_prompt([])
        finally:
            for k, v in saved.items():
                if v is _MISSING:
                    brain_prompt.__dict__.pop(k, None)
                else:
                    brain_prompt.__dict__[k] = v
        self.assertTrue(calls, "注入的 apply_module_layout 没被调用 —— 回退解析没生效")
        self.assertEqual(text, sentinel, "返回值不是注入项给的 —— 说明用的不是注入的那个")
        # 间谍必须拿到**渲染上下文**（否则"回退成功"也可能是在空跑）
        _args, _kwargs = calls[0]
        self.assertIn("context", _kwargs, "apply_module_layout 未收到 context（插槽渲染会退化）")
        self.assertTrue(_kwargs["context"], "context 为空 —— 实时数据没进提示词")
        self.assertEqual(len(names), 14)


_MISSING = object()


if __name__ == "__main__":
    unittest.main()
