"""LLM 策略常量：重试/回退预算、支持的 API 格式、默认供应商。

**不含任何文件路径** —— 路径常量（LLM_CONFIG_FILE 等）留在 llm_manager.py，
因为测试靠直接赋值/ patch 它们做沙箱隔离（那是测试注入接缝）。
本模块全是不可变策略值，无测试依赖，故整块迁出。结构优化阶段 2（B4）。
"""
from __future__ import annotations

import os

# ── LLM 韧性（重试 / 回退）默认值 ──
# request_attempts：单次调用中每个模型的最大请求次数（含首次），后台可调 1~10。
# fallback_model_ids：主模型重试耗尽或非瞬时失败后按序回退的模型链，最多 5 个。
DEFAULT_REQUEST_ATTEMPTS = 3
MIN_REQUEST_ATTEMPTS = 1
MAX_REQUEST_ATTEMPTS = 10
MAX_FALLBACK_MODELS = 5
# 整条模型链的总等待软预算（只在新一次尝试发起前检查，不切断进行中的请求）；
# 必须低于网关 trader 任务 840s 超时，避免整轮推演被调度器硬杀。
FAILOVER_MAX_TOTAL_WAIT = float(os.getenv("LLM_FAILOVER_MAX_WAIT_SECONDS", "600"))
SUPPORTED_API_FORMATS = [
    {"id": "openai_chat", "name": "OpenAI Chat (/chat/completions)", "desc": "标准 ChatML 对话格式，兼容 OpenAI/Gemini/DeepSeek/主流中继"},
    {"id": "openai_responses", "name": "OpenAI Responses (/responses)", "desc": "OpenAI 专属 Responses API 结构化接口"},
    {"id": "claude_messages", "name": "Claude Messages (/messages)", "desc": "Anthropic Claude 原生 Messages API，支持原生长思维链"},
]
STANDARD_REASONING_EFFORTS = ["max", "xhigh", "high", "medium", "low", "minimal", "none", "auto"]
DEFAULT_PROVIDERS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "type": "OpenAI",
        "group": "基础供应",
        "enabled": True,
        "multi_key_enabled": False,
        "response_api_enabled": False,
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "api_format": "openai_chat",
        "api_path": "/chat/completions",
        "description": "OpenAI 兼容协议端点，支持中继网关与官方直连",
        "models": [
            {
                "id": "gemini-3.7-flash-high",
                "name": "gemini-3.7-flash-high",
                "capabilities": ["chat", "vision", "tools", "reasoning"],
                "reasoning_type": "standard_effort",
                "reasoning_effort": "high",
                "context_length": 1048576,
                "description": "Gemini 3.7 Flash 深度推演版，极速响应与强逻辑决策",
            },
            {
                "id": "gemini-3.1-flash-image",
                "name": "gemini-3.1-flash-image",
                "capabilities": ["chat", "vision"],
                "reasoning_type": "none",
                "reasoning_effort": "none",
                "context_length": 131072,
                "description": "Gemini 多模态盘口图表视觉感知模型",
            },
        ],
    },
    {
        "id": "claude",
        "name": "Claude",
        "type": "Anthropic",
        "group": "基础供应",
        "enabled": False,
        "multi_key_enabled": False,
        "response_api_enabled": False,
        "base_url": "https://api.anthropic.com/v1",
        "api_key": "",
        "api_format": "claude_messages",
        "api_path": "/messages",
        "description": "Anthropic 官方原生 Messages API 直连",
        "models": [],
    },
    {
        "id": "gemini",
        "name": "Gemini",
        "type": "Gemini",
        "group": "基础供应",
        "enabled": False,
        "multi_key_enabled": False,
        "response_api_enabled": False,
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key": "",
        "api_format": "openai_chat",
        "api_path": "/chat/completions",
        "description": "Google AI Studio 官方原生/OpenAI 兼容端点",
        "models": [],
    },
]
