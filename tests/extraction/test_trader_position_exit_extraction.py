r"""position_exit 抽取对拍门（结构优化阶段 4·B3 第八十九刀）。

`manage_position_tp_and_trailing`（273 行）从 `scripts/ai_factor_trader.py`
**纯搬家**到 `scripts/trader/position_exit.py`（持仓机械退出：硬止损/三档棘轮/
时间止损/云端保护同步/平仓确认/台账）。

本门除常规三件外，用**硬止损分支**做端到端行为例：patch 门面的
`protection_signals` 强制命中 → 必须走 `close_position_confirmed`（平仓确认）
并落 `record_trade` 台账 —— 一次证明 3 项注入活在调用期解析。
（`record_trade`/`notify_trade_close` 在本例中一律替身，绝不写生产台账。）
"""
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "594b6fc"  # 本刀动工前最后提交（第八十八刀收口）
FN = "manage_position_tp_and_trailing"
INJ = ("_float_or_zero", "add_stop_cooldown", "build_signal_snapshot",
       "close_position_confirmed", "ensure_cloud_position_protection",
       "evaluate_asset_signal", "record_signal_snapshot", "record_trade",
       "sync_cloud_algo_stop", "venue_registry", "amend_venue_stop_loss",
       "ASSET_CLASS_PROFILES", "TAKER_FEE_RATE",
       "TIME_STOP_ATR_BAND", "TIME_STOP_HOURS", "_close_fee",
       "_close_trade_payload", "notify_trade_close", "protection_signals",
       "ratcheted_trailing_stop")


def _base_text() -> str:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/ai_factor_trader.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return r.stdout


def _get_func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name} 不在顶层")


def _body_dump(fn: ast.FunctionDef) -> str:
    return ast.dump(ast.Module(body=fn.body, type_ignores=[]), include_attributes=False)


class PositionExitVerbatimTest(unittest.TestCase):
    def test_shell_signature_and_injections(self):
        # ⚠️ 历史对拍已退役（2026-09-27）：原先这里把壳签名与**抽取前的提交**逐字比对，
        #    那部分价值在抽取合并那一刻已兑现，之后只是每次改动的税。
        #    留下的是**当前代码**的不变量：壳不得有 kw-only、必须转调子包、
        #    注入项必须都是门面全局（缺一个就会 NameError）。
        tree = ast.parse((ROOT / "scripts/ai_factor_trader.py").read_text(encoding="utf-8"))
        n = _get_func(tree, FN)
        self.assertFalse(n.args.kwonlyargs, "壳不应有 kw-only 注入")
        self.assertIn("_position_exit_manage", ast.unparse(n))
        facade = set(dir(__import__("scripts.ai_factor_trader", fromlist=["x"])))
        for g in INJ:
            self.assertIn(g, facade, f"{g} 不是门面全局 ⇒ 壳传参必 NameError")

    def test_hard_stop_branch_through_facade(self):
        """硬止损必须平仓确认 + 落台账（三项注入一起被证明活在调用期）。"""
        import scripts.ai_factor_trader as aft
        f = {"instId": "ETH-USDT-SWAP", "name": "ETH", "price": 2400.0, "atr": 20.0,
             "precision": 2, "ctVal": 0.1, "type": "crypto", "market_data_valid": True}
        curr_pos = {"pos": "2.0", "side": "long", "avgPx": "2500.0", "upl": -20.0}
        trackers: dict = {}
        actions: list = []
        closed_calls, trades, notices = [], [], []
        # ⚠️ 第八十九刀自伤修正：硬止损分支会调 `add_stop_cooldown`（写
        # `data/.stop_cooldown.json`）与 `record_signal_snapshot`（写
        # `data/signal_journal.json`）—— 不替身就会**真写生产**。
        # 离线套件把这类尝试记进 CONFIG_WRITE_ATTEMPTS 才暴露出来。
        with patch.object(aft, "protection_signals", lambda **k: True), \
             patch.object(aft, "close_position_confirmed",
                          lambda *a, **k: (closed_calls.append(a), (True, "ok"))[1]), \
             patch.object(aft, "record_trade", lambda *a, **k: trades.append(a)), \
             patch.object(aft, "add_stop_cooldown", lambda *a, **k: None), \
             patch.object(aft, "record_signal_snapshot", lambda *a, **k: None), \
             patch.object(aft, "notify_trade_close", lambda *a, **k: notices.append(a)):
            closed, reason = aft.manage_position_tp_and_trailing(
                f, curr_pos, trackers, "2026-09-07 10:00:00", actions)
        self.assertTrue(closed, f"硬止损必须判定已平仓，实际 {closed} / {reason}")
        self.assertEqual(len(closed_calls), 1, "没走 close_position_confirmed")
        self.assertEqual(closed_calls[0][0], "ETH-USDT-SWAP")
        self.assertEqual(len(trades), 1, "硬止损没有落台账")
        self.assertTrue(any("硬止损" in a for a in actions), f"动作流水缺硬止损: {actions}")

if __name__ == "__main__":
    unittest.main()
