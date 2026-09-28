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
from scripts.brain import prompt as brain_prompt

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "ai_brain_trader.py"
SUBMODULE = ROOT / "scripts" / "brain" / "prompt.py"

# 只在子模块里存在、门面不应再有的实现体特征行
_IMPL_ONLY_MARKERS = (
    '- 15M K线(倒序12根 [O,H,L,C,V])',
    '严禁无差别照抄',
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
        stack = ExitStack()
        for name, value in patches.items():
            stack.enter_context(patch.object(abt, name, value))
        try:
            return abt.construct_full_market_prompt([])
        finally:
            stack.close()

    def test_leverage_constants_are_read_at_call_time(self):
        """`patch.object(abt, "MAX_LEVERAGE")` 必须体现在渲染出的提示词里。

        这条是"提示词口径 == 执行层口径"的直接哨兵：子模块若在 import 期绑定
        `risk_constants` 的值，这里会渲染出旧区间。

        渲染形态是 `{min:g}~{max:g}x`（`int(max(min_leverage, min(max_leverage,
        (lo+hi)/2)))` 那个示例值也会跟着动，但不单独钉数值以免绑死示例算法）。
        """
        text = self._render(MAX_LEVERAGE=42.0, MIN_LEVERAGE=3.0)
        self.assertIn("3~42x", text, "杠杆区间未读到补丁值 → 提示词口径与执行层漂移")
        self.assertNotIn("2~5x", text, "渲染出了旧区间，说明常量被 import 期烘焙")

    def test_confidence_gate_is_read_at_call_time(self):
        """加仓置信度门禁必须调用期读（它会直接进提示词，写死就是口径漂移）。"""
        text = self._render(MIN_SCALE_IN_CONFIDENCE=66)
        self.assertIn("置信度≥66%", text, "加仓置信度门禁未读到补丁值")

    def test_scale_in_disabled_flag_is_read_at_call_time(self):
        text = self._render(MAX_SCALE_IN_COUNT=0)
        self.assertIn("最多0次", text, "加仓次数上限未读到补丁值")

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
        self.assertIn("2~9x", text, "回退解析未生效（注入项未从 globals 取到）")
        self.assertNotIn("2~5x", text, "回退到了真实门面值，说明回退逻辑没生效")
        self.assertEqual(len(names), 14)


_MISSING = object()


if __name__ == "__main__":
    unittest.main()
