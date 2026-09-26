"""Unified multi-format LLM management, connection testing, and runtime dispatch.
Supports:
1. openai_chat: OpenAI Standard /chat/completions (OpenAI, Gemini OpenAI endpoint, DeepSeek, etc.)
2. openai_responses: OpenAI Structured /responses API (Responses API format)
3. claude_messages: Anthropic Claude /messages API (Claude 3.7 / 3.5 native)
"""
from __future__ import annotations
import copy
import json
import os
import re
import socket
import tempfile
import time
from datetime import datetime, timedelta, timezone
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .file_locks import file_lock

# ── 结构优化阶段2（B4）─────────────────────────────────────────────
# 下列实现已迁往 astra_backend.llm.*，此处保留**同名重导出**，使所有既有导入路径、
# 属性访问（含测试对 _join_api_path / build_request_spec / _atomic_write_json 等
# 私有名的直接访问）全部不变。迁移只选「不引用模块常量、也不调用读常量兄弟函数」
# 的部分，因此不会打断测试以模块常量做注入的接缝。
from astra_backend.llm.capabilities import _detect_api_format, _detect_capabilities, _detect_reasoning_type
from astra_backend.llm.providers import (
    _join_api_path,
    _model_holder_pids,
    _provider_holds_active_model,
    _resolve_active_provider_id,
    _url_path_of,
)
from astra_backend.llm.transport import (
    TRANSIENT_MARKERS,
    _LLMHardError,
    _LLMTransientError,
    _attempt_llm_call,
    _is_transient_http,
    _parse_llm_response,
    build_chat_payload,
    build_request_spec,
)
from astra_backend.llm.util import _atomic_write_json, mask_secret
from astra_backend.llm.policy import (
    DEFAULT_PROVIDERS,
    DEFAULT_REQUEST_ATTEMPTS,
    FAILOVER_MAX_TOTAL_WAIT,
    MAX_FALLBACK_MODELS,
    MAX_REQUEST_ATTEMPTS,
    MIN_REQUEST_ATTEMPTS,
    STANDARD_REASONING_EFFORTS,
    SUPPORTED_API_FORMATS,
)
from astra_backend.llm.call import (
    _lookup_api_path as _core__lookup_api_path,
    execute_llm_request as _core_execute_llm_request,
    fetch_remote_models as _core_fetch_remote_models,
    test_llm_connection as _core_test_llm_connection,
)
from astra_backend.llm.failover import recent_failover_events as _core_recent_failover_events
from astra_backend.llm.store import (
    activate_provider_model as _store_activate_provider_model,
    update_llm_settings as _store_update_llm_settings,
    upsert_model as _store_upsert_model,
    delete_model as _store_delete_model,
    upsert_provider as _store_upsert_provider,
    toggle_provider as _store_toggle_provider,
    clear_provider_models as _store_clear_provider_models,
    delete_provider as _store_delete_provider,
    get_active_llm_runtime as _store_get_active_llm_runtime,
    init_llm_config as _store_init_llm_config,
    load_llm_config as _store_load_llm_config,
    resolve_model_runtime as _store_resolve_model_runtime,
)

_BJ = timezone(timedelta(hours=8))

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LLM_CONFIG_FILE = DATA_DIR / "llm_models.json"
LEGACY_PROVIDERS_FILE = DATA_DIR / "llm_providers.json"
FAILOVER_EVENTS_FILE = DATA_DIR / "llm_failover_events.json"


def init_llm_config() -> Dict[str, Any]:
    """薄壳：调用时解析 LLM_CONFIG_FILE 模块全局，测试沙箱 patch / 直接赋值必然生效。

    实现已迁往 astra_backend.llm.store.init_llm_config（结构优化阶段 2 / B4）。
    """
    return _store_init_llm_config(LLM_CONFIG_FILE)


# Backwards compatibility alias for app.py
LLM_PROVIDERS_FILE = LLM_CONFIG_FILE
init_llm_providers = init_llm_config


def save_llm_config(config: Dict[str, Any]) -> None:
    """唯一配置写入口：调用时解析 LLM_CONFIG_FILE 模块全局，测试沙箱 patch 必然生效。

    审计 P2-6：llm_models.json 同属多进程 RMW 目标（LLM 页保存 / 主脑探活写回 /
    模型同步脚本）——旧实现只有原子写、没有互斥，两个并发保存会丢一个。"""
    with file_lock(LLM_CONFIG_FILE):
        _atomic_write_json(LLM_CONFIG_FILE, config)


