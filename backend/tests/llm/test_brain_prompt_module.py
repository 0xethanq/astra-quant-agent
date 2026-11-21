"""全市场提示词装配（brain/prompt.py）收口 —— 第 307 刀。

本模块的 `construct_full_market_prompt` **设计上就不是被直接 import 调用的**：
模块全局里 `safe_float` / `active_profile` / `active_profile` 这些名字**一个都没有**
（实测 `NameError`），它靠函数内的 `_resolve("名", fallback)` 从**调用方注入的命名空间**
按名解析 —— 因为 `pin_baseline_risk_env()` 会**原地重载**门面，子模块 import 期绑定
会变成过期快照，而提示词里的风控口径与执行层不一致会让模型**按不存在的空间规划**。

所以本刀沿用既有隔离测试的配方（`tests.source_scan.find_function_node` 取节点 →
exec 进注入命名空间），但**只钉门面调用约定与三处降级**，渲染细节归 `test_prompt_rendering_isolated.py`。
"""
from __future__ import annotations

import ast
import json
import sys
import datetime
import os
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import scripts.evolution_shield as evolution_shield  # noqa: E402
import scripts.risk_constants as risk_constants  # noqa: E402
from scripts.brain import prompt as bp  # noqa: E402
from scripts.brain.prescreen import select_deep_analysis_packages  # noqa: E402
from tests import source_scan  # noqa: E402

_SRC = Path(bp.__file__).read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)
_CONSTRUCT_NODE = next(n for n in _TREE.body if isinstance(n, ast.FunctionDef))
_RESOLVE_NODE = next(n for n in ast.walk(_CONSTRUCT_NODE)
                     if isinstance(n, ast.FunctionDef) and n.name == "_resolve")


class ResolveContractTests(unittest.TestCase):
    """`_resolve` 的三段式：`_g` → `_fallback()` → **抛 KeyError**。

    钉它的理由写在源码注释里：本函数体会被 AST 抽取后**隔离 exec**，
    用裸下标 `_g["NAME"]` 会让"新增一个注入项"直接打挂隔离测试 ——
    而隔离测试本来就不该知道依赖清单。
    """

    def _resolve(self, **g):
        ns = {"_g": dict(g)}
        node = ast.Module(body=[_RESOLVE_NODE], type_ignores=[])
        ast.fix_missing_locations(node)
        exec(compile(node, bp.__file__, "exec"), ns)  # noqa: S102
        return ns["_resolve"]

    def test_resolves_from_injected_namespace(self):
        resolve = self._resolve(safe_float="FROM_NS")
        self.assertEqual(resolve("safe_float", lambda: "FROM_FALLBACK"), "FROM_NS")

    def test_falls_back_when_name_is_absent(self):
        resolve = self._resolve()
        self.assertEqual(resolve("safe_float", lambda: "FROM_FALLBACK"), "FROM_FALLBACK")

    def test_raises_key_error_when_neither_namespace_nor_fallback(self):
        resolve = self._resolve()
        with self.assertRaises(KeyError) as ctx:
            resolve("definitely_missing")
        # KeyError 的参数就是缺的名字本身（便于定位是哪个注入项漏了）
        self.assertEqual(ctx.exception.args[0], "definitely_missing")

    def test_falsy_namespace_value_still_wins(self):
        # 命中判定是 `in`，不是真值判断 —— 注入 0/None 也不许回落
        resolve = self._resolve(safe_float=0)
        self.assertEqual(resolve("safe_float", lambda: "FROM_FALLBACK"), 0)
        resolve_none = self._resolve(safe_float=None)
        self.assertIsNone(resolve_none("safe_float", lambda: "FROM_FALLBACK"))


