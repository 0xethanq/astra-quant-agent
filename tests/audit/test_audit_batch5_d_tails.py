"""批5 D级尾巴回归钉（审计 2026-09-13 第二轮收口）。

- #4 worker tick 饥饿：循环每轮必 tick、投递每轮至多 1 条（source 形态钉）
- #11 claim_due 租约老化：崩溃遗留 processing 行过租约可重领（功能实测）
- #12 job_runs 僵尸 running：启动收编 interrupted（功能实测）
- ② 重定向拒跳 safe_urlopen：本地 302 实测不跟随（真 socket，零外部网）
- D cleanup_disk：copytruncate 保 inode（活 fd 续写不丢）、/tmp 清扫限 astra-* 前缀
- D 百度 OAuth：token 参数 POST body（secret 不落 query）
- D 枚举文案：登录四态对外同话术（批5 已并入 test_admin_auth，此处不重复）
- ⑤ portfolio_aggregator：eq/avail 门对称（半坏卡不渗聚合）
- ④8 外所 GTC 回收：执行闸开才扫、超时撤、keep_ids 豁免、闸关零触碰（功能实测）
- ④5 杠杆落地：source 反漂移钉（notify 真值 / submit 前落档 / 三所 set_leverage 对称）
"""
from __future__ import annotations

import http.server
import inspect
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# --------------------------------------------------------------- 网关三件


class TestGatewayJobRuns(unittest.TestCase):
    def test_zombie_running_adopted(self):
        from astra_gateway.store import GatewayStore
        db = os.path.join(tempfile.mkdtemp(prefix="astra-b5-jr-"), "gw.sqlite3")
        store = GatewayStore(Path(db))
        run_id = store.begin_job("trader")            # 模拟 running 中进程被杀
        self.assertEqual(store.job_runs(5)[0]["status"], "running")
        n = store.recover_stale_job_runs()
        self.assertEqual(n, 1)
        row = store.job_runs(5)[0]
        self.assertEqual(row["status"], "interrupted")
        self.assertTrue(row["finished_at"])
        self.assertEqual(store.recover_stale_job_runs(), 0)   # 幂等

    def test_claim_lease_aging(self):
        from datetime import datetime, timedelta
        from astra_gateway.store import GatewayStore, BJ_TZ
        from astra_gateway.events import GatewayEvent
        db = os.path.join(tempfile.mkdtemp(prefix="astra-b5-cl-"), "gw.sqlite3")
        store = GatewayStore(Path(db))
        ev = GatewayEvent(event_type="test", title="t", message="m")
        store.publish(ev, ["webhook"])
        first = store.claim_due(5, lease_seconds=120)
        self.assertEqual(len(first), 1)
        self.assertEqual(store.claim_due(5), [], "租约未到期不得重复领取")
        # 时间旅行：租约拨回过去 = 模拟 worker 崩溃后 lease 过期
        with store.connect() as conn:
            old = (datetime.now(BJ_TZ) - timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE deliveries SET next_attempt_at=? WHERE status='processing'", (old,))
        again = store.claim_due(5)
        self.assertEqual(len(again), 1, "过期租约的 processing 行必须可老化重领")

    def test_worker_loop_tick_not_starved(self):
        src = (ROOT / "astra_gateway" / "worker.py").read_text(encoding="utf-8")
        self.assertIn("store.claim_due(1)", src)       # 每轮至多一发，发完即回 tick
        self.assertNotIn("claim_due(20)", src)
        loop = src.split("while RUNNING:")[1]
        self.assertLess(loop.index("scheduler.tick()"), loop.index("claim_due"),
                        "tick 必须在投递领取之前（每轮先喂排程）")


# ------------------------------------------------- safe_urlopen 真 302 拒跳


class _RedirectServer(http.server.BaseHTTPRequestHandler):
    followed = False

    def do_GET(self):  # noqa: N802
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:%d/payload" % self.server.server_address[1])
            self.end_headers()
        else:
            type(self).followed = True
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"leaked": true}')

    def log_message(self, *a):
        pass


class TestNoRedirect(unittest.TestCase):
    def test_safe_urlopen_refuses_302(self):
        from astra_backend.net_security import safe_urlopen
        import urllib.error
        import urllib.request
        _RedirectServer.followed = False
        srv = http.server.HTTPServer(("127.0.0.1", 0), _RedirectServer)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/start")
            with self.assertRaises(urllib.error.HTTPError) as cm:
                safe_urlopen(req, timeout=5)
            self.assertIn(cm.exception.code, (301, 302, 307))
            self.assertFalse(_RedirectServer.followed, "302 目标被访问=跟随重定向未禁")
        finally:
            srv.shutdown()
            srv.server_close()


