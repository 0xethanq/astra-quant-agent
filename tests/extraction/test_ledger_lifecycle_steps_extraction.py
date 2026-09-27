r"""`build_lifecycle_ledger` 两个步骤抽取对拍门（第一百一十刀）。

`scripts/sync_full_ledger.py::build_lifecycle_ledger`（209 行，全仓最大）里两段：
- **批E·幽灵持仓清理** → `scripts/ledger/holdings.py::purge_stale_holding_rows`；
- **新平仓 QQ 通知** → `scripts/ledger/notify.py::notify_newly_closed_trades`（新文件）。

## 本门钉的安全规则（幽灵清理，审计批E）

旧实现"只按 id 覆盖新行、从不删除失效行" ⇒ 平仓后 holding 行**永久留存**
（实测 `holding_ALGO_多` 标 venue=okx 而 OKX 已零持仓，前台挂着不存在的仓）。
修法两条**必须同时成立**：
1. 只在**本轮成功取数的场所**（`_queried_venues`）里清理；
2. **取数失败的场所保守保留旧行** —— "缺失 ≠ 已平仓"，绝不能用一次失败抹掉真实持仓。

第二条是本门存在的意义：把"保守保留"写成断言，防止后人图省事改成全量清理。

基线：`879702f`（本刀动工前最后提交）。
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import sys
import types
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "879702f"
FACADE = ROOT / "scripts" / "sync_full_ledger.py"
HOLDINGS = ROOT / "scripts" / "ledger" / "holdings.py"
NOTIFY = ROOT / "scripts" / "ledger" / "notify.py"
OWNER = "build_lifecycle_ledger"
SPECS = {"purge_stale_holding_rows": (33, 35), "notify_newly_closed_trades": (41, 41)}


def _module_of(name: str) -> Path:
    return HOLDINGS if name == "purge_stale_holding_rows" else NOTIFY


def _baseline_fn() -> ast.FunctionDef:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/sync_full_ledger.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return next(n for n in ast.parse(normalize(r.stdout)).body
                if isinstance(n, ast.FunctionDef) and n.name == OWNER)


def _impl(name: str) -> ast.FunctionDef:
    t = ast.parse(_module_of(name).read_text(encoding="utf-8"))
    return next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _facade_calls() -> dict:
    out = {}
    for n in ast.walk(ast.parse(FACADE.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in SPECS:
            out.setdefault(n.func.id, n)
    return out


class LedgerLifecycleStepsTest(unittest.TestCase):
    def test_call_sites_shape(self):
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
                mod = ast.parse(_module_of(name).read_text(encoding="utf-8"))
                mod_names = {n.name for n in mod.body if isinstance(n, ast.FunctionDef)}
                fn = _impl(name)
                local = {a.arg for a in fn.args.kwonlyargs}
                for n in ast.walk(fn):
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

    # ---------- 行为例：幽灵清理 ----------

    def _purge(self, trades_map, holding_rows, queried):
        from scripts.ledger.holdings import purge_stale_holding_rows
        return purge_stale_holding_rows(_holding_rows=holding_rows,
                                        _queried_venues=queried, trades_map=trades_map)

    def test_purges_ghost_holding_in_queried_venue(self):
        live = [{"id": "holding_okx_BTC_多"}]
        trades = {"holding_okx_BTC_多": {"id": "holding_okx_BTC_多", "status": "holding", "venue": "okx"},
                  "holding_okx_ALGO_多": {"id": "holding_okx_ALGO_多", "status": "holding", "venue": "okx"}}
        purged = self._purge(trades, live, {"okx"})
        self.assertEqual(purged, ["holding_okx_ALGO_多"], "已零持仓的幽灵行必须消失")
        self.assertNotIn("holding_okx_ALGO_多", trades, "必须真的 pop 出字典")
        self.assertIn("holding_okx_BTC_多", trades)

    def test_failed_venue_is_kept_conservatively(self):
        """**取数失败 ≠ 已平仓**：不在本轮成功场所里的 holding 行保守保留。"""
        trades = {"holding_gate_ETH_空": {"id": "holding_gate_ETH_空", "status": "holding", "venue": "gate"}}
        purged = self._purge(trades, [], {"okx", "binance"})
        self.assertEqual(purged, [])
        self.assertIn("holding_gate_ETH_空", trades, "gate 取数失败时不得抹掉其持仓行")

    def test_closed_rows_are_never_touched(self):
        trades = {"t1": {"id": "t1", "status": "closed", "venue": "okx"}}
        self.assertEqual(self._purge(trades, [], {"okx"}), [])
        self.assertIn("t1", trades)

    def test_venue_match_is_case_insensitive(self):
        trades = {"h": {"id": "h", "status": "holding", "venue": "OKX"}}
        self.assertEqual(self._purge(trades, [], {"okx"}), ["h"], "venue 比较要小写归一")

    # ---------- 行为例：新平仓通知 ----------

    def _notify(self, fake):
        from scripts.ledger.notify import notify_newly_closed_trades
        old = sys.modules.get("qq_notifier")
        sys.modules["qq_notifier"] = fake
        try:
            notify_newly_closed_trades(binance_trades=[], existing_closed_ids={"old-1"},
                                       gate_trades=[], trades_lifecycle=[])
        finally:
            if old is None:
                sys.modules.pop("qq_notifier", None)
            else:
                sys.modules["qq_notifier"] = old

    def test_only_newly_closed_are_notified(self):
        calls = []
        from scripts.ledger.notify import notify_newly_closed_trades
        fake = types.SimpleNamespace(notify_trade_close=lambda **kw: calls.append(kw))
        old = sys.modules.get("qq_notifier")
        sys.modules["qq_notifier"] = fake
        try:
            notify_newly_closed_trades(
                binance_trades=[{"id": "old-1", "status": "closed"}],
                existing_closed_ids={"old-1"},
                gate_trades=[{"id": "new-2", "status": "closed", "inst": "ETH", "pnl": 3.5,
                              "exit_reason": "止盈", "close_px": 2500.0, "roi_pct": 1.25,
                              "duration": "42分钟"}],
                trades_lifecycle=[{"id": "still-open", "status": "holding"}])
        finally:
            if old is None:
                sys.modules.pop("qq_notifier", None)
            else:
                sys.modules["qq_notifier"] = old
        self.assertEqual(len(calls), 1, "既有已平的不重发，未平的不发")
        self.assertEqual(calls[0]["inst"], "ETH")
        self.assertEqual(calls[0]["pnl"], 3.5)
        self.assertEqual(calls[0]["stage"], "止盈")
        self.assertEqual(calls[0]["duration_str"], "42分钟",
                         "台账行的 `duration` 键必须映射成通知的 `duration_str` 参数")

    def test_defaults_when_fields_missing(self):
        calls = []
        fake = types.SimpleNamespace(notify_trade_close=lambda **kw: calls.append(kw))
        from scripts.ledger.notify import notify_newly_closed_trades
        old = sys.modules.get("qq_notifier")
        sys.modules["qq_notifier"] = fake
        try:
            notify_newly_closed_trades(binance_trades=[], existing_closed_ids=set(),
                                       gate_trades=[{"id": "g1", "status": "closed"}],
                                       trades_lifecycle=[])
        finally:
            if old is None:
                sys.modules.pop("qq_notifier", None)
            else:
                sys.modules["qq_notifier"] = old
        self.assertEqual(calls[0], {"inst": "CRYPTO", "pnl": 0.0, "stage": "平仓结清",
                                    "exit_px": 0.0, "roi_pct": 0.0, "duration_str": ""})

    def test_notifier_failure_never_breaks_sync(self):
        def boom(**kw):
            raise RuntimeError("QQ 掉线")
        from scripts.ledger.notify import notify_newly_closed_trades
        old = sys.modules.get("qq_notifier")
        sys.modules["qq_notifier"] = types.SimpleNamespace(notify_trade_close=boom)
        try:
            notify_newly_closed_trades(binance_trades=[], existing_closed_ids=set(),
                                       gate_trades=[{"id": "g1", "status": "closed"}],
                                       trades_lifecycle=[])   # 不得抛错
        finally:
            if old is None:
                sys.modules.pop("qq_notifier", None)
            else:
                sys.modules["qq_notifier"] = old

if __name__ == "__main__":
    unittest.main()
