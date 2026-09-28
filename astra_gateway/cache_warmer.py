"""Prompt Cache Warmer: keeps the long-tail static prefix warm in cloud GPU memory."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict

_last_warmup_time: float = 0.0


def send_cache_warmup_ping(timeout: float = 15.0) -> Dict[str, Any]:
    """Send a micro-ping with the static prefix to prevent 5-10min GPU cache eviction."""
    global _last_warmup_time
    try:
        from astra_backend.llm_manager import get_active_llm_runtime
        rt = get_active_llm_runtime()
        if not rt or not rt.get("model") or not rt.get("base_url") or not rt.get("api_key"):
            return {"ok": False, "reason": "No active LLM runtime or key configured"}

        from scripts.ai_brain_trader import SYSTEM_PROMPT
        from astra_backend.llm.transport import build_request_spec, _parse_llm_response

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "PING_CACHE_WARMUP"}
        ]

        endpoint, headers, payload = build_request_spec(
            model=rt["model"],
            messages=messages,
            base_url=rt["base_url"],
            api_key=rt.get("api_key", ""),
            api_format=rt.get("api_format", "openai_chat"),
            reasoning_effort="none",
            max_tokens=1,
            api_path=rt.get("api_path", ""),
        )
        payload["max_tokens"] = 1

        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers)
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            latency_ms = int((time.time() - t0) * 1000)
            _, _, usage = _parse_llm_response(rt.get("api_format", "openai_chat"), res_json)
            _last_warmup_time = time.time()
            cached = usage.get("cached_tokens", 0)
            prompt_t = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
            rate = round(cached / prompt_t * 100, 1) if prompt_t and cached else 0.0
            print(f"[Cache Warmer] ⚡ 缓存保活探针成功 ({latency_ms}ms | 缓存: {cached}/{prompt_t} tokens, {rate}%)")
            return {"ok": True, "latency_ms": latency_ms, "cached_tokens": cached, "usage": usage}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def check_and_warmup_cache(idle_threshold_seconds: float = 270.0) -> bool:
    """Check if model has been idle for >= 4.5 minutes, and if so, trigger warmup."""
    global _last_warmup_time
    now = time.time()
    if now - _last_warmup_time < idle_threshold_seconds:
        return False
    res = send_cache_warmup_ping()
    return bool(res.get("ok"))