# ------------------------------------------------------ cleanup_disk 两钉


class TestCleanupDisk(unittest.TestCase):
    def test_copytruncate_keeps_inode_for_live_writer(self):
        import cleanup_disk as cd
        import shutil
        d = tempfile.mkdtemp(prefix="astra-b5-cl2-")
        # 事故(2026-09-13)：本钉写 10MB 日志却从不清理——全量套件每跑一轮就在 /tmp
        # (256MB tmpfs) 漏 11MB，累积把 tmpfs 撑满→其余测试集体 Errno 28、套件中断。
        # 测试自己造的临时物必须自己收尸（addCleanup 无论成败都执行）。
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        log = os.path.join(d, "uvicorn.log")
        with open(log, "wb") as f:
            f.write(b"x" * (10 * 1024 * 1024 + 10))   # 越 10MB 阈值
        inode_before = os.stat(log).st_ino
        live = open(log, "ab")                          # 模拟 uvicorn 持 fd 追加
        try:
            with patch.object(cd, "LOGS_DIR", d):
                actions = cd.clean_logs()
            self.assertTrue(any(r.startswith("Rotated uvicorn.log") for r in actions), actions)
            self.assertTrue(os.path.exists(log + ".1"))
            self.assertEqual(os.stat(log).st_ino, inode_before, "inode 必须原地不动（copytruncate）")
            self.assertEqual(os.path.getsize(log), 0)
            live.write(b"after-rotate\n"); live.flush()
            with open(log) as f:
                self.assertEqual(f.read(), "after-rotate\n")  # 活 fd 续写进新档而非归档
        finally:
            live.close()

    def test_tmp_sweep_scoped_to_astra_prefix(self):
        lines = [ln for ln in (ROOT / "scripts" / "cleanup_disk.py").read_text(encoding="utf-8").splitlines()
                 if not ln.lstrip().startswith("#")]   # 注释里引用旧命令不算复活
        body = "\n".join(lines)
        self.assertNotIn("-type f -mtime +2 -delete", body)
        self.assertIn("-maxdepth 1 -name 'astra-*'", body)


class TestBaiduTokenPost(unittest.TestCase):
    def test_secret_params_not_in_query(self):
        import backup_runtime as br
        captured = []

        def fake_json(url, data=None, timeout=60):
            captured.append((url, data))
            if len(captured) == 1:
                return {"access_token": "AT"}
            if len(captured) == 2:
                return {"uploadid": "u1"}
            return {"fs_id": "f1"}
        d = tempfile.mkdtemp(prefix="astra-b5-bd-")
        import shutil
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        src = Path(d) / "astra_backup_x_20260913_010000.tar.gz"
        src.write_bytes(b"payload-less-than-chunk" * 3)
        target = {"id": "j", "credential_ref": "c", "remote_path": "ASTRA"}
        with patch.object(br, "_credentials", lambda t: {"app_key": "AK", "app_secret": "SEC",
                                                          "refresh_token": "RT", "access_token": ""}), \
             patch.object(br, "_urlencoded_json", side_effect=fake_json), \
             patch.object(br, "_multipart_upload", return_value={"md5": None}), \
             redirect_stdout(io.StringIO()):
            br.upload_baidu_oauth(src, target)
        token_url, token_data = captured[0]
        self.assertNotIn("client_secret", token_url)
        self.assertNotIn("?", token_url.split("baidu.com")[-1] or "")
        self.assertEqual(token_data["client_secret"], "SEC")
        self.assertEqual(token_data["grant_type"], "refresh_token")


# ------------------------------------------- portfolio_aggregator 门对称


class TestAggregatorSymmetry(unittest.TestCase):
    def test_half_broken_card_does_not_leak_avail(self):
        from astra_backend.portfolio_aggregator import aggregate_venue_accounts
        venues = {
            "okx": {"status": "ready", "equity": 1000.0, "available": 800.0, "positions_count": 1, "open_orders_count": 0},
            "gate": {"status": "ready", "equity": -5, "available": 500.0, "positions_count": 2, "open_orders_count": 0},  # eq 坏
            "binance": {"status": "ready", "equity": 200.0, "available": None, "positions_count": 0, "open_orders_count": 0},
        }
        out = aggregate_venue_accounts(venues, "demo")
        self.assertEqual(out["total_equity"], 1200.0)
        self.assertEqual(out["total_available"], 800.0,
                         "gate 的 500 avail 不得在其 eq 无效时渗入聚合")
        self.assertNotIn("gate", out["reporting_venues"])
        self.assertEqual(out["margin_used"], 400.0)   # binance avail 缺失→按其 eq 全额占用（保守）


