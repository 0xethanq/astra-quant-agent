"""平仓收尾：核验归零后撤掉**可证明属于本系统**的保护腿（第一百一十三刀）。

三条铁律（顺序不可变，本门逐条钉住）：
1. **先核验归零**：未确认归零绝不撤腿（撤早了，还在保护中的仓就裸了）；
2. **该合约必须整体归零**（任何方向都没仓）；
3. **只撤可证明属于本系统的腿**（`matched` / Gate `t-astra` 标签）：
   归属不可判定的腿可能是**用户手单**，撤错不可逆。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.trader.venue_protection import select_legs_to_cancel_after_close  # noqa: E402


def _leg(symbol, order_type, side, qty, trig, algo_id):
    return {"id": algo_id, "algo_id": algo_id, "symbol": symbol, "side": side,
            "trigger_price": trig, "type": "CONDITIONAL",
            "raw": {"symbol": symbol, "orderType": order_type, "side": side.upper(),
                    "quantity": str(qty), "triggerPrice": str(trig), "algoStatus": "NEW"}}


def _gate_leg(contract, text, auto_size, trig, algo_id, direction="long"):
    return {"id": algo_id, "status": "open", "direction": direction,
            "trigger": {"price": str(trig), "rule": 1, "expiration": 604800},
            "initial": {"contract": contract, "size": 0, "text": text,
                        "is_reduce_only": True, "auto_size": auto_size, "amount": "0"},
            "raw": None}


CLOSED_POS = {"base": "UNI", "side": "short", "size_signed": -82.0}
LEGS = [
    _leg("UNIUSDT", "STOP_MARKET", "buy", 82.0, 9.025, "al-1"),
    _leg("UNIUSDT", "TAKE_PROFIT_MARKET", "buy", 82.0, 8.125, "al-2"),
]


class SelectLegsPureLogicTest(unittest.TestCase):
    """纯判定层：输入平仓前后实况与腿列表，输出该撤哪几张。"""

    def test_gate_tag_marker_proven_even_without_ledger(self):
        """Gate 的 `t-astra-sl` / `t-astra-tp` text 是防伪指纹，无需台账证明。"""
        pos = {"base": "BTC", "side": "long", "size_signed": 5.0}
        legs = [
            _gate_leg("BTC_USDT", "t-astratp1", "close_long", 89000.0, "g-tp"),
            _gate_leg("BTC_USDT", "t-astrasl1", "close_long", 81320.0, "g-sl"),
            _gate_leg("BTC_USDT", "", "close_long", 80000.0, "g-manual"),  # 人工挂的
        ]
        r = select_legs_to_cancel_after_close(pos, legs, [])
        self.assertEqual(sorted(r["ids"]), ["g-sl", "g-tp"])
        self.assertEqual(r["counts"]["not_touched"], 1)
        self.assertEqual(len(r["not_touched"]["foreign"]), 1, "人工挂的单绝对不撤")

    def test_gate_dual_mode_other_direction_never_cancelled(self):
        """双向持仓下平掉空头，多头的止盈止损绝不能被撤。"""
        pos = {"base": "BTC", "side": "short", "size_signed": -5.0}
        legs = [
            _gate_leg("BTC_USDT", "t-astrasl1", "close_short", 89000.0, "g-short-sl"),
            _gate_leg("BTC_USDT", "t-astrasl1", "close_long", 75000.0, "g-long-sl"),
        ]
        r = select_legs_to_cancel_after_close(pos, legs, [])
        self.assertEqual(r["ids"], ["g-short-sl"])
        self.assertEqual(r["counts"]["not_touched"], 1)

    def test_binance_matched_leg_cancelled(self):
        """Binance 的腿若能归属到该仓（matched），归零后必须进撤销名单。"""
        r = select_legs_to_cancel_after_close(CLOSED_POS, LEGS, [])
        self.assertIn("al-1", r["ids"])

    def test_empty_legs_returns_clean_dict(self):
        r = select_legs_to_cancel_after_close(CLOSED_POS, [], [])
        self.assertEqual(r["ids"], [])
        self.assertEqual(r["counts"]["to_cancel"], 0)

    def test_gate_full_close_leg_matches_without_size(self):
        """Gate 整仓平腿 size=0，但覆盖全部 ⇒ 平掉该仓后应可撤。"""
        pos = {"base": "BTC", "side": "short", "size_signed": -5.0}
        leg = _gate_leg("BTC_USDT", "t-astrasl1", "close_short", 81320.0, "g1")
        r = select_legs_to_cancel_after_close(pos, [leg], [])
        self.assertEqual(r["ids"], ["g1"])


if __name__ == "__main__":
    unittest.main()