class _PromptSandbox(unittest.TestCase):
    """按既有配方把 `construct_full_market_prompt` exec 进受控命名空间。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.news = self.root / "news.json"
        self.memory_md = self.root / "memory.md"
        self.memory_json = self.root / "memory.json"
        self.memory_text = "隔离心法"
        self.regime = {"summary_text": "REGIME_TEXT", "regime": "BULL_STABLE"}
        self.applied: list = []
        self.ns = self._namespace()
        self.construct = self._exec()

    def _namespace(self):
        ns = {
            "List": List, "Dict": Dict, "Any": Any,
            "datetime": datetime, "json": json, "os": os,
            "__version__": "9.9.9-sandbox",
            "safe_float": lambda v: float(v or 0),
            "active_profile": lambda: {"name": "沙盒策略"},
            "apply_module_layout": self._apply,
            "build_risk_budget_text": lambda usdt: f"BUDGET({usdt})",
            "_sl_atr_mult_for": lambda *a, **k: 1.5,
            "_xvenue_prompt_line": lambda *a, **k: "",
            "AI_MEMORY_MD_FILE": str(self.memory_md),
            "AI_MEMORY_FILE": str(self.memory_json),
            "NEWS_SENTIMENT_FILE": str(self.news),
            "detect_macro_market_regime": lambda pkgs: self.regime,
            "render_trading_memory": lambda md, js: self.memory_text,
        }
        ns.update({k: v for k, v in vars(risk_constants).items() if k.isupper()})
        return ns

    def _apply(self, template, profile, slot, title, context=None):
        self.applied.append({"slot": slot, "title": title, "context": context})
        return f"PROMPT[{template}]"

    def _exec(self):
        node = ast.Module(body=[_CONSTRUCT_NODE], type_ignores=[])
        ast.fix_missing_locations(node)
        exec(compile(node, bp.__file__, "exec"), self.ns)  # noqa: S102
        return self.ns["construct_full_market_prompt"]

    def _call(self, **kw):
        kw.setdefault("packages", [])
        # ⚠️ `render_trading_memory` 是**函数体内** `from scripts.evolution_shield import ...`
        #    ⇒ 命名空间里注入的那个会被**局部名遮蔽**。必须 patch 源模块属性，
        #    这也正是"局部 import 要用源模块打桩"那条老规矩的又一例。
        with patch.object(evolution_shield, "render_trading_memory",
                          lambda md, js: self.memory_text):
            return self.construct(**kw)

    def _write_news(self, payload):
        # 真实临时文件：`os.path.exists` 自然为真，不需要 patch 全局
        self.news.write_text(json.dumps(payload), encoding="utf-8")


class BalanceContextTests(_PromptSandbox, unittest.TestCase):
    """★ `None` 与 `0` 必须区分：缺上下文 ≠ 余额为零。"""

    def test_missing_balance_is_marked_not_zero(self):
        out = {}
        self._call(usdt_available=None, runtime_context_out=out)
        self.assertEqual(out["account_balance"], "【当前账户可用资金】: [MISSING_CONTEXT:account_balance]")

    def test_negative_balance_is_treated_as_missing(self):
        out = {}
        self._call(usdt_available=-1.0, runtime_context_out=out)
        self.assertIn("[MISSING_CONTEXT:account_balance]", out["account_balance"])

    def test_real_zero_is_rendered_as_zero(self):
        out = {}
        self._call(usdt_available=0.0, runtime_context_out=out)
        self.assertIn("0.00 USDT", out["account_balance"])
        self.assertNotIn("MISSING_CONTEXT", out["account_balance"])

    def test_missing_positions_default_is_explicit(self):
        out = {}
        self._call(runtime_context_out=out)
        self.assertIn("[MISSING_CONTEXT:account_positions]", out["account_positions"])


class NewsDegradationTests(_PromptSandbox, unittest.TestCase):
    """新闻是**外部输入**：坏掉必须降级成"无可验证新闻"，而不是崩或静默当无风险。"""

    def test_no_news_file_uses_the_explicit_no_input_text(self):
        out = {}
        self._call(runtime_context_out=out)
        self.assertIn("无可验证新闻输入", out["news_intelligence"])
        self.assertIn("中性平衡", out["news_intelligence"])

    def test_corrupt_news_json_is_swallowed_and_degrades(self):
        # ★ 走 `except Exception: pass` —— 解析失败不许把整条提示词链路打挂
        self.news.write_text("{ this is not json", encoding="utf-8")
        out = {}
        self._call(runtime_context_out=out)
        self.assertIn("无可验证新闻输入", out["news_intelligence"])
        self.assertIn("中性平衡", out["news_intelligence"])

    def test_valid_news_is_rendered_with_macro_tone(self):
        self._write_news({"macro_sentiment": "偏空", "latest_news": [
            {"time": "2026-01-01T00:00:00", "title": "T1", "summary": "S" * 200}]})
        out = {}
        self._call(runtime_context_out=out)
        self.assertIn("偏空", out["news_intelligence"])
        self.assertIn("T1", out["news_intelligence"])
        self.assertNotIn("无可验证新闻输入", out["news_intelligence"])

    def test_news_is_capped_at_six_items_and_summary_at_eighty_chars(self):
        self._write_news({"macro_sentiment": "中性", "latest_news": [
            {"time": f"t{i}", "title": f"T{i}", "summary": "X" * 200} for i in range(10)]})
        out = {}
        self._call(runtime_context_out=out)
        text = out["news_intelligence"]
        self.assertIn("T5", text)
        self.assertNotIn("T6", text)                 # 只取前 6 条
        self.assertIn("X" * 80 + "...", text)        # 摘要截断到 80 字
        self.assertNotIn("X" * 81, text)

    def test_missing_news_keys_fall_back_to_defaults(self):
        self._write_news({"latest_news": [{}]})
        out = {}
        self._call(runtime_context_out=out)
        self.assertIn("中性平衡", out["news_intelligence"])


class RetiredRegimeBlockIsGoneTests(_PromptSandbox, unittest.TestCase):
    """★ 2026-10 用户拍板：提示词里的【全市场宏观体制】块**已移除**。

    被移除的是**已退役数理系统**的输出（`scripts/calculus_engine` →
    `scripts/calculus/regime.py`），且它缺数据时会**凭空编结论**：函数内写死
    `atr_pct=1.5` / `adx=20.0` 兜底，而实盘 `calculus` 块早已完全不存在
    ⇒ 其"震荡/冲击"分是用**假零**算出来的，却以"当前全市场宏观体制为【X】｜
    主导方向=Y"的结论句进入提示词，还不在 P0–P3 证据分级里。

    本门是**正向钉子**：即便把那个引擎函数打桩成会返回内容，提示词也**不许**再出现它
    —— 防止有人"顺手"把退役接线接回去。
    """

    def test_retired_regime_engine_output_never_reaches_the_prompt(self):
        import types
        fake = types.ModuleType("calculus_engine")
        fake.detect_macro_market_regime = lambda pkgs: {"summary_text": "REGIME_TEXT"}
        with patch.dict(sys.modules, {"scripts.calculus_engine": fake, "calculus_engine": fake}):
            out = {}
            self._call(runtime_context_out=out)
        self.assertNotEqual(out.get("market_regime"), {"summary_text": "REGIME_TEXT"})
        self.assertNotIn("REGIME_TEXT", out["market_regime"])
        self.assertNotIn("REGIME_TEXT", out["market_matrix"])
        self.assertNotIn("市场体制自适应识别", out["market_matrix"])

    def test_market_regime_runtime_variable_is_an_empty_string(self):
        """插槽保留但恒为空：`market_matrix` 退化成"只有行情矩阵"（不留悬空换行）。"""
        out = {}
        self._call(runtime_context_out=out)
        self.assertEqual(out["market_regime"], "")
        self.assertNotIsInstance(out["market_regime"], dict)


class PolicySnapshotContextTests(_PromptSandbox, unittest.TestCase):
    """★ 策略快照回填：只在**真有**快照时才写，缺省不乱塞空字典。"""

    def test_snapshot_is_written_back_when_present(self):
        snapshot = {"policy_version": "v7.9.2", "policy_hash": "deadbeef"}
        out = {}
        self._call(runtime_context_out=out, policy_snapshot=snapshot)
        self.assertIs(out["policy_snapshot"], snapshot)
        self.assertEqual(out["policy_version"], "v7.9.2")
        self.assertEqual(out["policy_hash"], "deadbeef")

    def test_absent_snapshot_leaves_the_key_unset(self):
        out = {}
        self._call(runtime_context_out=out, policy_snapshot=None)
        self.assertNotIn("policy_snapshot", out)
        self.assertEqual(out["policy_hash"], "")

    def test_empty_snapshot_dict_is_falsy_so_key_is_still_unset(self):
        # ★ `if policy_snapshot:` 是**真值**判断 ⇒ `{}` 与 None 同待遇
        out = {}
        self._call(runtime_context_out=out, policy_snapshot={})
        self.assertNotIn("policy_snapshot", out)

    def test_none_runtime_context_out_is_tolerated(self):
        self.assertIsInstance(self._call(runtime_context_out=None), str)

    def test_policy_version_falls_back_to_system_version(self):
        out = {}
        self._call(runtime_context_out=out, policy_snapshot=None)
        self.assertEqual(out["policy_version"], "v9.9.9-sandbox")


class RuntimeVarsTests(_PromptSandbox, unittest.TestCase):
    def test_every_documented_slot_is_populated(self):
        out = {}
        self._call(runtime_context_out=out)
        for key in ("decision_timestamp", "account_balance", "risk_budget",
                    "account_positions", "pending_orders", "news_intelligence",
                    "trading_memory", "market_regime", "market_matrix",
                    "timestamp", "timezone", "active_instruments",
                    "strategy_version", "policy_version", "policy_hash", "profile_name"):
            self.assertIn(key, out, key)

    def test_memory_text_is_taken_from_the_injected_renderer(self):
        out = {}
        self._call(runtime_context_out=out)
        self.assertEqual(out["trading_memory"], self.memory_text)

    def test_timezone_is_asia_shanghai(self):
        out = {}
        self._call(runtime_context_out=out)
        self.assertEqual(out["timezone"], "Asia/Shanghai")

    @staticmethod
    def _pkg(**over):
        """宽松包：缺键返回 `""`（渲染器里 `p['name']` 是**硬下标**，缺键直接 KeyError）。"""
        import collections
        pkg = collections.defaultdict(str)
        pkg.update({"name": "BTC", "instId": "BTC-USDT-SWAP", "price": 100.0,
                    "chg24h": 1.5, "bidPx": 99.5, "askPx": 100.5,
                    "data_quality": "valid", "smart_money": {"available": False},
                    "calculus": {"valid": True}})
        pkg.update(over)
        return pkg

    def test_active_instruments_uses_name_then_inst_id(self):
        out = {}
        self._call(packages=[self._pkg(name="BTC", instId="I1"),
                             self._pkg(name="", instId="ETH-USDT-SWAP")],
                   runtime_context_out=out)
        self.assertEqual(out["active_instruments"], "BTC,ETH-USDT-SWAP")

    def test_empty_package_list_yields_empty_instrument_list(self):
        out = {}
        self._call(packages=[], runtime_context_out=out)
        self.assertEqual(out["active_instruments"], "")

    def test_package_rendering_requires_name_and_inst_id_keys(self):
        # 硬下标：空 dict 的包直接 KeyError（不是静默空串）。
        # （注意不能用 defaultdict —— 它会替缺键返回 ""，把这个性质掩盖掉）
        with self.assertRaises(KeyError):
            self._call(packages=[{}], runtime_context_out={})

    def test_market_matrix_does_not_prepend_any_regime_block(self):
        """★ 退役块移除后：矩阵**只有**行情矩阵本身，不许再前置任何体制结论。"""
        import types
        fake = types.ModuleType("calculus_engine")
        fake.detect_macro_market_regime = lambda pkgs: {"summary_text": "REG"}
        with patch.dict(sys.modules, {"scripts.calculus_engine": fake, "calculus_engine": fake}):
            out = {}
            self._call(runtime_context_out=out)
        self.assertFalse(out["market_matrix"].startswith("REG"))
        self.assertNotIn("REG", out["market_matrix"][:3])

    def test_layout_is_applied_with_the_profile_name(self):
        self._call()
        self.assertEqual(self.applied[0]["slot"], "trading_user")
        self.assertIn("沙盒策略", self.applied[0]["title"])

    def test_result_is_the_layout_output(self):
        self.assertTrue(self._call().startswith("PROMPT["))


class InjectionSurfaceTests(_PromptSandbox, unittest.TestCase):
    """★ 注入面必须"按名解析"：这些名字在**模块全局里一个都没有**。"""

    def test_module_globals_do_not_hold_the_injected_names(self):
        for name in ("safe_float", "_sl_atr_mult_for", "_xvenue_prompt_line",
                     "build_risk_budget_text", "active_profile", "apply_module_layout",
                     "AI_MEMORY_MD_FILE", "NEWS_SENTIMENT_FILE", "render_trading_memory"):
            self.assertFalse(hasattr(bp, name), name)

    def test_module_only_imports_the_narrow_stdlib_surface(self):
        imported = set()
        for node in _TREE.body:
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        # 模块自述："只依赖 json / urllib …"，此处实测为 datetime/json/os + typing
        self.assertEqual(imported, {"datetime", "json", "os", "typing"})

    def test_explicit_argument_beats_the_injected_namespace(self):
        # 门面显式传参时不许再去看命名空间
        out = {}
        self._call(usdt_available=123.45, runtime_context_out=out)
        self.assertIn("123.45 USDT", out["account_balance"])

    def test_build_risk_budget_text_receives_usdt_available(self):
        out = {}
        self._call(usdt_available=500.0, runtime_context_out=out)
        self.assertEqual(out["risk_budget"], "BUDGET(500.0)")


class ScreenedOutRenderingTests(_PromptSandbox):
    """2026-11 上下文漏斗：深度包只含候选；落选以紧凑观察池披露。"""

    @staticmethod
    def _pkg(**over):
        pkg = {"name": "BTC", "instId": "BTC-USDT-SWAP", "price": 100.0,
               "chg24h": 1.5, "bidPx": 99.5, "askPx": 100.5,
               "data_quality": "valid", "smart_money": {"available": False},
               "quant_factors": {"trend_momentum": {"macd_hist": 1.0}},
               "adx_1h": 25.0}
        pkg.update(over)
        return pkg

    ROW = {"instId": "ARB-USDT-SWAP", "name": "ARB", "score": 10.0,
           "signal": "WAIT", "rank": 6,
           "reason": "未进入 Top 5 候选（评分 10.0）"}

    def _all_pool(self):
        return [self._pkg(), self._pkg(name="ARB", instId="ARB-USDT-SWAP",
                                       chg24h=-0.5, data_quality="valid")]

    def test_only_deep_packages_get_the_full_tier_matrix(self):
        out = {}
        self._call(packages=[self._pkg()], all_packages=self._all_pool(),
                   screened_out=[dict(self.ROW)],
                   prescreen_meta={"candidate_limit": 5, "pool_size": 2},
                   runtime_context_out=out)
        matrix = out["market_matrix"]
        self.assertIn("【预筛落选观察池 · 未进入本轮深度分析】", matrix)
        self.assertIn("- ARB (ARB-USDT-SWAP) | 评分=10.0 | 信号=WAIT "
                      "| 24H=-0.5% | 数据质量=valid", matrix)
        self.assertIn("宿主已对全部 2 个标的做确定性评分", matrix)
        self.assertIn("不得臆测", matrix)
        self.assertEqual(matrix.count("T0 衍生品博弈"), 1,
                         "落选标的不得注入完整七梯队矩阵")
        self.assertNotIn("【ARB (ARB-USDT-SWAP)】", matrix)

    def test_empty_screened_out_list_renders_no_watchlist(self):
        out = {}
        self._call(packages=[self._pkg()], screened_out=[],
                   runtime_context_out=out)
        self.assertNotIn("预筛落选观察池", out["market_matrix"])

    def test_prescreen_unavailable_is_disclosed(self):
        out = {}
        self._call(packages=[self._pkg()], screened_out=[],
                   prescreen_meta={"prescreen_unavailable": True,
                                   "reason": "positions_unreadable"},
                   runtime_context_out=out)
        self.assertIn("本轮预筛降级（positions_unreadable）", out["market_matrix"])
        self.assertIn("不构成落选", out["market_matrix"])

    def test_missing_score_degradation_is_disclosed(self):
        out = {}
        self._call(packages=[self._pkg()], screened_out=[],
                   prescreen_meta={"degraded": True,
                                   "missing_score_inst_ids": ["SUI-USDT-SWAP"]},
                   runtime_context_out=out)
        self.assertIn("缺分标的已全部并入深度分析", out["market_matrix"])
        self.assertIn("SUI-USDT-SWAP", out["market_matrix"])
        self.assertIn("缺分不等于落选", out["market_matrix"])

    def test_active_instruments_still_lists_the_whole_pool(self):
        out = {}
        self._call(packages=[self._pkg()], all_packages=self._all_pool(),
                   screened_out=[dict(self.ROW)], runtime_context_out=out)
        self.assertEqual(out["active_instruments"], "BTC,ARB")

    def test_legacy_call_renders_no_funnel_dressing(self):
        out = {}
        self._call(packages=[self._pkg()], runtime_context_out=out)
        self.assertNotIn("预筛落选观察池", out["market_matrix"])
        self.assertNotIn("本轮预筛降级", out["market_matrix"])
        self.assertEqual(out["active_instruments"], "BTC")

    def test_funnel_matrix_is_at_least_forty_percent_smaller(self):
        """R9：11 标的、Top 5 时，全标的矩阵字符数必须下降 ≥ 40%。"""
        names = ["ARB", "BTC", "DOGE", "ETH", "SOL", "XRP",
                 "SUI", "AVAX", "LINK", "OP", "BNB"]
        pool = []
        for index, name in enumerate(names):
            pkg = self._pkg(name=name, instId=f"{name}-USDT-SWAP")
            pkg["factor_ranking"] = {"composite_alpha_score": float(index),
                                     "signal_recommendation": "WAIT"}
            pool.append(pkg)
        pre = select_deep_analysis_packages(pool, limit=5)
        self.assertEqual(len(pre["deep_packages"]), 5)
        self.assertEqual(len(pre["screened_out"]), 6)

        full_ctx, funnel_ctx = {}, {}
        self._call(packages=pool, runtime_context_out=full_ctx)
        self._call(packages=pre["deep_packages"], all_packages=pool,
                   screened_out=pre["screened_out"], prescreen_meta=pre["meta"],
                   runtime_context_out=funnel_ctx)
        full_len = len(full_ctx["market_matrix"])
        funnel_len = len(funnel_ctx["market_matrix"])
        self.assertGreater(full_len, 5000, "全量矩阵过短 ⇒ 本用例会空转")
        self.assertLess(funnel_len, full_len * 0.6,
                        f"矩阵压缩不足 40%：full={full_len} funnel={funnel_len}")


if __name__ == "__main__":
    unittest.main()
