"""测试网关大模型前缀缓存高级统计（Token 复用率、单次命中效率与向后兼容性）。"""
import tempfile
import unittest
from pathlib import Path

from astra_gateway.store import GatewayStore


class GatewayCacheStatsTests(unittest.TestCase):
    def test_cache_stats_empty_database(self):
        """数据库无任何调用记录时，所有比率均为 None，不伪装成 0。"""
        with tempfile.TemporaryDirectory() as td:
            store = GatewayStore(Path(td) / "gateway.db")
            stats = store.model_stats(detailed=True)
            self.assertEqual(stats["total_calls"], 0)
            self.assertEqual(stats["cached_tokens_total"], 0)
            self.assertIsNone(stats["cache_hit_rate"])
            self.assertIsNone(stats["call_hit_rate"])
            self.assertIsNone(stats["token_cache_rate"])
            self.assertIsNone(stats["hit_token_efficiency"])

    def test_cache_stats_with_hits_and_misses(self):
        """验证命中请求、未命中请求与未上报请求各维度的 Token 与调用统计。"""
        with tempfile.TemporaryDirectory() as td:
            store = GatewayStore(Path(td) / "gateway.db")
            base = {
                "caller": "trading_brain", "model": "gemini-3.8-flash", "reasoning_effort": "high",
                "status": "success", "started_at": "2026-10-03 12:00:00", "duration_ms": 1000,
                "input_chars": 5000, "output_chars": 1000, "prompt_fingerprint": "fp1",
                "prompt_transport": "python-direct", "error_type": "", "usage_keys": "prompt_tokens"
            }
            # 1. 命中调用：输入 12,000，缓存 8,000，输出 2,000，总 14,000
            store.record_model_call({
                **base, "input_tokens": 12000, "output_tokens": 2000, "total_tokens": 14000,
                "cached_tokens": 8000, "cache_status": "hit"
            })
            # 2. 未命中调用（已上报）：输入 8,000，缓存 0，输出 1,000，总 9,000
            store.record_model_call({
                **base, "input_tokens": 8000, "output_tokens": 1000, "total_tokens": 9000,
                "cached_tokens": 0, "cache_status": "miss"
            })
            # 3. 未上报调用：输入 5,000，缓存 0，输出 500，总 5,500
            store.record_model_call({
                **base, "input_tokens": 5000, "output_tokens": 500, "total_tokens": 5500,
                "cached_tokens": 0, "cache_status": "unreported"
            })

            stats = store.model_stats(detailed=True)

            # 调用次数
            self.assertEqual(stats["total_calls"], 3)
            self.assertEqual(stats["cache_hit_calls"], 1)
            self.assertEqual(stats["cache_reporting_calls"], 2)  # unreported 不进分母

            # 调用级命中率：1 / 2 = 50.0%
            self.assertEqual(stats["cache_hit_rate"], 50.0)
            self.assertEqual(stats["call_hit_rate"], 50.0)

            # Token 统计
            self.assertEqual(stats["cached_tokens_total"], 8000)
            self.assertEqual(stats["hit_input_tokens"], 12000)
            self.assertEqual(stats["reporting_input_tokens"], 20000)  # 12,000 + 8,000

            # 单次命中效率：8,000 / 12,000 = 66.7%
            self.assertEqual(stats["hit_token_efficiency"], 66.7)

            # 上报调用的 Token 复用率：8,000 / 20,000 = 40.0%
            self.assertEqual(stats["token_cache_rate"], 40.0)


if __name__ == "__main__":
    unittest.main()
