"""Best-effort model-call telemetry; never stores prompt or response content."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib
import time
from typing import Any

from astra_gateway.publisher import DB_PATH
from astra_gateway.store import GatewayStore

BJ_TZ = timezone(timedelta(hours=8))


class ModelCallTelemetry:
    def __init__(self, caller: str, model: str, reasoning_effort: str, system_prompt: str, user_prompt: str):
        self.caller = caller
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.input_chars = len(system_prompt) + len(user_prompt)
        fingerprint_source = f"{system_prompt}\0{user_prompt}".encode("utf-8")
        self.prompt_fingerprint = hashlib.sha256(fingerprint_source).hexdigest()[:16]
        self.started_at = datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
        self.started = time.monotonic()

    def finish(self, status: str, response: dict[str, Any] | None = None, output_chars: int = 0, error: Exception | None = None) -> None:
        usage = (response or {}).get("usage", {}) if isinstance(response, dict) else {}
        if not isinstance(usage, dict):
            usage = {}
        input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        output_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens)
        cached_raw = usage.get("cached_tokens")
        # 三态判定（2026-09-29 事故后固化）：**不可判定 ≠ 0**。
        #   hit        上游明确上报命中（cached > 0）
        #   miss       上游明确上报了缓存字段但为 0
        #   unreported 响应体里根本没有缓存字段（如 /chat/completions 无命中时整段省略）
        # 旧实现把后两者一律打印成「缓存: 0」，导致"还是 0 缓存"既不能证实也不能证伪。
        cache_reported = bool(usage.get("cache_reported")) or cached_raw is not None
        try:
            cached_tokens = int(cached_raw) if cached_raw is not None else 0
        except (TypeError, ValueError):
            cached_tokens = 0
        if status != "success":
            cache_status = ""
        elif not cache_reported:
            cache_status = "unreported"
        elif cached_tokens > 0:
            cache_status = "hit"
        else:
            cache_status = "miss"
        # 只留 usage 的**顶层键名**（诊断上游到底报了什么），绝不落任何内容。
        usage_keys = ",".join(sorted(str(key) for key in usage.keys()))[:200]

        record = {
            "caller": self.caller,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "status": status,
            "started_at": self.started_at,
            "duration_ms": max(0, round((time.monotonic() - self.started) * 1000)),
            "input_chars": self.input_chars,
            "output_chars": output_chars,
            "prompt_fingerprint": self.prompt_fingerprint,
            "prompt_transport": "python-direct",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cached_tokens": cached_tokens,
            "cache_status": cache_status,
            "usage_keys": usage_keys,
            "error_type": type(error).__name__ if error else "",
        }

        # 实时打印：命中 / 上报未命中 / 上游未上报，三态分开，不再出现伪 0
        if cache_status == "hit" and input_tokens:
            cache_rate = round(cached_tokens / input_tokens * 100, 1)
            print(f"[LLM Telemetry] 🎯 命中前缀缓存: {cached_tokens} tokens ({cache_rate}% | {self.caller} | {self.model})")
        elif cache_status == "miss" and input_tokens:
            print(f"[LLM Telemetry] ⏱️ 上游上报未命中 | 输入: {input_tokens} tokens (缓存: 0) | 输出: {output_tokens} tokens | 耗时: {record['duration_ms']}ms | {self.model}")
        elif cache_status == "unreported" and input_tokens:
            print(f"[LLM Telemetry] ℹ️ 上游未上报缓存指标（当前路由不返回缓存字段） | 输入: {input_tokens} tokens | 输出: {output_tokens} tokens | 耗时: {record['duration_ms']}ms | {self.model}")
        elif input_tokens:
            print(f"[LLM Telemetry] ℹ️ 调用完成 | 输入: {input_tokens} tokens | 输出: {output_tokens} tokens | 耗时: {record['duration_ms']}ms | {self.model}")
        if isinstance(usage.get("truncated"), bool) and usage["truncated"]:
            print(f"[LLM Telemetry] ⚠️ 响应被截断（finish/status 非完成态）| {self.caller} | {self.model} | usage_keys={usage_keys}")

        # 记录最近一次真实调用时间（诊断用）：预热策略已改为默认 off / jit 按槽位触发，
        # 不再依赖这个计时器，但它仍能回答"上次真调用是多久之前"。
        try:
            from astra_gateway import cache_warmer
            cache_warmer._last_warmup_time = time.time()
        except Exception:
            pass

        try:
            GatewayStore(DB_PATH).record_model_call(record)
        except Exception:
            pass
