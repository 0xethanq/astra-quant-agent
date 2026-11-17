"""测试网关大模型前缀缓存与真实 Token 消耗量统计（输入、输出、推理、缓存与费用折算）。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_gateway.store import GatewayStore
import astra_gateway.telemetry as telemetry
from astra_backend.llm.capabilities import estimate_total_spend_usd, estimate_cache_savings_usd


class GatewayCacheStatsTests(unittest.TestCase):
    def test_cache_stats_empty_database(self):
        """数据库无任何调用记录时，所有比率均为 None，不伪装成 0。"""
        with tempfile.TemporaryDirectory() as td:
            store = GatewayStore(Path(td) / "gateway.db")
            stats = store.model_stats(detailed=True)
            self.assertEqual(stats["total_calls"], 0)
            self.assertEqual(stats["cached_tokens_total"], 0)
            self.assertEqual(stats["input_tokens_total"], 0)
            self.assertEqual(stats["output_tokens_total"], 0)
            self.assertEqual(stats["reasoning_tokens_total"], 0)
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
            # 1. 命中调用：输入 12,000，缓存 8,000，输出 2,000（其中推理 1,500），总 14,000
            store.record_model_call({
                **base, "input_tokens": 12000, "output_tokens": 2000, "reasoning_tokens": 1500,
                "total_tokens": 14000, "cached_tokens": 8000, "cache_status": "hit"
            })
            # 2. 未命中调用（已上报）：输入 8,000，缓存 0，输出 1,000，总 9,000
            store.record_model_call({
                **base, "input_tokens": 8000, "output_tokens": 1000, "reasoning_tokens": 0,
                "total_tokens": 9000, "cached_tokens": 0, "cache_status": "miss"
            })
            # 3. 未上报调用：输入 5,000，缓存 0，输出 500，总 5,500
            store.record_model_call({
                **base, "input_tokens": 5000, "output_tokens": 500, "reasoning_tokens": 0,
                "total_tokens": 5500, "cached_tokens": 0, "cache_status": "unreported"
            })

            stats = store.model_stats(detailed=True)

            # 调用次数
            self.assertEqual(stats["total_calls"], 3)
            self.assertEqual(stats["cache_hit_calls"], 1)
            self.assertEqual(stats["cache_reporting_calls"], 2)  # unreported 不进分母

            # 调用级命中率：1 / 2 = 50.0%
            self.assertEqual(stats["cache_hit_rate"], 50.0)
            self.assertEqual(stats["call_hit_rate"], 50.0)

            # 四大真实 Token 消耗量统计
            self.assertEqual(stats["input_tokens_total"], 25000)
            self.assertEqual(stats["output_tokens_total"], 3500)
            self.assertEqual(stats["reasoning_tokens_total"], 1500)
            self.assertEqual(stats["cached_tokens_total"], 8000)
            self.assertEqual(stats["total_tokens"], 28500)

            # 命中效率与复用率
            self.assertEqual(stats["hit_input_tokens"], 12000)
            self.assertEqual(stats["reporting_input_tokens"], 20000)
            self.assertEqual(stats["hit_token_efficiency"], 66.7)  # 8000 / 12000
            self.assertEqual(stats["token_cache_rate"], 40.0)     # 8000 / 20000

    def test_telemetry_nested_details_extraction(self):
        """验证遥测能准确从现代主流厂商嵌套字典中提取 reasoning_tokens 与 cached_tokens。"""
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "gateway.db"
            with patch.object(telemetry, "DB_PATH", db):
                call = telemetry.ModelCallTelemetry("trading_brain", "gemini-3.8-flash", "high", "SYS", "USER")
                # 模拟 Gemini / OpenAI 格式响应体的 usage 字段
                raw_usage = {
                    "prompt_tokens": 10000,
                    "completion_tokens": 2000,
                    "total_tokens": 12000,
                    "prompt_tokens_details": {"cached_tokens": 6000},
                    "output_tokens_details": {"reasoning_tokens": 1200},
                    "cache_reported": True,
                }
                call.finish("success", {"usage": raw_usage}, output_chars=500)

            rows = GatewayStore(db).model_calls()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["input_tokens"], 10000)
            self.assertEqual(row["output_tokens"], 2000)
            self.assertEqual(row["cached_tokens"], 6000)
            self.assertEqual(row["reasoning_tokens"], 1200)
            self.assertEqual(row["cache_status"], "hit")

    def test_spend_and_savings_calculation(self):
        """验证按大模型官方公开计费标准的累计支出与节约金额折算。"""
        # Gemini Flash: $0.075/1M in, $0.30/1M out, $0.01875/1M cached in
        # 10M input (of which 5M cached), 2M output
        spend = estimate_total_spend_usd("gemini-3.8-flash", input_tokens=10_000_000, output_tokens=2_000_000, cached_tokens=5_000_000)
        # 未缓存输入 5M: $0.375; 缓存输入 5M: $0.09375; 输出 2M: $0.60 -> total $1.0688
        self.assertAlmostEqual(spend, 1.0688, places=3)

        # 缓存节约: 5M * $0.1125/1M = $0.5625
        saved = estimate_cache_savings_usd("gemini-3.8-flash", cached_tokens=5_000_000)
        self.assertAlmostEqual(saved, 0.5625, places=3)


if __name__ == "__main__":
    unittest.main()
