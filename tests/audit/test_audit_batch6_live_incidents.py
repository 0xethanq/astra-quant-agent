"""批6 现场事故修复回归钉（2026-09-13 下午·用户报「挂单重复/台账停更」）。

四条根因、四条钉：
① PEPE 挂单纯永动机：对账意图匹配 next() 取**最老**意图 + 意图只增不清 →
   当日首笔意图过 TTL 后每轮撤掉上一轮新单再重挂。修：max-ts 匹配 + 写侧清理。
② 交易全链停摆（我自己批5 引入）：gate 执行闸开但凭证坏，回收枚举异常被当
   fail-closed 拦轮 → 每 15 分钟 Abort，台账/开平仓全停。修：凭证类错误按所
   隔离跳过 + CRITICAL，只有真不可核验才拦轮。
③ 外所单守卫盲区：pending 去重/配额只数 OKX → binance demo BTC/SUI 成对重复。
   修：回收接管同尺（新鲜意图保留 + 同向只保最新一条，其余收敛撤销）。
④ 台账 sync 静默死亡：subprocess "python3 …" shell 串（主机无裸 python3，
   rc=127 被 capture_output 吞）→ 台账 sync_full_ledger/db_manager 从不执行。
   修：astra_backend/spawn.run_script（sys.executable + 非零必吼）六点接入。
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ------------------------------------------------ ① 意图匹配 max-ts 与写侧清理


class TestIntentPerpetualFix(unittest.TestCase):
    def test_max_ts_intent_takeover(self):
        import scripts.ai_factor_trader as aft
        now = int(time.time() * 1000)
        pending = [{"instId": "PEPE-USDT-SWAP", "ordId": "o1", "side": "buy",
                    "state": "live", "posSide": "net", "cTime": now - 60_000}]
        with patch.object(aft, "load_open_intents", lambda: [
                {"instId": "PEPE-USDT-SWAP", "side": "buy", "ts": now - 8 * 3600_000},   # 老（超TTL）
                {"instId": "PEPE-USDT-SWAP", "side": "buy", "ts": now - 10 * 60_000}]):   # 新
            with redirect_stdout(io.StringIO()) as buf:
                ok, kept = aft.reconcile_pending_orders(trackers={}, now_ms=now, pending=pending)
        self.assertTrue(ok)
        self.assertEqual(kept, {"o1"}, "存在新鲜意图时最老过期意图不得再判死新挂单")
        self.assertIn("意图归属", buf.getvalue())

    def test_only_stale_intent_correctly_cancels(self):
        import scripts.ai_factor_trader as aft
        now = int(time.time() * 1000)
        pending = [{"instId": "PEPE-USDT-SWAP", "ordId": "o1", "side": "buy",
                    "state": "live", "posSide": "net", "cTime": now - 8 * 3600_000}]
        cancelled: list = []
        with patch.object(aft, "load_open_intents", lambda: [
                {"instId": "PEPE-USDT-SWAP", "side": "buy", "ts": now - 8 * 3600_000}]), \
             patch.object(aft, "okx_rest", type("O", (), {
                 "cancel_order": staticmethod(lambda i, o: cancelled.append(o)),
                 "pending_orders": staticmethod(lambda **k: [])})()):
            ok, kept = aft.reconcile_pending_orders(trackers={}, now_ms=now, pending=pending)
        self.assertTrue(ok)
        self.assertEqual(kept, set())
        self.assertEqual(cancelled, ["o1"], "全部意图过期时撤销语义照旧正确")

    def test_record_intent_purges_and_dedupes(self):
        import scripts.ai_factor_trader as aft
        d = tempfile.mkdtemp(prefix="astra-b6-int-")
        f = os.path.join(d, "intents.json")
        now = int(time.time() * 1000)
        Path(f).write_text(json.dumps([   # 过期→清 / 保留 / 同键旧条目→被替换
            {"instId": "PEPE-USDT-SWAP", "side": "buy", "ts": now - 9 * 3600_000},
            {"instId": "BTC-USDT-SWAP", "side": "buy", "ts": now - 3600_000},
            {"instId": "PEPE-USDT-SWAP", "side": "buy", "ts": now - 2 * 3600_000},
        ]))
        with patch.object(aft, "OPEN_INTENT_FILE", f):
            aft.record_open_intent("PEPE-USDT-SWAP", "buy", ts_ms=now)
        rows = json.loads(Path(f).read_text())
        self.assertFalse(any(now - int(r["ts"]) > 6 * 3600_000 for r in rows), "过期条目必须清")
        pepe = [r for r in rows if r["instId"] == "PEPE-USDT-SWAP" and r["side"] == "buy"]
        self.assertEqual(len(pepe), 1, "同标的同方向只留最新")
        self.assertEqual(pepe[0]["ts"], now)
        self.assertEqual(len(rows), 2)


# ----------------------------------------- ② gate 凭证错误不再拦全链


class TestAuthErrorIsolation(unittest.TestCase):
    def _okx_stub(self):
        return type("O", (), {"pending_orders": staticmethod(lambda **k: []),
                              "cancel_order": staticmethod(lambda *a, **k: None)})()

    def test_gate_bad_key_skips_not_blocks(self):
        import scripts.ai_factor_trader as aft
        gate_err = type("GateAPIError", (Exception,), {})("Gate INVALID_KEY: Invalid key provided")
        gate = type("G", (), {"list_open_orders": lambda self, b: (_ for _ in ()).throw(gate_err)})()
        with patch.object(aft, "_BROKEN_VENUES", set()), \
             patch.object(aft, "okx_rest", self._okx_stub()), \
             patch.object(aft, "current_environment", lambda: type("E", (), {"mode": "demo"})()), \
             patch.object(aft.venue_registry, "execution_open", lambda v, e: v == "gate"), \
             patch.object(aft.venue_registry, "get_adapter", lambda v, environment=None: gate), \
             patch.object(aft, "load_instruments", lambda: [{"instId": "BTC-USDT-SWAP"}]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok, msg = aft.clean_stale_open_orders()
        self.assertTrue(ok, f"凭证坏所应跳过而非拦轮: {msg}")
        self.assertIn("CRITICAL", buf.getvalue())

    def test_network_error_still_blocks_fail_closed(self):
        import scripts.ai_factor_trader as aft
        boom = ConnectionResetError("connection reset by peer")
        gate = type("G", (), {"list_open_orders": lambda self, b: (_ for _ in ()).throw(boom)})()
        with patch.object(aft, "okx_rest", self._okx_stub()), \
             patch.object(aft, "current_environment", lambda: type("E", (), {"mode": "demo"})()), \
             patch.object(aft.venue_registry, "execution_open", lambda v, e: v == "gate"), \
             patch.object(aft.venue_registry, "get_adapter", lambda v, environment=None: gate), \
             patch.object(aft, "load_instruments", lambda: [{"instId": "BTC-USDT-SWAP"}]), \
             redirect_stdout(io.StringIO()):
            ok, msg = aft.clean_stale_open_orders()
        self.assertFalse(ok, "非凭证类不可核验仍须 fail-closed")
        self.assertIn("gate", msg)

    def test_healthy_gate_still_gets_reclaimed(self):
        # 反证：gate 正常时回收仍必须工作（凭证隔离不得变成 gate 免检）
        import scripts.ai_factor_trader as aft
        now_ts = int(time.time() * 1000)
        cancelled = []
        gate = type("G", (), {
            "list_open_orders": lambda self, b: [
                {"id": "g1", "contract": "BTC_USDT", "side": "buy",
                 "create_time": (now_ts - 400_000) / 1000}],
            "cancel_order": lambda self, b, oid: cancelled.append((b, oid)),
        })()
        with patch.object(aft, "okx_rest", self._okx_stub()), \
             patch.object(aft, "current_environment", lambda: type("E", (), {"mode": "demo"})()), \
             patch.object(aft.venue_registry, "execution_open", lambda v, e: v == "gate"), \
             patch.object(aft.venue_registry, "get_adapter", lambda v, environment=None: gate), \
             patch.object(aft, "load_instruments", lambda: [{"instId": "BTC-USDT-SWAP"}]), \
             patch.object(aft, "load_open_intents", lambda: []), \
             redirect_stdout(io.StringIO()):
            ok, _ = aft.clean_stale_open_orders()
        self.assertTrue(ok)
        self.assertEqual(cancelled, [("BTC", "g1")], "gate 健康时必须照常撤超时孤儿")

    def test_broken_key_venue_dropped_from_routing(self):
        # 回收实证坏键 → 同进程路由必须否决该场（坏键以最低费率赢下评分后死在
        # 下单阶段=白烧信号），并证明健康场不受牵连
        import scripts.ai_factor_trader as aft
        gate_err = type("GateAPIError", (Exception,), {})("Gate INVALID_KEY: Invalid key provided")
        gate = type("G", (), {"list_open_orders": lambda self, b: (_ for _ in ()).throw(gate_err)})()
        healthy_binance = type("B", (), {"open_orders": lambda self, symbol=None: []})()
        with patch.object(aft, "_BROKEN_VENUES", set()), \
             patch.object(aft, "okx_rest", type("O", (), {
                 "pending_orders": staticmethod(lambda **k: []),
                 "cancel_order": staticmethod(lambda *a, **k: None)})()), \
             patch.object(aft, "current_environment", lambda: type("E", (), {"mode": "demo"})()), \
             patch.object(aft.venue_registry, "execution_open", lambda v, e: True), \
             patch.object(aft.venue_registry, "get_adapter",
                          lambda v, environment=None: healthy_binance if v == "binance" else gate), \
             patch.object(aft, "load_instruments", lambda: [{"instId": "BTC-USDT-SWAP"}]), \
             redirect_stdout(io.StringIO()):
            ok, _ = aft.clean_stale_open_orders()
            self.assertIn("gate", aft._BROKEN_VENUES, "凭证实证失败必须入账")
            self.assertTrue(ok)
            self.assertFalse(aft.venue_execution_ready("gate", "demo"),
                             "坏键场在本轮路由必须被摘除执行资格")
            self.assertTrue(aft.venue_execution_ready("binance", "demo"),
                            "未实证失败的场不受牵连")


# --------------------------------------------- ③ 外所同向重复单收敛


class TestExternalDedupeConvergence(unittest.TestCase):
    def test_same_direction_pair_converges_to_latest(self):
        import scripts.ai_factor_trader as aft
        now_ts = int(time.time() * 1000)
        cancelled = []
        binance = type("B", (), {
            "open_orders": lambda self, symbol=None: [
                {"order_id": "old", "inst_id": "SUIUSDT", "base": "SUI", "side": "sell",
                 "raw": {"time": now_ts - 900_000}},
                {"order_id": "new", "inst_id": "SUIUSDT", "base": "SUI", "side": "sell",
                 "raw": {"time": now_ts - 300_500}},
            ],
            "cancel_order": lambda self, b, oid: cancelled.append((b, oid)),
        })()
        with patch.object(aft, "okx_rest", type("O", (), {
                "pending_orders": staticmethod(lambda **k: []),
                "cancel_order": staticmethod(lambda *a, **k: None)})()), \
             patch.object(aft, "current_environment", lambda: type("E", (), {"mode": "demo"})()), \
             patch.object(aft.venue_registry, "execution_open", lambda v, e: v == "binance"), \
             patch.object(aft.venue_registry, "get_adapter", lambda v, environment=None: binance), \
             patch.object(aft, "load_open_intents", lambda: [
                {"instId": "SUI-USDT-SWAP", "side": "sell", "ts": now_ts - 10 * 60_000}]), \
             redirect_stdout(io.StringIO()) as buf:
            ok, _ = aft.clean_stale_open_orders()
        self.assertTrue(ok)
        self.assertEqual(cancelled, [("SUI", "old")], "同向重复只撤旧留新（新单有新鲜意图归属）")
        self.assertIn("重复单收敛", buf.getvalue())


# --------------------------------------------- ④ spawn 子进程卫生


class TestSpawnHygiene(unittest.TestCase):
    def test_run_script_same_interpreter_and_noisy(self):
        # 第七十八刀：以 spawn 为被测行为，离线守护下如实 skip（守卫在 spawn 前）。
        from tests.config_sandbox import skip_if_offline_suite
        skip_if_offline_suite(self)
        from astra_backend.spawn import run_script
        d = tempfile.mkdtemp(prefix="astra-b6-sp-")
        good = os.path.join(d, "good.py")
        bad = os.path.join(d, "bad.py")
        Path(good).write_text("import sys; print(sys.executable)")
        Path(bad).write_text("import sys\nprint('boom', file=sys.stderr)\nsys.exit(3)\n")
        cp = run_script(good, timeout=15)
        self.assertEqual(cp.returncode, 0)
        self.assertIn("python", cp.stdout)
        self.assertTrue(Path(cp.stdout.strip()).exists(), "sys.executable 路径必须真实")
        with redirect_stdout(io.StringIO()) as buf:
            cp2 = run_script(bad, timeout=15, label="wreck")
        self.assertEqual(cp2.returncode, 3)
        out = buf.getvalue()
        self.assertIn("wreck", out)
        self.assertIn("boom", out, "非零退出的 stderr 必须吼出来，不再静默")

    def test_no_bare_python3_shell_remains(self):
        import re
        bad = []
        # 批7 教训：dashboard/ 曾被漏扫，其触发的台账 sync 同为裸 python3 静默死亡
        for f in (list((ROOT / "scripts").glob("*.py")) + list((ROOT / "astra_backend").rglob("*.py"))
                  + list((ROOT / "astra_backend").glob("dashboard_cache.py"))):
            src = f.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r'subprocess\.run\(\s*f["\']python3 ', src):
                line = src[:m.start()].count("\n") + 1
                bad.append(f"{f.name}:{line}")
        self.assertEqual(bad, [], "裸 python3 shell 串复活:\n" + "\n".join(bad))


# ------------------------------------ 跨所快照单点化（打印归位 + 复用不出网）


class TestVenueSnapshotSingleSource(unittest.TestCase):
    def test_fetch_is_silent_and_owner_prints(self):
        # 领域定位：fetch_other_venue_positions 及其唯一归属打印都属执行层领域。
        # 其中 `assertNotIn` 是**负向**断言——单文件定位在搬家后会静默空转。
        from tests.source_scan import combined
        src = combined("scripts/ai_factor_trader.py", pkg_name="trader")
        fetch_body = src.split("def fetch_other_venue_positions")[1].split("\ndef ")[0]
        self.assertNotIn("纳入本周期仓位配额", fetch_body,
                         "fetcher 复活逐仓打印=多点复用日志成倍的老病")
        owner = src.split("# 1a. 跨所封顶")[1].split("# 1b.")[0]
        self.assertIn("纳入本周期仓位配额", owner, "唯一归属打印必须在主周期 1a 块")

    def test_panorama_reuses_frozen_snapshot(self):
        """全景装配必须复用 1a 已冻结的周期快照（零重复出网）。

        ## 第九十二刀为什么重写这条判据

        原写法是**跨文件文本切片**：
        `combined(facade, pkg_name="trader").split(标记)[1].split("except Exception as _xv_e")[0]`
        —— 它依赖"标记之后、下一个 `_xv_e` 之前"这段**跨文件拼接文本**恰好延伸到
        `position_universe.py` 的实现（`_xv_snap = xv_positions_by_venue`）。
        `cycle_stages.py` 一加入域文本，切片就在它那里的 `_xv_e` 提前截断 ⇒ 翻红。
        这是 §103.2 同一类坑：**别拿跨文件文本切片当判据**。

        现改为两处**各自精确定位**（语义不变）：
        1. 实现体 `merge_cross_venue_positions`（`position_universe.py`）必须
           冻结快照再遍历，且**不得**自己现拉外所；
        2. 门面相位 4 的调用点必须传入 `xv_positions_by_venue`（1a 冻结的那份）。
        """
        import ast
        from tests.source_scan import find_function_node
        uni = ROOT / "scripts" / "trader" / "position_universe.py"
        node, _where = find_function_node(uni, "merge_cross_venue_positions")
        impl = ast.get_source_segment(uni.read_text(encoding="utf-8"), node)
        self.assertIn("_xv_snap = xv_positions_by_venue", impl,
                      "全景块复活现拉=同周期两次外所读取撕裂的老病")
        self.assertNotIn("fetch_other_venue_positions(", impl,
                         "实现体不得自己发起外所读取（必须吃冻结快照）")
        # ⚠️ 第九十三刀：相位 4 前段（含此处调用点）已迁入 cycle_stages.py
        # ⇒ 判据对象随实现迁移（"必须传入 1a 冻结的快照"这条不变量不变）。
        stages = ROOT / "scripts" / "trader" / "cycle_stages.py"
        snode, _w2 = find_function_node(stages, "scan_risk_gates_and_ai_brain")
        simp = ast.get_source_segment(stages.read_text(encoding="utf-8"), snode)
        self.assertIn("_merge_cross_venue_positions(active_pos_list, xv_positions_by_venue",
                      simp, "调用点必须传入 1a 冻结的快照（不得现拉）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
