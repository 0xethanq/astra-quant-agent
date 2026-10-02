"""B3（交易员侧第十七块）`scripts/trader/cycle_snapshot.py` 的抽取回归。

## 这个测试在守什么

`cycle_snapshot.py` 现存两段**纯装配**：

1. `build_state_payload` —— 面板/巡检读取的 17 字段快照。
   字段名或四舍五入精度错一个，面板就显示错。
2. `venue_position_span` —— 巡检通知与 AI 提示词共用的「持仓构成」一行。
   OKX 专用化后系统只有一个场所，故只报 OKX —— 但那是**真实全量**，
   不再是旧实现的"跨所拉不到 ⇒ 漏报另两所"。

## 已随多所执行面拆除（本文件不再覆盖）

- `collect_pending_inst_ids`（外所挂单枚举与去重计数）—— 外所挂单不存在了，
  枚举归零；
- `broken_execution_venues`（执行闸开着却不可就绪的外所）—— 同一原因。

历史外所行只做**只读容错**：这些行不会进配额与敞口，相关判据不在本模块。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from scripts.trader import cycle_snapshot

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "ai_factor_trader.py"
SUBMODULE = ROOT / "scripts" / "trader" / "cycle_snapshot.py"


class BuildStatePayloadTest(unittest.TestCase):
    def _factor(self, **over):
        f = dict(name="BTC", instId="BTC-USDT-SWAP", type="swap", price=79000.0,
                 rsi=55.123, rsi_7=51.987, vwap_bias=0.4567, macd_hist=1.5,
                 macd_accel=0.25, obv_flow="INFLOW", bb_bandwidth=0.03,
                 vol_ratio=1.8, market_regime="TREND", structure_1h="BULL",
                 trend_1h_bullish=True, position=1)
        f.update(over)
        return f

    def _build(self, factors=None, **over):
        kw = dict(timestamp_full="2026-09-14 12:00:00", active_pos_count=2,
                  max_positions=8, long_count=1, short_count=1, cb_active=False,
                  cb_reason="", executed_actions=["a1"], all_factors=factors or [],
                  evaluate_asset_signal=lambda f: (88.5, "BUY_LONG", ["r"], "T", "D"))
        kw.update(over)
        return cycle_snapshot.build_state_payload(**kw)

    def test_top_level_fields(self):
        p = self._build()
        self.assertEqual(p["timestamp"], "2026-09-14 12:00:00")
        self.assertEqual(p["active_positions_count"], 2)
        self.assertEqual(p["max_positions"], 8)
        self.assertEqual(p["long_count"], 1)
        self.assertEqual(p["short_count"], 1)
        self.assertEqual(p["circuit_breaker"], {"active": False, "reason": ""})
        self.assertEqual(p["executed_actions"], ["a1"])
        self.assertEqual(p["instruments"], [])

    def test_field_order_is_stable(self):
        """键顺序即 `json.dump` 的输出顺序 —— 面板 diff / 人工比对都依赖它。"""
        p = self._build()
        self.assertEqual(list(p.keys()), [
            "timestamp", "active_positions_count", "max_positions", "long_count",
            "short_count", "circuit_breaker", "executed_actions", "instruments"])

    def test_instrument_field_order_and_precision(self):
        p = self._build(factors=[self._factor()])
        inst = p["instruments"][0]
        self.assertEqual(list(inst.keys()), [
            "name", "instId", "type", "price", "rsi", "rsi_7", "vwap_bias",
            "macd_hist", "macd_accel", "obv_flow", "bb_bandwidth", "vol_ratio",
            "market_regime", "structure_1h", "trend_1h", "trend_4h",
            "score", "action", "strategy", "desc", "position"])
        self.assertEqual(inst["rsi"], 55.1, "rsi 必须 round 到 1 位")
        self.assertEqual(inst["rsi_7"], 52.0, "rsi_7 必须 round 到 1 位")
        self.assertEqual(inst["vwap_bias"], 0.46, "vwap_bias 必须 round 到 2 位")

    def test_trend_labels_come_from_boolean_flags(self):
        p = self._build(factors=[self._factor(trend_1h_bullish=True,
                                              trend_4h_bullish=False)])
        self.assertEqual(p["instruments"][0]["trend_1h"], "多头")
        self.assertEqual(p["instruments"][0]["trend_4h"], "空头")

    def test_missing_optional_fields_are_explicitly_missing(self):
        """★ 2026-10「不许假数据」：可选字段缺失 ⇒ **显式缺失**，不再回填
        `50.0 / 0.0 / 1.0 / NEUTRAL / CHOP / 空头`。

        这些值会写进 `trading_state.json` 供看板展示 —— 旧断言把"没取到"钉成了
        "RSI 中性、量能正常、区间震荡、趋势空头"这类**结论**。
        """
        bare = dict(name="X", instId="X-USDT-SWAP", type="swap", price=1.0,
                    rsi=50.0, position=0)
        p = self._build(factors=[bare])
        inst = p["instruments"][0]
        self.assertIsNone(inst["rsi_7"])
        self.assertIsNone(inst["vwap_bias"])
        self.assertIsNone(inst["macd_hist"])
        self.assertIsNone(inst["macd_accel"])
        self.assertEqual(inst["obv_flow"], "--")
        self.assertIsNone(inst["bb_bandwidth"])
        self.assertIsNone(inst["vol_ratio"])
        self.assertEqual(inst["market_regime"], "--")
        self.assertEqual(inst["structure_1h"], "--")
        self.assertEqual(inst["trend_1h"], "--")     # 未知：不再默认显示"空头"
        self.assertEqual(inst["trend_4h"], "--")
        # 有值的字段照旧原样透传（缺失语义不能吃掉正常路径）
        self.assertEqual(inst["rsi"], 50.0)

    def test_signal_evaluator_is_called_once_per_factor(self):
        calls = []

        def ev(f):
            calls.append(f["name"])
            return (1.0, "HOLD", [], "T", "D")

        p = self._build(factors=[self._factor(name="A"), self._factor(name="B")],
                        evaluate_asset_signal=ev)
        self.assertEqual(calls, ["A", "B"])
        self.assertEqual(len(p["instruments"]), 2)
        self.assertEqual(p["instruments"][0]["score"], 1.0)
        self.assertEqual(p["instruments"][0]["action"], "HOLD")

    def test_reasons_is_dropped_from_payload(self):
        """`reasons` 参与了求值但**不**进快照 —— 原实现如此，别顺手加。"""
        p = self._build(factors=[self._factor()])
        self.assertNotIn("reasons", p["instruments"][0])


class VenuePositionSpanTest(unittest.TestCase):
    """「持仓构成」一行（OKX 专用）—— 巡检通知与 AI 提示词共用同一口径。

    口径错一个数字，通知与喂给主脑的持仓全景就会说谎；而这两处此前各自
    写死过场所，正是"同一语义两处写"的成因。故逐字钉住渲染结果。
    """

    def test_span_reports_okx_only(self):
        self.assertEqual(
            cycle_snapshot.venue_position_span(
                okx_count=7, okx_long=4, okx_short=3, max_positions=9),
            "持仓 7/9 (多4/空3)｜okx 7")

    def test_span_on_empty_book(self):
        self.assertEqual(
            cycle_snapshot.venue_position_span(
                okx_count=0, okx_long=0, okx_short=0, max_positions=8),
            "持仓 0/8 (多0/空0)｜okx 0")

    def test_span_casts_counts_to_int(self):
        self.assertEqual(
            cycle_snapshot.venue_position_span(
                okx_count="3", okx_long=1.9, okx_short=0, max_positions=6),
            "持仓 3/6 (多1/空0)｜okx 3")


class WiringTest(unittest.TestCase):
    def test_impl_lives_in_submodule_not_facade(self):
        facade = FACADE.read_text(encoding="utf-8")
        sub = SUBMODULE.read_text(encoding="utf-8")
        for fn in ("build_state_payload", "venue_position_span"):
            self.assertIn(f"def {fn}(", sub)
            self.assertNotIn(f"def {fn}(", facade)

    def test_old_venue_loop_is_gone_from_facade(self):
        facade = FACADE.read_text(encoding="utf-8")
        self.assertNotIn('for _gv in ("gate", "binance")', facade)
        self.assertNotIn('_gv_mode and venue_registry.execution_open', facade)

    def test_facade_keeps_the_reserved_count_arithmetic(self):
        """预占槽位算式 —— 它是"能不能再开仓"的直接依据，必须一眼可见。

        ⚠️ 第九十二刀：该算式随相位 1 整体搬入 `scripts/trader/cycle_stages.py`
        （`fetch_positions_and_reconcile` 段体 AST 逐字）。判定对象随实现迁移，
        并加反证：门面不得残留副本（残留=孪生）。
        """
        stages = (ROOT / "scripts" / "trader" / "cycle_stages.py").read_text(encoding="utf-8")
        facade = FACADE.read_text(encoding="utf-8")
        for line in ("reserved_slot_count = active_pos_count + len(pending_inst_ids)",
                     "reserved_long_count = long_count + pending_long_count",
                     "reserved_short_count = short_count + pending_short_count"):
            self.assertIn(line, stages, f"cycle_stages 缺 {line!r}")
            self.assertNotIn(line, facade, "门面残留该算式 ⇒ 出现孪生")

    def test_facade_keeps_the_atomic_write(self):
        """原子写（异常语义"照旧上抛"，属控制流不属装配）。

        ⚠️ 第九十一刀：该行随相位 5 整体搬入 `cycle_stages.py`
        （异常照旧上抛的语义未变：段体 AST 逐字）。判定对象随实现迁移，
        并加反证 —— 它不该出现在 `cycle_snapshot.py`（那是纯装配模块）。
        """
        stages = (ROOT / "scripts" / "trader" / "cycle_stages.py").read_text(encoding="utf-8")
        self.assertIn('_atomic_write_json(os.path.join(DATA_DIR, "trading_state.json")',
                      stages)
        self.assertNotIn("_atomic_write_json", SUBMODULE.read_text(encoding="utf-8"))

    def test_every_call_site_defines_every_name_it_passes(self):
        """路径感知判据：只沿到达该调用的唯一路径收集定义。

        OKX 专用化后两处调用**同在** `cycle_stages.py`：
        `build_state_payload` 与 `venue_position_span` 在
        `persist_state_and_sync_ledger`，`venue_position_span` 另在
        `scan_risk_gates_and_ai_brain`。判据分别在其**所属**函数内跑
        （路径感知：只看到达该调用的那条路径）。
        """
        from tests.source_scan import names_defined_at_call

        targets = ("build_state_payload", "venue_position_span")
        stages_tree = ast.parse(
            (ROOT / "scripts" / "trader" / "cycle_stages.py").read_text(encoding="utf-8"))
        plans = [(stages_tree, next(n for n in ast.walk(stages_tree)
                                    if isinstance(n, ast.FunctionDef)
                                    and n.name == "persist_state_and_sync_ledger")),
                 (stages_tree, next(n for n in ast.walk(stages_tree)
                                    if isinstance(n, ast.FunctionDef)
                                    and n.name == "scan_risk_gates_and_ai_brain"))]

        checked = 0
        work = []
        for tr, fn in plans:
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in targets):
                    work.append((tr, fn, node))
        for tree, func, node in work:
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in targets):
                continue
            passed = set()
            for arg in node.args:
                for nm in ast.walk(arg):
                    if isinstance(nm, ast.Name):
                        passed.add(nm.id)
            for kw in node.keywords:
                for nm in ast.walk(kw.value):
                    if isinstance(nm, ast.Name):
                        passed.add(nm.id)
            available = names_defined_at_call(func, node, module_tree=tree)
            missing = sorted(n for n in passed if n not in available)
            self.assertEqual(missing, [],
                             f"{node.func.id} 调用（L{node.lineno}）引用了未定义的名字 "
                             f"{missing}；实盘会 NameError")
            checked += 1
        self.assertEqual(checked, 3, f"应有 3 处调用，实际 {checked}")


if __name__ == "__main__":
    unittest.main()
