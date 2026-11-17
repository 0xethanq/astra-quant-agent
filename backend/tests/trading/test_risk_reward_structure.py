"""盈亏比**结构**护栏（2026-09-30 用户报"每次止盈十几二十 U，亏损一大笔"）。

## 这组门守什么

用户实测当天 18 笔：8 盈 +190.99U / 10 亏 −480.14U（净 −289.15U），
**均盈 23.87U 对均亏 48.01U（盈亏比 0.50）**。翻代码发现这不是运气问题，
而是**机械结构**把盈亏比倒过来了：

- 真实止损 = 标的池 `sl_atr_mult` × ATR（主流币 **1.8**、其余 **2.2**）；
- 而首批止盈门槛当时是 `ASTRA_SCALE_OUT_TRIGGER_ATR=1.0`（`.env` 现值）、
  比例 50% ⇒ **一半仓位在 0.45R 处就落袋了**。
  赢的时候只锁到不足半个 R，输的时候亏满 1 个 R —— 胜率再高也难赚。

现行口径（用户 2026-09-30 拍板）：**2.0 × ATR 落袋 35%** ⇒ tier_1 ≈ 1.11R、
tier_2 ≈ 0.91R，且**剩余 65% 继续跟随趋势**（让利润奔跑的那一段仍是主体）。

## 为什么用"夹具完整的沙箱"读池

本仓禁止"断言依赖生产数据内容"。`tests.config_sandbox.isolate_config` 会把
`data/instrument_pool.json` 复制成**沙箱夹具**：读的是副本（不碰生产），
但副本的 `sl_atr_mult` 与生产同步 ⇒ 池里真被改成 3.0×ATR 时本门仍会红。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.config_sandbox import isolate_config

ROOT = Path(__file__).resolve().parents[2]

#: 允许的最低"首批锁定 R"。用户选定的 2.0×ATR 对最宽止损 2.2 ⇒ 0.909，
#: 故门槛取 0.9（比旧口径的 0.45 高一个量级，且给"主流币 1.8"留出 1.11R 空间）。
#: 若要把两个 tier 都推到 ≥1.0R，门槛需 ≥2.2×ATR —— 那是用户的下一档选择。
MIN_FIRST_TRANCHE_R = 0.9


class RiskRewardStructureTests(unittest.TestCase):
    def _pool_stop_multiples(self) -> list:
        """从**沙箱夹具**读各标的的止损 ATR 倍数（不碰生产文件）。"""
        isolate_config(self)
        from instrument_pool import load_instruments
        mults = []
        for item in load_instruments():
            try:
                mults.append(float(item.get("sl_atr_mult")))
            except (TypeError, ValueError):
                continue
        return mults

    def test_first_tranche_locks_at_least_about_one_R(self):
        """★ 首批止盈不得在止损之前落袋：锁定 R 必须 ≥ 0.9。

        这是本门存在的全部意义：防止有人把触发门槛改回 1.0×ATR（0.45R）这类
        "赢小输大"的结构 —— 那种改法在功能测试里**完全不会红**。
        """
        from scripts.risk_constants import SCALE_OUT_TRIGGER_ATR
        mults = self._pool_stop_multiples()
        self.assertTrue(mults, "标的池读不到止损倍数 —— 沙箱夹具不完整？")
        worst = max(mults)
        worst_r = float(SCALE_OUT_TRIGGER_ATR) / worst
        detail = "、".join(f"sl={m:g}×ATR ⇒ 首批锁定 {float(SCALE_OUT_TRIGGER_ATR) / m:.2f}R"
                          for m in sorted(set(mults)))
        self.assertGreaterEqual(
            worst_r, MIN_FIRST_TRANCHE_R,
            f"首批止盈门槛 {SCALE_OUT_TRIGGER_ATR:g}×ATR 对最宽止损 {worst:g}×ATR "
            f"只锁 {worst_r:.2f}R ⇒ 结构上赢小输大。各档：{detail}")

    def test_the_runner_keeps_the_majority_of_the_position(self):
        """落袋的必须是**少数**：剩余仓位才是"让利润奔跑"的主体。"""
        from scripts.risk_constants import SCALE_OUT_RATIO
        ratio = float(SCALE_OUT_RATIO)
        self.assertGreater(ratio, 0.0)
        self.assertLess(ratio, 0.5, "首批落袋超过一半 ⇒ 盈利单被削平，回到'赢小输大'")
        self.assertGreaterEqual(1.0 - ratio, 0.5, "余仓必须是主体（≥50%）")

    def test_shipped_defaults_and_docs_agree(self):
        """`env.example` 与代码默认值必须同口径（防"改一处漏一处"）。"""
        from scripts.risk_constants import DEFAULTS
        text = (ROOT / "env.example").read_text(encoding="utf-8")
        self.assertIn(f"ASTRA_SCALE_OUT_TRIGGER_ATR={DEFAULTS['ASTRA_SCALE_OUT_TRIGGER_ATR']:.2f}", text)
        self.assertIn(f"ASTRA_SCALE_OUT_RATIO={DEFAULTS['ASTRA_SCALE_OUT_RATIO']:.2f}", text)

    def test_no_risk_suite_reintroduces_the_inverted_setup(self):
        """三个一键套装（保守/均衡/激进）都不得把口径改回"止损前落袋"。"""
        import astra_backend.risk_config as RC
        worst = max(self._pool_stop_multiples())
        for suite in RC.SUITES:
            trigger = float(suite["values"]["ASTRA_SCALE_OUT_TRIGGER_ATR"])
            ratio = float(suite["values"]["ASTRA_SCALE_OUT_RATIO"])
            with self.subTest(suite=suite["id"]):
                self.assertGreaterEqual(
                    trigger / worst, MIN_FIRST_TRANCHE_R,
                    f"套装 {suite['id']} 的首批锁定 R 只有 {trigger / worst:.2f}（触发 {trigger}×ATR）")
                self.assertLess(ratio, 0.5, f"套装 {suite['id']} 首批比例 {ratio} 超过一半")

    def test_disclosure_matches_the_knobs(self):
        """给模型看的"风险预算"文案必须与实际生效的旋钮同源（不许手写死数）。"""
        from scripts.ai_brain_trader import build_risk_budget_text
        from scripts.risk_constants import SCALE_OUT_RATIO, SCALE_OUT_TRIGGER_ATR
        text = build_risk_budget_text(1000.0) or ""
        self.assertTrue(text, "本环境未装配风险预算文案")
        self.assertIn(f"底仓浮盈达到 {float(SCALE_OUT_TRIGGER_ATR):g}x ATR", text)
        self.assertIn(f"市价平仓 {float(SCALE_OUT_RATIO):.0%}", text)


if __name__ == "__main__":
    unittest.main()
