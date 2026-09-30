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
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
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

    def _isolate_state(self):
        """把去重集落点重定向到临时目录。

        ⚠️ 必须做：去重集是**生产**文件（`data/close_notify_state.json`，已进写保护名单）。
        2026-09-30 实测：本组用例第一次跑就把夹具 id 写进了生产去重集 —— 之后真实的
        平仓行会被当成"已通知"而**静默漏发**。故显式 patch（与 scale_out 事件流水同款纪律）。
        """
        import scripts.ledger.notify as _notify
        td = tempfile.TemporaryDirectory(prefix="astra-notify-state-")
        self.addCleanup(td.cleanup)
        target = Path(td.name) / "state.json"
        patcher = patch.object(_notify, "CLOSE_NOTIFY_STATE_FILE", target)
        patcher.start()
        self.addCleanup(patcher.stop)
        return target

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
        self._isolate_state()
        calls = []
        from scripts.ledger.notify import notify_newly_closed_trades
        fake = types.SimpleNamespace(notify_trade_close=lambda **kw: calls.append(kw))
        old = sys.modules.get("qq_notifier")
        sys.modules["qq_notifier"] = fake
        try:
            notify_newly_closed_trades(
                existing_closed_ids={"old-1"},
                trades_lifecycle=[
                    {"id": "old-1", "status": "closed"},
                    {"id": "new-2", "status": "closed", "inst": "ETH", "pnl": 3.5,
                     "exit_reason": "止盈", "close_px": 2500.0, "roi_pct": 1.25,
                     "duration": "42分钟"},
                    {"id": "still-open", "status": "holding"},
                ])
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
        self._isolate_state()
        calls = []
        fake = types.SimpleNamespace(notify_trade_close=lambda **kw: calls.append(kw))
        from scripts.ledger.notify import notify_newly_closed_trades
        old = sys.modules.get("qq_notifier")
        sys.modules["qq_notifier"] = fake
        try:
            notify_newly_closed_trades(existing_closed_ids=set(),
                                       trades_lifecycle=[{"id": "g1", "status": "closed"}])
        finally:
            if old is None:
                sys.modules.pop("qq_notifier", None)
            else:
                sys.modules["qq_notifier"] = old
        self.assertEqual(calls[0], {"inst": "CRYPTO", "pnl": 0.0, "stage": "平仓结清",
                                    "exit_px": 0.0, "roi_pct": 0.0, "duration_str": ""})

    def test_notifier_failure_never_breaks_sync(self):
        self._isolate_state()
        def boom(**kw):
            raise RuntimeError("QQ 掉线")
        from scripts.ledger.notify import notify_newly_closed_trades
        old = sys.modules.get("qq_notifier")
        sys.modules["qq_notifier"] = types.SimpleNamespace(notify_trade_close=boom)
        try:
            notify_newly_closed_trades(existing_closed_ids=set(),
                                       trades_lifecycle=[{"id": "g1", "status": "closed"}])   # 不得抛错
        finally:
            if old is None:
                sys.modules.pop("qq_notifier", None)
            else:
                sys.modules["qq_notifier"] = old

    # ---------- 行为例：去重 / 并发 / 部分平仓延后（2026-09-30 真机事故）----------

    def _run_notify(self, existing_closed_ids, rows, state_file):
        """跑一次通知，返回发出的 payload 列表（`qq_notifier` 用假模块注入）。"""
        import scripts.ledger.notify as _notify
        calls = []
        fake = types.SimpleNamespace(notify_trade_close=lambda **kw: calls.append(kw))
        old = sys.modules.get("qq_notifier")
        sys.modules["qq_notifier"] = fake
        try:
            with patch.object(_notify, "CLOSE_NOTIFY_STATE_FILE", state_file):
                _notify.notify_newly_closed_trades(existing_closed_ids=existing_closed_ids,
                                                   trades_lifecycle=rows)
        finally:
            if old is None:
                sys.modules.pop("qq_notifier", None)
            else:
                sys.modules["qq_notifier"] = old
        return calls

    def test_the_same_row_is_never_notified_twice_across_processes(self):
        """★ 20:34:41 / 20:34:43 两条同 payload、不同 event_id 的 XRP 卡片。

        根因：`existing_closed_ids` 只是**本进程**读到的旧台账；四个调用点并发时，
        两边都判"这是新平仓" ⇒ 同一笔发两张。持久化去重集必须挡住第二个进程。
        """
        row = {"id": "pos_hist_3963287216620990465_XRP_1790666189", "status": "closed",
               "inst": "XRP", "pnl": 9.32, "exit_reason": "🎯 目标止盈达成",
               "close_px": 1.5235, "roi_pct": 6.22, "duration": "5时17分"}
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            first = self._run_notify(set(), [row], state)
            # 第二个进程：它读到的旧台账里同样**没有**这一行（并发竞态现场）
            second = self._run_notify(set(), [row], state)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [], "跨进程第二次跑不得再发同一条")

    def test_state_file_is_what_dedupes_not_the_in_process_set(self):
        """去重集必须**真的落盘**（只靠进程内集合挡不住四个并发调用点）。"""
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            self._run_notify(set(), [{"id": "a1", "status": "closed", "inst": "BTC"}], state)
            self.assertIn("a1", state.read_text(encoding="utf-8"))

    def test_corrupt_state_file_still_notifies(self):
        """读不到 ≠ 没有：去重集损坏时**照常通知**（静音比重复严重一个量级）。"""
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            state.write_text("{ 这不是 JSON")
            calls = self._run_notify(set(), [{"id": "b1", "status": "closed", "inst": "ETH"}], state)
        self.assertEqual(len(calls), 1, "损坏时宁可重发一条，也不能永久静音")

    def test_partial_close_is_deferred_until_the_position_really_finishes(self):
        """★ 分批腿的部分平仓行先不发，等余仓也平掉后用整笔数字发一条。

        现场（2026-09-29 XRP）：20:34 部分行（sz 5.97 / +9.32U）发了；
        20:38 余仓平掉后该行被**改写**成整笔（sz 11.95 / +39.06U），
        而 id 已在"已平集合"里 ⇒ **真正的结清一条都没发**。
        """
        partial_row = {"id": "pos_XRP_1", "status": "closed", "inst": "XRP", "side": "多",
                       "open_time": "2026-09-29 15:16:29", "open_px": 1.5056,
                       "sz": 5.97, "pnl": 9.32, "exit_reason": "🎯 目标止盈达成"}
        holding_row = {"id": "holding_okx_XRP_多", "status": "holding", "inst": "XRP",
                       "side": "多", "open_time": "2026-09-29 15:16:29", "open_px": 1.5056,
                       "sz": 5.98}
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            while_open = self._run_notify(set(), [partial_row, holding_row], state)
            # 余仓也平掉：holding 行消失，同一行被改写成整笔
            finished = dict(partial_row, sz=11.95, pnl=39.06,
                            exit_reason="🎯 目标止盈达成", close_px=1.5398)
            settled = self._run_notify(set(), [finished], state)
        self.assertEqual(while_open, [], "余仓还在跑 ⇒ 不得先发半仓金额")
        self.assertEqual(len(settled), 1, "整笔结清必须发得出去（旧实现把它漏了）")
        self.assertEqual(settled[0]["pnl"], 39.06)

    def test_a_new_position_in_the_same_inst_does_not_block_the_old_close(self):
        """同标的新仓（开仓时刻不同）不得让**上一笔**的结清通知被无限延后。"""
        closed = {"id": "pos_BTC_old", "status": "closed", "inst": "BTC", "side": "多",
                  "open_time": "2026-09-29 08:00:00", "open_px": 80000.0,
                  "sz": 1.0, "pnl": 12.0, "exit_reason": "🎯 目标止盈达成"}
        fresh = {"id": "holding_okx_BTC_多", "status": "holding", "inst": "BTC", "side": "多",
                 "open_time": "2026-09-29 16:16:09", "open_px": 84046.1, "sz": 2.85}
        with tempfile.TemporaryDirectory() as td:
            calls = self._run_notify(set(), [closed, fresh], Path(td) / "state.json")
        self.assertEqual(len(calls), 1, "同标的但不同一笔持仓 ⇒ 该发就发")

    def test_writer_cannot_touch_the_production_state_from_a_test(self):
        """真实事故回归：本组用例第一次跑就把夹具 id 写进了**生产**去重集。

        防线两条（与 scale_out 事件流水同款）：① 落点是模块常量（用例可 patch）；
        ② 该文件已登记进 `tests/__init__.py` 写保护名单 ⇒ 忘 patch 时测试守卫拦下。
        """
        import scripts.ledger.notify as _notify
        prod = Path(_notify._PRODUCTION_STATE_FILE)
        before = prod.stat().st_size if prod.exists() else None
        _notify._save_notified({"fixture-should-not-land"})
        after = prod.stat().st_size if prod.exists() else None
        self.assertEqual(before, after, "生产去重集不得被用例写入")
        self.assertNotIn("fixture-should-not-land",
                         prod.read_text(encoding="utf-8") if prod.exists() else "")


if __name__ == "__main__":
    unittest.main()
