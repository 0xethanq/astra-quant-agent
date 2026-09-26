"""批7 回归钉（2026-09-13 · 用户报「前台今日已实现和台账对不上」）。

取证结论：两边各错一处，互相放大——
① 台账吞腿（sync_full_ledger）：D8 修复把行 id 改成 `pos_hist_{posId}_{inst}`，
   但 OKX posId 在同标的同方向**多轮往返间复用**（实证：PEPE 06:33→10:31 +7.89
   与 15:37→16:30 -18.18 两条 history 共享 posId 391748010248）→ 合并表撞键，
   第二腿真实亏损被覆盖蒸发。修：id 追加开仓时刻 c_ts + 同键自增序号。
② 前台单所视野（astra_backend/dashboard_cache.py）：「今日已实现」从 OKX bills 聚合，binance/gate
   当日平仓（SUI +27.63）永远不可见；而熔断/台账早已三所合并 → 同一句话两个数。
   修：新 ledger_today_stats（与熔断 ledger_daily_closed_pnl 逐字同式）覆盖 KPI，
   bills 退化为台账缺失时的降级兜底；today_stats.source 明示口径。
③ 连坐修复：dashboard 触发的台账 sync 也是裸 `python3` shell 串（服务器侧从未成功
   过）且 timeout=10s 短于真实全史拉取——换 spawn + 45s。
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

import scripts.okx_rest as okx_rest
import scripts.okx_runtime as okx_runtime
import scripts.sync_full_ledger as sfl
from astra_backend.execution.circuit_breaker import (
    ledger_daily_closed_pnl, ledger_today_stats)

DEMO_VALUES = {
    "ASTRA_OKX_ENV": "demo",
    "OKX_DEMO_API_KEY": "AKD", "OKX_DEMO_SECRET_KEY": "SKD", "OKX_DEMO_PASSPHRASE": "PPD",
}

_POS_ID = "391748010248"   # 真实复用样本：PEPE 当日两腿共享同一 posId


def _hist_rows(u_shift_ms: int = 0) -> list:
    """两条 positions-history：同 posId、不同开/平仓时刻（复现 PEPE 双往返）。"""
    return [
        {"instId": "PEPE-USDT-SWAP", "instType": "SWAP", "mgnMode": "cross", "type": "2",
         "posSide": "net", "direction": "long", "posId": _POS_ID,
         "pnl": "7.89", "fee": "-0.63", "fundingFee": "0", "lever": "10",
         "openAvgPx": "0.0000026", "closeAvgPx": "0.0000027",
         "openMaxPos": "263000", "closeTotalPos": "263000",
         "cTime": "1789252404961", "uTime": "1789266669782"},
        {"instId": "PEPE-USDT-SWAP", "instType": "SWAP", "mgnMode": "cross", "type": "2",
         "posSide": "net", "direction": "long", "posId": _POS_ID,
         "pnl": "-18.18", "fee": "-0.72", "fundingFee": "0", "lever": "10",
         "openAvgPx": "0.0000030", "closeAvgPx": "0.0000030",
         "openMaxPos": "303000", "closeTotalPos": "303000",
         "cTime": "1789285020519", "uTime": str(1789288258858 + u_shift_ms)},
    ]


def _table(hist_rows) -> dict:
    return {
        "/api/v5/account/positions-history": {"code": "0", "data": hist_rows},
        "/api/v5/account/positions": {"code": "0", "data": []},
        "/api/v5/trade/orders-history": {"code": "0", "data": []},
    }


class _Resp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _transport(table):
    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for frag, payload in table.items():
            if frag in url:
                return _Resp(payload)
        raise AssertionError(f"unexpected URL: {url}")
    return _open


class TestPosIdReuseRoundtrips(unittest.TestCase):
    """①台账吞腿：同 posId 多轮往返必须都在；uTime 改写重跑绝不双计。"""

    def setUp(self):
        okx_runtime.freeze_environment(dict(DEMO_VALUES))
        self._pool = sfl.TARGET_INSTRUMENTS
        sfl.TARGET_INSTRUMENTS = [{"instId": "PEPE-USDT-SWAP", "name": "PEPE", "ctVal": 1.0}]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.tmp.name
        self.paths = {
            "DATA_DIR": d,
            "LEDGER_JSON_FILE": os.path.join(d, "trading_ledger.json"),
            "INITIAL_STATE_FILE": os.path.join(d, "account_initial_state.json"),
            "POSITION_TRACKER_FILE": os.path.join(d, "position_trackers.json"),
        }

    def tearDown(self):
        sfl.TARGET_INSTRUMENTS = self._pool
        okx_runtime.unfreeze_environment()

    def _build(self, hist_rows):
        with patch.object(okx_rest, "urlopen", _transport(_table(hist_rows))), \
             patch.multiple(sfl, **self.paths), \
             patch.object(sfl, "get_ct_val", lambda inst: 1.0), \
             patch.object(sfl, "fetch_binance_closed_trades", lambda *a, **k: []), \
             patch.object(sfl, "fetch_gate_closed_trades", lambda *a, **k: []), \
             patch.object(sfl, "_other_venue_live_positions", lambda axis: ([], set())), \
             redirect_stdout(io.StringIO()):
            sfl.build_lifecycle_ledger()
        with open(self.paths["LEDGER_JSON_FILE"], "r", encoding="utf-8") as f:
            return json.load(f)

    def test_both_roundtrips_survive(self):
        ledger = self._build(_hist_rows())
        pepe = [t for t in ledger if t.get("inst") == "PEPE" and t.get("status") == "closed"]
        self.assertEqual(len(pepe), 2, "同 posId 的两条真实往返一条都不能被吞")
        pnls = sorted(round(float(t["pnl"]), 2) for t in pepe)
        self.assertEqual(pnls, [-18.90, 7.26])
        self.assertNotEqual(pepe[0]["id"], pepe[1]["id"], "id 必须唯一（否则合并覆盖）")

    def test_utime_rewrite_no_double_count(self):
        # D8 原始担忧保留：uTime 被补算改写后重跑，行数不增（id 不含 uTime）
        first = self._build(_hist_rows())
        second = self._build(_hist_rows(u_shift_ms=90_000))
        self.assertEqual(len(first), len(second),
                         "uTime 改写不得令同笔平仓双计")
        self.assertEqual(sum(1 for t in second if t.get("status") == "closed"), 2)


class TestLedgerTodayStats(unittest.TestCase):
    """②KPI 口径：三所合并 + 环境轴 + 尘单剔除，且与熔断锚点同式。"""

    TODAY = "2026-09-13"

    def _rows(self):
        mk = lambda **kw: {"status": "closed", "close_time": f"{self.TODAY} 10:00:00",
                           "pnl": 0.0, "gross_pnl": 0.0, "fee": 0.0, "funding_fee": 0.0,
                           "environment": "demo", **kw}
        return [
            mk(venue="okx", inst="PEPE", gross_pnl=7.89, fee=-0.63, pnl=7.26),
            mk(venue="okx", inst="PEPE", gross_pnl=-18.18, fee=-0.72, pnl=-18.90),
            mk(venue="binance", inst="SUI", gross_pnl=28.10, fee=-0.47, pnl=27.63),
            mk(venue="binance", inst="DOGE", gross_pnl=0.004, fee=0.0, pnl=0.004),   # 尘单
            mk(venue="gate", inst="XRP", pnl=99.0, environment="live"),              # 他环境
            mk(venue="okx", inst="BTC", pnl=50.0, close_time="2026-09-12 23:00:00"),  # 昨日
            mk(venue="okx", inst="ETH", pnl=1.0, status="holding"),                   # 未平
        ]

    def test_multi_venue_and_axes(self):
        s = ledger_today_stats(self._rows(), "demo", self.TODAY)
        self.assertEqual(s["net_realized"], round(7.26 - 18.90 + 27.63, 2))
        self.assertEqual(s["win_trades"], 2)
        self.assertEqual(s["loss_trades"], 1)   # 尘单与 live/昨日/holding 全部出局
        self.assertEqual(s["fees_paid"], round(-0.63 - 0.72 - 0.47, 2))
        self.assertEqual(s["source"], "ledger")

    def test_consistent_with_breaker_anchor(self):
        # 单一事实源：KPI net 与熔断日亏必须逐字同值（两数打架=用户再次对不上）
        rows = self._rows()
        self.assertEqual(ledger_today_stats(rows, "demo", self.TODAY)["net_realized"],
                         round(ledger_daily_closed_pnl(rows, "demo", self.TODAY), 2))

    def test_env_axis_conservative_inclusion(self):
        # 当前环境不可得("") → 含标签行也保守全计（与熔断纪律同款）
        s = ledger_today_stats([{"status": "closed", "close_time": f"{self.TODAY} 09:00:00",
                                 "pnl": 5.0, "gross_pnl": 5.0, "fee": 0.0,
                                 "funding_fee": 0.0, "environment": "live"}], "", self.TODAY)
        self.assertEqual(s["net_realized"], 5.0)


class TestDashboardKpiWiring(unittest.TestCase):
    """③防漂移钉：dashboard 必须走台账口径，且不再有裸 python3/短 timeout。"""

    # 阶段 2·B2：dashboard 的域代码正被逐步拆到 astra_backend/dashboard_payload/。
    # 这条锚点钉的是**语义**（dashboard 走台账口径、且不得有裸 python3/短 timeout），
    # 不是"必须写在某一个文件里"—— 故定位方式升级为"该领域的运行时源码集合"：
    # 搬家不再误报，覆盖面反而比原来只看一个文件更广，
    # 负向断言（不许有裸 python3）也随之覆盖到全部已迁出的模块。
    DASH_DOMAIN = [ROOT / "astra_backend" / "dashboard_cache.py"] + sorted(
        (ROOT / "astra_backend" / "dashboard_payload").glob("*.py"))

    def test_dashboard_sources_stats_from_ledger(self):
        from tests import source_scan
        src = source_scan.combined(*self.DASH_DOMAIN)
        # 防空：assertNotIn 在"读到空/读错目录"时会假通过，故先确认领域确实读到了
        source_scan.assert_area_looks_real(self, src, must_contain="ledger_today_stats",
                                           min_chars=60000)
        self.assertIn("ledger_today_stats", src)
        self.assertIn('"source": _today_stats_source', src)
        self.assertNotIn('f"python3', src.replace("'", '"'),
                         "dashboard 裸 python3 shell 串复活")
        self.assertIn('timeout=45', src, "台账 sync 触发不得退回 10s 必超时短闸")


if __name__ == "__main__":
    unittest.main(verbosity=2)
