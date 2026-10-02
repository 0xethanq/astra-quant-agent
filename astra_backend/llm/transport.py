"""单次请求的构建、发送与响应解析（传输层）。

纯函数，不读任何模块级常量；TRANSIENT_MARKERS 随本模块一起迁出。
对 llm_manager 内**会读常量**的函数（init_llm_config / get_active_llm_runtime 等）
没有任何依赖，故可直接搬迁而不破坏测试注入接缝。
结构优化阶段 2（B4）。
"""
from __future__ import annotations

import hashlib
import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from astra_backend.llm.capabilities import _detect_reasoning_type
from astra_backend.llm.providers import _join_api_path


# Transient upstream faults (gateway route flaps, bot/rate shields, 5xx) must not
# silently degrade a trading or self-evolution cycle into NO_CHANGE. Retry with backoff.
# 注：unknown provider / model_not_found 已移出瞬时名单（2026-09-09 事件复盘）——
# 网关不认识该模型是轮内持续故障，原地重试只会白白烧掉请求窗口，按硬故障立即换模型。
TRANSIENT_MARKERS = (
    "upstream", "temporarily unavailable", "overloaded", "rate limit",
    "too many requests", "capacity", "busy", "bad gateway", "gateway timeout",
)


class _LLMTransientError(Exception):
    """可重试错误：瞬时 HTTP、超时、连接层异常（拒绝/重置/DNS/TLS）、坏响应体、空正文。

    fail_over_now=True：错误本身可再试（末位模型仍会重试），但链上还有下一个模型时
    立即切换——504/思考超时属"慢故障"，同一轮内原地重试大概率再烧满一个超时窗口。"""

    def __init__(self, message: str, timed_out: bool = False, fail_over_now: bool = False):
        super().__init__(message)
        self.timed_out = timed_out
        self.fail_over_now = fail_over_now


class _LLMHardError(Exception):
    """不可重试错误（对该模型）：认证失败、404、参数被拒等——直接切换下一个回退模型。"""


def _is_transient_http(code: int, body: str) -> bool:
    low = (body or "").lower()
    if code in (408, 409, 425, 429, 500, 502, 503, 504):
        return True
    if code in (400, 401, 402, 403) and any(m in low for m in TRANSIENT_MARKERS):
        return True
    return False


