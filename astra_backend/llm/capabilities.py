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
        m.startswith(("o1", "o3", "o4", "gpt-5", "gpt-6", "chatgpt-6"))
        or "/o1" in m or "/o3" in m or "/o4" in m
        or "gpt-5" in m or "gpt-6" in m or "chatgpt-6" in m
        or "deepseek-v4" in m or "deepseek-v4.1" in m or "v4.1" in m
        or "gemini" in m
        or "claude-3-7" in m
        or "claude-3.7" in m
        or "claude-4" in m
        or "qwq" in m
        # qwen3 全系（qwen3.x、qwen-3.x、qwen3-vl 等）为思考模型：
        # 旧规则把所有含 "qwen" 的模型判为 none，导致 qwen3.x 的
        # reasoning_effort 参数在运行时被静默丢弃（2026-09 用户反馈）。
        or "qwen3" in m or "qwen-3" in m
        or "kimi-k3" in m or "kimi-k2.7" in m
        or "glm-5" in m
        or "minimax-m2" in m
        or "mimo-v2" in m
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
    vision_families = ["gemini", "claude", "gpt-4o", "gpt-5", "gpt-6", "chatgpt-6", "grok", "muse", "qwen", "glm"]
    text_only_families = ["deepseek"]
    tokens = {t for t in re.split(r"[^a-z0-9]+", m) if t}
    has_vision_marker = any(k in m for k in vision_markers) or bool(tokens & {"vl", "4v", "5v", "6v"})
    in_vision_family = any(f in m for f in vision_families)
    in_text_family = any(f in m for f in text_only_families)
    if has_vision_marker or (in_vision_family and not in_text_family):
        caps.append("vision")
    if not ("-r1-distill" in m or "-thinking" in m):
        caps.append("tools")
    if any(k in m for k in [
        "reasoner", "r1", "o1", "o3", "o4", "gpt-5", "gpt-6", "chatgpt-6",
        "deepseek-v4", "v4.1", "claude-4", "kimi-k3", "glm-5",
        "high", "thinking", "qwq", "deepseek-r1"
    ]):
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


def detect_caching_capabilities(model_id: str, api_format: str = "") -> dict[str, Any]:
    """2026 大模型前缀缓存协议能力与规格判定。

    覆盖最新主流厂商前缀缓存协议与特性：
    - Anthropic Claude：支持 1h / 5m 分级 TTL 显式扩展缓存断点（cache_control）
    - Google Gemini：Gemini 2.5/3.x 原生隐式自动前缀缓存（门槛 2048 Tokens，0 存储费，减免 75%）
    - DeepSeek：HBM + NVMe SSD 上下文硬盘落盘缓存（门槛 64 Tokens，减免 75%~90%）
    - OpenAI：全自动前缀缓存 + 显式断点与保留策略（门槛 1024 Tokens，128 步长）
    - 阿里百炼 (Qwen) / Moonshot (Kimi)：显式 + 隐式双模缓存与 1h TTL
    - 一致性会话粘性路由 (Session Affinity)：跨反代防轮询打散
    """
    m = (model_id or "").lower()
    fmt = (api_format or "").lower()

    is_claude = "claude" in m or fmt == "claude_messages"
    is_deepseek = "deepseek" in m
    is_gemini = "gemini" in m
    is_qwen = "qwen" in m
    is_kimi = "kimi" in m or "moonshot" in m
    is_openai_proto = fmt in ("openai_chat", "openai_responses") or not fmt
    is_openai_family = not (is_claude or is_deepseek or is_gemini or is_qwen or is_kimi) and is_openai_proto

    if is_claude:
        primary_protocol = "Claude 1h 扩展缓存 / 显式断点 (90% 减免)"
        threshold_tokens = 1024 if "haiku" not in m else 2048
        ttl_tier = "1h (Extended) / 5m"
    elif is_gemini:
        primary_protocol = "Gemini 隐式自动前缀缓存 (75% 减免)"
        threshold_tokens = 2048 if ("2.5" in m or "flash" in m) else 4096
        ttl_tier = "滑动窗口 (自动)"
    elif is_deepseek:
        primary_protocol = "DeepSeek 硬盘落盘缓存 (HBM+SSD, 75%~90% 减免)"
        threshold_tokens = 64
        ttl_tier = "跨请求落盘单元持久化"
    elif is_qwen or is_kimi:
        primary_protocol = "百炼 / Kimi 双模缓存 (80%~90% 减免)"
        threshold_tokens = 1024
        ttl_tier = "1h / 5m 可配"
    else:
        primary_protocol = "OpenAI 自动/显式前缀缓存 (50%~80% 减免)"
        threshold_tokens = 1024
        ttl_tier = "5~10m 滑动"

    return {
        # 兼容旧键
        "claude_ephemeral": is_claude,
        "deepseek_prefix": is_deepseek,
        "openai_prefix": is_openai_family or (is_openai_proto and not (is_claude or is_deepseek)),
        "gemini_context": is_gemini,
        "session_affinity_active": True,
        # 2026 最新协议增强键
        "claude_extended_cache": is_claude,
        "gemini_implicit_cache": is_gemini,
        "deepseek_disk_cache": is_deepseek,
        "openai_auto_prefix": is_openai_family or is_openai_proto,
        "qwen_kimi_dual": is_qwen or is_kimi,
        "primary_protocol": primary_protocol,
        "threshold_tokens": threshold_tokens,
        "ttl_tier": ttl_tier,
    }


