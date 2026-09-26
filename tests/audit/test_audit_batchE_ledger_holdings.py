"""批E 回归钉（2026-09-13 · 用户报「台账和活动持仓还是对不上」）。

取证：活动持仓面板 6 条（全部 binance：ETH 多/SUI 空/LINK 空/BTC 空/AVAX 空/ALGO 多），
台账 holding 却只有 1 条且是 **venue=okx** 的 `holding_ALGO_多`——而 OKX 当时零持仓。
两个独立缺陷叠加：
① 台账 holding 行只由 `okx_rest.positions()` 生成（builder 全源 OKX V5），binance/gate
   的活动持仓在台账里根本不存在；
② 合并阶段只按 id 覆盖新行、**从不删除失效行**，OKX 平掉后那条 holding 行永久留存
   （幽灵持仓）——且旧 id `holding_{inst}_{side}` 不含场所，多所同标的还会撞键。

修：① 抽出共用行构造器 `_holding_row`，id 改为 `holding_{venue}_{inst}_{side}`，并由
`_other_venue_live_positions` 按仪表盘同一事实源（astra_backend.exchanges.get_adapter）
汇入 binance/gate 活动持仓；② 合并后清理「已成功取数的场所」中不在本轮实时持仓里的
holding 行——取数失败的场所保守保留（缺失≠已平仓）。
> ⚠️ 测试桩必须打在被测代码真正持有的模块对象上：sync_full_ledger 用
`import scripts.okx_rest as okx_rest`，而 `scripts/` 无 __init__.py（命名空间包），
于是顶层 `okx_rest` 与 `scripts.okx_rest` 是**两个不同的模块对象**——打错桩会静默
失效（桩没生效 → 测试跑真实网络数据 → 断言看似"通过"实则测了别的东西）。
本文件与批7 保持一致，统一用包限定导入。
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import scripts.okx_rest as okx_rest  # noqa: E402
import scripts.okx_runtime as okx_runtime  # noqa: E402
import sync_full_ledger as sfl  # noqa: E402

DEMO_VALUES = {
    "ASTRA_OKX_ENV": "demo", "OKX_IS_SIMULATED": "true",
    "OKX_DEMO_API_KEY": "k", "OKX_DEMO_SECRET_KEY": "s", "OKX_DEMO_PASSPHRASE": "p",
}


def _env():
    return okx_runtime.current_environment()


def _okx_pos(inst: str, side: str, sz: float, px: float, upl: float = 0.0) -> dict:
    return {
        "instId": f"{inst}-USDT-SWAP", "posSide": side, "pos": str(sz),
        "avgPx": str(px), "markPx": str(px), "upl": str(upl), "lever": "2",
        "fee": "0", "cTime": "1789000000000",
    }


class _Base(unittest.TestCase):
    def setUp(self):
        okx_runtime.freeze_environment(dict(DEMO_VALUES))
        self._pool = sfl.TARGET_INSTRUMENTS
        sfl.TARGET_INSTRUMENTS = [
            {"instId": f"{s}-USDT-SWAP", "name": s, "ctVal": 1.0}
            for s in ("ETH", "SUI", "ALGO", "BTC")
        ]
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

    def _seed_ledger(self, rows):
        with open(self.paths["LEDGER_JSON_FILE"], "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)

    def _build(self, *, okx_positions=(), other=(None, None)):
        """other=(items, ok_venues)：None 表示不 patch（走真实适配器，测试里别用）。"""
        patchers = [
            patch.object(okx_rest, "positions_history", lambda **k: []),
            patch.object(okx_rest, "orders_history", lambda **k: []),
            patch.object(okx_rest, "positions", lambda **k: list(okx_positions)),
            patch.multiple(sfl, **self.paths),
            patch.object(sfl, "get_ct_val", lambda inst: 1.0),
            patch.object(sfl, "fetch_binance_closed_trades", lambda *a, **k: []),
            patch.object(sfl, "fetch_gate_closed_trades", lambda *a, **k: []),
        ]
        if other and other[0] is not None:
            patchers.append(patch.object(sfl, "_other_venue_live_positions", lambda axis: other))
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        with redirect_stdout(io.StringIO()):
            sfl.build_lifecycle_ledger()
        with open(self.paths["LEDGER_JSON_FILE"], "r", encoding="utf-8") as f:
            return json.load(f)


class TestMultiVenueHoldings(_Base):
    def test_binance_holdings_land_in_ledger(self):
        """活动持仓面板有的，台账必须有（用户报障的直接症状）。"""
        other = ([
            {"venue": "binance", "instId": "ETH-USDT-SWAP", "posSide": "long", "pos": 0.275,
             "avgPx": 2538.5, "markPx": 2470.29, "upl": -18.59, "lever": 2, "fee": 0.0, "cTime": 0},
            {"venue": "binance", "instId": "SUI-USDT-SWAP", "posSide": "short", "pos": 569.4,
             "avgPx": 0.7287, "markPx": 0.7495, "upl": 11.86, "lever": 2, "fee": 0.0, "cTime": 0},
        ], {"binance"})
        ledger = self._build(other=other)
        hold = {t["id"]: t for t in ledger if t.get("status") == "holding"}
        self.assertIn("holding_binance_ETH_多", hold)
        self.assertIn("holding_binance_SUI_空", hold)
        self.assertEqual(len(hold), 2)
        self.assertEqual(hold["holding_binance_ETH_多"]["venue"], "binance")
        self.assertEqual(hold["holding_binance_SUI_空"]["side"], "空")
        self.assertAlmostEqual(hold["holding_binance_ETH_多"]["net_pnl"], -18.59, places=2)

    def test_ghost_holding_purged_when_venue_has_no_position(self):
        """OKX 平仓后旧 holding 行必须消失（实测幽灵 holding_ALGO_多 / venue=okx）。"""
        self._seed_ledger([{
            "id": "holding_ALGO_多", "inst": "ALGO", "side": "多", "venue": "okx",
            "status": "holding", "sz": 473.0, "open_px": 0.0934, "close_px": 0.0926,
            "close_time": "持仓中...", "net_pnl": -0.38,
        }])
        ledger = self._build(okx_positions=(), other=([], {"binance", "gate"}))
        ids = {t["id"] for t in ledger}
        self.assertNotIn("holding_ALGO_多", ids, "幽灵持仓必须被清理")
        self.assertEqual([t for t in ledger if t.get("status") == "holding"], [])

    def test_failed_venue_keeps_old_holdings(self):
        """取数失败的场所不得清行：缺失≠已平仓（保守留旧行，宁多勿删）。"""
        self._seed_ledger([{
            "id": "holding_binance_ETH_多", "inst": "ETH", "side": "多", "venue": "binance",
            "status": "holding", "sz": 0.275, "open_px": 2538.5, "close_px": 2470.29,
            "close_time": "持仓中...", "net_pnl": -18.59,
        }])
        # binance 取数失败（ok_venues 空）→ 旧行原样保留
        ledger = self._build(okx_positions=(), other=([], set()))
        ids = {t["id"] for t in ledger}
        self.assertIn("holding_binance_ETH_多", ids, "取数失败时旧持仓行必须保留")

    def test_okx_holdings_still_built(self):
        """回归：OKX 自己的活动持仓仍要照常入账。"""
        ledger = self._build(okx_positions=[_okx_pos("BTC", "short", 0.01, 77000.0, 5.0)],
                             other=([], {"binance", "gate"}))
        hold = [t for t in ledger if t.get("status") == "holding"]
        self.assertEqual(len(hold), 1)
        self.assertEqual(hold[0]["id"], "holding_okx_BTC_空")
        self.assertEqual(hold[0]["venue"], "okx")


class TestHoldingRowBuilder(unittest.TestCase):
    """行构造器：场所进 id（多所同标的防撞键）+ 净模式判向 + 白名单 + 零仓丢弃。"""

    def setUp(self):
        okx_runtime.freeze_environment(dict(DEMO_VALUES))
        self.addCleanup(okx_runtime.unfreeze_environment)

    def _row(self, **kw):
        base = dict(env=_env(), trackers={}, tz_bj=sfl.datetime.timezone(sfl.datetime.timedelta(hours=8)),
                    allowed={"ETH-USDT-SWAP"}, council_by_inst={})
        base.update(kw)
        return sfl._holding_row(base.pop("p"), base.pop("venue"), **base)

    def test_id_contains_venue(self):
        p = _okx_pos("ETH", "long", 1.0, 100.0)
        a = self._row(p=dict(p), venue="okx")
        b = self._row(p=dict(p), venue="binance")
        self.assertNotEqual(a["id"], b["id"], "多所同标同向必须区分，否则合并撞键")
        self.assertEqual(a["id"], "holding_okx_ETH_多")
        self.assertEqual(b["id"], "holding_binance_ETH_多")

    def test_net_mode_side_falls_back_to_sign(self):
        """审计 C8 不回退：net 模式无 posSide，按符号判向，不可判标未知。"""
        row = self._row(p=_okx_pos("ETH", "net", 2.0, 100.0), venue="binance")
        # posSide="net" 不含 long/short → 符号回退；pos 为正 → 多
        self.assertEqual(row["side"], "多")

    def test_zero_pos_and_not_allowed_dropped(self):
        self.assertIsNone(self._row(p=_okx_pos("ETH", "long", 0.0, 100.0), venue="okx"))
        self.assertIsNone(self._row(p=_okx_pos("BTC", "long", 1.0, 100.0), venue="okx"))

    def test_missing_ctime_renders_dash_not_fake_time(self):
        p = _okx_pos("ETH", "long", 1.0, 100.0)
        p["cTime"] = 0
        self.assertEqual(self._row(p=p, venue="binance")["open_time"], "--", "缺失≠随便编个时间")


if __name__ == "__main__":
    unittest.main()
