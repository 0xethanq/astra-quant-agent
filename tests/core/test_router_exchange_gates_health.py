"""交易所路由：健康度落盘解析。
"""

import json
import tempfile
import types
import unittest
from unittest import mock

from astra_backend.routers import exchanges as R


def _auth_off(test):
    for name in ("require_admin_header", "require_superadmin"):
        patcher = mock.patch.object(R, name, mock.Mock(), create=True)
        patcher.start()
        test.addCleanup(patcher.stop)


class VenueHealthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(R, "DATA_DIR", __import__("pathlib").Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch.object(R, "okx_env", types.SimpleNamespace(simulated=True),
                               create=True)
        p2.start()
        self.addCleanup(p2.stop)
        _auth_off(self)

    def _status(self):
        return R.admin_multi_exchange_status(x_astra_admin_token="t")

    def _write_health(self, payload):
        (__import__("pathlib").Path(self.tmp.name) / "venue_health.json").write_text(
            payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")

    def test_corrupt_health_file_degrades_to_empty(self):
        self._write_health("{ 坏")
        out = self._status()
        self.assertIsInstance(out, dict, "读不动也要给出响应，不炸")

    def test_okx_section_is_completed_with_testnet_and_latency(self):
        self._write_health({"venues": {"okx": {"avg_ms": None}}})
        with mock.patch("astra_backend.exchanges.diagnostics.diagnose_venue_connection",
                        return_value={"latency_ms": 42}):
            out = self._status()
        dumped = json.dumps(out, ensure_ascii=False, default=str)
        self.assertIn("42", dumped, "现场诊断出的延迟必须出现在响应里")
        self.assertIn('"testnet": true', dumped, "testnet 取 okx_env.simulated")

    def test_latency_diagnosis_failure_is_swallowed(self):
        self._write_health({"venues": {"okx": {}}})
        with mock.patch("astra_backend.exchanges.diagnostics.diagnose_venue_connection",
                        side_effect=RuntimeError("诊断也挂了")):
            out = self._status()
        self.assertIsInstance(out, dict, "诊断失败不影响整体响应")


def _roster(*names):
    return [{"instId": f"{n}-USDT-SWAP", "name": n} for n in names]


def _cache(names, age=3.0, price=1.0):
    return {"data_health": {"cache_age_seconds": age},
            "factors": [{"name": n, "instId": f"{n}-USDT-SWAP", "price": price} for n in names]}


class PoolHealthProjectionTest(unittest.TestCase):
    """健康名单**只**来自「标的池 × 实时行情证据」（2026-09-30 真机事故回归）。

    事故原样：写 `venue_health.json` 里 `venues.okx.ok` 的 `scripts/brain/xvenue.py`
    在 OKX 专用化提交里被删除，但两个路由只把 `avg_ms/testnet/updated_utc` 叠写在旧
    blob 上 ⇒ 名单冻结在 9 个标的（含早已移除的 UNI），面板整天显示 `9/9 币`全绿。
    因此本组用例的牙齿是：**遗留名单里出现的标的，若不在池内，绝不许进入响应。**
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(R, "DATA_DIR", __import__("pathlib").Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        p2 = mock.patch.object(R, "okx_env", types.SimpleNamespace(simulated=True), create=True)
        p2.start()
        self.addCleanup(p2.stop)
        _auth_off(self)
        # 离线测试缝：绝不读生产池/生产缓存
        self._patch_seam(_roster("BTC", "ETH", "SOL"), _cache(["BTC", "ETH", "SOL"]))

    def _patch_seam(self, roster, cache):
        for name, value in (("_pool_roster", roster), ("_market_cache", cache)):
            patcher = mock.patch.object(R, name, mock.Mock(return_value=value), create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _okx(self):
        out = R.admin_multi_exchange_status(x_astra_admin_token="t")
        return out["health"]["venues"]["okx"]

    def _write_health(self, payload):
        (__import__("pathlib").Path(self.tmp.name) / "venue_health.json").write_text(
            json.dumps(payload), encoding="utf-8")

    def test_legacy_roster_cannot_leak_into_the_card(self):
        """僵尸快照里写着 UNI（不在池内）⇒ 响应里**不得**出现 UNI（本 bug 的牙齿）。"""
        self._write_health({"updated_utc": "2026-09-30 10:00:00",
                            "venues": {"okx": {"ok": ["ADA", "UNI", "XRP"], "failed": {},
                                               "avg_ms": 120}}})
        h = self._okx()
        self.assertEqual(h["ok"], ["BTC", "ETH", "SOL"])
        self.assertEqual(h["total"], 3, "total 必须等于池容量，而不是遗留名单长度")
        self.assertNotIn("UNI", json.dumps(h, ensure_ascii=False), "遗留名单漏进了面板")

    def test_total_follows_the_pool_not_the_snapshot(self):
        self._patch_seam(_roster("BTC", "ETH", "SOL", "XRP", "DOGE", "ARB"),
                         _cache(["BTC", "ETH", "SOL", "XRP", "DOGE", "ARB"]))
        h = self._okx()
        self.assertEqual(h["total"], 6)
        self.assertEqual(len(h["ok"]), 6)
        self.assertEqual(h["unknown"], [])
        self.assertTrue(set(h["ok"]) <= {"BTC", "ETH", "SOL", "XRP", "DOGE", "ARB"})

    def test_stale_or_missing_snapshot_is_unverified_never_green(self):
        for cache in (_cache(["BTC", "ETH", "SOL"], age=5000.0),
                      {"data_health": {}, "factors": [{"name": "BTC", "price": 1.0}]},
                      None):
            with self.subTest(cache=str(cache)[:40]):
                self._patch_seam(_roster("BTC", "ETH", "SOL"), cache)
                h = self._okx()
                self.assertEqual(h["ok"], [], "读不到/过期不得算作可用")
                self.assertEqual(sorted(h["unknown"]), ["BTC", "ETH", "SOL"])
                self.assertEqual(h["total"], 3, "未核实时 total 仍是池容量（前端显示 n/3）")

    def test_untrusted_pool_shows_no_roster_at_all(self):
        self._patch_seam([], _cache(["BTC"]))
        h = self._okx()
        self.assertEqual(h["total"], 0)
        self.assertEqual((h["ok"], h["failed"], h["unknown"]), ([], [], []))
        self.assertIn("标的池不可信", h["note"])

    def test_missing_symbol_row_is_failed_not_ok(self):
        self._patch_seam(_roster("BTC", "ETH", "SOL"), _cache(["BTC", "ETH"]))
        h = self._okx()
        self.assertEqual(h["ok"], ["BTC", "ETH"])
        self.assertEqual(h["failed"], ["SOL"], "池内有名、行情无据 ⇒ 必须单列")
        self.assertEqual(h["total"], 3)

    def test_zero_price_is_not_health(self):
        self._patch_seam(_roster("BTC", "ETH"), _cache(["BTC"], price=0.0))
        h = self._okx()
        self.assertEqual(h["ok"], [])
        self.assertEqual(sorted(h["failed"]), ["BTC", "ETH"])

    def test_projection_failure_hides_the_roster_instead_of_falling_back(self):
        patcher = mock.patch.object(R, "_pool_roster",
                                    mock.Mock(side_effect=RuntimeError("boom")), create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self._write_health({"venues": {"okx": {"ok": ["UNI"], "avg_ms": 100}}})
        h = self._okx()
        self.assertEqual(h["total"], 0)
        self.assertNotIn("UNI", json.dumps(h, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
