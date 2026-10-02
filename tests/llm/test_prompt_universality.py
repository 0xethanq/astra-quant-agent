"""预设提示词与风控阈值的「资金规模通用性」回归测试。

背景：预设曾把单笔保证金写成绝对金额「100~200U」、单标的上限写成「600 USDT」、
日亏熔断写成「150 USDT」。对可用余额仅 80U 的小资金账户，这些数值互相冲突且
风控线永不触发（等于没有熔断）。v7.5.5 起一律改为按实际可用余额自适应推导。
本测试锁定该不变量，禁止绝对金额重新写回预设与执行层。
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from tests.risk_test_env import pin_baseline_risk_env  # noqa: E402


_READ_SCOPE = None


def setUpModule():
    """第二百三十六刀：本文件断言**线上**方案快照/池措辞的健康度（如"不含绝对金额"、
    "池规模措辞未硬编码"）—— **有意的线上守卫**。只读、不改；显式声明，把
    「依赖线上配置内容」从静默变成可审计（未声明时严格模式会报错）。同时锁 risk 基线。"""
    global _READ_SCOPE
    from tests import allow_real_data_reads
    _READ_SCOPE = allow_real_data_reads()
    _READ_SCOPE.__enter__()
    # risk_budget 渲染断言锁定基线（5% 日亏/2% 单笔）；隔离生产 .env 当前套件值
    pin_baseline_risk_env()


def tearDownModule():
    global _READ_SCOPE
    if _READ_SCOPE is not None:
        _READ_SCOPE.__exit__(None, None, None)
        _READ_SCOPE = None

# 绝对法币金额：数字或区间 + U/USDT
_ABS_MONEY = re.compile(r"(?<![\d.%])\d{2,5}(?:\.\d+)?\s*(?:~|～|至|-)\s*\d{2,5}(?:\.\d+)?\s*(?:USDT|U)\b|(?<![\d.])\d{3,5}\s*(?:USDT|U)\b")
# 允许出现绝对金额的位置：自适应风险预算自身的示例文案、以及带「可用余额」前缀的举例
_ALLOWED_MARKERS = ("可用余额 80U", "可用余额 4000U", "本周期风险预算", "自适应推导")


def _offenders(text: str) -> list[str]:
    out = []
    for m in _ABS_MONEY.finditer(text or ""):
        window = text[max(0, m.start() - 60):m.end() + 30]
        if any(marker in window for marker in _ALLOWED_MARKERS):
            continue
        out.append(window.replace("\n", " ").strip())
    return out


class PromptUniversalityTests(unittest.TestCase):
    def test_base_system_prompt_has_no_absolute_money(self):
        from scripts.ai_brain_trader import get_effective_system_prompt
        self.assertEqual(_offenders(get_effective_system_prompt()), [], "代码 base 系统提示词含绝对金额")

    def test_base_user_prompt_has_no_absolute_money(self):
        """用户提示词模板（现由 JSON 方案模块承载）不得写死绝对法币金额。

        ★ 2026-09-30 提示词来源迁移后重钉：旧写法在 `scripts/brain/prompt.py` 源码里
        slice 出 f-string 模板（`prompt = f...` 到 `runtime_vars = {...}` 之间），而该函数现已改为
        只组装 `runtime_vars` 再调 `apply_module_layout("", …)`，两个 marker 都不复存在。
        判据改落在**组装后的用户提示词**（JSON `trading_user` 模块；不注入运行期 context，
        故插槽保持 `{{...}}` 形态，量出来的正是模板正文而非运行期数字），
        仍然守住"模板不得硬编码金额、一切金额按可用余额自适应推导"这一不变量。
        """
        from scripts.prompt_library import active_profile, apply_module_layout, base_template_text
        text = apply_module_layout(base_template_text("trading_user"), active_profile(), "trading_user", "x")
        self.assertGreater(len(text), 500, "用户提示词为空 —— 否则本用例会退化成对空串的假通过")
        self.assertEqual(_offenders(text), [], "代码 base 用户提示词含绝对金额")

    def test_source_presets_have_no_absolute_money(self):
        src = (ROOT / "scripts" / "prompt_library.py").read_text(encoding="utf-8")
        block = src[src.index("PRESETS: dict"):src.index("\nEMPTY_CUSTOM")]
        self.assertEqual(_offenders(block), [], "源码预设含绝对金额，小资金账户会冲突")

    def test_live_profile_has_no_absolute_money(self):
        """出厂基线的**每一条**方案都不得含绝对金额（2026-09-30 起遍历全部）。

        此前只查 `profiles["stable"]`：预设换成单条「全形态波段策略(提示词样板)」后，
        那种写法会 KeyError（或更糟——静默查了个空）。遍历才是"出厂方案整体"的判据。
        """
        live = json.loads((ROOT / "data" / "prompt_library.json").read_text(encoding="utf-8"))
        profiles = live.get("profiles") or {}
        self.assertTrue(profiles, "出厂基线里没有任何方案？")
        for pid, prof in profiles.items():
            with self.subTest(profile=pid):
                self.assertEqual(_offenders(json.dumps(prof, ensure_ascii=False)), [],
                                 f"出厂方案 {pid} 含绝对金额")

    def test_risk_budget_is_an_allowed_variable_and_rendered(self):
        import prompt_library as pl
        self.assertIn("risk_budget", pl.ALLOWED_VARIABLES)
        ctx = {}
        from scripts.ai_brain_trader import construct_full_market_prompt
        construct_full_market_prompt([], "无", [], [], "2026-09-07 21:00:00",
                                     usdt_available=80.0, runtime_context_out=ctx)
        self.assertIn("risk_budget", ctx)
        self.assertIn("2.4", ctx["risk_budget"])      # 80U * 3%
        self.assertIn("9.6", ctx["risk_budget"])      # 80U * 12%
        self.assertIn("-4.0 USDT", ctx["risk_budget"])  # 80U * 5% 日亏熔断
        self.assertIn("小资金账户提示", ctx["risk_budget"])

    def test_risk_budget_missing_context_fails_loud(self):
        from scripts.ai_brain_trader import construct_full_market_prompt
        ctx = {}
        construct_full_market_prompt([], "无", [], [], "2026-09-07 21:00:00",
                                     usdt_available=None, runtime_context_out=ctx)
        self.assertIn("MISSING_CONTEXT:risk_budget", ctx["risk_budget"])

    def test_multiline_block_var_not_embedded_in_system_prose(self):
        """risk_budget 是多行块，内插进 system 正文会把句子撑断（曾在实盘 prompt 中出现）。
        约定：它只能作为独立小节出现在 trading_user，不得出现在 trading_system 文本里。"""
        live = json.loads((ROOT / "data" / "prompt_library.json").read_text(encoding="utf-8"))
        prof = live["profiles"][live["active_profile_id"]]
        sys_blob = json.dumps(
            {"modules": (prof.get("pipelines") or {}).get("trading_system", []),
             "legacy": prof.get("trading_system")}, ensure_ascii=False)
        self.assertNotIn("{{risk_budget}}", sys_blob,
                         "多行块变量被内插进 system 提示词，会撑断句子")

    def test_rendered_system_prompt_has_no_injected_block(self):
        from scripts.ai_brain_trader import (get_effective_system_prompt, apply_module_layout,
                                             active_profile, construct_full_market_prompt)
        ctx = {}
        construct_full_market_prompt([], "无", [], [], "2026-09-07 21:00:00",
                                     usdt_available=20.0, runtime_context_out=ctx)
        rendered = apply_module_layout(get_effective_system_prompt(), active_profile(),
                                       "trading_system", "t", context=ctx)
        self.assertNotIn("{{risk_budget}}", rendered)
        self.assertNotIn("】:\n- 常规单笔保证金", rendered, "system 正文中出现被撑断的预算块")
        self.assertNotIn("取值严禁", rendered, "历史替换造成的语句粘连残留")

    def test_pool_size_wording_is_not_hardcoded(self):
        """标的池可增删，提示词与日志不得写死具体数量（如「六币种」「6 个标的」）。"""
        from scripts.ai_brain_trader import get_effective_system_prompt
        corpus = get_effective_system_prompt()
        corpus += (ROOT / "scripts" / "prompt_library.py").read_text(encoding="utf-8")
        corpus += json.dumps(json.loads((ROOT / "data" / "prompt_library.json").read_text(encoding="utf-8")),
                             ensure_ascii=False)
        for bad in ("六币种", "6币种", "在 6 个标的", "6 个标的中"):
            self.assertNotIn(bad, corpus, f"提示词写死了标的数量: {bad}")


class AdaptiveRiskLimitTests(unittest.TestCase):
    def test_small_account_daily_loss_limit_is_tighter_than_absolute_cap(self):
        import ai_factor_trader as aft
        self.assertLess(aft.effective_daily_loss_limit(80.0), aft.MAX_DAILY_LOSS_USDT)
        self.assertAlmostEqual(aft.effective_daily_loss_limit(80.0), 4.0, places=2)
        self.assertAlmostEqual(aft.effective_single_asset_margin(80.0), 24.0, places=2)

    def test_large_account_keeps_legacy_absolute_caps(self):
        import ai_factor_trader as aft
        self.assertEqual(aft.effective_daily_loss_limit(4000.0), aft.MAX_DAILY_LOSS_USDT)
        self.assertEqual(aft.effective_single_asset_margin(4000.0), aft.MAX_SINGLE_ASSET_MARGIN)

    def test_limits_are_env_overridable(self):
        import os, importlib
        import astra_backend.config as backend_config
        import risk_constants
        import ai_factor_trader as aft
        os.environ["ASTRA_MAX_DAILY_LOSS_USDT"] = "99"
        original_loader = backend_config.load_dotenv
        backend_config.load_dotenv = lambda path: None  # 屏蔽仓库 .env 覆盖测试环境变量
        try:
            importlib.reload(risk_constants)  # v7.6 起常量单一事实源在 risk_constants
            importlib.reload(aft)
            self.assertEqual(aft.MAX_DAILY_LOSS_USDT, 99.0)
        finally:
            backend_config.load_dotenv = original_loader
            del os.environ["ASTRA_MAX_DAILY_LOSS_USDT"]
            importlib.reload(risk_constants)
            importlib.reload(aft)


if __name__ == "__main__":
    unittest.main()
