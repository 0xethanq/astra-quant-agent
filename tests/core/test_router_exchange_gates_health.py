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


if __name__ == "__main__":
    unittest.main()