def load_llm_config(mask_keys: bool = True) -> Dict[str, Any]:
    """薄壳：调用时解析模块全局，测试对 init_llm_config / LLM_CONFIG_FILE 的注入必然生效。

    实现已迁往 astra_backend.llm.store（结构优化阶段 2 / B4）。
    """
    return _store_load_llm_config(init_llm_config(), mask_keys)


def get_active_llm_runtime() -> Dict[str, Any]:
    """薄壳：调用时解析模块全局，测试对 init_llm_config / LLM_CONFIG_FILE 的注入必然生效。

    实现已迁往 astra_backend.llm.store（结构优化阶段 2 / B4）。
    """
    return _store_get_active_llm_runtime(init_llm_config())


def resolve_model_runtime(model_id: str) -> Optional[Dict[str, Any]]:
    """薄壳：调用时解析模块全局，测试对 init_llm_config / LLM_CONFIG_FILE 的注入必然生效。

    实现已迁往 astra_backend.llm.store（结构优化阶段 2 / B4）。
    """
    return _store_resolve_model_runtime(init_llm_config(), model_id)


def record_failover_event(entry: Dict[str, Any]) -> None:
    """Append a resilience event (retry exhausted / fallback hit / chain failure) for admin visibility."""
    try:
        events: List[Dict[str, Any]] = []
        if FAILOVER_EVENTS_FILE.exists():
            try:
                with open(FAILOVER_EVENTS_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    events = loaded
            except Exception:
                events = []
        entry["ts"] = int(time.time())
        entry["time_str"] = datetime.fromtimestamp(entry["ts"], _BJ).isoformat(sep=" ", timespec="seconds")
        events.insert(0, entry)
        _atomic_write_json(FAILOVER_EVENTS_FILE, events[:200])
    except Exception:
        # Resilience telemetry must never break the trading path.
        pass


def recent_failover_events(limit: int = 30) -> List[Dict[str, Any]]:
    """薄壳：调用时解析门面模块全局（常量与函数），使测试的 patch / 直接赋值生效。

    实现已迁往 astra_backend.llm（结构优化阶段 2 / B4）。
    """
    return _core_recent_failover_events(FAILOVER_EVENTS_FILE, limit)


def activate_provider_model(provider_id: str, model_id: str, reasoning_effort: Optional[str] = None, thinking_timeout: Optional[float] = None) -> Dict[str, Any]:
    """薄壳：调用时解析 LLM_CONFIG_FILE 与 init_llm_config 模块全局，
    使测试对二者的 patch / 直接赋值必然生效。实现已迁往 astra_backend.llm.store
    （结构优化阶段 2 / B4）。"""
    return _store_activate_provider_model(LLM_CONFIG_FILE, init_llm_config, provider_id, model_id, reasoning_effort, thinking_timeout)


def update_llm_settings(
    active_model_id: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    thinking_timeout: Optional[float] = None,
    request_attempts: Optional[int] = None,
    fallback_model_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """薄壳：调用时解析 LLM_CONFIG_FILE 与 init_llm_config 模块全局，
    使测试对二者的 patch / 直接赋值必然生效。实现已迁往 astra_backend.llm.store
    （结构优化阶段 2 / B4）。"""
    return _store_update_llm_settings(LLM_CONFIG_FILE, init_llm_config, active_model_id, reasoning_effort, thinking_timeout, request_attempts, fallback_model_ids)


def upsert_model(provider_id: str, model_data: Dict[str, Any]) -> Dict[str, Any]:
    """薄壳：调用时解析 LLM_CONFIG_FILE 与 init_llm_config 模块全局，
    使测试对二者的 patch / 直接赋值必然生效。实现已迁往 astra_backend.llm.store
    （结构优化阶段 2 / B4）。"""
    return _store_upsert_model(LLM_CONFIG_FILE, init_llm_config, provider_id, model_data)


def delete_model(provider_id: str, model_id: str) -> bool:
    """薄壳：调用时解析 LLM_CONFIG_FILE 与 init_llm_config 模块全局，
    使测试对二者的 patch / 直接赋值必然生效。实现已迁往 astra_backend.llm.store
    （结构优化阶段 2 / B4）。"""
    return _store_delete_model(LLM_CONFIG_FILE, init_llm_config, provider_id, model_id)


def upsert_provider(provider_data: Dict[str, Any]) -> Dict[str, Any]:
    """薄壳：调用时解析 LLM_CONFIG_FILE 与 init_llm_config 模块全局，
    使测试对二者的 patch / 直接赋值必然生效。实现已迁往 astra_backend.llm.store
    （结构优化阶段 2 / B4）。"""
    return _store_upsert_provider(LLM_CONFIG_FILE, init_llm_config, provider_data)


def toggle_provider(provider_id: str, enabled: Optional[bool] = None) -> Dict[str, Any]:
    """薄壳：调用时解析 LLM_CONFIG_FILE 与 init_llm_config 模块全局，
    使测试对二者的 patch / 直接赋值必然生效。实现已迁往 astra_backend.llm.store
    （结构优化阶段 2 / B4）。"""
    return _store_toggle_provider(LLM_CONFIG_FILE, init_llm_config, provider_id, enabled)


def clear_provider_models(provider_id: str) -> bool:
    """薄壳：调用时解析 LLM_CONFIG_FILE 与 init_llm_config 模块全局，
    使测试对二者的 patch / 直接赋值必然生效。实现已迁往 astra_backend.llm.store
    （结构优化阶段 2 / B4）。"""
    return _store_clear_provider_models(LLM_CONFIG_FILE, init_llm_config, provider_id)


def delete_provider(provider_id: str) -> bool:
    """薄壳：调用时解析 LLM_CONFIG_FILE 与 init_llm_config 模块全局，
    使测试对二者的 patch / 直接赋值必然生效。实现已迁往 astra_backend.llm.store
    （结构优化阶段 2 / B4）。"""
    return _store_delete_provider(LLM_CONFIG_FILE, init_llm_config, provider_id)


def fetch_remote_models(
    base_url: str = "",
    api_key: str = "",
    provider_id: Optional[str] = None,
    timeout: float = 12.0,
) -> Dict[str, Any]:
    """薄壳：调用时解析门面模块全局（常量与函数），使测试的 patch / 直接赋值生效。

    实现已迁往 astra_backend.llm（结构优化阶段 2 / B4）。
    """
    return _core_fetch_remote_models(init_llm_config, get_active_llm_runtime, base_url, api_key, provider_id, timeout)


# ── LLM 韧性调用链：模型内重试 + 跨模型回退 ──
def execute_llm_request(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    api_format: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    temperature: Optional[float] = 0.2,
    response_format: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    allow_fallback: bool = True,
) -> Tuple[str, str, Dict[str, Any], int]:
    """薄壳：调用时解析门面模块全局（常量与函数），使测试的 patch / 直接赋值生效。

    实现已迁往 astra_backend.llm（结构优化阶段 2 / B4）。
    """
    return _core_execute_llm_request(get_active_llm_runtime, resolve_model_runtime, record_failover_event, messages, model, base_url, api_key, api_format, reasoning_effort, temperature, response_format, timeout, allow_fallback)


def _lookup_api_path(base_url: str, model_id: str) -> str:
    """薄壳：调用时解析门面模块全局（常量与函数），使测试的 patch / 直接赋值生效。

    实现已迁往 astra_backend.llm（结构优化阶段 2 / B4）。
    """
    return _core__lookup_api_path(init_llm_config, base_url, model_id)


def test_llm_connection(
    base_url: str,
    api_key: str,
    model: str,
    api_format: str = "openai_chat",
    reasoning_effort: str = "auto",
    reasoning_type: str = "auto",
    timeout: float = 15.0,
    api_path: str = "",
) -> Dict[str, Any]:
    """薄壳：调用时解析门面模块全局（常量与函数），使测试的 patch / 直接赋值生效。

    实现已迁往 astra_backend.llm（结构优化阶段 2 / B4）。
    """
    return _core_test_llm_connection(init_llm_config, base_url, api_key, model, api_format, reasoning_effort, reasoning_type, timeout, api_path)
