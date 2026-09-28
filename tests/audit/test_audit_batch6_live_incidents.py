"""批6 现场事故修复回归钉（2026-09-13 下午·用户报「挂单重复/台账停更」）。

四条根因、四条钉：
① PEPE 挂单纯永动机：对账意图匹配 next() 取**最老**意图 + 意图只增不清 →
   当日首笔意图过 TTL 后每轮撤掉上一轮新单再重挂。修：max-ts 匹配 + 写侧清理。
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
