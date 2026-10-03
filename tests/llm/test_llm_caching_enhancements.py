"""大模型缓存增强专项测试套件（2026 前缀缓存、L1 精确查询缓存与会话粘性）。"""
import time
import unittest
from unittest.mock import patch

from astra_backend.llm.query_cache import (
    clear_query_cache,
    compute_cache_key,
    get_cached_query,
    get_query_cache_stats,
    put_cached_query,
)
from astra_backend.llm.transport import _parse_llm_response, build_request_spec


class TransportCachingSpecTests(unittest.TestCase):
    def test_claude_messages_prompt_caching_short_system(self):
        endpoint, headers, payload = build_request_spec(
            model="claude-3-5-sonnet",
            messages=[{"role": "system", "content": "Short system prompt"}, {"role": "user", "content": "Hello"}],
            base_url="https://api.anthropic.com/v1",
            api_format="claude_messages",
        )
        self.assertIn("anthropic-beta", headers)
        self.assertEqual(headers["anthropic-beta"], "prompt-caching-2024-07-31")
        self.assertIn("X-Session-ID", headers)
        # 短系统提示词保持字符串格式（兼容旧测试与 API）
        self.assertEqual(payload["system"], "Short system prompt")

    def test_claude_messages_prompt_caching_long_system(self):
        long_sys = "System instruction rule set. " * 80  # > 1000 chars
        endpoint, headers, payload = build_request_spec(
            model="claude-3-7-sonnet",
            messages=[{"role": "system", "content": long_sys}, {"role": "user", "content": "Analyze market"}],
            base_url="https://api.anthropic.com/v1",
            api_format="claude_messages",
        )
        self.assertIsInstance(payload["system"], list)
        self.assertEqual(len(payload["system"]), 1)
        self.assertEqual(payload["system"][0]["type"], "text")
        # 默认 2026 规范：1h 扩展生命周期，避免 15 分钟交易周期击穿短缓存
        self.assertEqual(payload["system"][0]["cache_control"], {"type": "ephemeral", "ttl": "1h"})
        self.assertEqual(payload["system"][0]["text"], long_sys)

        # 显式 5m 回退测试
        with patch.dict("os.environ", {"ASTRA_LLM_CACHE_TTL": "5m"}):
            _, _, payload_5m = build_request_spec(
                model="claude-3-7-sonnet",
                messages=[{"role": "system", "content": long_sys}, {"role": "user", "content": "Analyze market"}],
                base_url="https://api.anthropic.com/v1",
                api_format="claude_messages",
            )
            self.assertEqual(payload_5m["system"][0]["cache_control"], {"type": "ephemeral"})

    def test_openai_session_affinity_injection(self):
        _, headers_chat, payload_chat = build_request_spec(
            model="gpt-4o",
            messages=[{"role": "system", "content": "Trader bot"}, {"role": "user", "content": "Run cycle"}],
            base_url="https://api.openai.com/v1",
            api_format="openai_chat",
        )
        self.assertIn("X-Session-ID", headers_chat)
        self.assertIn("X-Astra-Affinity", headers_chat)
        self.assertIn("X-Channel-Affinity", headers_chat)
        self.assertTrue(headers_chat["X-Session-ID"].startswith("astra-"))
        self.assertEqual(payload_chat["user"], headers_chat["X-Session-ID"])

        _, headers_resp, payload_resp = build_request_spec(
            model="gemini-3.8-flash",
            messages=[{"role": "system", "content": "Trader bot"}, {"role": "user", "content": "Run cycle"}],
            base_url="https://cpa.example.com/v1",
            api_format="openai_responses",
        )
        self.assertIn("X-Session-ID", headers_resp)
        self.assertIn("X-Astra-Affinity", headers_resp)
        self.assertIn("X-Channel-Affinity", headers_resp)
        self.assertEqual(payload_resp["user"], headers_resp["X-Session-ID"])

    def test_parse_llm_response_hit_ratio_calculation(self):
        res_json = {
            "choices": [{"message": {"content": "OK"}}],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 50,
                "total_tokens": 1050,
                "prompt_tokens_details": {"cached_tokens": 800},
            },
        }
        content, _, usage = _parse_llm_response("openai_chat", res_json)
        self.assertEqual(usage["cached_tokens"], 800)
        self.assertTrue(usage["cache_reported"])
        self.assertEqual(usage["cache_hit_ratio"], 80.0)


class QueryCacheL1Tests(unittest.TestCase):
    def setUp(self):
        clear_query_cache()

    def tearDown(self):
        clear_query_cache()

    def test_deterministic_cache_key(self):
        msgs1 = [{"role": "system", "content": "Sys"}, {"role": "user", "content": "User"}]
        msgs2 = [{"content": "Sys", "role": "system"}, {"content": "User", "role": "user"}]
        k1 = compute_cache_key("GPT-4O", "https://api.openai.com/v1/", msgs1, 0.2, None)
        k2 = compute_cache_key("gpt-4o", "https://api.openai.com/v1", msgs2, 0.2000, None)
        self.assertEqual(k1, k2)

    def test_put_and_get_l1_cache(self):
        k = "test_cache_key_123"
        usage = {"prompt_tokens": 500, "completion_tokens": 50}
        put_cached_query(k, "m1", "https://api.test", "Result content", "Reasoning", usage, 120, ttl_seconds=60.0)

        hit = get_cached_query(k)
        self.assertIsNotNone(hit)
        content, reasoning, ret_usage, lat = hit
        self.assertEqual(content, "Result content")
        self.assertEqual(reasoning, "Reasoning")
        self.assertEqual(ret_usage["cache_source"], "l1_exact_cache")
        self.assertEqual(ret_usage["cached_tokens"], 500)
        self.assertEqual(lat, 120)

    def test_expired_l1_cache(self):
        k = "test_expired_key"
        now = time.time()
        put_cached_query(k, "m1", "https://api.test", "Content", "", {}, 10, ttl_seconds=5.0, now=now)
        # 4 秒后未过期
        self.assertIsNotNone(get_cached_query(k, now=now + 4.0))
        # 6 秒后已过期
        self.assertIsNone(get_cached_query(k, now=now + 6.0))

    def test_cache_stats(self):
        stats = get_query_cache_stats()
        self.assertIn("in_memory_entries", stats)
        self.assertIn("hits", stats)
        self.assertIn("misses", stats)


