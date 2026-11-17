"""Offline isolated test for Prompt Anti-Drawdown TP & Position Data Feed Enrichment.
Validates:
1. High Water Mark, peak profit gain, and retracement drawdown percentage are properly injected into account_positions.
2. System prompt and active profile enforce anti-drawdown take-profit and CLOSE_MARKET directives.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

import scripts.ai_brain_trader as abt


class PromptAntiDrawdownTakeProfitTests(unittest.TestCase):
    def test_position_feed_enriches_peak_and_drawdown(self):
        active_positions = [
            {
                "instId": "ETH-USDT-SWAP",
                "name": "ETH",
                "side": "long",
                "lever": "3",
                "avgPx": "2500.0",
                "markPx": "2520.0",
                "pos": "2.0",
                "upl": "4.0",
                "uplRatio": "0.016",
                "highWaterMark": 2560.0,
                "lowWaterMark": 2495.0,
                "trailingStopPx": 2505.0,
                "takeProfitPx": 2600.0,
                "stage_desc": "已推保本无风险",
            }
        ]

        prompt_str = abt.construct_full_market_prompt(
            packages=[],
            pos_summary="1多0空",
            active_positions_detail=active_positions,
            current_time_str="2026-09-07 15:00:00"
        )

        self.assertIn("曾最高到: 2560.0", prompt_str)
        self.assertIn("极值浮盈 +2.4%", prompt_str)
        # Drawdown from peak: (2560 - 2520) / (2560 - 2500) = 40 / 60 = 66.7%
        self.assertIn("回撤 66.7%", prompt_str)
        self.assertIn("动态止损线: 2505.0", prompt_str)
        self.assertIn("目标止盈: 2600.0", prompt_str)

    def test_effective_system_prompt_contains_anti_drawdown_directives(self):
        """★ 判据必须落在**模型真正收到的 System Prompt** 上，而不是方案的 flat 文本。

        2026-09-30 换出厂预设时暴露的判据缺陷：旧写法读 `active_profile()["trading_system"]`
        —— 那只是方案的"风格层"文本；而风控指令属于**代码基座**（`SYSTEM_PROMPT`），
        渲染时永远在方案层之前注入。旧写法在"方案层不含这些词"时会误报。

        ★ 2026-09-30 提示词来源迁移后再次重钉：`SYSTEM_PROMPT` 如今只剩只读输出 JSON
        Schema，反回撤正文全部搬进 `data/prompt_library.json` 的 `trading_system` 模块
        （「快节奏兑现与亏损截断」）。故 `get_effective_system_prompt()` 仍是对的对象，
        但承载这些指令的**文本来源**从代码基座换成了 JSON 方案模块；新正文用
        「分批止盈 / 失效即离场 / 峰值回撤 / CLOSE_MARKET / 时间止损」表达同一语义。
        """
        from scripts.ai_brain_trader import get_effective_system_prompt
        sys_prompt = get_effective_system_prompt()
        self.assertGreater(len(sys_prompt), 1000, "effective system prompt 为空 —— 定位错了对象")
        # 语义不变：分批兑现 + 峰值回撤主动止盈 + 失效/时间止损 + CLOSE_MARKET 指令
        self.assertIn("分批止盈", sys_prompt)
        self.assertIn("峰值回撤", sys_prompt)
        self.assertIn("失效即离场", sys_prompt)
        self.assertIn("时间止损", sys_prompt)
        self.assertIn("CLOSE_MARKET", sys_prompt)


if __name__ == "__main__":
    unittest.main()
