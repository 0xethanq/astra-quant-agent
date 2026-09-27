r"""routing_policy 抽取对拍门（结构优化阶段 4·B3 第八十七刀）。

八函数（219 行：load_routing_mode / load_preferred_venue /
portfolio_risk_budget_usdt / estimate_margin_usdt / _decision_payload /
_rejection_focus_reason / portfolio_budget_guard / route_and_reserve_signal）
从 `scripts/ai_factor_trader.py` **纯搬家**到 `scripts/trader/routing_policy.py`。

- 本刀注入面最宽（route 一个函数 14 项）；同名注入 ⇒ body AST 零例外全等。
- **壳签名必须与基线逐字相同**（本刀教训：手写壳签名把
  `_decision_payload(decision, preferred)` 写成单参，18 个用例报错；
  门里因此加"位置参数=基线"断言，钉死这类手写事故）。
- 路由主流程的行为证明由既有 `tests/venues/test_venue_wiring.py`（40 例，
  全程 patch 门面全局驱动路由）承担，本门另钉四个小函数的注入面。
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "7ef5e53"  # 本刀动工前最后提交（第八十六刀收口）
FNS = ("load_routing_mode", "load_preferred_venue", "portfolio_risk_budget_usdt",
       "estimate_margin_usdt", "_decision_payload", "_rejection_focus_reason",
       "portfolio_budget_guard", "route_and_reserve_signal")
INJ = {
    "load_routing_mode": ("routing_policy",),
    "load_preferred_venue": ("routing_policy",),
    "portfolio_risk_budget_usdt": ("PORTFOLIO_RISK_BUDGET_ENV",),
    "estimate_margin_usdt": (),
    "_decision_payload": (),
    "_rejection_focus_reason": (),
    "portfolio_budget_guard": (),
    "route_and_reserve_signal": ("_decision_payload", "_rejection_focus_reason",
                                 "build_venue_candidates", "estimate_margin_usdt",
                                 "load_preferred_venue", "load_routing_mode",
                                 "persist_venue_decision", "portfolio_budget_guard",
                                 "portfolio_risk_budget_usdt", "reservation_manager",
                                 "VENUE_SUBMITTERS", "current_environment",
                                 "risk_reservation", "venue_router"),
}


def _base_text() -> str:
    """基线源码，**已归一命名空间**（r20_* → astra_*）；见 `rename_baseline`。"""
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/ai_factor_trader.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return normalize(r.stdout)


def _get_func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name} 不在顶层")


def _body_dump(fn: ast.FunctionDef) -> str:
    return ast.dump(ast.Module(body=fn.body, type_ignores=[]), include_attributes=False)


class RoutingPolicyVerbatimTest(unittest.TestCase):
    def test_shell_signatures_and_injections(self):
        """壳必须：①无 kw-only ②必须转调子包 ③注入项全是门面全局。

        ⚠️ 历史对拍已退役（2026-09-27）：原先还有一条「签名 = 抽取前基线逐字」，
        价值在抽取合并时已兑现，之后只对每次改动收税。
        """
        tree = ast.parse((ROOT / "scripts/ai_factor_trader.py").read_text(encoding="utf-8"))
        facade = set(dir(__import__("scripts.ai_factor_trader", fromlist=["x"])))
        for fn in FNS:
            with self.subTest(fn=fn):
                n = _get_func(tree, fn)
                self.assertFalse(n.args.kwonlyargs, f"{fn} 壳不应有 kw-only 注入")
                self.assertIn("_routing_policy_", ast.unparse(n), "壳没转调子包")
                for g in INJ[fn]:
                    self.assertIn(g, facade, f"{g} 不是门面全局 ⇒ 壳传参必 NameError")

    def test_module_injection_is_live(self):
        """patch 门面 `routing_policy` 模块对象必须改变经壳行为。"""
        import scripts.ai_factor_trader as aft
        stub = types.SimpleNamespace(load_preferred_venue=lambda: "gate-locked",
                                     load_routing_mode=lambda: "locked")
        with patch.object(aft, "routing_policy", stub):
            self.assertEqual(aft.load_preferred_venue(), "gate-locked")
            self.assertEqual(aft.load_routing_mode(), "locked")

    def test_constant_injection_and_pure_semantics(self):
        """patch 门面常量名 + 环境变量必须改变预算读取；两个纯函数语义不变。"""
        import scripts.ai_factor_trader as aft
        with patch.object(aft, "PORTFOLIO_RISK_BUDGET_ENV", "ASTRA_TEST_BUDGET_ONLY"), \
             patch.dict(os.environ, {"ASTRA_TEST_BUDGET_ONLY": "777.5"}, clear=False):
            self.assertEqual(aft.portfolio_risk_budget_usdt(), 777.5)
        # 0 = 不限（既有语义）
        self.assertIsNone(aft.portfolio_budget_guard(0.0, 9999.0, 500.0))
        self.assertIsNotNone(aft.portfolio_budget_guard(1000.0, 700.0, 400.0, "demo"))
        # 保证金估算：无 margin 时按 3x 折算
        self.assertEqual(aft.estimate_margin_usdt(300.0), 100.0)
        self.assertEqual(aft.estimate_margin_usdt(300.0, 50.0), 50.0)

if __name__ == "__main__":
    unittest.main()
