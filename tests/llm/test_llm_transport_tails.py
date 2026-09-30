"""LLM 传输层（`astra_backend/llm/transport.py`）残余分支收口测试 —— 第 338 刀。

本模块 342 行，是单次模型调用的请求构建、发送与响应解析核心：
- 错误分类系统：瞬时故障（_LLMTransientError，支持指数退避与慢故障快速回退）与
  硬故障（_LLMHardError，不可重试直接切换候选模型）；
- 三协议请求组装：Claude Messages、OpenAI Responses、OpenAI Chat；
- 协议参数自适应降级：HTTP 400 参数冲突时的自适应重试（剥离 reasoning_effort/temperature）；
- 响应解析：多协议内容抽取、链式推演（thinking/reasoning）提取与 Token 用量统计。
"""
from __future__ import annotations

import json
import socket
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from astra_backend.llm.transport import (
    _LLMHardError,
    _LLMTransientError,
    _attempt_llm_call,
    _is_transient_http,
    _parse_llm_response,
    build_chat_payload,
    build_request_spec,
)


def _make_mock_response(payload: dict | list | str | bytes, code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.getcode.return_value = code
    if isinstance(payload, bytes):
        body = payload
    elif isinstance(payload, str):
        body = payload.encode("utf-8")
    else:
        body = json.dumps(payload).encode("utf-8")
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda *a: False
    return resp


def _make_http_error(code: int, body: str | bytes = b"", msg: str = "HTTP Error") -> urllib.error.HTTPError:
    err = urllib.error.HTTPError("http://test.api", code, msg, {}, None)
    if isinstance(body, str):
        body_bytes = body.encode("utf-8")
    else:
        body_bytes = body
    err.read = lambda: body_bytes
    return err


class LlmTransportTailsTests(unittest.TestCase):
    # -------------------------------------------------------------------------
    # 1. 瞬时错误与错误分类 (_is_transient_http)
    # -------------------------------------------------------------------------
    def test_is_transient_http_standard_codes(self):
        # 5xx 与特定 4xx 属于标称瞬时错误
        for code in (408, 409, 425, 429, 500, 502, 503, 504):
            with self.subTest(code=code):
                self.assertTrue(_is_transient_http(code, ""))

    def test_is_transient_http_client_errors_with_transient_markers(self):
        # 400-403 若带有 rate limit、overloaded 等提示，也视作瞬时可重试
        for code in (400, 401, 402, 403):
            with self.subTest(code=code):
                self.assertTrue(_is_transient_http(code, "Server is overloaded right now"))
                self.assertTrue(_is_transient_http(code, "Rate limit exceeded (too many requests)"))
                self.assertFalse(_is_transient_http(code, "Invalid API key or token"))

    def test_is_transient_http_non_transient_codes(self):
        self.assertFalse(_is_transient_http(404, "Not Found"))
        self.assertFalse(_is_transient_http(405, "Method Not Allowed"))

    # -------------------------------------------------------------------------
    # 2. 响应体解析 (_parse_llm_response)
    # -------------------------------------------------------------------------
    def test_parse_claude_messages_with_thinking_and_usage_fallback(self):
        res_json = {
            "content": [
                {"type": "thinking", "thinking": "Let me think..."},
                {"type": "text", "text": "Hello "},
                {"type": "text", "text": "World!"},
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
            },
        }
        content, reasoning, usage = _parse_llm_response("claude_messages", res_json)
        self.assertEqual(content, "Hello World!")
        self.assertEqual(reasoning, "Let me think...")
        self.assertEqual(usage.get("input_tokens"), 10)

    def test_parse_claude_messages_usage_computed_when_empty(self):
        res_json = {
            "content": [{"type": "text", "text": "Hi"}],
            "usage": {},
        }
        content, reasoning, usage = _parse_llm_response("claude_messages", res_json)
        self.assertEqual(content, "Hi")
        # 2026-09-29：usage 现在恒定带两个规范化标注 —— `cache_reported`（上游到底有没有
        # 上报缓存字段）与 `truncated`（finish/status 是否非完成态）。这里两者都必须为 False：
        # 没有缓存字段 ≠ 命中 0；没有 finish_reason ≠ 被截断。
        self.assertEqual(usage, {"total_tokens": 0, "cache_reported": False, "truncated": False})

    def test_parse_openai_responses_output_text(self):
        res_json = {
            "output_text": "Direct response text",
        }
        content, reasoning, usage = _parse_llm_response("openai_responses", res_json)
        self.assertEqual(content, "Direct response text")
        self.assertEqual(reasoning, "")

    def test_parse_openai_responses_structured_output_parts(self):
        # 当 output_text 为空时，深度遍历 output 结构
        res_json = {
            "output": [
                {
                    "type": "reasoning",
                    "content": "Step 1 reasoning.",
                },
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Part 1 "},
                        {"text": "Part 2"},
                    ],
                },
            ]
        }
        content, reasoning, usage = _parse_llm_response("openai_responses", res_json)
        self.assertEqual(content, "Part 1 Part 2")
        self.assertEqual(reasoning, "Step 1 reasoning.")

    def test_parse_openai_chat_default(self):
        res_json = {
            "choices": [{"message": {"content": "Answer", "reasoning_content": "Chain"}}],
            "usage": {"total_tokens": 50},
        }
        content, reasoning, usage = _parse_llm_response("openai_chat", res_json)
        self.assertEqual(content, "Answer")
        self.assertEqual(reasoning, "Chain")
        self.assertEqual(usage["total_tokens"], 50)

    def test_parse_llm_response_extracts_cached_tokens(self):
        # OpenAI style cached_tokens
        res_openai = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 2000, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 1500}},
        }
        _, _, u1 = _parse_llm_response("openai_chat", res_openai)
        self.assertEqual(u1.get("cached_tokens"), 1500)

        # DeepSeek style prompt_cache_hit_tokens
        res_ds = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 2000, "completion_tokens": 10, "prompt_cache_hit_tokens": 1800},
        }
        _, _, u2 = _parse_llm_response("openai_chat", res_ds)
        self.assertEqual(u2.get("cached_tokens"), 1800)

        # Claude style cache_read_input_tokens
        res_claude = {
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 2000, "output_tokens": 10, "cache_read_input_tokens": 1600},
        }
        _, _, u3 = _parse_llm_response("claude_messages", res_claude)
        self.assertEqual(u3.get("cached_tokens"), 1600)

    def test_parse_extracts_openai_responses_cached_tokens_and_reports_presence(self):
        """Responses 形态：`input_tokens_details.cached_tokens`（2026-09-29 实测缺这条会瞎）。

        上游 `/responses` **始终**返回该字段（0 或 N），而 `/chat/completions` 在无命中时
        整段省略 `prompt_tokens_details`。故 `cache_reported` 必须把两者分开。
        """
        res_hit = {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"input_tokens": 28432, "output_tokens": 10,
                      "input_tokens_details": {"cached_tokens": 24544}},
        }
        _, _, u = _parse_llm_response("openai_responses", res_hit)
        self.assertEqual(u.get("cached_tokens"), 24544)
        self.assertTrue(u.get("cache_reported"))
        self.assertFalse(u.get("truncated"))

        res_miss = {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"input_tokens": 5437, "output_tokens": 10,
                      "input_tokens_details": {"cached_tokens": 0}},
        }
        _, _, u_miss = _parse_llm_response("openai_responses", res_miss)
        self.assertEqual(u_miss.get("cached_tokens"), 0)
        self.assertTrue(u_miss.get("cache_reported"), "上报为 0 也是上报：不可判定 ≠ 0")

    def test_parse_marks_cache_unreported_when_field_absent(self):
        """Chat 形态无命中时整段省略 ⇒ `cache_reported=False`（不是 cached=0）。"""
        res = {"choices": [{"message": {"content": "ok"}}],
               "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105}}
        _, _, u = _parse_llm_response("openai_chat", res)
        self.assertFalse(u.get("cache_reported"))
        self.assertNotIn("cached_tokens", u)

    def test_parse_marks_truncation_for_both_protocols(self):
        """截断必须显性化：Responses 看 status，Chat 看 finish_reason=length。"""
        _, _, u_resp = _parse_llm_response("openai_responses", {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "{"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 2},
        })
        self.assertTrue(u_resp.get("truncated"))

        _, _, u_chat = _parse_llm_response("openai_chat", {
            "choices": [{"message": {"content": "{"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        })
        self.assertTrue(u_chat.get("truncated"))

        _, _, u_ok = _parse_llm_response("openai_chat", {
            "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        })
        self.assertFalse(u_ok.get("truncated"))

    def test_parse_extracts_anthropic_cache_creation_tokens(self):
        """Anthropic 写缓存（cache_creation）≠ 读命中（cache_read），两者都要留痕。"""
        res = {
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 2000, "output_tokens": 10,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1800},
        }
        _, _, u = _parse_llm_response("claude_messages", res)
        self.assertEqual(u.get("cached_tokens"), 0)
        self.assertTrue(u.get("cache_reported"))
        self.assertEqual(u.get("cache_creation_tokens"), 1800)

    # -------------------------------------------------------------------------
    # 3. 请求规约构建 (build_request_spec & build_chat_payload)
    # -------------------------------------------------------------------------
    def test_build_request_spec_custom_api_path_normalization(self):
        # 自定义路径前置补斜杠，标准路径重置为空
        ep1, _, _ = build_request_spec("gpt-4o", [], "https://api.openai.com", api_path="v1/custom/chat")
        self.assertIn("/v1/custom/chat", ep1)

        ep2, _, _ = build_request_spec("gpt-4o", [], "https://api.openai.com", api_path="/chat/completions")
        self.assertTrue(ep2.endswith("/chat/completions"))

    def test_build_request_spec_claude_messages_effort_none(self):
        # claude_messages 模式下 effort="none" -> thinking disabled 且附带 temperature
        _, _, payload = build_request_spec(
            "claude-3-5-sonnet",
            [{"role": "user", "content": "hi"}],
            "https://api.anthropic.com",
            api_format="claude_messages",
            reasoning_effort="none",
            temperature=0.7,
        )
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["temperature"], 0.7)

    def test_build_request_spec_claude_messages_effort_high_and_system_split(self):
        _, _, payload = build_request_spec(
            "claude-3-5-sonnet",
            [{"role": "system", "content": "Be helpful"}, {"role": "user", "content": "hi"}],
            "https://api.anthropic.com",
            api_format="claude_messages",
            reasoning_effort="high",
        )
        self.assertEqual(payload["system"], "Be helpful")
        self.assertEqual(payload["thinking"]["type"], "enabled")
        self.assertEqual(payload["thinking"]["budget_tokens"], 16000)

    def test_build_request_spec_openai_responses(self):
        _, _, payload = build_request_spec(
            "gpt-4o",
            [{"role": "user", "content": "hi"}],
            "https://api.openai.com",
            api_format="openai_responses",
            reasoning_effort="medium",
            response_format={"type": "json_object"},
        )
        self.assertEqual(payload["reasoning"], {"effort": "medium"})
        self.assertEqual(payload["text"], {"format": {"type": "json_object"}})

    def test_build_request_spec_openai_chat_gemini_temperature(self):
        # 推演模型通常不传 temperature，但 gemini 允许保留
        _, _, payload = build_request_spec(
            "gemini-2.0-flash-thinking",
            [{"role": "user", "content": "hi"}],
            "https://api.google.com",
            api_format="openai_chat",
            temperature=0.5,
        )
        self.assertEqual(payload["temperature"], 0.5)

    def test_build_request_spec_openai_chat_effort_none_for_gpt(self):
        # effort="none" 在 gpt/gemini 系列透传 "none"
        _, _, payload = build_request_spec(
            "gpt-5",
            [{"role": "user", "content": "hi"}],
            "https://api.openai.com",
            api_format="openai_chat",
            reasoning_effort="none",
        )
        self.assertEqual(payload.get("reasoning_effort"), "none")

    def test_build_request_spec_openai_chat_response_format_exclusion(self):
        # deepseek_reasoner 不支持 response_format，其余支持
        _, _, p1 = build_request_spec(
            "deepseek-reasoner",
            [],
            "https://api.deepseek.com",
            response_format={"type": "json_object"},
            reasoning_type="deepseek_reasoner",
        )
        self.assertNotIn("response_format", p1)

        _, _, p2 = build_request_spec(
            "gpt-4o",
            [],
            "https://api.openai.com",
            response_format={"type": "json_object"},
        )
        self.assertEqual(p2.get("response_format"), {"type": "json_object"})

    def test_build_chat_payload_compatibility_wrapper(self):
        payload = build_chat_payload(
            model="gpt-4o",
            messages=[{"role": "user", "content": "ping"}],
            temperature=0.3,
        )
        self.assertEqual(payload["model"], "gpt-4o")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "ping"}])
        self.assertEqual(payload["temperature"], 0.3)

    # -------------------------------------------------------------------------
    # 4. 单次调用执行 (_attempt_llm_call)
    # -------------------------------------------------------------------------
    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_success(self, mock_urlopen):
        mock_urlopen.return_value = _make_mock_response({
            "choices": [{"message": {"content": "pong", "reasoning_content": "think"}}],
            "usage": {"total_tokens": 12},
        })
        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        content, reasoning, usage, latency = _attempt_llm_call(
            cand, [{"role": "user", "content": "ping"}], temperature=0.2, response_format=None, effective_timeout=10.0
        )
        self.assertEqual(content, "pong")
        self.assertEqual(reasoning, "think")
        self.assertEqual(usage["total_tokens"], 12)
        self.assertGreaterEqual(latency, 0)

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_empty_content_raises_transient_error(self, mock_urlopen):
        mock_urlopen.return_value = _make_mock_response({
            "choices": [{"message": {"content": "", "reasoning_content": ""}}],
        })
        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMTransientError) as ctx:
            _attempt_llm_call(cand, [{"role": "user", "content": "ping"}], None, None, 10.0)
        self.assertIn("返回空正文", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_invalid_json_body_raises_transient_error(self, mock_urlopen):
        mock_urlopen.return_value = _make_mock_response(b"<html>Bad Gateway</html>")
        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMTransientError) as ctx:
            _attempt_llm_call(cand, [{"role": "user", "content": "ping"}], None, None, 10.0)
        self.assertIn("LLM 响应体非 JSON", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_socket_timeout_raises_transient_with_failover(self, mock_urlopen):
        mock_urlopen.side_effect = socket.timeout("timed out")
        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMTransientError) as ctx:
            _attempt_llm_call(cand, [], None, None, 5.0)
        self.assertTrue(ctx.exception.timed_out)
        self.assertTrue(ctx.exception.fail_over_now)

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_url_error_wrapping_timeout(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError(socket.timeout("read timed out"))
        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMTransientError) as ctx:
            _attempt_llm_call(cand, [], None, None, 5.0)
        self.assertTrue(ctx.exception.timed_out)
        self.assertTrue(ctx.exception.fail_over_now)

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_url_error_general(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMTransientError) as ctx:
            _attempt_llm_call(cand, [], None, None, 5.0)
        self.assertFalse(ctx.exception.timed_out)
        self.assertFalse(ctx.exception.fail_over_now)
        self.assertIn("Connection refused", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_value_error_raises_transient(self, mock_urlopen):
        mock_urlopen.side_effect = ValueError("Corrupted read buffer")
        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMTransientError) as ctx:
            _attempt_llm_call(cand, [], None, None, 5.0)
        self.assertIn("LLM 响应体解析失败", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_http_504_gateway_timeout_sets_fail_over_now(self, mock_urlopen):
        mock_urlopen.side_effect = _make_http_error(504, "Gateway Timeout")
        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMTransientError) as ctx:
            _attempt_llm_call(cand, [], None, None, 5.0)
        self.assertTrue(ctx.exception.fail_over_now)

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_http_500_transient_error(self, mock_urlopen):
        mock_urlopen.side_effect = _make_http_error(500, "Internal Server Error")
        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMTransientError) as ctx:
            _attempt_llm_call(cand, [], None, None, 5.0)
        self.assertFalse(ctx.exception.fail_over_now)

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_http_401_hard_error(self, mock_urlopen):
        mock_urlopen.side_effect = _make_http_error(401, "Unauthorized")
        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMHardError) as ctx:
            _attempt_llm_call(cand, [], None, None, 5.0)
        self.assertIn("HTTP 401", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_adaptive_retry_success(self, mock_urlopen):
        # 第一次请求返回 400 且提示 reasoning_effort 参数无效，自适应重试成功返回
        conflict_err = _make_http_error(400, "Unrecognized parameter: reasoning_effort")
        success_resp = _make_mock_response({
            "choices": [{"message": {"content": "pong after retry"}}],
            "usage": {"total_tokens": 15},
        })
        mock_urlopen.side_effect = [conflict_err, success_resp]

        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1", "api_format": "openai_chat"}
        content, reasoning, usage, latency = _attempt_llm_call(cand, [{"role": "user", "content": "ping"}], None, None, 5.0)
        self.assertEqual(content, "pong after retry")
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_adaptive_retry_empty_content_raises_transient(self, mock_urlopen):
        conflict_err = _make_http_error(400, "invalid parameter: temperature")
        empty_resp = _make_mock_response({"choices": [{"message": {"content": ""}}]})
        mock_urlopen.side_effect = [conflict_err, empty_resp]

        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMTransientError) as ctx:
            _attempt_llm_call(cand, [], None, None, 5.0)
        self.assertIn("已自适应去参数重试", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_adaptive_retry_fails_with_hard_error(self, mock_urlopen):
        conflict_err = _make_http_error(400, "reasoning_effort not supported")
        hard_err = _make_http_error(401, "Invalid API key")
        mock_urlopen.side_effect = [conflict_err, hard_err]

        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMHardError) as ctx:
            _attempt_llm_call(cand, [], None, None, 5.0)
        self.assertIn("HTTP 401", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_adaptive_retry_fails_with_transient_error(self, mock_urlopen):
        conflict_err = _make_http_error(400, "reasoning_effort not supported")
        transient_err = _make_http_error(503, "Service Unavailable")
        mock_urlopen.side_effect = [conflict_err, transient_err]

        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMTransientError) as ctx:
            _attempt_llm_call(cand, [], None, None, 5.0)
        self.assertIn("HTTP 400", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_attempt_llm_call_http_error_body_read_exception_handled(self, mock_urlopen):
        err = _make_http_error(404, "Not Found")
        # 模拟读取错误流异常
        err.read = MagicMock(side_effect=OSError("Stream read failure"))
        mock_urlopen.side_effect = err

        cand = {"model": "gpt-4o", "base_url": "https://api.openai.com/v1"}
        with self.assertRaises(_LLMHardError) as ctx:
            _attempt_llm_call(cand, [], None, None, 5.0)
        self.assertIn("HTTP 404", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