def _parse_llm_response(target_format: str, res_json: Dict[str, Any]) -> Tuple[str, str, Dict[str, Any]]:
    content = ""
    reasoning_content = ""
    raw_usage = res_json.get("usage", {}) if isinstance(res_json, dict) else {}
    usage = dict(raw_usage) if isinstance(raw_usage, dict) else {}

    # Protocol 1: Claude Messages Response
    if target_format == "claude_messages":
        text_chunks = [c.get("text", "") for c in res_json.get("content", []) if c.get("type") == "text"]
        thinking_chunks = [c.get("thinking", "") for c in res_json.get("content", []) if c.get("type") == "thinking"]
        content = "".join(text_chunks).strip()
        reasoning_content = "\n".join(thinking_chunks).strip()
        if not usage:
            usage = {
                "total_tokens": res_json.get("usage", {}).get("input_tokens", 0) + res_json.get("usage", {}).get("output_tokens", 0)
            }

    # Protocol 2: OpenAI Responses Response
    elif target_format == "openai_responses":
        content = str(res_json.get("output_text") or "").strip()
        if not content:
            for item in res_json.get("output", []):
                if item.get("type") == "message":
                    for part in item.get("content", []):
                        if part.get("type") == "output_text" or "text" in part:
                            content += str(part.get("text", ""))
                elif item.get("type") == "reasoning":
                    reasoning_content += str(item.get("content") or item.get("summary") or "")
        content = content.strip()
        reasoning_content = reasoning_content.strip()

    # Protocol 3: OpenAI Chat Completions Response
    else:
        msg = res_json.get("choices", [{}])[0].get("message", {})
        content = str(msg.get("content", "")).strip()
        reasoning_content = str(msg.get("reasoning_content") or "").strip()

    # 规范化提取各厂商 Prompt Caching 缓存命中指标（OpenAI, DeepSeek, Claude, Gemini, Qwen）
    #
    # 三种形态都要认（2026-09-29 实测）：
    #   1) Chat Completions：usage.prompt_tokens_details.cached_tokens（且**无命中时该字段整段省略**）
    #   2) Responses：usage.input_tokens_details.cached_tokens（**始终存在**，0 或 N）—— 本仓生产
    #      切到 /responses 后靠它把"上游说 0"与"上游什么都没说"分开；
    #   3) Anthropic Messages：usage.cache_read_input_tokens / cache_creation_input_tokens；
    #      DeepSeek：prompt_cache_hit_tokens；Gemini 原生：cached_content_token_count。
    prompt_details = usage.get("prompt_tokens_details", {}) if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    input_details = usage.get("input_tokens_details", {}) if isinstance(usage.get("input_tokens_details"), dict) else {}
    # ⚠️ 不能用 `a or b or c` 串：**显式的 0 是"上报了 0"，不是"没上报"**。
    # Anthropic 在无命中时给的正是 `cache_read_input_tokens: 0`，用 or 会把"命中 0"
    # 误判成"上游没上报"，于是又回到"不可判定 ≠ 0"的反面。
    _candidates = (
        prompt_details.get("cached_tokens") if "cached_tokens" in prompt_details else None,
        input_details.get("cached_tokens") if "cached_tokens" in input_details else None,
        usage.get("prompt_cache_hit_tokens"),
        usage.get("cache_read_input_tokens"),
        usage.get("cached_content_token_count"),
        usage.get("cached_tokens"),
    )
    cached_tokens = next((value for value in _candidates if value is not None), None)
    #: 是否**真的上报过**缓存指标：False ⇒ 上游对本响应只字未提（不可判定 ≠ 0）。
    usage["cache_reported"] = cached_tokens is not None
    if cached_tokens is not None:
        try:
            usage["cached_tokens"] = int(cached_tokens)
        except (TypeError, ValueError):
            pass
    cache_creation = usage.get("cache_creation_input_tokens")
    if cache_creation is not None:
        try:
            usage["cache_creation_tokens"] = int(cache_creation)
        except (TypeError, ValueError):
            pass

    # 2026 缓存效能归一化：计算命中率 (0.0% ~ 100.0%)
    input_t = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    if isinstance(input_t, (int, float)) and input_t > 0 and usage.get("cached_tokens") is not None:
        usage["cache_hit_ratio"] = round(float(usage["cached_tokens"]) / float(input_t) * 100.0, 1)

    # 截断显性化：Responses 用 status/incomplete_details，Chat 用 finish_reason=length。
    # 只做标注、不改控制流 —— 硬门禁仍是决策层的 JSON 校验。
    if target_format == "openai_responses":
        status = str(res_json.get("status") or "").strip().lower()
        usage["truncated"] = bool(status and status not in ("completed", "success"))
    else:
        finish = str((res_json.get("choices") or [{}])[0].get("finish_reason") or "").strip().lower()
        usage["truncated"] = finish == "length"

    return content, reasoning_content, usage


