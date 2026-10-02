"""自进化复盘的**归因维度**回归（2026-10）。

## 这个测试在守什么

复盘提示词里的【多维量化战绩透视矩阵】是模型唯一能据以"逐标的"校准的证据。
实测缺陷：`_compute_multi_dimensional_breakdown` 先取 `symbol`/`instId`，而
`load_closed_trades` 产出的条目用的是台账字段 `inst` —— 两者都不存在，于是
**全部交易塌成一个 `UNKNOWN` 桶**。生产提示词里就一行：

    • UNKNOWN: 37笔 (胜16/负21 | 胜率 43.2% | 净利 -349.97 USDT)

后果不是"少个字段"：逐标的归因这一维被整块抹平，而 `asset_multipliers`
完全由模型据此定夺，**直接乘在真实保证金上**（`brain/decisions.py`）。

本测试从**真实台账行形状**（含 `inst`）反推，钉死"逐标的必须真的分开"。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# 与同族"导入 scripts 模块"的测试同一段前置：scripts 模块用**裸兄弟导入**
# （`from instrument_pool import load_instruments`），故 scripts/ 必须先上 sys.path。
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.self_improvement_engine import _compute_multi_dimensional_breakdown  # noqa: E402


def _trade(inst, pnl, *, side="多", exit_reason="🛑 止损离场", **over):
    """台账平仓行的**真实形状**：标的键是 `inst`（不是 symbol/instId）。"""
    row = {
        "inst": inst, "side": side, "time": "2026-10-01 12:00:00",
        "open_time": "2026-10-01 10:00:00", "strategy": "🌊 顺势做多",
        "margin": 200.0, "gross_pnl": pnl, "fee": 1.0, "net_pnl": pnl,
        "exit_reason": exit_reason,
    }
    row.update(over)
    return row


class SymbolAttributionTests(unittest.TestCase):
    def test_per_symbol_rows_are_not_collapsed_to_unknown(self):
        """★ 核心回归：多标的台账必须产出**逐标的**分布，绝不出现 UNKNOWN。"""
        trades = [
            _trade("BTC", 40.0), _trade("BTC", -20.0),
            _trade("ETH", -35.0),
            _trade("SOL", 12.0),
        ]
        text = _compute_multi_dimensional_breakdown(trades)
        self.assertNotIn("UNKNOWN", text, "标的键又塌回 UNKNOWN 了（逐标的归因全废）")
        for inst in ("BTC", "ETH", "SOL"):
            self.assertIn(inst, text, f"{inst} 必须单独成行")

    def test_per_symbol_numbers_are_correct(self):
        trades = [
            _trade("BTC", 40.0), _trade("BTC", -20.0),
            _trade("ETH", -35.0),
        ]
        text = _compute_multi_dimensional_breakdown(trades)
        # BTC: 2 笔 / 胜 1 / 胜率 50.0% / 净利 +20.00；ETH: 1 笔 / 胜 0 / 0.0% / -35.00
        self.assertIn("BTC: 2笔 (胜1/负1 | 胜率 50.0% | 净利 +20.00 USDT)", text)
        self.assertIn("ETH: 1笔 (胜0/负1 | 胜率 0.0% | 净利 -35.00 USDT)", text)

    def test_sorted_by_net_pnl_desc(self):
        trades = [_trade("ETH", -35.0), _trade("BTC", 40.0), _trade("SOL", 12.0)]
        text = _compute_multi_dimensional_breakdown(trades)
        order = [text.index(s) for s in ("BTC:", "SOL:", "ETH:")]
        self.assertEqual(order, sorted(order), "标的行必须按净利从高到低排（最差的一眼可见）")

    def test_legacy_symbol_key_still_supported(self):
        """旧形态（`symbol` 键）不得因为本次修复而失效 —— 兼容而非替换。"""
        trades = [{"symbol": "XRP", "side": "long", "net_pnl": 5.0, "fee": 0.1}]
        text = _compute_multi_dimensional_breakdown(trades)
        self.assertIn("XRP", text)

    def test_missing_keys_still_fall_back_to_unknown(self):
        """真的是三无条目才给 UNKNOWN（诚实兜底，不是把有标的的也塌进去）。"""
        text = _compute_multi_dimensional_breakdown([{"net_pnl": 1.0, "fee": 0.0}])
        self.assertIn("UNKNOWN", text)


class ExitMechanismDisclosureTests(unittest.TestCase):
    def test_exit_reason_distribution_still_counts(self):
        trades = [
            _trade("BTC", -10.0, exit_reason="🛑 止损出场"),
            _trade("BTC", 10.0, exit_reason="🎯 目标止盈达成"),
            _trade("BTC", 3.0, exit_reason="🛡️ 保本平仓"),
        ]
        text = _compute_multi_dimensional_breakdown(trades)
        self.assertIn("出场形态分布", text)
        self.assertIn("止损触发: 1笔", text)
        self.assertIn("止盈达成: 1笔", text)


class SideBreakdownTests(unittest.TestCase):
    def test_long_short_split_is_preserved(self):
        trades = [
            _trade("BTC", 10.0, side="多"),
            _trade("ETH", -5.0, side="空"),
        ]
        text = _compute_multi_dimensional_breakdown(trades)
        self.assertIn("多头 1笔 (胜率 100.0% | 净利 +10.00 U)", text)
        self.assertIn("空头 1笔 (胜率 0.0% | 净利 -5.00 U)", text)


class EmptyInputTests(unittest.TestCase):
    def test_empty_returns_placeholder(self):
        self.assertEqual(_compute_multi_dimensional_breakdown([]), "暂无平仓样本")
        self.assertEqual(_compute_multi_dimensional_breakdown(None), "暂无平仓样本")


if __name__ == "__main__":
    unittest.main()