def estimate_cache_savings_usd(model_id: str, cached_tokens: int) -> float:
    """按模型厂商真实折扣动态估算缓存节约金额（USD）。"""
    if not cached_tokens or cached_tokens <= 0:
        return 0.0
    m = (model_id or "").lower()
    # 每 1M cached tokens 估算节约（USD）
    if "claude" in m:
        rate_per_m = 2.70  # $3.00 base -> $0.30 cached, save $2.70/1M
    elif "deepseek" in m:
        rate_per_m = 0.21  # ¥2.00 base -> ¥0.50 cached, save ¥1.50/1M ≈ $0.21/1M
    elif "gemini" in m:
        if "pro" in m:
            rate_per_m = 0.9375  # $1.25 base -> $0.3125 cached, save $0.9375/1M
        else:
            rate_per_m = 0.1125  # $0.15 base -> $0.0375 cached, save $0.1125/1M
    elif "gpt-4o-mini" in m:
        rate_per_m = 0.075  # $0.15 base -> $0.075 cached
    elif "gpt-4o" in m:
        rate_per_m = 1.25  # $2.50 base -> $1.25 cached
    elif "o1" in m or "o3" in m or "o4" in m:
        rate_per_m = 7.50  # $15.00 base -> $7.50 cached
    else:
        rate_per_m = 1.25  # 行业平均
    return round(float(cached_tokens) * (rate_per_m / 1_000_000.0), 4)


def estimate_total_spend_usd(model_id: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
    """根据大模型厂商官方标准定价动态估算累计 Token 支出（USD）。"""
    if (input_tokens + output_tokens) <= 0:
        return 0.0
    m = (model_id or "").lower()

    # 官方基准价（每 1M Tokens，USD）：(input_price_per_m, output_price_per_m, cached_input_price_per_m)
    if "claude-3-5" in m or "claude-3.5" in m or "claude-3-7" in m or "claude-3.7" in m:
        p_in, p_out, p_cache = 3.00, 15.00, 0.30
    elif "claude" in m and "haiku" in m:
        p_in, p_out, p_cache = 0.80, 4.00, 0.08
    elif "deepseek-reasoner" in m or "deepseek-r1" in m:
        p_in, p_out, p_cache = 0.55, 2.19, 0.14
    elif "deepseek" in m:
        p_in, p_out, p_cache = 0.14, 0.28, 0.035
    elif "gemini" in m:
        if "pro" in m:
            p_in, p_out, p_cache = 1.25, 5.00, 0.3125
        else:  # flash family (gemini-1.5-flash, gemini-2.0-flash, gemini-2.5-flash, gemini-3.8-flash)
            p_in, p_out, p_cache = 0.075, 0.30, 0.01875
    elif "gpt-4o-mini" in m:
        p_in, p_out, p_cache = 0.15, 0.60, 0.075
    elif "gpt-4o" in m:
        p_in, p_out, p_cache = 2.50, 10.00, 1.25
    elif "o1" in m or "o3" in m or "o4" in m:
        p_in, p_out, p_cache = 15.00, 60.00, 7.50
    elif "qwen" in m:
        p_in, p_out, p_cache = 0.20, 0.60, 0.05
    elif "kimi" in m:
        p_in, p_out, p_cache = 0.30, 0.90, 0.10
    else:
        p_in, p_out, p_cache = 0.50, 1.50, 0.15

    # 实际未缓存输入 Token = 总输入 - 缓存复用
    uncached_in = max(0, input_tokens - cached_tokens)
    cost = (
        (uncached_in / 1_000_000.0) * p_in
        + (cached_tokens / 1_000_000.0) * p_cache
        + (output_tokens / 1_000_000.0) * p_out
    )
    return round(cost, 4)

