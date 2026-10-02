"""开仓数理快照 schema 兼容回归钉扎（2026-09-09）。

事故：build_signal_snapshot 只认 factor_library 块结构（calculus_dynamics 等），
而开仓路径传入的执行层 f 携带的是 calculate_multi_timeframe 聚合结构
（f["calculus"]），导致 signal_journal 全部条目 22/24 字段为 None，
自进化复盘对所有样本输出「数理快照不可观测」、逐单因果归因失效。
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

import ai_factor_trader as aft

EXEC_LAYER_MULTI = {
    "valid": True,
    "velocity": 1.61, "acceleration": 0.42, "max_abs_jerk": 2.5, "impulse": -0.9,
    "curvature": 0.2, "power": 1.4, "power_regime": "KINETIC_ACCELERATING",
    "regime": "BULL_ACCELERATING", "quality": 0.87,
    "definite_integrals": {"energy_integral": -0.61, "deviation_area_integral": -3.2, "volume_action_integral": 0.1},
    "probability_theory": {
        "continuation_prob_pct": 66.9, "breakdown_prob_pct": 8.1,
        "var_95_pct": 0.57, "cvar_95_pct": 0.71, "prob_regime": "TREND_PERSISTENT", "is_fat_tail": False,
    },
}

FACTOR_LIBRARY_F = {
    "instId": "SOL-USDT-SWAP", "name": "SOL", "price": 100.0, "atr": 1.0,
    "calculus_dynamics": {"velocity": 0.3, "acceleration": 0.64, "jerk": 0.22, "impulse": -1.05,
                          "quality": 0.8, "regime": "RANGE"},
    "probability_theory": {"continuation_prob_pct": 66.9, "var_95_pct": 0.57, "cvar_95_pct": 0.71},
    "definite_integrals": {"energy_integral": -1.0, "deviation_area_integral": -4.9},
    "trend_momentum": {"adx": 25.0, "rsi": 55.0},
    "microstructure": {"funding_rate": 0.01},
    "smart_money_derivatives": {"net_flow": 123.0},
    "composite_alpha_score": 3.2,
}


class SignalSnapshotSchemaTests(unittest.TestCase):
    def test_exec_layer_factor_tiers_populate_evidence(self):
        """★ 2026-10 重钉：快照的**归因证据**由 7 梯队因子承载。

        原来这条守的是"执行层 calculus 块 → 22/24 字段有值"。数理链退场后，
        同一意图（开仓时刻有**可观测、可复核**的证据可归因）改由新梯队字段承载，
        故判据改钉新字段；旧动力学键仍可读（历史 journal），但不再是证据来源。
        """
        f = {"instId": "BTC-USDT-SWAP", "name": "BTC", "price": 78000.0, "atr": 370.0,
             "rsi": 55.0,
             "trend_momentum": {"macd_hist": 45.2, "macd_accel": 12.8,
                                "macd_momentum_state": "ACCELERATING",
                                "macd_divergence": "NONE", "rsi_1h": 61.5,
                                "rsi_zone": "BULL_MOMENTUM", "rsi_divergence": "NONE"},
             "volume_money_flow": {"cvd_5m_usd": 6800000.0, "cvd_1h_usd": 14200000.0,
                                   "cvd_divergence": "NONE",
                                   "taker_buy_sell_ratio": 1.19},
             "microstructure": {"obi_pct": 28.5, "bid_ask_depth_ratio": 1.42,
                                "spread_bps": 0.33},
             "volume_profile": {"vwap_bias_pct": 0.44,
                                "value_area_position": "INSIDE_VALUE_AREA",
                                "vpvr_poc": 61680.0},
             "smart_money_derivatives": {"funding_rate_pct": 0.0036,
                                         "funding_crowding": "NEUTRAL",
                                         "oi_chg_1h_pct": 3.2,
                                         "oi_price_quadrant": "LONG_BUILDUP",
                                         "elite_divergence": "NEUTRAL",
                                         "basis_annualized_pct": 7.4},
             "calculus": {"valid": False, "retired": True}}
        snap = aft.build_signal_snapshot(f)
        self.assertEqual(snap["macd_hist"], 45.2)
        self.assertEqual(snap["macd_accel"], 12.8)
        self.assertEqual(snap["rsi_1h"], 61.5)
        self.assertEqual(snap["cvd_5m_usd"], 6800000.0)
        self.assertEqual(snap["taker_buy_sell_ratio"], 1.19)
        self.assertEqual(snap["obi_pct"], 28.5)
        self.assertEqual(snap["vwap_bias_pct"], 0.44)
        self.assertEqual(snap["vpvr_poc"], 61680.0)
        self.assertEqual(snap["oi_price_quadrant"], "LONG_BUILDUP")
        self.assertEqual(snap["elite_divergence"], "NEUTRAL")
        self.assertEqual(snap["rsi"], 55.0)
        # ★ 2026-10 彻底剥离：已退役动力学键不再出现在新快照中（不产出恒 None 键）
        self.assertNotIn("velocity", snap)
        self.assertNotIn("energy_integral", snap)

    def test_factor_library_schema_still_works(self):
        snap = aft.build_signal_snapshot(dict(FACTOR_LIBRARY_F))
        self.assertNotIn("velocity", snap)
        self.assertEqual(snap["adx"], 25.0)
        self.assertEqual(snap["funding_rate"], 0.01)
        self.assertEqual(snap["smart_money_net"], 123.0)
        self.assertEqual(snap["composite_alpha_score"], 3.2)

    def test_enrichment_from_factor_snapshot_file(self):
        lib = {"instruments": [{
            "instId": "BTC-USDT-SWAP", "name": "BTC",
            "trend_momentum": {"adx_1h": 24.4},
            "smart_money_derivatives": {"funding_rate_pct": 0.0094, "smart_money_flow_usd": 123.0},
            "composite_alpha_score": 12.0,
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "factor_library_snapshot.json"), "w", encoding="utf-8") as f:
                json.dump(lib, f)
            f_in = {"instId": "BTC-USDT-SWAP", "name": "BTC", "price": 1.0, "atr": 1.0,
                    "calculus": EXEC_LAYER_MULTI}
            with patch.object(aft, "DATA_DIR", tmp):
                snap = aft.build_signal_snapshot(f_in)
        self.assertEqual(snap["adx"], 24.4)               # 执行层无 ADX → 因子库补齐
        self.assertEqual(snap["funding_rate"], 0.0094)
        self.assertEqual(snap["composite_alpha_score"], 12.0)
        self.assertEqual(snap["smart_money_net"], 123.0)

    def test_enrichment_failure_is_silent(self):
        f_in = {"instId": "X-USDT-SWAP", "name": "X", "price": 1.0, "atr": 1.0}
        with patch.object(aft, "DATA_DIR", "/nonexistent-dir-xyz"):
            snap = aft.build_signal_snapshot(f_in)       # 不得抛异常
        self.assertNotIn("velocity", snap)
        self.assertEqual(snap["price"], 1.0)


class ProductionFlatShapeTests(unittest.TestCase):
    """★ 2026-10 回归钉扎：**生产真实形状**的扁平执行层 f 必须也能拿到梯队因子。

    事故（本类存在的原因）：梯队字段最初按 `f["trend_momentum"]` 等**嵌套组**取值，
    而真实调用方 `fetch_single_instrument_data` 产出的是**扁平 f**（只有
    `f["macd_hist"]` / `f["rsi"]` / `f["calculus"]`）。嵌套结构属于**因子库**。
    于是生产里 18 项梯队因子**恒为 None** —— 实测台账/journal 37/37 笔全判
    `PRICE_ONLY`，自进化复盘的因子归因长期失效。

    ⚠️ 原 `test_exec_layer_factor_tiers_populate_evidence` 用的是**嵌套形态**夹具，
    所以它一直是绿的：测试与生产不同形，正是这个缺口让缺陷活了很久。本类补上
    生产形状的夹具。
    """

    #: 与 `fetch_single_instrument_data` 逐字同形的扁平 f：指标全在**顶层**，
    #: 唯一的嵌套键是已退役的 `calculus`。
    FLAT_EXEC_F = {
        "instId": "BTC-USDT-SWAP", "name": "BTC", "price": 80000.0, "atr": 900.0,
        "rsi": 52.3, "rsi_7": 48.1,
        # 15M 口径的 MACD —— 刻意给一个与因子库不同的值，用于证明**没被误用**
        "macd_hist": 999.0, "macd_accel": 888.0,
        "vwap": 79800.0, "ema9": 80100.0, "ema21": 79900.0, "ema55": 79500.0,
        "calculus": {"velocity": 0.0, "acceleration": 0.0, "regime": "RANGE_LOW_VELOCITY"},
    }

    #: 因子库快照（真源）：梯队因子按 7 梯队分组承载。
    LIB = {"instruments": [{
        "instId": "BTC-USDT-SWAP", "name": "BTC", "composite_alpha_score": 12.0,
        "trend_momentum": {
            "adx_1h": 24.4, "rsi_1h": 61.5, "rsi_zone": "BULL_MOMENTUM",
            "rsi_divergence": "NONE", "macd_hist": 16.69, "macd_accel": 12.87,
            "macd_hist_pct": 0.0209, "macd_accel_pct": 0.0161,
            "macd_momentum_state": "BULL_EXPANDING", "macd_divergence": "NONE",
            "vwap_bias_pct": 0.29,
        },
        "volume_money_flow": {
            "cvd_5m_usd": -3803788.08, "cvd_1h_usd": -10233227.0,
            "cvd_divergence": "NONE", "taker_buy_sell_ratio": 0.964,
        },
        "microstructure": {
            "obi_pct": -99.48, "bid_ask_depth_ratio": 0.0013, "spread_bps": 0.0119,
        },
        "volume_profile": {
            "vpvr_poc": 83761.535, "value_area_position": "ABOVE_VWAP",
        },
        "smart_money_derivatives": {
            "funding_rate_pct": 0.0084, "funding_crowding": "NEUTRAL",
            "oi_chg_1h_pct": 0.6589, "oi_price_quadrant": "NEUTRAL",
            "elite_divergence": "NEUTRAL", "basis_annualized_pct": 7.4,
            "smart_money_flow_usd": "-1.1万 U",
        },
    }]}

    def _snap(self, f_in=None, lib=None):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "factor_library_snapshot.json"), "w", encoding="utf-8") as fh:
                json.dump(self.LIB if lib is None else lib, fh)
            with patch.object(aft, "DATA_DIR", tmp):
                return aft.build_signal_snapshot(dict(self.FLAT_EXEC_F if f_in is None else f_in))

    def test_flat_exec_shape_yields_all_eighteen_tier_factors(self):
        """扁平 f + 因子库 ⇒ 18 项梯队因子**全非空**，且判定为可观测。"""
        from scripts.evolution.observability import (
            DYNAMICS_FIELDS, classify_snapshot_observability,
        )
        snap = self._snap()
        missing = [k for k in DYNAMICS_FIELDS if snap.get(k) is None]
        self.assertEqual(missing, [], f"扁平生产形状下梯队因子仍缺失: {missing}")
        self.assertEqual(classify_snapshot_observability(snap), "DYNAMICS_OBSERVED",
                         "扁平形状必须能被判定为可观测（否则复盘恒 PRICE_ONLY）")

    def test_flat_macd_is_not_used_for_the_one_hour_slot(self):
        """★ 时间框架纪律：15M 的 `f["macd_hist"]` **不得**填进 1H 槽位。

        扁平 f 给的是诱饵值（999.0/888.0），因子库给的是 1H 真值。跨框架回填
        等于伪造证据（宿主宪章明令禁止），故必须取因子库值。
        """
        snap = self._snap()
        self.assertEqual(snap["macd_hist"], 16.69, "1H MACD 被 15M 值覆盖 ⇒ 伪造证据")
        self.assertEqual(snap["macd_accel"], 12.87)
        self.assertEqual(snap["rsi_1h"], 61.5, "1H RSI 必须是因子库值，不是 15M 的 f['rsi']")

    def test_no_library_file_leaves_tier_factors_none_not_fabricated(self):
        """fail-soft：因子库不可读 ⇒ 梯队因子保持 None，**绝不**用扁平 f 凑数。"""
        snap = self._snap(lib={"instruments": []})
        self.assertIsNone(snap["macd_hist"], "库里取不到就该诚实不可观测，不得回填 15M 值")
        self.assertIsNone(snap["obi_pct"])
        self.assertIsNone(snap["rsi_1h"])

    def test_legacy_four_field_backfill_is_unchanged(self):
        """旧四字段补齐语义逐字保留（既有专测的契约不得漂移）。"""
        snap = self._snap()
        self.assertEqual(snap["adx"], 24.4)
        self.assertEqual(snap["funding_rate"], 0.0084)
        self.assertEqual(snap["composite_alpha_score"], 12.0)
        self.assertEqual(snap["smart_money_net"], "-1.1万 U")


if __name__ == "__main__":
    unittest.main()
