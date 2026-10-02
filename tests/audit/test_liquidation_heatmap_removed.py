"""★ 2026-10 用户拍板：预估型强平热力图**整块移除** —— 本文件是它的**墓碑门**。

## 为什么移除（不是"先关掉"）

- R2 是 Binance 免费 OI 历史**重建估算**：实测毛/净换手差 **26~356×** ⇒ 绝对金额不可信；
- 它既不在系统提示词的 P0–P3 证据分级里，也没有可验证的校准样本（OKX 爆仓流水需要
  连续数天采集才能给出秩相关/命中率）；
- 结论：**不可靠的图不该留在系统里**（哪怕只是展示），否则看板上的"预估金额"会持续
  给人错误暗示。

## 本门在守什么

一层一层钉死"移除是彻底的"，而不是留半截接线：构建脚本与调度任务、引擎默认块与工厂、
提示词开关与渲染、看板载荷与前端卡片/文案、信号快照字段。任何一处被"顺手接回"都会红。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LiquidationHeatmapRemovedTest(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    # ── 1. 被删的文件确实不存在 ────────────────────────────────────────────
    def test_removed_files_are_gone(self):
        for rel in ("scripts/liq_heatmap_builder.py",
                    "scripts/factors/liquidation_heatmap.py",
                    "tests/ops/test_liq_heatmap_builder.py",
                    "tests/trading/test_liquidation_heatmap.py"):
            self.assertFalse((ROOT / rel).exists(), f"应已移除：{rel}")

    # ── 2. 调度器不再有该任务 ──────────────────────────────────────────────
    def test_scheduler_has_no_heatmap_job(self):
        src = self._read("astra_gateway/scheduler.py")
        self.assertNotIn("liq_heatmap", src)
        self.assertNotIn("liq_heatmap_builder.py", src)

    # ── 3. 引擎不再生产该块 ────────────────────────────────────────────────
    def test_engine_no_longer_produces_the_block(self):
        for rel in ("scripts/factor_library.py",
                    "scripts/factors/defaults.py",
                    "scripts/factors/__init__.py",
                    "scripts/brain/packages.py"):
            self.assertNotIn("liquidation_heatmap", self._read(rel), rel)
        # 只有 `build_default_factors` 的键集（外加每个标的的 instId/name 等）
        from scripts.factors.defaults import build_default_factors
        self.assertNotIn("liquidation_heatmap", build_default_factors("X-USDT-SWAP", "X"))

    # ── 4. 提示词不再有开关/渲染 ───────────────────────────────────────────
    def test_prompt_has_no_switch_and_no_rendering(self):
        src = self._read("scripts/brain/prompt.py")
        self.assertNotIn("PROMPT_INJECT_LIQUIDATION_HEATMAP", src)
        self.assertNotIn("tier_line_heat", src)
        # 渲染标签不得再出现（源码里保留一句"已整块移除"的说明是允许的）
        self.assertNotIn("🔥 T0·强平热力图", src)

    def test_a_stray_block_cannot_reach_the_prompt(self):
        """即便硬塞一个 `liquidation_heatmap` 块进快照，提示词也不得渲染它。"""
        import sys
        from unittest.mock import patch
        sys.path.insert(0, str(ROOT / "scripts"))
        import ai_brain_trader

        pkg = {"name": "BTC", "instId": "BTC-USDT-SWAP", "data_quality": "valid",
               "price": 60000.0, "chg24h": 1.0, "bidPx": 59999.0, "askPx": 60001.0,
               "smart_money": {}, "recent_15m": [], "recent_1h": [], "recent_4h": [],
               "quant_factors": {"liquidation_heatmap": {
                   "available": True, "top_level": "99999",
                   "nearest_above": {"price": 99999, "distance_pct": 66.6, "side": "short"},
                   "reason": ""}}}
        missing = "/tmp/astra-none"
        with patch.object(ai_brain_trader, "NEWS_SENTIMENT_FILE", missing), \
             patch.object(ai_brain_trader, "AI_MEMORY_MD_FILE", missing), \
             patch.object(ai_brain_trader, "AI_MEMORY_FILE", missing):
            prompt = ai_brain_trader.construct_full_market_prompt(
                [pkg], current_time_str="T", usdt_available=1000.0)
        self.assertNotIn("强平热力图", prompt)
        self.assertNotIn("99999", prompt)

    # ── 5. 看板载荷与前端 ──────────────────────────────────────────────────
    def test_payload_builders_have_no_heat_field(self):
        for rel in ("astra_backend/dashboard_payload/factors.py",
                    "astra_backend/dashboard_payload/factors_view.py"):
            self.assertNotIn("liquidation_heatmap", self._read(rel), rel)

    def test_frontend_has_no_heat_card_or_strings(self):
        for rel in ("frontend/src/components/dashboard/FactorDrawer.vue",
                    "frontend/src/locales/zh/dash/matrix.ts",
                    "frontend/src/locales/en/dash/matrix.ts"):
            src = self._read(rel)
            self.assertNotIn("heat", src, rel)
            self.assertNotIn("heatmap", src, rel)

    def test_signal_snapshot_has_no_heat_fields(self):
        self.assertNotIn("heat_", self._read("scripts/trader/signal_snapshot.py"))

    # ── 6. 归档留痕（可恢复）── 只在本地 `.archive/`，不入库 ────────────────
    def test_removed_sources_are_archived_locally(self):
        """归档目录可能不存在（`.archive/` 不入库、别的机器上没有）⇒ 存在才查内容。"""
        arc = ROOT / ".archive" / "liq_heatmap_removed"
        if not arc.exists():
            self.skipTest("本机没有归档目录（.archive/ 不入库）")
        names = {p.name for p in arc.rglob("*") if p.is_file()}
        self.assertIn("liq_heatmap_builder.py", names)
        self.assertIn("liquidation_heatmap.py", names)


if __name__ == "__main__":
    unittest.main()
