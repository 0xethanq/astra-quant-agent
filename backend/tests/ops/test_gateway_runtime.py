"""Model telemetry privacy and encrypted secret-store tests."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import astra_gateway.secrets as secrets
import astra_gateway.telemetry as telemetry
from astra_gateway.store import GatewayStore


class GatewayRuntimePrivacyTests(unittest.TestCase):
    def test_telemetry_never_persists_prompt_content(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "gateway.db"
            system_prompt = "PRIVATE_SYSTEM_PROMPT_123"
            user_prompt = "PRIVATE_USER_PROMPT_456"
            with patch.object(telemetry, "DB_PATH", db):
                call = telemetry.ModelCallTelemetry("trading_brain", "model", "high", system_prompt, user_prompt)
                call.finish("success", {"usage": {"total_tokens": 12}}, output_chars=42)
            raw = db.read_bytes()
            self.assertNotIn(system_prompt.encode(), raw)
            self.assertNotIn(user_prompt.encode(), raw)
            record = GatewayStore(db).model_calls()[0]
            self.assertEqual(record["prompt_transport"], "python-direct")
            self.assertEqual(record["input_chars"], len(system_prompt) + len(user_prompt))

    def test_telemetry_failure_is_non_fatal(self):
        call = telemetry.ModelCallTelemetry("trading_brain", "model", "high", "s", "u")
        with patch("astra_gateway.telemetry.GatewayStore", side_effect=OSError("disk")):
            call.finish("failed", error=RuntimeError("model"))

    def test_secret_store_encrypts_and_uses_0600(self):
        with tempfile.TemporaryDirectory() as td:
            original_key, original_store = secrets.KEY_FILE, secrets.STORE_FILE
            secrets.KEY_FILE = Path(td) / ".key"
            secrets.STORE_FILE = Path(td) / "secrets.enc"
            try:
                secrets.save_secrets({"LLM_API_KEY": "PRIVATE-KEY-123", "NOT_ALLOWED": "ignored"})
                self.assertNotIn(b"PRIVATE-KEY-123", secrets.STORE_FILE.read_bytes())
                self.assertEqual(secrets.load_secrets(), {"LLM_API_KEY": "PRIVATE-KEY-123"})
                self.assertEqual(secrets.KEY_FILE.stat().st_mode & 0o777, 0o600)
                self.assertEqual(secrets.STORE_FILE.stat().st_mode & 0o777, 0o600)
            finally:
                secrets.KEY_FILE, secrets.STORE_FILE = original_key, original_store


class PromptCacheTelemetryTests(unittest.TestCase):
    """前缀缓存三态必须落库可分（2026-09-29）。

    事故形状：上游 `/chat/completions` 在**没有命中**时整段省略缓存字段，而旧遥测把它
    和真正的"上报为 0"都打印成「缓存: 0」——于是"还是 0 缓存"既不能证实也不能证伪，
    也没有任何持久化记录可以回看。本组用例把三态钉死在库表里。
    """

    def _record(self, usage: dict, status: str = "success") -> dict:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "gateway.db"
            with patch.object(telemetry, "DB_PATH", db):
                call = telemetry.ModelCallTelemetry("trading_brain", "gemini-3.8-flash", "high", "SYS", "USER")
                call.finish(status, {"usage": usage}, output_chars=12)
            return GatewayStore(db).model_calls()[0]

    def test_hit_persists_cached_tokens_and_status(self):
        row = self._record({"prompt_tokens": 1000, "completion_tokens": 5, "cached_tokens": 4076,
                            "cache_reported": True})
        self.assertEqual(row["cached_tokens"], 4076)
        self.assertEqual(row["cache_status"], "hit")

    def test_reported_zero_is_a_miss_not_unreported(self):
        row = self._record({"prompt_tokens": 1000, "completion_tokens": 5, "cached_tokens": 0,
                            "cache_reported": True})
        self.assertEqual(row["cached_tokens"], 0)
        self.assertEqual(row["cache_status"], "miss", "上游明确上报 0 ⇒ miss，不是 unreported")

    def test_absent_field_is_unreported(self):
        row = self._record({"prompt_tokens": 1000, "completion_tokens": 5})
        self.assertEqual(row["cache_status"], "unreported", "上游没上报 ⇒ 不可判定，绝不伪装成 0")
        self.assertEqual(row["cached_tokens"], 0)

    def test_usage_keys_are_persisted_but_never_prompt_content(self):
        row = self._record({"prompt_tokens": 10, "completion_tokens": 1,
                            "prompt_tokens_details": {"cached_tokens": 4}, "cache_reported": True})
        self.assertIn("prompt_tokens_details", row["usage_keys"])
        self.assertNotIn("SYS", row["usage_keys"])
        self.assertNotIn("USER", row["usage_keys"])

    def test_failed_call_has_empty_cache_status(self):
        row = self._record({}, status="failed")
        self.assertEqual(row["cache_status"], "")


class ModelStatsCacheAggregateTests(unittest.TestCase):
    def test_hit_rate_is_none_when_nothing_was_reported(self):
        with tempfile.TemporaryDirectory() as td:
            store = GatewayStore(Path(td) / "gateway.db")
            store.record_model_call({"caller": "c", "model": "m", "reasoning_effort": "high",
                                     "status": "success", "started_at": "2026-09-29 12:00:00",
                                     "duration_ms": 1, "input_chars": 1, "output_chars": 1,
                                     "prompt_fingerprint": "f", "prompt_transport": "python-direct", "total_tokens": 10,
                                     "error_type": "", "usage_keys": "prompt_tokens",
                                     "cached_tokens": 0, "cache_status": "unreported"})
            stats = store.model_stats()
        self.assertEqual(stats["cache_reporting_calls"], 0)
        self.assertIsNone(stats["cache_hit_rate"], "一次上报都没有 ⇒ 命中率不可判定（None），不是 0")

    def test_hit_rate_counts_only_reported_calls(self):
        with tempfile.TemporaryDirectory() as td:
            store = GatewayStore(Path(td) / "gateway.db")
            base = {"caller": "c", "model": "m", "reasoning_effort": "high", "status": "success",
                    "started_at": "2026-09-29 12:00:00", "duration_ms": 1, "input_chars": 1,
                    "output_chars": 1, "prompt_fingerprint": "f", "prompt_transport": "python-direct", "total_tokens": 10,
                    "error_type": "", "usage_keys": ""}
            store.record_model_call({**base, "cached_tokens": 4076, "cache_status": "hit"})
            store.record_model_call({**base, "cached_tokens": 0, "cache_status": "miss"})
            store.record_model_call({**base, "cached_tokens": 0, "cache_status": "unreported"})
            stats = store.model_stats()
        self.assertEqual(stats["cache_hit_calls"], 1)
        self.assertEqual(stats["cache_reporting_calls"], 2, "unreported 不进分母")
        self.assertEqual(stats["cache_hit_rate"], 50.0)
        self.assertEqual(stats["cached_tokens_total"], 4076)


class LegacyModelCallsMigrationTests(unittest.TestCase):
    def test_old_table_gains_cache_columns_in_place(self):
        """老库必须**原地补列**：里面存着全部调用遥测，不能重建。"""
        import sqlite3
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "gateway.db"
            legacy = sqlite3.connect(db)
            legacy.execute(
                """CREATE TABLE model_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, caller TEXT NOT NULL,
                   model TEXT NOT NULL, reasoning_effort TEXT NOT NULL, status TEXT NOT NULL,
                   started_at TEXT NOT NULL, duration_ms INTEGER NOT NULL, input_chars INTEGER NOT NULL,
                   output_chars INTEGER NOT NULL, prompt_fingerprint TEXT NOT NULL,
                   prompt_transport TEXT NOT NULL DEFAULT 'python-direct', input_tokens INTEGER,
                   output_tokens INTEGER, total_tokens INTEGER, error_type TEXT NOT NULL DEFAULT '')"""
            )
            legacy.execute("INSERT INTO model_calls(caller,model,reasoning_effort,status,started_at,"
                           "duration_ms,input_chars,output_chars,prompt_fingerprint,total_tokens)"
                           " VALUES ('old','m','high','success','2026-09-01 00:00:00',5,1,1,'f',9)")
            legacy.commit()
            legacy.close()

            store = GatewayStore(db)
            rows = store.model_calls()
            self.assertEqual(len(rows), 1, "老数据必须还在")
            self.assertEqual(rows[0]["cached_tokens"] if rows[0]["cached_tokens"] is not None else 0, 0)
            self.assertEqual(rows[0]["cache_status"], "")
            store.record_model_call({"caller": "c", "model": "m", "reasoning_effort": "high",
                                     "status": "success", "started_at": "2026-09-29 12:00:00",
                                     "duration_ms": 1, "input_chars": 1, "output_chars": 1,
                                     "prompt_fingerprint": "f", "prompt_transport": "python-direct", "error_type": "", "cached_tokens": 5,
                                     "cache_status": "hit", "usage_keys": "prompt_tokens"})
            self.assertEqual(store.model_calls()[0]["cache_status"], "hit")

    def test_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "gateway.db"
            GatewayStore(db)
            GatewayStore(db)
            GatewayStore(db)
            self.assertEqual(GatewayStore(db).model_stats()["total_calls"], 0)


if __name__ == "__main__":
    unittest.main()
