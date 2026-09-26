"""模型能力判定：思维链类型 / 视觉 / API 格式。

纯函数，不读任何模块级常量 —— 因此可安全离开 llm_manager（不破坏测试注入接缝）。
结构优化阶段 2（B4）。
"""
from __future__ import annotations

import re
from typing import List


def _detect_reasoning_type(model_id: str) -> str:
    m = model_id.lower()
    if "deepseek-reasoner" in m or "deepseek-r1" in m or "-r1" in m:
        return "deepseek_reasoner"
    if (
        m.startswith(("o1", "o3", "o4"))
        or "/o1" in m or "/o3" in m or "/o4" in m
        or "gemini" in m
        or "claude-3-7" in m
        or "claude-3.7" in m
        or "qwq" in m
        # qwen3 全系（qwen3.x、qwen-3.x、qwen3-vl 等）为思考模型：
        # 旧规则把所有含 "qwen" 的模型判为 none，导致 qwen3.x 的
        # reasoning_effort 参数在运行时被静默丢弃（2026-09 用户反馈）。
        or "qwen3" in m or "qwen-3" in m
    ):
        return "standard_effort"
    if "chat" in m or "gpt-4o" in m or "gpt-3" in m or "qwen" in m or "llama" in m:
        return "none"
    return "auto"


def _detect_capabilities(model_id: str) -> List[str]:
    m = model_id.lower()
    caps = ["chat"]
    # 视觉能力按「显式多模态标记 ∪ 家族默认」判定，而非靠 flash 这类词——
    # 历史版本把 "flash" 当视觉关键词，会误标 deepseek-v4-flash 等纯文本模型。
    # 该网关下 qwen / glm / gemini / claude / gpt / grok 家族的新式模型普遍多模态，
    # 归为视觉家族；deepseek 归纯文本家族，除非名字带显式 vision 标记。
    vision_markers = ["vision", "image", "omni", "multimodal", "vl-", "-vl", "_vl", ".vl"]
    vision_families = ["gemini", "claude", "gpt-4o", "gpt-5", "gpt-6", "grok", "muse", "qwen", "glm"]
    text_only_families = ["deepseek"]
    tokens = {t for t in re.split(r"[^a-z0-9]+", m) if t}
    has_vision_marker = any(k in m for k in vision_markers) or bool(tokens & {"vl", "4v", "5v", "6v"})
    in_vision_family = any(f in m for f in vision_families)
    in_text_family = any(f in m for f in text_only_families)
    if has_vision_marker or (in_vision_family and not in_text_family):
        caps.append("vision")
    if not ("-r1-distill" in m or "-thinking" in m):
        caps.append("tools")
    if any(k in m for k in ["reasoner", "r1", "o1", "o3", "o4", "gpt-5", "gpt-6", "high", "thinking", "qwq", "deepseek-r1"]):
        caps.append("reasoning")
    return caps


def _detect_api_format(url: str, model_id: str) -> str:
    u = url.lower()
    m = model_id.lower()
    if "anthropic.com" in u or "claude" in u or "claude" in m and "messages" in u:
        return "claude_messages"
    if "responses" in u:
        return "openai_responses"
    return "openai_chat"
