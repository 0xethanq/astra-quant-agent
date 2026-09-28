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
        input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        output_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens)
        cached_tokens = usage.get("cached_tokens") or 0
        if not cached_tokens and isinstance(usage.get("prompt_tokens_details"), dict):
            cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)

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
            "error_type": type(error).__name__ if error else "",
        }

        # 实时打印缓存命中与遥测日志
        if cached_tokens and input_tokens:
            cache_rate = round(cached_tokens / input_tokens * 100, 1)
            print(f"[LLM Telemetry] 🎯 命中前缀缓存: {cached_tokens} tokens ({cache_rate}% | {self.caller} | {self.model})")
        elif input_tokens:
            print(f"[LLM Telemetry] ℹ️ 调用完成 | 输入: {input_tokens} tokens (缓存: 0) | 输出: {output_tokens} tokens | 耗时: {record['duration_ms']}ms | {self.model}")

        # 刷新缓存保活计时器，避免真实调用后产生冗余探针
        try:
            from astra_gateway import cache_warmer
            cache_warmer._last_warmup_time = time.time()
        except Exception:
            pass

        try:
            GatewayStore(DB_PATH).record_model_call(record)
        except Exception:
            pass
