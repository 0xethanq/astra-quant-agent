"""三协议 SSE 流式调用与原生 Tool Calling（含不兼容网关自动 ReAct JSON 降级）。"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from astra_backend.llm.transport import build_request_spec


def _normalize_tools_for_format(api_format: str, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not tools:
        return []
    if api_format == "claude_messages":
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters") or {"type": "object", "properties": {}},
            }
            for t in tools
        ]
    if api_format == "openai_responses":
        return [
            {
                "type": "function",
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters") or {"type": "object", "properties": {}},
            }
            for t in tools
        ]
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters") or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def _convert_messages_for_claude(messages: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
    system_parts: List[str] = []
    out: List[Dict[str, Any]] = []
    pending_tool_results: List[Dict[str, Any]] = []

    def _flush_tool_results() -> None:
        if pending_tool_results:
            out.append({"role": "user", "content": list(pending_tool_results)})
            pending_tool_results.clear()

    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            if m.get("content"):
                system_parts.append(str(m["content"]))
            continue
        if role == "tool":
            pending_tool_results.append({
                "type": "tool_result",
                "tool_use_id": str(m.get("tool_call_id") or ""),
                "content": str(m.get("content") or "{}"),
            })
            continue

        _flush_tool_results()
        if role == "assistant" and m.get("tool_calls"):
            blocks: List[Dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": str(m["content"])})
            for tc in m.get("tool_calls") or []:
                args = tc.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args) if args.strip() else {}
                    except json.JSONDecodeError:
                        args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": str(tc.get("id") or f"call_{uuid.uuid4().hex[:10]}"),
                    "name": str(tc.get("name") or ""),
                    "input": args if isinstance(args, dict) else {},
                })
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": role, "content": str(m.get("content") or "")})

    _flush_tool_results()
    return "\n\n".join(system_parts), out


def _convert_messages_for_responses(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "user")
        if role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": str(m.get("tool_call_id") or ""),
                "output": str(m.get("content") or "{}"),
            })
            continue
        if role == "assistant" and m.get("tool_calls"):
            if m.get("content"):
                items.append({"role": "assistant", "content": str(m["content"])})
            for tc in m.get("tool_calls") or []:
                raw_args = tc.get("arguments")
                arg_str = raw_args if isinstance(raw_args, str) else json.dumps(raw_args or {}, ensure_ascii=False)
                items.append({
                    "type": "function_call",
                    "call_id": str(tc.get("id") or f"call_{uuid.uuid4().hex[:10]}"),
                    "name": str(tc.get("name") or ""),
                    "arguments": arg_str,
                })
            continue
        items.append({"role": role, "content": str(m.get("content") or "")})
    return items


def _convert_messages_for_openai_chat(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "user")
        if role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": str(m.get("tool_call_id") or ""),
                "content": str(m.get("content") or "{}"),
            })
            continue
        if role == "assistant" and m.get("tool_calls"):
            formatted_calls = []
            for tc in m.get("tool_calls") or []:
                raw_args = tc.get("arguments")
                arg_str = raw_args if isinstance(raw_args, str) else json.dumps(raw_args or {}, ensure_ascii=False)
                formatted_calls.append({
                    "id": str(tc.get("id") or f"call_{uuid.uuid4().hex[:10]}"),
                    "type": "function",
                    "function": {"name": str(tc.get("name") or ""), "arguments": arg_str},
                })
            out.append({
                "role": "assistant",
                "content": str(m.get("content") or "") or None,
                "tool_calls": formatted_calls,
            })
            continue
        out.append({"role": role, "content": str(m.get("content") or "")})
    return out


def _safe_parse_args(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"_raw": parsed}
    except json.JSONDecodeError:
        return {"_raw_args": text}


def _should_fallback_react(status_code: int, body_text: str) -> bool:
    if status_code not in (400, 404, 415, 422):
        return False
    low = (body_text or "").lower()
    markers = ("tools", "tool_choice", "function", "stream", "unsupported", "invalid parameter", "unknown field", "thinking")
    return any(m in low for m in markers)


def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", cleaned)
    candidates = [fence.group(1)] if fence else []
    candidates.append(cleaned)
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidates.append(cleaned[first_brace : last_brace + 1])
    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict) and ("tool_calls" in obj or "final_answer" in obj):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _build_react_messages(messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    tool_brief = [
        {"name": t["name"], "description": t.get("description", ""), "parameters": t.get("parameters", {})}
        for t in tools
    ]
    react_instr = (
        "\n\n【兼容工具调用协议（JSON）】\n"
        "当前模型通道以纯文本响应。若需要调用工具，请**仅输出一个 JSON 对象**：\n"
        '{"thought":"简短思考","tool_calls":[{"name":"工具名","arguments":{...}}]}\n'
        "若已有足够信息回答用户，请**仅输出**：\n"
        '{"final_answer":"给用户的完整回复"}\n'
        f"可用工具清单：\n{json.dumps(tool_brief, ensure_ascii=False)}"
    )
    out: List[Dict[str, str]] = []
    sys_injected = False
    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            content = str(m.get("content") or "")
            if not sys_injected:
                content += react_instr
                sys_injected = True
            out.append({"role": "system", "content": content})
        elif role == "tool":
            out.append({
                "role": "user",
                "content": f"[工具返回 {m.get('tool_name') or m.get('tool_call_id') or 'tool'}]: {m.get('content') or '{}'}",
            })
        elif role == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": json.dumps({"thought": m.get("content") or "", "tool_calls": m["tool_calls"]}, ensure_ascii=False),
            })
        else:
            out.append({"role": role if role in ("user", "assistant") else "user", "content": str(m.get("content") or "")})
    if not sys_injected:
        out.insert(0, {"role": "system", "content": react_instr.strip()})
    return out


async def _react_fallback_turn(
    runtime: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    temperature: float,
    timeout: float,
) -> AsyncIterator[Dict[str, Any]]:
    from astra_backend.llm_manager import execute_llm_request

    react_msgs = _build_react_messages(messages, tools)
    content, reasoning, usage, _latency = await asyncio.to_thread(
        execute_llm_request,
        messages=react_msgs,
        model=runtime.get("model"),
        base_url=runtime.get("base_url"),
        api_key=runtime.get("api_key"),
        api_format=runtime.get("api_format"),
        reasoning_effort=runtime.get("reasoning_effort"),
        temperature=temperature,
        timeout=timeout,
        allow_fallback=True,
    )
    if reasoning:
        yield {"type": "reasoning_delta", "text": reasoning}
    parsed = _extract_json_block(content)
    if parsed and isinstance(parsed.get("tool_calls"), list) and parsed["tool_calls"]:
        calls = []
        for idx, tc in enumerate(parsed["tool_calls"]):
            if not isinstance(tc, dict) or not tc.get("name"):
                continue
            args = tc.get("arguments")
            if isinstance(args, str):
                args = _safe_parse_args(args)
            calls.append({
                "id": str(tc.get("id") or f"call_react_{idx}_{uuid.uuid4().hex[:6]}"),
                "name": str(tc["name"]),
                "arguments": args if isinstance(args, dict) else {},
            })
        if calls:
            yield {"type": "tool_calls", "calls": calls}
            if usage:
                yield {"type": "usage", "usage": usage}
            return
    final_text = str(parsed.get("final_answer") if parsed and parsed.get("final_answer") else content or "")
    if final_text:
        yield {"type": "text_delta", "text": final_text}
    if usage:
        yield {"type": "usage", "usage": usage}


def _build_streaming_request(
    runtime: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    temperature: float,
) -> tuple[str, Dict[str, str], Dict[str, Any], str]:
    api_format = str(runtime.get("api_format") or "openai_chat")
    model = str(runtime.get("model") or "")
    base_url = str(runtime.get("base_url") or "")
    api_key = str(runtime.get("api_key") or "")
    effort = str(runtime.get("reasoning_effort") or "medium")
    rtype = str(runtime.get("reasoning_type") or "auto")
    api_path = str(runtime.get("api_path") or "")

    # 多轮工具回传时不强制开启 Claude thinking，避免缺少 signature 触发 400
    has_tool_history = any(m.get("role") == "tool" or m.get("tool_calls") for m in messages)
    effective_effort = "none" if (api_format == "claude_messages" and has_tool_history and effort != "none") else effort

    if api_format == "claude_messages":
        sys_text, conv_msgs = _convert_messages_for_claude(messages)
        seed_msgs = ([{"role": "system", "content": sys_text}] if sys_text else []) + [{"role": "user", "content": "init"}]
        endpoint, headers, payload = build_request_spec(
            model=model,
            messages=seed_msgs,
            base_url=base_url,
            api_key=api_key,
            api_format=api_format,
            reasoning_effort=effective_effort,
            temperature=temperature,
            reasoning_type=rtype,
            max_tokens=4096,
            api_path=api_path,
        )
        payload["messages"] = conv_msgs
        payload["stream"] = True
        if tools:
            payload["tools"] = _normalize_tools_for_format(api_format, tools)
        return endpoint, headers, payload, api_format

    if api_format == "openai_responses":
        input_items = _convert_messages_for_responses(messages)
        endpoint, headers, payload = build_request_spec(
            model=model,
            messages=[{"role": "user", "content": "init"}],
            base_url=base_url,
            api_key=api_key,
            api_format=api_format,
            reasoning_effort=effective_effort,
            temperature=temperature,
            reasoning_type=rtype,
            api_path=api_path,
        )
        payload["input"] = input_items
        payload["stream"] = True
        if tools:
            payload["tools"] = _normalize_tools_for_format(api_format, tools)
            payload["tool_choice"] = "auto"
        return endpoint, headers, payload, api_format

    chat_msgs = _convert_messages_for_openai_chat(messages)
    endpoint, headers, payload = build_request_spec(
        model=model,
        messages=chat_msgs,
        base_url=base_url,
        api_key=api_key,
        api_format="openai_chat",
        reasoning_effort=effective_effort,
        temperature=temperature,
        reasoning_type=rtype,
        api_path=api_path,
    )
    payload["stream"] = True
    if tools:
        payload["tools"] = _normalize_tools_for_format("openai_chat", tools)
        payload["tool_choice"] = "auto"
    return endpoint, headers, payload, "openai_chat"


async def stream_llm_turn(
    runtime: Dict[str, Any],
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    temperature: float = 0.2,
    timeout: Optional[float] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """流式请求一轮大模型推理，产出标准化的 text_delta / reasoning_delta / tool_calls / usage / error 事件。"""
    effective_timeout = float(timeout or runtime.get("thinking_timeout") or 120.0)
    endpoint, headers, payload, api_format = _build_streaming_request(runtime, messages, tools, temperature)

    client_timeout = httpx.Timeout(connect=15.0, read=effective_timeout, write=30.0, pool=15.0)
    openai_tool_buf: Dict[int, Dict[str, str]] = {}
    responses_tool_buf: Dict[str, Dict[str, str]] = {}
    claude_tool_buf: Dict[int, Dict[str, str]] = {}
    usage_data: Dict[str, Any] = {}
    saw_sse = False
    raw_non_sse: List[str] = []

    try:
        async with httpx.AsyncClient(timeout=client_timeout, follow_redirects=True) as client:
            async with client.stream("POST", endpoint, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    err_bytes = await resp.aread()
                    err_text = err_bytes.decode("utf-8", errors="replace")
                    if tools and _should_fallback_react(resp.status_code, err_text):
                        async for ev in _react_fallback_turn(runtime, messages, tools, temperature, effective_timeout):
                            yield ev
                        return
                    yield {"type": "error", "error": f"LLM 网关返回 HTTP {resp.status_code}: {err_text[:280]}"}
                    return

                content_type = str(resp.headers.get("content-type") or "").lower()
                if "application/json" in content_type and "text/event-stream" not in content_type:
                    body_bytes = await resp.aread()
                    raw_non_sse.append(body_bytes.decode("utf-8", errors="replace"))
                else:
                    current_event = ""
                    async for raw_line in resp.aiter_lines():
                        line = raw_line.rstrip("\r")
                        if not line:
                            current_event = ""
                            continue
                        if line.startswith("event:"):
                            current_event = line[6:].strip()
                            continue
                        if not line.startswith("data:"):
                            if not saw_sse:
                                raw_non_sse.append(line)
                            continue
                        saw_sse = True
                        data_str = line[5:].strip()
                        if not data_str or data_str == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(chunk, dict):
                            continue

                        if api_format == "claude_messages":
                            etype = str(chunk.get("type") or current_event)
                            if etype == "message_start":
                                msg_usage = (chunk.get("message") or {}).get("usage")
                                if isinstance(msg_usage, dict):
                                    usage_data.update(msg_usage)
                            elif etype == "content_block_start":
                                idx = int(chunk.get("index", 0))
                                block = chunk.get("content_block") or {}
                                if block.get("type") == "tool_use":
                                    claude_tool_buf[idx] = {
                                        "id": str(block.get("id") or f"call_{uuid.uuid4().hex[:10]}"),
                                        "name": str(block.get("name") or ""),
                                        "args": "",
                                    }
                            elif etype == "content_block_delta":
                                idx = int(chunk.get("index", 0))
                                delta = chunk.get("delta") or {}
                                dtype = delta.get("type")
                                if dtype == "thinking_delta" and delta.get("thinking"):
                                    yield {"type": "reasoning_delta", "text": str(delta["thinking"])}
                                elif dtype == "text_delta" and delta.get("text"):
                                    yield {"type": "text_delta", "text": str(delta["text"])}
                                elif dtype == "input_json_delta" and delta.get("partial_json"):
                                    if idx in claude_tool_buf:
                                        claude_tool_buf[idx]["args"] += str(delta["partial_json"])
                            elif etype == "message_delta":
                                if isinstance(chunk.get("usage"), dict):
                                    usage_data.update(chunk["usage"])

                        elif api_format == "openai_responses":
                            etype = str(chunk.get("type") or current_event)
                            if etype == "response.reasoning_summary_text.delta" and chunk.get("delta"):
                                yield {"type": "reasoning_delta", "text": str(chunk["delta"])}
                            elif etype == "response.output_text.delta" and chunk.get("delta"):
                                yield {"type": "text_delta", "text": str(chunk["delta"])}
                            elif etype == "response.output_item.added":
                                item = chunk.get("item") or {}
                                if item.get("type") == "function_call":
                                    item_id = str(item.get("id") or item.get("call_id") or f"fc_{len(responses_tool_buf)}")
                                    responses_tool_buf[item_id] = {
                                        "id": str(item.get("call_id") or item_id),
                                        "name": str(item.get("name") or ""),
                                        "args": str(item.get("arguments") or ""),
                                    }
                            elif etype == "response.function_call_arguments.delta":
                                item_id = str(chunk.get("item_id") or "")
                                if item_id in responses_tool_buf and chunk.get("delta"):
                                    responses_tool_buf[item_id]["args"] += str(chunk["delta"])
                            elif etype == "response.completed":
                                resp_obj = chunk.get("response") or {}
                                if isinstance(resp_obj.get("usage"), dict):
                                    usage_data.update(resp_obj["usage"])

                        else:
                            if isinstance(chunk.get("usage"), dict):
                                usage_data.update(chunk["usage"])
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = (choices[0] or {}).get("delta") or {}
                            if delta.get("reasoning_content"):
                                yield {"type": "reasoning_delta", "text": str(delta["reasoning_content"])}
                            if delta.get("content"):
                                yield {"type": "text_delta", "text": str(delta["content"])}
                            for tc in delta.get("tool_calls") or []:
                                if not isinstance(tc, dict):
                                    continue
                                idx = int(tc.get("index", 0))
                                entry = openai_tool_buf.setdefault(idx, {"id": "", "name": "", "args": ""})
                                if tc.get("id"):
                                    entry["id"] = str(tc["id"])
                                fn = tc.get("function") or {}
                                if fn.get("name"):
                                    entry["name"] = str(fn["name"])
                                if fn.get("arguments"):
                                    entry["args"] += str(fn["arguments"])
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        yield {"type": "error", "error": f"LLM 请求连接或超时异常: {exc}"}
        return

    # 如果上游忽略了 stream=True 直接返回普通 JSON 响应，尝试解析或走 ReAct 降级
    if not saw_sse and raw_non_sse:
        combined_raw = "\n".join(raw_non_sse).strip()
        try:
            res_json = json.loads(combined_raw)
            if isinstance(res_json, dict) and "error" in res_json:
                yield {"type": "error", "error": f"LLM 上游错误: {str(res_json['error'])[:260]}"}
                return
            from astra_backend.llm.transport import _parse_llm_response
            c_txt, c_reason, c_usage = _parse_llm_response(api_format, res_json if isinstance(res_json, dict) else {})
            if c_reason:
                yield {"type": "reasoning_delta", "text": c_reason}
            if api_format == "openai_chat" and isinstance(res_json, dict):
                msg = (res_json.get("choices") or [{}])[0].get("message") or {}
                if msg.get("tool_calls"):
                    parsed_calls = []
                    for i, tc in enumerate(msg["tool_calls"]):
                        fn = tc.get("function") or {}
                        parsed_calls.append({
                            "id": str(tc.get("id") or f"call_{i}"),
                            "name": str(fn.get("name") or ""),
                            "arguments": _safe_parse_args(str(fn.get("arguments") or "")),
                        })
                    if parsed_calls:
                        yield {"type": "tool_calls", "calls": parsed_calls}
                        if c_usage:
                            yield {"type": "usage", "usage": c_usage}
                        return
            if c_txt:
                yield {"type": "text_delta", "text": c_txt}
            if c_usage:
                yield {"type": "usage", "usage": c_usage}
            return
        except Exception:
            if tools:
                async for ev in _react_fallback_turn(runtime, messages, tools, temperature, effective_timeout):
                    yield ev
                return

    assembled_calls: List[Dict[str, Any]] = []
    for idx in sorted(openai_tool_buf):
        item = openai_tool_buf[idx]
        if item["name"]:
            assembled_calls.append({
                "id": item["id"] or f"call_{idx}_{uuid.uuid4().hex[:6]}",
                "name": item["name"],
                "arguments": _safe_parse_args(item["args"]),
            })
    for item in responses_tool_buf.values():
        if item["name"]:
            assembled_calls.append({
                "id": item["id"] or f"call_resp_{uuid.uuid4().hex[:6]}",
                "name": item["name"],
                "arguments": _safe_parse_args(item["args"]),
            })
    for idx in sorted(claude_tool_buf):
        item = claude_tool_buf[idx]
        if item["name"]:
            assembled_calls.append({
                "id": item["id"] or f"call_cld_{idx}_{uuid.uuid4().hex[:6]}",
                "name": item["name"],
                "arguments": _safe_parse_args(item["args"]),
            })

    if assembled_calls:
        yield {"type": "tool_calls", "calls": assembled_calls}
    if usage_data:
        yield {"type": "usage", "usage": usage_data}