class CouncilSharedPrefixTests(unittest.TestCase):
    def test_debate_prompt_shared_prefix_structure(self):
        from astra_backend.council.debate import _call_single_trader
        from unittest.mock import MagicMock

        captured_messages = []

        def fake_exec(messages, **kwargs):
            captured_messages.append(messages)
            return "OK", "", {"prompt_tokens": 100}, 50

        seat_resolver = MagicMock(return_value={
            "model": "gemini-3.8-flash", "base_url": "https://api.example/v1",
            "api_key": "k", "api_format": "openai_chat", "effort": "high",
            "requested": "gemini", "registered": "gemini", "fallback": None, "reason": "ok"
        })

        with patch("astra_backend.llm_manager.execute_llm_request", fake_exec):
            market_data = "MARKET_DATA_7_TIER_FACTORS_ABC_123"
            constitution = "CONSTITUTION_RULES_XYZ"

            # 模拟两个不同的交易员角色
            role1 = {"name": "趋势交易员", "prompt": "专注顺势突破", "weight": 1.0}
            role2 = {"name": "均值回归员", "prompt": "专注极限反弹", "weight": 1.0}

            _call_single_trader(seat_resolver, "trend", role1, market_data, constitution)
            _call_single_trader(seat_resolver, "mean_rev", role2, market_data, constitution)

            self.assertEqual(len(captured_messages), 2)
            u1 = captured_messages[0][1]["content"]
            u2 = captured_messages[1][1]["content"]

            # 两个角色的 user prompt 前部公共市场数据及通用审查要求完全相同
            common_marker = "【作战提案审查通用要求（所有席位统一标准）】"
            self.assertIn(common_marker, u1)
            self.assertIn(common_marker, u2)

            prefix1 = u1[:u1.index("【本席位提交指令】")]
            prefix2 = u2[:u2.index("【本席位提交指令】")]
            self.assertEqual(prefix1, prefix2)


class CachingCapabilitiesAndSavingsTests(unittest.TestCase):
    def test_detect_caching_capabilities_claude(self):
        from astra_backend.llm.capabilities import detect_caching_capabilities
        caps = detect_caching_capabilities("claude-3-7-sonnet", "claude_messages")
        self.assertTrue(caps["claude_ephemeral"])
        self.assertTrue(caps["claude_extended_cache"])
        self.assertEqual(caps["threshold_tokens"], 1024)
        self.assertIn("1h (Extended)", caps["ttl_tier"])

    def test_detect_caching_capabilities_gemini(self):
        from astra_backend.llm.capabilities import detect_caching_capabilities
        caps = detect_caching_capabilities("gemini-3.8-flash", "openai_chat")
        self.assertTrue(caps["gemini_context"])
        self.assertTrue(caps["gemini_implicit_cache"])
        self.assertEqual(caps["threshold_tokens"], 2048)
        self.assertIn("隐式自动前缀缓存", caps["primary_protocol"])

    def test_detect_caching_capabilities_deepseek(self):
        from astra_backend.llm.capabilities import detect_caching_capabilities
        caps = detect_caching_capabilities("deepseek-reasoner", "openai_chat")
        self.assertTrue(caps["deepseek_prefix"])
        self.assertTrue(caps["deepseek_disk_cache"])
        self.assertEqual(caps["threshold_tokens"], 64)
        self.assertIn("硬盘落盘缓存", caps["primary_protocol"])

    def test_detect_caching_capabilities_qwen_kimi(self):
        from astra_backend.llm.capabilities import detect_caching_capabilities
        caps_q = detect_caching_capabilities("qwen-max", "openai_chat")
        self.assertTrue(caps_q["qwen_kimi_dual"])
        caps_k = detect_caching_capabilities("kimi-k3", "openai_chat")
        self.assertTrue(caps_k["qwen_kimi_dual"])

    def test_estimate_cache_savings_usd(self):
        from astra_backend.llm.capabilities import estimate_cache_savings_usd
        # 0 tokens
        self.assertEqual(estimate_cache_savings_usd("gpt-4o", 0), 0.0)
        # Claude (2.70 / 1M)
        self.assertEqual(estimate_cache_savings_usd("claude-3-7-sonnet", 1_000_000), 2.70)
        # DeepSeek (0.21 / 1M)
        self.assertEqual(estimate_cache_savings_usd("deepseek-chat", 1_000_000), 0.21)
        # Gemini Flash (0.1125 / 1M)
        self.assertEqual(estimate_cache_savings_usd("gemini-2.5-flash", 1_000_000), 0.1125)
        # Gemini Pro (0.9375 / 1M)
        self.assertEqual(estimate_cache_savings_usd("gemini-2.5-pro", 1_000_000), 0.9375)


if __name__ == "__main__":
    unittest.main()
