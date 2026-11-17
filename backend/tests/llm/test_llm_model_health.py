"""模型条目结构自检（`astra_backend/llm/model_health.py`）与两个新后台端点。

## 这组测试守什么

2026-09-29 实测后台配置：三条模型里两条是死的 —— `glm-5.3-flash` 真机 402 余额不足、
`gemini-3.1-flash-image` 无密钥且供应商不存在，而界面把三条并列显示、无任何标记，
`fallback_model_ids` 还是空的（等于没有回退）。这组测试把"**看得出哪条能用**"
钉住，并且钉住那条关键边界：

- 结构死（无密钥）⇒ `dead`，可被"一键清理"删除；
- **运行态挂**（402/限流/供应商停用）⇒ 最多 `warn`，**绝不判死、绝不删除** ——
  否则配置页会撒谎（充值后条目仍是"死"的）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import astra_backend.app as app_module
import astra_backend.llm_manager as llm_manager
from astra_backend.admin_auth import AdminAuthStore
from astra_backend.llm.model_health import audit_llm_config, audit_model_entry, dead_model_ids

FORMATS = ("openai_chat", "openai_responses", "claude_messages")


def _model(**over):
    base = {
        "id": "m-1", "name": "m-1", "provider_id": "p-1", "provider_name": "P",
        "base_url": "https://relay.example/v1", "api_key": "sk-x",
        "api_format": "openai_chat", "api_path": "/chat/completions",
    }
    base.update(over)
    return base


def _provider(**over):
    base = {"id": "p-1", "name": "P", "enabled": True, "base_url": "https://relay.example/v1",
            "api_key": "sk-provider", "api_format": "openai_chat", "api_path": "/chat/completions"}
    base.update(over)
    return base


class ModelEntryAuditTests(unittest.TestCase):
    def test_a_healthy_entry_is_ok(self):
        report = audit_model_entry(_model(), [_provider()], FORMATS, active_model_id="m-1")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["role"], "active")
        self.assertEqual(report["issues"], [])

    def test_a_key_from_the_provider_is_enough(self):
        """密钥唯一存放处是供应商（模型条目只是快照）—— 供应商有密钥就不算缺。"""
        report = audit_model_entry(_model(api_key=""), [_provider(api_key="sk-provider")], FORMATS)
        self.assertEqual(report["status"], "ok")

    def test_missing_key_everywhere_is_dead(self):
        report = audit_model_entry(_model(api_key=""), [_provider(api_key="")], FORMATS)
        self.assertEqual(report["status"], "dead")
        self.assertIn("no_api_key", {i["code"] for i in report["issues"]})

    def test_a_named_provider_that_vanished_is_only_a_warning(self):
        """条目自带端点与密钥就能直连 ⇒ 供应商不见了只提示，不判死。"""
        report = audit_model_entry(_model(provider_id="ghost", api_key="sk-x"), [_provider()], FORMATS)
        self.assertEqual(report["status"], "warn")
        self.assertIn("provider_missing", {i["code"] for i in report["issues"]})

    def test_the_custom_pseudo_provider_is_not_missing(self):
        report = audit_model_entry(_model(provider_id="custom"), [_provider()], FORMATS)
        self.assertEqual(report["status"], "ok")

    def test_a_disabled_provider_warns_but_never_dies(self):
        """停用是用户的选择、余额是运行态 —— 两者都不该让条目被判死删除。"""
        report = audit_model_entry(_model(api_key=""), [_provider(enabled=False, api_key="sk-p")], FORMATS)
        self.assertEqual(report["status"], "warn")
        self.assertIn("provider_disabled", {i["code"] for i in report["issues"]})
        self.assertNotIn("dead", {i["level"] for i in report["issues"]})

    def test_an_unknown_format_warns_and_is_auto_detected_at_runtime(self):
        report = audit_model_entry(_model(api_format="gemini_native"), [_provider()], FORMATS)
        self.assertIn("unsupported_format", {i["code"] for i in report["issues"]})
        self.assertEqual(report["status"], "warn")

    def test_a_standard_path_is_not_reported_but_a_custom_one_is(self):
        """标准路径会被 transport 主动清空（写了也无害）；只有非标准路径才真的改端点。"""
        self.assertEqual(audit_model_entry(_model(api_path="/chat/completions"), [_provider()], FORMATS)["status"], "ok")
        self.assertEqual(audit_model_entry(_model(api_path="/v1/responses"), [_provider()], FORMATS)["status"], "ok")
        custom = audit_model_entry(_model(api_path="/openai/v2/chat"), [_provider()], FORMATS)
        self.assertIn("custom_api_path", {i["code"] for i in custom["issues"]})
        self.assertEqual(custom["status"], "ok", "非标准路径是能力，不是缺陷")


class ConfigAuditTests(unittest.TestCase):
    def test_roles_and_counts(self):
        config = {
            "active_model_id": "a", "fallback_model_ids": ["b"], "request_attempts": 3,
            "providers": [_provider()],
            "models": [_model(id="a"), _model(id="b"), _model(id="c")],
        }
        report = audit_llm_config(config, FORMATS)
        self.assertEqual(report["models"]["a"]["role"], "active")
        self.assertEqual(report["models"]["b"]["role"], "fallback")
        self.assertEqual(report["models"]["c"]["role"], "dormant")
        self.assertEqual(report["counts"], {"ok": 3, "warn": 0, "dead": 0})

    def test_an_empty_fallback_chain_is_called_out(self):
        """每模型重试 3 次却没有回退模型 = 单点故障，必须显式提示。"""
        config = {"active_model_id": "a", "fallback_model_ids": [], "request_attempts": 3,
                  "providers": [_provider()], "models": [_model(id="a")]}
        report = audit_llm_config(config, FORMATS)
        self.assertIn("no_fallback_chain", {w["code"] for w in report["warnings"]})

    def test_a_single_attempt_needs_no_fallback(self):
        config = {"active_model_id": "a", "fallback_model_ids": [], "request_attempts": 1,
                  "providers": [_provider()], "models": [_model(id="a")]}
        self.assertEqual(audit_llm_config(config, FORMATS)["warnings"], [])

    def test_a_dead_fallback_does_not_count_as_a_safety_net(self):
        """回退链里挂着一条无密钥的模型 ≈ 没有回退 —— 提示不能因为"名单非空"就闭嘴。"""
        config = {"active_model_id": "a", "fallback_model_ids": ["z"], "request_attempts": 3,
                  "providers": [_provider()], "models": [_model(id="a"), _model(id="z", api_key="", provider_id="custom")]}
        report = audit_llm_config(config, FORMATS)
        self.assertIn("no_fallback_chain", {w["code"] for w in report["warnings"]})

    def test_duplicate_ids_keep_the_first_entry(self):
        """运行期按列表首个命中解析 ⇒ 报告与运行期同序。"""
        config = {"models": [_model(id="dup", api_key="sk"), _model(id="dup", api_key="")],
                  "providers": [_provider()]}
        report = audit_llm_config(config, FORMATS)
        self.assertEqual(report["models"]["dup"]["status"], "ok")

    def test_dead_ids_only_contain_structurally_dead_entries(self):
        config = {
            "providers": [_provider()],
            "models": [_model(id="ok"), _model(id="nokey", api_key="", provider_id="custom"),
                       _model(id="stopped", provider_id="p-off")],
            "active_model_id": "ok",
        }
        dead = dead_model_ids(audit_llm_config(config, FORMATS))
        self.assertIn("nokey", dead)
        self.assertNotIn("stopped", dead, "供应商停用 ≠ 条目结构死，删掉用户配置属越权")


class ModelHealthEndpointTests(unittest.TestCase):
    """端点级：GET /models 带自检、/test-all 跳过死条目、/cleanup 只删死条目。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp.name)
        self.orig_models_file = llm_manager.LLM_CONFIG_FILE
        self.orig_providers_file = llm_manager.LLM_PROVIDERS_FILE
        self.orig_legacy_file = llm_manager.LEGACY_PROVIDERS_FILE
        test_file = self.temp_path / "llm_models.json"
        llm_manager.LLM_CONFIG_FILE = test_file
        llm_manager.LLM_PROVIDERS_FILE = test_file
        llm_manager.LEGACY_PROVIDERS_FILE = self.temp_path / "absent_legacy.json"

        self.orig_auth = app_module.admin_auth
        app_module.admin_auth = AdminAuthStore(self.temp_path / "admin.db")
        app_module.admin_auth.initialize_from_legacy("TestAdminPass123456")

        self.patcher_env = patch("astra_backend.settings_store.update_env")
        self.patcher_secrets = patch("astra_gateway.secrets.save_secrets")
        self.patcher_env.start()
        self.patcher_secrets.start()
        self.addCleanup(self.patcher_env.stop)
        self.addCleanup(self.patcher_secrets.stop)
        self.addCleanup(self._restore)

        self.client = TestClient(app_module.app)
        self.headers = self._login()

    def _restore(self):
        llm_manager.LLM_CONFIG_FILE = self.orig_models_file
        llm_manager.LLM_PROVIDERS_FILE = self.orig_providers_file
        llm_manager.LEGACY_PROVIDERS_FILE = self.orig_legacy_file
        app_module.admin_auth = self.orig_auth
        self.temp.cleanup()

    def _login(self):
        resp = self.client.post("/api/v1/admin/auth/login",
                                json={"username": "admin", "password": "TestAdminPass123456"})
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"X-Astra-Session": resp.json()["session_token"]}

    def _seed(self, models, providers):
        llm_manager.LLM_CONFIG_FILE.write_text(
            json.dumps({"version": "3.2", "defaults_seeded": True, "active_model_id": models[0]["id"],
                        "active_reasoning_effort": "high", "request_attempts": 3,
                        "fallback_model_ids": [], "providers": providers, "models": models},
                       ensure_ascii=False), encoding="utf-8")

    def test_the_model_list_carries_the_self_check(self):
        self._seed([_model(id="good"), _model(id="dead", api_key="", provider_id="custom")],
                   [_provider()])
        resp = self.client.get("/api/v1/admin/llm/models", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        health = resp.json()["model_health"]
        self.assertEqual(health["models"]["good"]["status"], "ok")
        self.assertEqual(health["models"]["dead"]["status"], "dead")

    def test_test_all_skips_structurally_dead_entries_without_network(self):
        self._seed([_model(id="good"), _model(id="dead", api_key="", provider_id="custom")],
                   [_provider()])
        calls = []

        def _fake_test(**kwargs):
            calls.append(kwargs["model"])
            return {"ok": True, "status_code": 200, "latency_ms": 12,
                    "endpoint": "https://relay.example/v1/chat/completions"}

        with patch.object(app_module, "test_llm_connection", side_effect=_fake_test):
            resp = self.client.post("/api/v1/admin/llm/test-all", headers=self.headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        rows = {r["model"]: r for r in body["rows"]}
        self.assertEqual(calls, ["good"], "死条目不该浪费真机请求")
        self.assertTrue(rows["good"]["ok"])
        self.assertTrue(rows["dead"]["skipped"])
        self.assertIn("没有 API Key", rows["dead"]["error"])
        self.assertEqual(body["skipped"], 1)

    def test_a_runtime_failure_is_reported_but_not_written_into_the_config(self):
        """402 只代表此刻余额不足：真机结论绝不能落进配置（充值后条目仍是死的）。"""
        self._seed([_model(id="poor")], [_provider()])

        def _fake_test(**_kwargs):
            return {"ok": False, "status_code": 402, "latency_ms": 9,
                    "error": 'HTTP 402: {"code":"INSUFFICIENT_BALANCE"}'}

        with patch.object(app_module, "test_llm_connection", side_effect=_fake_test):
            resp = self.client.post("/api/v1/admin/llm/test-all", headers=self.headers)
        self.assertEqual(resp.json()["failed"], 1)
        stored = json.loads(llm_manager.LLM_CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("status", stored["models"][0])
        self.assertEqual(stored["models"][0]["id"], "poor", "条目必须原样保留")

    def test_cleanup_removes_only_structurally_dead_entries(self):
        self._seed([_model(id="good"), _model(id="dead", api_key="", provider_id="custom"),
                    _model(id="stopped", provider_id="p-off")],
                   [_provider(), _provider(id="p-off", enabled=False)])
        resp = self.client.post("/api/v1/admin/llm/models/cleanup", headers=self.headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["removed"], ["dead"])
        stored = json.loads(llm_manager.LLM_CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual([m["id"] for m in stored["models"]], ["good", "stopped"])

    def test_cleanup_never_deletes_the_active_model(self):
        """活跃模型即使缺密钥也不能被一键清理悄悄干掉（delete_model 会拒绝）。"""
        self._seed([_model(id="active-nokey", api_key="", provider_id="custom")], [_provider()])
        resp = self.client.post("/api/v1/admin/llm/models/cleanup", headers=self.headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["removed"], [])
        self.assertEqual(len(body["failed"]), 1)
        self.assertEqual(body["failed"][0]["model"], "active-nokey")


if __name__ == "__main__":
    unittest.main()