def build_request_spec(
    model: str,
    messages: List[Dict[str, str]],
    base_url: str,
    api_key: str = "",
    api_format: str = "openai_chat",
    reasoning_effort: str = "high",
    temperature: Optional[float] = 0.2,
    response_format: Optional[Dict[str, Any]] = None,
    reasoning_type: str = "auto",
    max_tokens: int = 4096,
    api_path: str = "",
) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
    """Build endpoint URL, headers, and request payload according to the specific API protocol format."""
    cleaned_url = base_url.rstrip("/")
    # 「API 路径」字段生效：标准路径由协议格式决定；仅非标准自定义路径覆盖之。
    custom_path = str(api_path or "").strip()
    if custom_path and not custom_path.startswith("/"):
        custom_path = "/" + custom_path
    if custom_path in ("/chat/completions", "/messages", "/responses", "/v1/chat/completions", "/v1/messages", "/v1/responses"):
        custom_path = ""
    m_lower = model.lower()
    rtype = reasoning_type if reasoning_type != "auto" else _detect_reasoning_type(model)
    effort = (reasoning_effort or "auto").strip().lower()

    # 2026 会话亲和性标识（Session Affinity）：防止反代或中转集群轮询不同 Key 打散服务端显存 KV Cache
    first_sys = next((str(m.get("content") or "") for m in messages if m.get("role") == "system"), "")
    if not first_sys and messages:
        first_sys = str(messages[0].get("content") or "")
    affinity_seed = f"{model}:{first_sys[:300]}"
    affinity_id = f"astra-{hashlib.sha256(affinity_seed.encode('utf-8')).hexdigest()[:16]}"

    # Protocol 1: Anthropic Claude Messages API
    if api_format == "claude_messages":
        endpoint = _join_api_path(cleaned_url, custom_path or "/messages")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AstraQuant/8.3 (Claude-Messages)",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "X-Session-ID": affinity_id,
        }
        if api_key:
            headers["x-api-key"] = api_key

        # Separate system message
        system_chunks = [m["content"] for m in messages if m.get("role") == "system"]
        chat_messages = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") != "system"]

        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": chat_messages,
        }
        if system_chunks:
            sys_combined = "\n\n".join(system_chunks)
            # 2026 Claude Prompt Caching: >=1000 字符长系统提示词注入 ephemeral 缓存断点
            if len(sys_combined) >= 1000:
                payload["system"] = [
                    {
                        "type": "text",
                        "text": sys_combined,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                payload["system"] = sys_combined

        if effort in ("max", "xhigh", "high", "medium", "low"):
            budget_map = {
                "max": 64000,
                "xhigh": 32000,
                "high": 16000,
                "medium": 8000,
                "low": 2048,
            }
            budget = budget_map[effort]
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
            payload["max_tokens"] = budget + max_tokens
        elif effort == "none":
            payload["thinking"] = {"type": "disabled"}
            if temperature is not None:
                payload["temperature"] = temperature
        else:
            if temperature is not None:
                payload["temperature"] = temperature

        return endpoint, headers, payload

    # Protocol 2: OpenAI Responses API (/responses)
    elif api_format == "openai_responses":
        endpoint = _join_api_path(cleaned_url, custom_path or "/responses")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AstraQuant/8.3 (OpenAI-Responses)",
            "X-Session-ID": affinity_id,
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload: Dict[str, Any] = {
            "model": model,
            "input": messages,
            "user": affinity_id,
        }
        if response_format and response_format.get("type") == "json_object":
            payload["text"] = {"format": {"type": "json_object"}}
        if effort in ("max", "xhigh", "high", "medium", "low", "minimal"):
            payload["reasoning"] = {"effort": effort}

        return endpoint, headers, payload

    # Protocol 3: OpenAI Chat Completions (/chat/completions, Default)
    else:
        endpoint = _join_api_path(cleaned_url, custom_path or "/chat/completions")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AstraQuant/8.3 (OpenAI-Chat)",
            "X-Session-ID": affinity_id,
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "user": affinity_id,
        }

        # Temperature handling for reasoning models vs normal models
        is_reasoning_model = (
            rtype in ("deepseek_reasoner", "standard_effort")
            or m_lower.startswith(("o1", "o3", "o4", "gpt-5", "gpt-6", "chatgpt-6"))
            or "gpt-5" in m_lower or "gpt-6" in m_lower or "chatgpt-6" in m_lower
            or "deepseek-v4" in m_lower or "v4.1" in m_lower
            or "reasoner" in m_lower
            or "-r1" in m_lower
            or "qwen3" in m_lower or "qwen-3" in m_lower or "qwq" in m_lower
            or "kimi-k" in m_lower or "glm-5" in m_lower
        )
        if not is_reasoning_model:
            if temperature is not None:
                payload["temperature"] = temperature
        else:
            if "gemini" in m_lower and temperature is not None:
                payload["temperature"] = temperature

        # Standard reasoning effort parameter (supports max, xhigh, high, medium, low, minimal, none)
        if rtype == "standard_effort" or (rtype == "auto" and (
            "gemini" in m_lower or "qwen3" in m_lower or "qwen-3" in m_lower or "qwq" in m_lower
            or m_lower.startswith(("o1", "o3", "o4", "gpt-5", "gpt-6", "chatgpt-6"))
            or "gpt-5" in m_lower or "gpt-6" in m_lower or "chatgpt-6" in m_lower
            or "deepseek-v4" in m_lower or "v4.1" in m_lower
            or "kimi-k" in m_lower or "glm-5" in m_lower
        )):
            if effort in ("max", "xhigh", "high", "medium", "low", "minimal"):
                payload["reasoning_effort"] = effort
            elif effort == "none":
                payload["reasoning_effort"] = "none"

        if response_format and rtype != "deepseek_reasoner":
            payload["response_format"] = response_format

        return endpoint, headers, payload


def build_chat_payload(
    model: str,
    messages: List[Dict[str, str]],
    reasoning_effort: str = "high",
    temperature: Optional[float] = 0.2,
    response_format: Optional[Dict[str, Any]] = None,
    reasoning_type: str = "auto",
) -> Dict[str, Any]:
    """Compatibility wrapper for standard chat payload generation."""
    _, _, payload = build_request_spec(
        model=model,
        messages=messages,
        base_url="https://api.openai.com/v1",
        api_format="openai_chat",
        reasoning_effort=reasoning_effort,
        temperature=temperature,
        response_format=response_format,
        reasoning_type=reasoning_type,
    )
    return payload


def _attempt_llm_call(
    cand: Dict[str, Any],
    messages: List[Dict[str, str]],
    temperature: Optional[float],
    response_format: Optional[Dict[str, Any]],
    effective_timeout: float,
) -> Tuple[str, str, Dict[str, Any], int]:
    """单次请求一个模型；失败时抛 _LLMTransientError（可重试）或 _LLMHardError（换模型）。"""
    endpoint, headers, payload = build_request_spec(
        model=cand["model"],
        messages=messages,
        base_url=cand["base_url"],
        api_key=cand.get("api_key", ""),
        api_format=cand.get("api_format", "openai_chat"),
        reasoning_effort=cand.get("reasoning_effort", "high"),
        temperature=temperature,
        response_format=response_format,
        reasoning_type=cand.get("reasoning_type", "auto"),
        api_path=cand.get("api_path", ""),
    )

    t0 = time.perf_counter()
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers)
    try:
        resp_handle = urllib.request.urlopen(req, timeout=effective_timeout)
    except urllib.error.HTTPError as exc:
        err_b = ""
        try:
            err_b = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        # Adaptive fallback retry on rejected parameter (400: reasoning_effort/temperature/response_format)
        if (
            exc.code == 400
            and cand.get("api_format", "openai_chat") == "openai_chat"
            and any(kw in err_b.lower() for kw in ["reasoning_effort", "temperature", "response_format", "invalid parameter"])
        ):
            fb_payload = {"model": cand["model"], "messages": messages}
            fb_req = urllib.request.Request(endpoint, data=json.dumps(fb_payload).encode("utf-8"), headers=headers)
            try:
                with urllib.request.urlopen(fb_req, timeout=effective_timeout) as fb_resp:
                    latency_ms = int((time.perf_counter() - t0) * 1000)
                    fb_json = json.loads(fb_resp.read().decode("utf-8", errors="replace"))
                content, reasoning, usage = _parse_llm_response(cand.get("api_format", "openai_chat"), fb_json)
                if not content and not reasoning:
                    raise _LLMTransientError(f"模型 {cand['model']} 返回空正文（已自适应去参数重试）")
                return content, reasoning, usage, latency_ms
            except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError) as fb_exc:
                fb_code = getattr(fb_exc, "code", 0) or 0
                if fb_code and not _is_transient_http(fb_code, str(getattr(fb_exc, "msg", "") or fb_exc)):
                    raise _LLMHardError(f"LLM 网关返回 HTTP {fb_code}（模型 {cand['model']}）：{str(fb_exc)[:280]}") from fb_exc
                raise _LLMTransientError(f"LLM 网关返回 HTTP {exc.code}（模型 {cand['model']}）：{(err_b or '')[:280]}") from fb_exc
        if _is_transient_http(exc.code, err_b):
            raise _LLMTransientError(
                f"LLM 网关返回 HTTP {exc.code}（模型 {cand['model']}）：{(err_b or '')[:280]}",
                fail_over_now=(exc.code == 504),  # 504=上游已超时：链上有下一个模型则立即切换
            ) from exc
        raise _LLMHardError(f"LLM 网关返回 HTTP {exc.code}（模型 {cand['model']}）：{(err_b or '')[:280]}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise _LLMTransientError(
            f"LLM 推演超时（已达到思考上限时间 {effective_timeout:.0f}s）：模型思考链过长未在时限内完成响应，可前往后台 AI 模型设置中调大思考上限时间",
            timed_out=True,
            fail_over_now=True,  # 慢故障：有回退链时立即切换，不再原地烧第二个超时窗口
        ) from exc
    except urllib.error.URLError as exc:
        # 连接层异常（拒绝/重置/DNS/TLS/断线）与超时包装同样属于瞬时故障：
        # 旧版在此处直接 raise，导致「失败一次就不再请求」——现在纳入重试与回退。
        reason = getattr(exc, "reason", None)
        timed_out = isinstance(reason, (socket.timeout, TimeoutError))
        raise _LLMTransientError(
            f"LLM 连接层异常（模型 {cand['model']}）：{type(reason).__name__ if reason is not None else type(exc).__name__}: {str(reason or exc)[:220]}",
            timed_out=timed_out,
            fail_over_now=timed_out,  # 连接层包装的超时同样按慢故障快速换模型
        ) from exc
    except (ValueError, OSError) as exc:
        # 响应体非 JSON（如反代 HTML 错误页）、读取中断等：可重试
        raise _LLMTransientError(f"LLM 响应体解析失败（模型 {cand['model']}）：{str(exc)[:200]}") from exc

    with resp_handle as resp:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        body_bytes = resp.read()
        try:
            res_json = json.loads(body_bytes.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise _LLMTransientError(f"LLM 响应体非 JSON（模型 {cand['model']}）：{str(body_bytes[:160])!r}") from exc

    content, reasoning, usage = _parse_llm_response(cand.get("api_format", "openai_chat"), res_json)
    if not content and not reasoning:
        raise _LLMTransientError(f"模型 {cand['model']} 返回空正文（HTTP 200 但无 content/reasoning，疑似上游静默失败）")
    return content, reasoning, usage, latency_ms