# ------------------------------------------------- ④8 外所 GTC 回收


class TestExternalVenueReclaim(unittest.TestCase):
    def _setup(self, trader):
        trader = sys.modules["scripts.ai_factor_trader"]
        self.trader = trader
        self._trader = trader

    def test_reclaim_stale_and_keep(self):
        import scripts.ai_factor_trader as aft
        now_ts = int(time.time() * 1000)
        old_s = (now_ts - 400_000) // 1000       # gate create_time 秒制
        old_ms = now_ts - 400_000                # binance raw.time 毫秒制

        gate_cancelled, bin_cancelled = [], []
        gate = type("G", (), {
            "list_open_orders": lambda self, base: [
                {"id": "g-old", "contract": f"{base}_USDT", "side": "buy", "create_time": old_s},
                {"id": "g-young", "contract": f"{base}_USDT", "side": "buy", "create_time": time.time()},
                {"id": "g-keep", "contract": f"{base}_USDT", "side": "buy", "create_time": old_s},
            ],
            "cancel_order": lambda self, base, oid: gate_cancelled.append((base, oid)),
        })()
        binance = type("B", (), {
            "open_orders": lambda self, symbol=None: [
                {"order_id": "b-old", "inst_id": "ETHUSDT", "base": "ETH", "side": "sell", "raw": {"time": old_ms}},
                {"order_id": "b-young", "inst_id": "ETHUSDT", "base": "ETH", "side": "sell", "raw": {"time": now_ts}},
            ],
            "cancel_order": lambda self, base, oid: bin_cancelled.append((base, oid)),
        })()
        ad_map = {"gate": gate, "binance": binance}
        env = type("E", (), {"mode": "demo"})()
        with patch.object(aft, "okx_rest", type("X", (), {
                "pending_orders": staticmethod(lambda **k: []),
                "cancel_order": staticmethod(lambda *a, **k: None)})()), \
             patch.object(aft, "current_environment", lambda: env), \
             patch.object(aft.venue_registry, "execution_open", lambda v, e: True), \
             patch.object(aft.venue_registry, "get_adapter", lambda v, environment=None: ad_map[v]), \
             patch.object(aft, "load_instruments", lambda: [{"instId": "BTC-USDT-SWAP"}, {"instId": "ETH-USDT-SWAP"}]), \
             patch.object(aft, "load_open_intents", lambda: []), \
             redirect_stdout(io.StringIO()):
            ok, msg = aft.clean_stale_open_orders(keep_ord_ids={"g-keep"})
        self.assertTrue(ok, msg)
        self.assertIn(("BTC", "g-old"), gate_cancelled)
        self.assertNotIn(("BTC", "g-keep"), gate_cancelled, "对账已接管的单不得被回收")
        self.assertNotIn(("BTC", "g-young"), gate_cancelled, "未超龄不得撤")
        self.assertEqual(bin_cancelled, [("ETH", "b-old")])

    def test_gated_off_venue_untouched(self):
        import scripts.ai_factor_trader as aft
        env = type("E", (), {"mode": "demo"})()
        def _boom(*a, **k):
            raise AssertionError("执行闸关所不得被枚举——更不得因其故障拦轮")
        with patch.object(aft, "okx_rest", type("X", (), {
                "pending_orders": staticmethod(lambda **k: []),
                "cancel_order": staticmethod(lambda *a, **k: None)})()), \
             patch.object(aft, "current_environment", lambda: env), \
             patch.object(aft.venue_registry, "execution_open", lambda v, e: False), \
             patch.object(aft.venue_registry, "get_adapter", _boom):
            ok, msg = aft.clean_stale_open_orders()
        self.assertTrue(ok, msg)

    def test_enumeration_failure_blocks_cycle(self):
        import scripts.ai_factor_trader as aft
        env = type("E", (), {"mode": "live"})()
        broken = type("B", (), {"open_orders": lambda self, symbol=None: (_ for _ in ()).throw(
            ConnectionError("binance 不可达"))})()
        with patch.object(aft, "okx_rest", type("X", (), {
                "pending_orders": staticmethod(lambda **k: []),
                "cancel_order": staticmethod(lambda *a, **k: None)})()), \
             patch.object(aft, "current_environment", lambda: env), \
             patch.object(aft.venue_registry, "execution_open", lambda v, e: v == "binance"), \
             patch.object(aft.venue_registry, "get_adapter", lambda v, environment=None: broken), \
             redirect_stdout(io.StringIO()):
            ok, msg = aft.clean_stale_open_orders()
        self.assertFalse(ok, "闸开所枚举失败必须 fail-closed 拦轮")
        self.assertIn("binance", msg)


