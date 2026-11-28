"""Comprehensive tests for AstraQuant built-in Strategy Ops Agent (L4 modules + HTTP/SSE API).

Covers all 8 modules under ``astra_backend/agent/`` and ``astra_backend/routers/agent.py``:
- ``astra_backend.agent.config`` (load/save, validation, runtime resolution)
- ``astra_backend.agent.store`` (SQLite WAL sessions, messages, proposals, cascade delete)
- ``astra_backend.agent.tools_read`` (redaction, state summary, read-only diagnostics)
- ``astra_backend.agent.tools_write`` (Diff proposal generation, high-risk & red-line guards)
- ``astra_backend.agent.tools_verify`` (live snapshot dry-run preview, fail-closed backtest compare)
- ``astra_backend.agent.llm_stream`` (OpenAI Chat / Responses / Claude SSE + ReAct fallback)
- ``astra_backend.agent.proposals`` (partial apply, phrase confirmation, snapshot, audit)
- ``astra_backend.agent.engine`` (multi-round tool orchestration, RBAC enforcement)
- ``astra_backend.routers.agent`` (FastAPI HTTP/SSE endpoints & superadmin vs admin RBAC)
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import astra_backend.app as app_module
import astra_backend.policy.paths  # noqa: F401
import evolution_shield  # noqa: F401
import prompt_library  # noqa: F401
import scripts.evolution_shield  # noqa: F401
import scripts.prompt_library  # noqa: F401
from astra_backend.admin_auth import AdminAuthStore
from astra_backend import risk_config
from astra_backend.agent import config as agent_config
from astra_backend.agent import engine as agent_engine
from astra_backend.agent import llm_stream as agent_llm_stream
from astra_backend.agent import proposals as agent_proposals
from astra_backend.agent import store as agent_store
from astra_backend.agent import tools_read as agent_tools_read
from astra_backend.agent import tools_verify as agent_tools_verify
from astra_backend.agent import tools_write as agent_tools_write
from astra_backend.config import refresh_settings
from astra_backend.routers import agent as agent_router
from scripts.risk_constants import RISK_ENV_KEYS
from tests.config_sandbox import isolate_config


class _SandboxMixin:
    def _init_sandbox(self) -> None:
        import astra_backend.settings_store as ss

        risk_snapshot = {k: os.environ.get(k) for k in RISK_ENV_KEYS}
        for k in RISK_ENV_KEYS:
            os.environ.pop(k, None)

        self.root = Path(isolate_config(self))
        self.env_file = self.root / ".env"
        self.env_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.env_file.exists():
            self.env_file.write_text("", encoding="utf-8")

        orig_env_file = ss.ENV_FILE
        ss.ENV_FILE = self.env_file
        self.addCleanup(setattr, ss, "ENV_FILE", orig_env_file)

        self._set_env("ASTRA_AGENT_DB", str(self.root / "data" / "astra_agent.db"))
        self._set_env("ASTRA_AGENT_CONFIG_FILE", str(self.root / "data" / "agent_config.json"))
        self._set_env("ASTRA_AUDIT_FILE", str(self.root / "logs" / "astra_admin_audit.jsonl"))

        def _restore_risk() -> None:
            for rk, rv in risk_snapshot.items():
                if rv is None:
                    os.environ.pop(rk, None)
                else:
                    os.environ[rk] = rv
            refresh_settings()
            risk_config.reload_risk_constants()

        self.addCleanup(_restore_risk)
        refresh_settings()
        risk_config.reload_risk_constants()

    def _set_env(self, key: str, value: str) -> None:
        prev = os.environ.get(key)
        os.environ[key] = value

        def _restore() -> None:
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

        self.addCleanup(_restore)


class _AgentSandboxCase(_SandboxMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._init_sandbox()


class _AgentAsyncSandboxCase(_SandboxMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._init_sandbox()


class _FakeStreamResponse:
    def __init__(self, status_code: int = 200, lines: list[str] | None = None, body: str = "", content_type: str = "text/event-stream"):
        self.status_code = status_code
        self._lines = lines or []
        self._body = body
        self.headers = {"content-type": content_type}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aread(self) -> bytes:
        return self._body.encode("utf-8")

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln


class _FakeAsyncClient:
    def __init__(self, response: _FakeStreamResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method: str, url: str, headers=None, json=None):
        return self._response


class AgentConfigAndStoreTests(_AgentSandboxCase):
    def test_config_defaults_save_validation_and_runtime_resolution(self) -> None:
        cfg = agent_config.load_agent_config()
        self.assertEqual(cfg["model_id"], "auto")
        self.assertEqual(cfg["reasoning_effort"], agent_config.DEFAULT_EFFORT)

        fake_models = [
            {
                "id": "gpt-test",
                "name": "GPT Test",
                "provider_id": "openai",
                "provider_name": "OpenAI",
                "api_format": "openai_chat",
                "reasoning_effort": "medium",
                "capabilities": ["chat"],
                "status": "ready",
            }
        ]
        with patch.object(agent_config, "_safe_available_models", return_value=fake_models):
            saved = agent_config.save_agent_config({
                "model_id": "gpt-test",
                "reasoning_effort": "high",
                "max_tool_rounds": 10,
            })
            self.assertEqual(saved["model_id"], "gpt-test")
            self.assertEqual(saved["reasoning_effort"], "high")
            self.assertEqual(saved["max_tool_rounds"], 10)

            with self.assertRaises(ValueError):
                agent_config.save_agent_config({"model_id": "unregistered-model"})
            with self.assertRaises(ValueError):
                agent_config.save_agent_config({"reasoning_effort": "invalid-effort"})
            with self.assertRaises(ValueError):
                agent_config.save_agent_config({"max_tool_rounds": 99})

        with patch("astra_backend.llm_manager.get_active_llm_runtime", return_value={"model": "main-m", "api_format": "openai_chat"}):
            with patch("astra_backend.llm_manager.resolve_model_runtime", return_value=None):
                rt = agent_config.resolve_agent_llm_runtime({"model_id": "auto", "reasoning_effort": "low"})
                self.assertEqual(rt["model"], "main-m")
                self.assertEqual(rt["reasoning_effort"], "low")
                self.assertFalse(rt["agent_dedicated"])

        with patch("astra_backend.llm_manager.get_active_llm_runtime", return_value={}):
            with patch("astra_backend.llm_manager.resolve_model_runtime", return_value=None):
                with self.assertRaises(RuntimeError):
                    agent_config.resolve_agent_llm_runtime({"model_id": "auto"})

    def test_store_crud_and_cascade_delete(self) -> None:
        store = agent_store.AgentStore()
        self.assertEqual(store.resolved_path().resolve(), Path(os.environ["ASTRA_AGENT_DB"]).resolve())

        sess = store.create_session(actor="alice", title="风控检查", model_id="auto")
        self.assertTrue(sess["id"].startswith("sess_"))
        self.assertEqual(len(store.list_sessions()), 1)

        renamed = store.rename_session(sess["id"], title="复盘诊断")
        self.assertEqual(renamed["title"], "复盘诊断")

        msg = store.append_message(
            sess["id"],
            role="assistant",
            content="检查完成",
            reasoning="先看风控再看台账",
            tool_calls=[{"id": "tc1", "name": "get_risk_config", "status": "ok"}],
            proposal_ids=[],
        )
        self.assertEqual(msg["content"], "检查完成")
        self.assertEqual(len(store.list_messages(sess["id"])), 1)

        prop = store.create_proposal(
            sess["id"],
            title="调整风控",
            items=[{"id": "i1", "domain": "risk", "action": "update", "title": "Lever"}],
            actor="alice",
        )
        self.assertEqual(prop["status"], "pending")
        self.assertEqual(len(store.list_proposals(sess["id"])), 1)

        self.assertTrue(store.delete_session(sess["id"]))
        self.assertIsNone(store.get_session(sess["id"]))
        self.assertEqual(store.list_messages(sess["id"]), [])
        self.assertEqual(store.list_proposals(sess["id"]), [])


class AgentToolsReadVerifyTests(_AgentSandboxCase):
    def test_redact_text_and_read_tools(self) -> None:
        redacted = agent_tools_read._redact_text(
            "Authorization: Bearer abcdef123456 sk-secretkey987654 api_key='tok_live_secret_value'"
        )
        self.assertNotIn("abcdef123456", redacted)
        self.assertNotIn("secretkey987654", redacted)
        self.assertNotIn("tok_live_secret_value", redacted)

        ledger_file = self.root / "data" / "trading_ledger.json"
        ledger_file.parent.mkdir(parents=True, exist_ok=True)
        ledger_file.write_text(
            json.dumps([
                {"inst": "BTC-USDT-SWAP", "side": "long", "status": "closed", "net_pnl": 120.5},
                {"inst": "BTC-USDT-SWAP", "side": "short", "status": "closed", "net_pnl": -40.5},
            ]),
            encoding="utf-8",
        )

        perf = agent_tools_read.execute_read_tool("get_trade_performance_and_ledger", {"symbol": "BTC"})
        self.assertEqual(perf["total_closed_trades"], 2)
        self.assertEqual(perf["win_rate_pct"], 50.0)
        self.assertEqual(perf["total_net_pnl_usdt"], 80.0)

        risk = agent_tools_read.execute_read_tool("get_risk_config", {})
        self.assertIn("current_values", risk)
        self.assertIn("HIGH_RISK_PHRASE", dir(risk_config))

        prompt_lib = agent_tools_read.execute_read_tool("get_prompt_library", {"include_content": True})
        self.assertIn("allowed_variables", prompt_lib)
        self.assertIn("template_variables", prompt_lib)

        summary = agent_tools_read.build_state_summary()
        for key in ("environment", "version", "risk", "prompt", "council", "instruments", "trading_session", "evolution", "policy"):
            self.assertIn(key, summary)

        with self.assertRaises(ValueError):
            agent_tools_read.execute_read_tool("nonexistent_tool", {})

    def test_verify_tools_dry_run_and_fail_closed_backtest(self) -> None:
        market_text, meta = agent_tools_verify._build_live_snapshot_market_context()
        self.assertIn("因子快照不可用", market_text)
        self.assertGreaterEqual(len(meta["missing"]), 1)

        with patch("scripts.backtest_engine.fetch_okx_candles", return_value=[]):
            bt = agent_tools_verify.execute_verify_tool(
                "backtest_risk_comparison",
                {"candidate_risk_values": {"ASTRA_MIN_ENTRY_CONFIDENCE": 82}},
            )
            self.assertFalse(bt["ok"])
            self.assertIn("OKX", bt["error"])

        with patch(
            "astra_backend.llm_manager.execute_llm_request",
            return_value=('{"action":"WAIT","reason":"choppy"}', "thinking", {"total_tokens": 20}, 123),
        ):
            preview = agent_tools_verify.execute_verify_tool(
                "dry_run_decision_preview",
                {"mode": "single", "custom_market_prompt": "BTC=90000"},
            )
            self.assertTrue(preview["ok"])
            self.assertEqual(preview["candidate_output"]["action"], "WAIT")


class AgentWriteProposalsAndApprovalTests(_AgentSandboxCase):
    def test_redlines_and_proposal_item_generation(self) -> None:
        names = {t["name"] for t in agent_tools_write.WRITE_TOOL_SCHEMAS}
        self.assertTrue(all(n.startswith("propose_") for n in names))
        for forbidden_substr in ("secret", "api_key", "live_switch", "close_position", "trade", "password", "backup"):
            self.assertFalse(any(forbidden_substr in n for n in names), f"Schema 违背安全红线: {names}")

        cur_lev = float(risk_config.current_values().get("ASTRA_MAX_LEVERAGE", 5.0))
        target_lev = 4.0 if abs(cur_lev - 4.0) > 0.1 else 3.0
        normal_item = agent_tools_write.build_proposal_item(
            "propose_risk_update",
            {"values": {"ASTRA_MAX_LEVERAGE": target_lev}, "reason": "收敛杠杆"},
        )
        self.assertFalse(normal_item["high_risk"])
        self.assertEqual(normal_item["required_phrase"], "")
        self.assertEqual(normal_item["domain"], "risk")

        extreme_item = agent_tools_write.build_proposal_item(
            "propose_risk_update",
            {"values": {"ASTRA_SINGLE_ASSET_EQUITY_RATIO": 1.0}},
        )
        self.assertTrue(extreme_item["high_risk"])
        self.assertEqual(extreme_item["required_phrase"], risk_config.HIGH_RISK_PHRASE)

        with self.assertRaises(ValueError):
            agent_tools_write.build_proposal_item(
                "propose_instrument_change",
                {"action": "remove", "inst_id": "BTC-USDT-SWAP"},
            )

        mem_reset = agent_tools_write.build_proposal_item("propose_memory_mutation", {"action": "reset"})
        self.assertTrue(mem_reset["high_risk"])
        self.assertEqual(mem_reset["required_phrase"], "RESET MEMORY")

        # Risk reset proposal when custom risk override differs from DEFAULTS
        with patch.dict(os.environ, {"ASTRA_MAX_LEVERAGE": "7.5"}):
            reset_item = agent_tools_write.build_proposal_item("propose_risk_reset", {"reason": "还原默认值"})
            self.assertTrue(reset_item["high_risk"])
            self.assertEqual(reset_item["required_phrase"], "RESET RISK")

        add_prompt = agent_tools_write.build_proposal_item(
            "propose_prompt_edit",
            {
                "action": "add_module",
                "pipeline": "trading_system",
                "module_title": "Agent 补充纪律",
                "content": "避免在极端插针期间追单。",
            },
        )
        self.assertEqual(add_prompt["diff_type"], "text")
        self.assertIn("Agent 补充纪律", add_prompt["title"])

        # Locked readonly output schema cannot be mutated
        lib = agent_tools_read.execute_read_tool("get_prompt_library", {"pipeline": "trading_system"})
        locked = [m for m in (lib["pipelines"].get("trading_system") or []) if m.get("locked")]
        if locked:
            with self.assertRaises(ValueError):
                agent_tools_write.build_proposal_item(
                    "propose_prompt_edit",
                    {
                        "action": "edit_module",
                        "pipeline": "trading_system",
                        "module_id": locked[0]["id"],
                        "content": "illegal overwrite",
                    },
                )

    def test_apply_partial_selection_phrase_check_snapshot_and_reject(self) -> None:
        store = agent_store.AgentStore()
        sess = store.create_session(actor="admin", title="提案应用测试")

        cur_lev = float(risk_config.current_values().get("ASTRA_MAX_LEVERAGE", 5.0))
        target_lev = 4.0 if abs(cur_lev - 4.0) > 0.1 else 3.0
        item_safe = agent_tools_write.build_proposal_item(
            "propose_risk_update",
            {"values": {"ASTRA_MAX_LEVERAGE": target_lev}},
        )
        item_risky = agent_tools_write.build_proposal_item(
            "propose_risk_update",
            {"values": {"ASTRA_SINGLE_ASSET_EQUITY_RATIO": 1.0}},
        )
        prop = store.create_proposal(sess["id"], title="组合提案", items=[item_safe, item_risky], actor="admin")

        # Missing high-risk phrase when risky item is selected -> ValueError
        with self.assertRaises(ValueError):
            agent_proposals.apply_proposal(
                store,
                prop["id"],
                actor="admin",
                selected_item_ids=[item_safe["id"], item_risky["id"]],
                confirmations={},
            )

        # Partial selection (only item_safe) succeeds without high-risk phrase
        res = agent_proposals.apply_proposal(
            store,
            prop["id"],
            actor="admin",
            selected_item_ids=[item_safe["id"]],
            confirmations={},
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "applied")
        self.assertEqual(len(res["results"]), 1)
        self.assertTrue(res["snapshot_hash"])
        self.assertIn(f"ASTRA_MAX_LEVERAGE={target_lev}", self.env_file.read_text(encoding="utf-8"))

        audit_log = Path(os.environ["ASTRA_AUDIT_FILE"]).read_text(encoding="utf-8")
        self.assertIn('"via":"agent"', audit_log)
        self.assertIn(prop["id"], audit_log)

        # Double apply blocked
        with self.assertRaises(ValueError):
            agent_proposals.apply_proposal(store, prop["id"], actor="admin")

        # Reject flow & case-insensitive confirmation phrase lookup
        prop_high = store.create_proposal(sess["id"], title="高危提案", items=[item_risky], actor="admin")
        res_high = agent_proposals.apply_proposal(
            store,
            prop_high["id"],
            actor="admin",
            selected_item_ids=[item_risky["id"]],
            confirmations={risk_config.HIGH_RISK_PHRASE.lower(): risk_config.HIGH_RISK_PHRASE.lower()},
        )
        self.assertTrue(res_high["ok"])

        prop2 = store.create_proposal(sess["id"], title="待拒绝提案", items=[item_safe], actor="admin")
        rej = agent_proposals.reject_proposal(store, prop2["id"], actor="admin", reason="暂不修改")
        self.assertTrue(rej["ok"])
        self.assertEqual(rej["proposal"]["status"], "rejected")


class AgentStreamAndEngineTests(_AgentAsyncSandboxCase):
    async def test_llm_stream_format_conversions_and_sse_parsing(self) -> None:
        tools = agent_tools_read.READ_TOOL_SCHEMAS[:1]
        self.assertEqual(agent_llm_stream._normalize_tools_for_format("claude_messages", tools)[0]["name"], tools[0]["name"])
        self.assertEqual(agent_llm_stream._normalize_tools_for_format("openai_responses", tools)[0]["type"], "function")
        self.assertEqual(agent_llm_stream._normalize_tools_for_format("openai_chat", tools)[0]["type"], "function")

        self.assertTrue(agent_llm_stream._should_fallback_react(400, "Unsupported parameter: tools"))
        self.assertFalse(agent_llm_stream._should_fallback_react(500, "internal server error"))
        self.assertEqual(
            agent_llm_stream._extract_json_block('```json\n{"final_answer": "done"}\n```'),
            {"final_answer": "done"},
        )

        # Mock OpenAI Chat streaming response with reasoning, text, and split tool_call chunks
        sse_lines = [
            'data: {"choices":[{"delta":{"reasoning_content":"check"}}]}',
            'data: {"choices":[{"delta":{"content":"hi"}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"get_risk_config","arguments":"{\\"group\\""}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":":\\"exposure\\"}"}}]}}]}',
            'data: {"usage":{"total_tokens":42}}',
            "data: [DONE]",
        ]
        runtime = {"model": "gpt-test", "base_url": "https://api.example.com/v1", "api_key": "sk-test", "api_format": "openai_chat"}
        with patch("httpx.AsyncClient", return_value=_FakeAsyncClient(_FakeStreamResponse(200, sse_lines))):
            events = [ev async for ev in agent_llm_stream.stream_llm_turn(runtime, [{"role": "user", "content": "hi"}], tools)]

        self.assertIn({"type": "reasoning_delta", "text": "check"}, events)
        self.assertIn({"type": "text_delta", "text": "hi"}, events)
        tool_ev = next(e for e in events if e["type"] == "tool_calls")
        self.assertEqual(tool_ev["calls"][0]["name"], "get_risk_config")
        self.assertEqual(tool_ev["calls"][0]["arguments"], {"group": "exposure"})

        # Mock 400 unsupported tools -> triggers ReAct JSON fallback
        with patch("httpx.AsyncClient", return_value=_FakeAsyncClient(_FakeStreamResponse(400, body="tools not supported"))):
            with patch("astra_backend.llm_manager.execute_llm_request", return_value=('{"final_answer":"react ok"}', "", {"total_tokens": 5}, 50)):
                fallback_evs = [ev async for ev in agent_llm_stream.stream_llm_turn(runtime, [{"role": "user", "content": "hi"}], tools)]
        self.assertIn({"type": "text_delta", "text": "react ok"}, fallback_evs)

    async def test_engine_runs_tools_creates_proposal_and_blocks_non_superadmin_write(self) -> None:
        store = agent_store.AgentStore()
        sess = store.create_session(actor="root", title="新会话")
        cur_lev = float(risk_config.current_values().get("ASTRA_MAX_LEVERAGE", 5.0))
        target_lev = 4.0 if abs(cur_lev - 4.0) > 0.1 else 3.0

        turn_counter = {"n": 0}

        async def _fake_stream_superadmin(runtime, messages, tools, **kwargs):
            turn_counter["n"] += 1
            if turn_counter["n"] == 1:
                yield {
                    "type": "tool_calls",
                    "calls": [
                        {"id": "c1", "name": "get_risk_config", "arguments": {}},
                        {"id": "c2", "name": "propose_risk_update", "arguments": {"values": {"ASTRA_MAX_LEVERAGE": target_lev}}},
                    ],
                }
            else:
                yield {"type": "text_delta", "text": "已生成风控调整提案。"}

        with patch.object(agent_engine, "resolve_agent_llm_runtime", return_value={"model": "m", "api_format": "openai_chat"}):
            with patch.object(agent_engine, "stream_llm_turn", side_effect=_fake_stream_superadmin):
                evs = [
                    ev async for ev in agent_engine.run_agent_chat(
                        store=store,
                        session_id=sess["id"],
                        user_message="请帮我分析风控并降低最大杠杆",
                        actor="root",
                        is_superadmin=True,
                    )
                ]

        etypes = [e["type"] for e in evs]
        self.assertIn("session_updated", etypes)
        self.assertIn("proposal", etypes)
        self.assertIn("done", etypes)
        self.assertEqual(len(store.list_proposals(sess["id"])), 1)

        # Non-superadmin cannot receive write tool schemas and write tool call is rejected even if hallucinated
        sess2 = store.create_session(actor="viewer", title="只读会话")
        seen_tools: list[str] = []

        async def _fake_stream_readonly(runtime, messages, tools, **kwargs):
            seen_tools.extend(t["name"] for t in tools)
            if len(seen_tools) <= len(agent_tools_read.READ_TOOL_SCHEMAS) + len(agent_tools_verify.VERIFY_TOOL_SCHEMAS):
                yield {"type": "tool_calls", "calls": [{"id": "c_bad", "name": "propose_risk_update", "arguments": {"values": {"ASTRA_MAX_LEVERAGE": target_lev}}}]}
            else:
                yield {"type": "text_delta", "text": "只读诊断。"}

        with patch.object(agent_engine, "resolve_agent_llm_runtime", return_value={"model": "m", "api_format": "openai_chat"}):
            with patch.object(agent_engine, "stream_llm_turn", side_effect=_fake_stream_readonly):
                ro_evs = [
                    ev async for ev in agent_engine.run_agent_chat(
                        store=store,
                        session_id=sess2["id"],
                        user_message="尝试调低杠杆",
                        actor="viewer",
                        is_superadmin=False,
                    )
                ]

        self.assertFalse(any(n.startswith("propose_") for n in seen_tools))
        tr = next(e for e in ro_evs if e["type"] == "tool_result" and e["id"] == "c_bad")
        self.assertEqual(tr["status"], "error")
        self.assertEqual(store.list_proposals(sess2["id"]), [])


class AgentRouterApiTests(_AgentSandboxCase):
    def setUp(self) -> None:
        super().setUp()
        orig_auth = app_module.admin_auth
        self._auth_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._auth_tmp.cleanup)
        self.auth_store = AdminAuthStore(Path(self._auth_tmp.name) / "admin_agent_test.db")
        self.auth_store.initialize_from_legacy("SuperSecret123456")
        self.auth_store.create_user("readonly_op", "OperatorSecret123", "admin")
        app_module.admin_auth = self.auth_store
        self.addCleanup(setattr, app_module, "admin_auth", orig_auth)
        self.client = TestClient(app_module.app)
        self.addCleanup(self.client.close)

    def _login(self, username: str, password: str) -> dict[str, str]:
        resp = self.client.post("/api/v1/admin/auth/login", json={"username": username, "password": password})
        self.assertEqual(resp.status_code, 200, resp.text)
        return {"X-Astra-Session": resp.json()["session_token"]}

    def test_rbac_config_sessions_chat_and_proposal_endpoints(self) -> None:
        # Unauthenticated rejected
        self.assertEqual(self.client.get("/api/v1/admin/agent/config").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/admin/agent/state-summary").status_code, 401)

        op_hdrs = self._login("readonly_op", "OperatorSecret123")
        su_hdrs = self._login("admin", "SuperSecret123456")

        # Read access for admin & superadmin
        self.assertEqual(self.client.get("/api/v1/admin/agent/config", headers=op_hdrs).status_code, 200)
        summary_res = self.client.get("/api/v1/admin/agent/state-summary", headers=op_hdrs)
        self.assertEqual(summary_res.status_code, 200)
        self.assertIn("risk", summary_res.json())

        # Admin blocked from modifying agent config
        self.assertEqual(
            self.client.put("/api/v1/admin/agent/config", headers=op_hdrs, json={"reasoning_effort": "low"}).status_code,
            403,
        )
        # Superadmin allowed
        put_res = self.client.put(
            "/api/v1/admin/agent/config",
            headers=su_hdrs,
            json={"reasoning_effort": "low", "max_tool_rounds": 6},
        )
        self.assertEqual(put_res.status_code, 200, put_res.text)
        self.assertEqual(put_res.json()["reasoning_effort"], "low")

        # Create session, invalid id checks, SSE chat
        sess_res = self.client.post("/api/v1/admin/agent/sessions", headers=su_hdrs, json={"title": "API测试"})
        self.assertEqual(sess_res.status_code, 200, sess_res.text)
        sid = sess_res.json()["session"]["id"]

        self.assertEqual(self.client.get("/api/v1/admin/agent/sessions/bad!id", headers=su_hdrs).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/admin/agent/sessions/sess_missing1234", headers=su_hdrs).status_code, 404)

        async def _fake_chat(store, session_id, user_message, actor, is_superadmin, model_override=None):
            yield {"type": "text_delta", "text": "hello"}
            yield {"type": "done", "message": {"id": 1, "content": "hello"}}

        with patch.object(agent_router, "run_agent_chat", side_effect=_fake_chat):
            chat_res = self.client.post(
                f"/api/v1/admin/agent/sessions/{sid}/chat",
                headers=su_hdrs,
                json={"message": "状态如何"},
            )
            self.assertEqual(chat_res.status_code, 200)
            self.assertIn('"type": "done"', chat_res.text)

        # Create proposal directly in shared router store and test apply/reject RBAC
        cur_lev = float(risk_config.current_values().get("ASTRA_MAX_LEVERAGE", 5.0))
        target_lev = 4.0 if abs(cur_lev - 4.0) > 0.1 else 3.0
        item = agent_tools_write.build_proposal_item("propose_risk_update", {"values": {"ASTRA_MAX_LEVERAGE": target_lev}})
        prop = agent_router._STORE.create_proposal(sid, title="API提案", items=[item], actor="admin")

        self.assertEqual(
            self.client.post(f"/api/v1/admin/agent/proposals/{prop['id']}/apply", headers=op_hdrs, json={}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(f"/api/v1/admin/agent/proposals/{prop['id']}/reject", headers=op_hdrs, json={}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/v1/admin/agent/proposals/bad!id/apply", headers=su_hdrs, json={}).status_code,
            400,
        )

        apply_res = self.client.post(
            f"/api/v1/admin/agent/proposals/{prop['id']}/apply",
            headers=su_hdrs,
            json={"selected_item_ids": [item["id"]]},
        )
        self.assertEqual(apply_res.status_code, 200, apply_res.text)
        self.assertTrue(apply_res.json()["ok"])

        # New endpoints: insights, inspector, and proposal rollback RBAC + execution
        self.assertEqual(self.client.get("/api/v1/admin/agent/insights").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/admin/agent/inspector").status_code, 401)

        ins_res = self.client.get("/api/v1/admin/agent/insights", headers=op_hdrs)
        self.assertEqual(ins_res.status_code, 200, ins_res.text)
        self.assertIn("health_score", ins_res.json())
        self.assertIn("insights", ins_res.json())

        insp_res = self.client.get("/api/v1/admin/agent/inspector", headers=op_hdrs)
        self.assertEqual(insp_res.status_code, 200, insp_res.text)
        for tab in ("overview", "risk", "prompt", "council", "snapshots"):
            self.assertIn(tab, insp_res.json())

        self.assertEqual(
            self.client.post(f"/api/v1/admin/agent/proposals/{prop['id']}/rollback", headers=op_hdrs).status_code,
            403,
        )
        rb_res = self.client.post(f"/api/v1/admin/agent/proposals/{prop['id']}/rollback", headers=su_hdrs)
        self.assertEqual(rb_res.status_code, 200, rb_res.text)
        self.assertTrue(rb_res.json()["proposal"]["rolled_back"])
        # Repeat rollback rejected
        self.assertEqual(
            self.client.post(f"/api/v1/admin/agent/proposals/{prop['id']}/rollback", headers=su_hdrs).status_code,
            400,
        )

    def test_v910_diagnostics_order_mode_rollback_and_parallel_telemetry(self) -> None:
        # 1. Four new read diagnostic tools work in sandbox
        funnel = agent_tools_read.execute_read_tool("diagnose_order_funnel", {"cycles": 10})
        self.assertIn("omitted_rate_pct", funnel)
        self.assertIn("gate_and_cancel_counts", funnel)

        conflicts = agent_tools_read.execute_read_tool("audit_strategy_conflicts", {})
        self.assertIn("conflicts", conflicts)
        self.assertIn("risk_audit", conflicts)

        debates = agent_tools_read.execute_read_tool("inspect_council_debates", {"cycles": 5})
        self.assertIn("council_rounds", debates)

        exec_view = agent_tools_read.execute_read_tool("inspect_order_execution_and_cancels", {"lines": 20})
        self.assertIn("order_mode", exec_view)

        # 2. propose_order_mode_update + apply + rollback
        store = agent_engine.AgentStore()
        sess = store.create_session(actor="root", title="v910测试")
        with patch.dict(os.environ, {"ASTRA_ORDER_MODE": "limit"}):
            om_item = agent_tools_write.build_proposal_item(
                "propose_order_mode_update",
                {"order_mode": "smart", "reason": "启用自适应撮合"},
            )
            self.assertEqual(om_item["domain"], "order_mode")
            prop = store.create_proposal(sess["id"], title="切换 smart", items=[om_item], actor="root")
            applied = agent_router.apply_proposal(store=store, proposal_id=prop["id"], actor="root")
            self.assertTrue(applied["ok"])
            self.assertEqual(os.environ.get("ASTRA_ORDER_MODE"), "smart")

            rolled = agent_router.rollback_proposal(store=store, proposal_id=prop["id"], actor="root")
            self.assertTrue(rolled["ok"])
            self.assertTrue(rolled["proposal"]["rolled_back"])
            self.assertEqual(os.environ.get("ASTRA_ORDER_MODE"), "limit")

        # 3. Parallel read execution & history context retention
        store.append_message(
            sess["id"],
            role="assistant",
            content="第一轮结论",
            tool_calls=[{"name": "diagnose_order_funnel", "summary": "遗漏率 0%"}],
            proposal_ids=[prop["id"]],
        )
        msgs_ctx = agent_engine._build_conversation_messages(
            store.list_messages(sess["id"]),
            True,
            proposals_by_id={prop["id"]: rolled["proposal"]},
        )
        joined = "\n".join(m["content"] for m in msgs_ctx)
        self.assertIn("历史工具摘要", joined)
        self.assertIn("已回滚", joined)

        async def _parallel_stream(runtime, messages, tools, **kwargs):
            if len(messages) == 2:
                yield {
                    "type": "tool_calls",
                    "calls": [
                        {"id": "p1", "name": "diagnose_order_funnel", "arguments": {}},
                        {"id": "p2", "name": "audit_strategy_conflicts", "arguments": {}},
                    ],
                }
            else:
                yield {"type": "text_delta", "text": "并行诊断完毕。"}

        async def _collect():
            with patch.object(agent_engine, "resolve_agent_llm_runtime", return_value={"model": "m", "api_format": "openai_chat"}):
                with patch.object(agent_engine, "stream_llm_turn", side_effect=_parallel_stream):
                    return [
                        ev async for ev in agent_engine.run_agent_chat(
                            store=store,
                            session_id=sess["id"],
                            user_message="检查并对比",
                            actor="root",
                            is_superadmin=True,
                        )
                    ]

        import asyncio
        evs = asyncio.run(_collect())
        trs = [e for e in evs if e["type"] == "tool_result"]
        self.assertEqual([t["id"] for t in trs], ["p1", "p2"])
        self.assertIn("duration_ms", trs[0])
        self.assertIn("result_preview", trs[0])


if __name__ == "__main__":
    unittest.main()
