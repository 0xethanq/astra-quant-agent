"""Unit tests for the public full ledger API endpoint."""

import unittest
from fastapi.testclient import TestClient
from astra_backend.app import app


class TestPublicLedgerApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_public_ledger_returns_trades_and_counts(self):
        resp = self.client.get("/api/v1/public/ledger")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("trades", data)
        self.assertIn("total", data)
        self.assertIn("closed_count", data)
        self.assertIn("holding_count", data)
        self.assertIn("db_total", data)
        self.assertIsInstance(data["trades"], list)
        self.assertEqual(data["total"], len(data["trades"]))
        # 不应受常规仪表盘 60 笔硬截断限制
        self.assertGreaterEqual(data["total"], 60)
        self.assertGreaterEqual(data["db_total"], 0)

    def test_public_ledger_all_time_parameter(self):
        resp_cycle = self.client.get("/api/v1/public/ledger?all_time=0")
        resp_all = self.client.get("/api/v1/public/ledger?all_time=1")
        self.assertEqual(resp_cycle.status_code, 200)
        self.assertEqual(resp_all.status_code, 200)
        data_cycle = resp_cycle.json()
        data_all = resp_all.json()
        # 全量历史数量应大于或等于当前周期
        self.assertGreaterEqual(data_all["total"], data_cycle["total"])
        self.assertGreaterEqual(data_all["closed_count"], data_cycle["closed_count"])