# ------------------------------------------------- ④5 杠杆落地反漂移


class TestLeverageLanding(unittest.TestCase):
    def test_source_pins(self):
        # 领域定位：把"四处开仓通知携带真实杠杆"从门面单文件放宽到整个执行层领域。
        # 这是**正向**计数断言，搬家会让单文件定位翻红（假红），领域定位才描述得准。
        #
        # 计数改走 AST（count_keyword_argument）—— 原先是文本 count
        # `"leverage=int(ai_lever),"`。文本计数有两个坑：①任何 docstring/注释里
        # 提到这段代码都会把计数抬高（本轮抽 notifications.py 时，我的模块 docstring
        # 解释了这 4 行的来由，计数就从 4 变 5 —— 行为毫无变化却翻红）；
        # ②换行/空格一变也失灵。
        # AST 版直接数 `notify_trade_open(..., leverage=...)` 的实参个数，
        # 既不受文档影响，也能真正表达"四处开仓通知都带杠杆"这个语义。
        from tests.source_scan import combined, count_keyword_argument
        trader_src = combined("scripts/ai_factor_trader.py", pkg_name="trader")
        self.assertEqual(
            count_keyword_argument("scripts/ai_factor_trader.py", "notify_trade_open",
                                   "leverage", value_must_contain="int(ai_lever)",
                                   pkg_name="trader"), 4,
            "四处开仓通知必须携带钳制后的真实杠杆（AST 计数，不受文档/换行影响）")
        # 第八十八刀：submit_protected_limit_order 已搬入
        # `scripts/trader/order_submit.py`。原先的 `trader_src.split("def ...")[1]`
        # 在**域合并文本**里会先撞上门面的**转发薄壳**（壳里没有 set_leverage），
        # 故改用 `source_scan.find_function_node`（优先实现体、忽略薄壳）取原文片段。
        import ast as _ast
        from tests.source_scan import find_function_node
        _node, _path = find_function_node(
            "scripts/ai_factor_trader.py", "submit_protected_limit_order",
            pkg_name="trader")
        self.assertEqual(_path.name, "order_submit.py",
                         f"发单主路径应住在子包实现里，实际 {_path.name}")
        submit_src = _ast.get_source_segment(_path.read_text(encoding="utf-8"), _node)
        self.assertIsNotNone(submit_src)
        self.assertIn("okx_rest.set_leverage(", submit_src,
                      "OKX 直下路径发单前必须落 AI 杠杆档位")
        self.assertIn('"leverage": ai_lever,', trader_src.split("def run_trading_cycle")[1]
                      if "def run_trading_cycle" in trader_src else trader_src)

    def test_three_venues_expose_set_leverage(self):
        from astra_backend.exchanges.okx import OKXAdapter
        from astra_backend.exchanges.binance import BinanceAdapter
        from astra_backend.exchanges.gate import GateAdapter
        import scripts.okx_rest as okx_rest
        for cls in (OKXAdapter, BinanceAdapter, GateAdapter):
            self.assertTrue(callable(cls.set_leverage), cls.__name__)
        # 适配器→okx_rest 参绑契约（幻影 kwarg 当场炸）
        seen = {}
        def fake(inst_id, lever, *, mgn_mode="cross", pos_side=None, env=None):
            seen.update(locals())
            return []
        ad = OKXAdapter(api_key="k", secret_key="s", passphrase="p", environment="demo")
        with patch.object(okx_rest, "set_leverage", fake):
            ad.set_leverage("BTC", 5.4, margin_mode="cross", pos_side="long")
        self.assertEqual((seen["inst_id"], seen["lever"], seen["pos_side"]),
                         ("BTC-USDT-SWAP", 5, "long"))   # int 钳制 + 原生符号


# ----------------------------------------------------------- db_manager 时区


class TestDbManagerTz(unittest.TestCase):
    def test_migration_log_aware_timestamp(self):
        import db_manager as dm
        d = tempfile.mkdtemp(prefix="astra-b5-db-")
        target = os.path.join(d, "mig.json")
        with patch.object(dm, "migration_log_path", lambda: target):
            dm._write_migration_log({"mode": "alter", "added": 1})
        ts = json.load(open(target))["ts"]
        self.assertIn("+08:00", ts, "迁移日志必须是带时区 ISO（全仓 BJ 约定）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
