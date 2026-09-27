r"""台账合并 / 平仓行装配抽取对拍门（第一百零三刀）。

从 `scripts/sync_full_ledger.py::build_lifecycle_ledger` 搬出一段**零注入面纯计算**到
`scripts/ledger/merge.py`：`merge_lifecycle_trades`（聚合去重合并）。

## 行为例钉的是两条**生产事故换来的**规则

**D8 迁移去重**：`posId` 换键首跑时，同一笔持仓新旧行 id 不同会**并存双计**；
但"窗口外无法再生的旧行"**一律不动** —— 后半句是防误删的安全边界，本门专钉。

## 为什么**没有**把平仓行循环也搬走（一次被既有门拦下的越界）

本刀曾同时抽出 `plan_closed_position_rows`（同 posId 唯一身份循环），但既有门
`test_ledger_okx_history_extraction::test_cross_row_sequence_state_stays_in_facade`
明确钉住"`_pos_id_seen` 是**跨行**状态，必须留在门面循环里"（上一轮成文决定：
交叉行状态属于循环，不属于单行翻译）。**已按该决定撤销**，只保留零注入面的合并段。

基线：`2e52131`（本刀动工前最后提交）。
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import sys
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "2e52131"
FACADE = ROOT / "scripts" / "sync_full_ledger.py"
OWNER = "build_lifecycle_ledger"
SPECS = {"merge_lifecycle_trades": (32, 37, "trades_map")}   # helper -> (下标, 特征标记)
MODS = {"merge_lifecycle_trades": ROOT / "scripts" / "ledger" / "merge.py"}


def _baseline_fn() -> ast.FunctionDef:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/sync_full_ledger.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return next(n for n in ast.parse(normalize(r.stdout)).body
                if isinstance(n, ast.FunctionDef) and n.name == OWNER)


def _impl(name: str) -> ast.FunctionDef:
    t = ast.parse(MODS[name].read_text(encoding="utf-8"))
    return next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _facade_calls() -> dict:
    out = {}
    for n in ast.walk(ast.parse(FACADE.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in SPECS:
            out.setdefault(n.func.id, n)
    return out


def _body_without_docstring(fn: ast.FunctionDef):
    body = list(fn.body)
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    return body


class LedgerExtractionTest(unittest.TestCase):
    def _baseline_segment(self, name: str):
        lo, hi, marker = SPECS[name]
        seg = _baseline_fn().body[lo:hi + 1]
        text = "\n".join(ast.unparse(s) for s in seg)
        self.assertIn(marker, text, f"基线语句 {lo}..{hi} 不是预期的 {name} 段（标记 {marker} 缺失）")
        return seg

    def test_calls_pass_every_parameter_once_same_name(self):
        calls = _facade_calls()
        for name in SPECS:
            with self.subTest(fn=name):
                params = [a.arg for a in _impl(name).args.kwonlyargs]
                call = calls[name]
                self.assertEqual(call.args, [])
                self.assertEqual([k.arg for k in call.keywords], params)
                for k in call.keywords:
                    self.assertEqual(ast.unparse(k.value), k.arg)

    def test_no_undeclared_free_names(self):
        for name in SPECS:
            with self.subTest(fn=name):
                module = ast.parse(MODS[name].read_text(encoding="utf-8"))
                mod_names = {n.name for n in module.body if isinstance(n, ast.FunctionDef)}
                fn = _impl(name)
                local = {a.arg for a in fn.args.kwonlyargs}
                for n in ast.walk(fn):
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        local.add(n.name); local |= {a.arg for a in n.args.args}
                    if isinstance(n, ast.comprehension):
                        tg = n.target
                        for e in (tg.elts if isinstance(tg, (ast.Tuple, ast.List)) else [tg]):
                            if isinstance(e, ast.Name):
                                local.add(e.id)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                        local.add(n.id)
                    if isinstance(n, ast.ExceptHandler) and n.name:
                        local.add(n.name)
                    if isinstance(n, (ast.Import, ast.ImportFrom)):
                        for a in n.names:
                            local.add(a.asname or a.name.split(".")[0])
                reads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
                         and isinstance(n.ctx, ast.Load)}
                missing = sorted(reads - local - set(dir(builtins)) - mod_names)
                self.assertEqual(missing, [], f"{name} 解析不到: {missing}")

    # ---------- 行为例：合并去重 ----------

    def test_merge_overlays_new_rows_over_old_same_id(self):
        from scripts.ledger.merge import merge_lifecycle_trades
        got = merge_lifecycle_trades(
            binance_trades=[{"id": "b1", "venue": "binance"}],
            gate_trades=[{"id": "g1", "venue": "gate"}],
            old_trades=[{"id": "old1", "venue": "okx"}, {"id": "b1", "venue": "stale"}],
            trades_lifecycle=[{"id": "new1", "venue": "okx"}])
        self.assertEqual(sorted(got), ["b1", "g1", "new1", "old1"])
        self.assertEqual(got["b1"]["venue"], "binance", "同 id 必须由新行覆盖旧行")

    def test_d8_migration_drops_colliding_legacy_row_but_keeps_untouched_ones(self):
        """D8：撞键的旧键行让位；**窗口外无法再生的旧行一律不动**（防迁移误删）。"""
        from scripts.ledger.merge import merge_lifecycle_trades
        colliding = {"id": "pos_hist_P1_BTC", "venue": "okx", "inst": "BTC-USDT-SWAP",
                     "open_time": "100", "close_time": "200"}
        untouched = {"id": "pos_hist_P9_ETH", "venue": "okx", "inst": "ETH-USDT-SWAP",
                     "open_time": "1", "close_time": "2"}
        regenerated = dict(colliding, id="pos_hist_P1_BTC_100")
        got = merge_lifecycle_trades(binance_trades=[], gate_trades=[],
                                     old_trades=[colliding, untouched],
                                     trades_lifecycle=[regenerated])
        self.assertNotIn("pos_hist_P1_BTC", got, "撞键的旧键行必须让位（否则双计）")
        self.assertIn("pos_hist_P9_ETH", got, "窗口外旧行**不得**被删（安全边界）")
        self.assertIn("pos_hist_P1_BTC_100", got)

    def test_d8_pass_only_touches_pos_hist_rows(self):
        from scripts.ledger.merge import merge_lifecycle_trades
        old_other = {"id": "pos_legacy_1", "venue": "okx", "inst": "X",
                     "open_time": "5", "close_time": "6"}
        new = {"id": "n1", "venue": "okx", "inst": "X", "open_time": "5", "close_time": "6"}
        got = merge_lifecycle_trades(binance_trades=[], gate_trades=[],
                                     old_trades=[old_other], trades_lifecycle=[new])
        self.assertIn("pos_legacy_1", got, "非 pos_hist_ 前缀的旧行不受 D8 清理影响")

if __name__ == "__main__":
    unittest.main()
