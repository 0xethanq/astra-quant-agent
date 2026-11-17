"""LLM 配置库的读写与规范化（llm_models.json）。

**薄壳 + 核心**（结构优化阶段 2 / B4）：路径常量留在 llm_manager.py，
由薄壳在调用时解析后传入 —— 测试对该常量的 patch 与直接赋值因此仍然生效。
本模块不 import llm_manager（无循环依赖）。
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from astra_backend.llm.capabilities import (
    _detect_api_format,
    _detect_capabilities,
    _detect_reasoning_type,
)
from astra_backend.llm.policy import (
    DEFAULT_PROVIDERS,
    DEFAULT_REQUEST_ATTEMPTS,
    MAX_FALLBACK_MODELS,
    MAX_REQUEST_ATTEMPTS,
    MIN_REQUEST_ATTEMPTS,
    STANDARD_REASONING_EFFORTS,
    SUPPORTED_API_FORMATS,
)
from astra_backend.llm.providers import _provider_holds_active_model, _resolve_active_provider_id
from astra_backend.llm.util import _atomic_write_json, mask_secret
from astra_backend.llm.env_sync import (
    build_env_values,
    resolve_effective_endpoint,
)
from astra_backend.llm.store_upsert import (
    write_model_into_providers_local_list,
    write_model_into_top_level_list,
)
from astra_backend.llm.store_normalize import (
    finalize_config_document,
    flatten_models_into_result,
    normalize_providers_into_result,
    resolve_brain_provider_attribution,
)


def init_llm_config(config_file: Path) -> Dict[str, Any]:
    """Load or initialize clean, user-centric model configuration with multi-provider support."""
    from ..config import settings

    data: Dict[str, Any] = {}
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
        except Exception:
            data = {}

    # Extract current settings from .env / settings
    # 安全约束：不再内置任何私有中继网关作为静默默认，出口地址必须由用户显式配置。
    cur_url = getattr(settings, "llm_base_url", "") or os.getenv("LLM_BASE_URL") or ""
    cur_key = getattr(settings, "llm_api_key", "") or os.getenv("LLM_API_KEY") or ""
    cur_model = getattr(settings, "llm_model", "") or os.getenv("LLM_MODEL") or ""
    cur_effort = getattr(settings, "llm_reasoning_effort", "") or os.getenv("LLM_REASONING_EFFORT") or "high"

    existing_providers = data.get("providers", [])
    merged_providers: List[Dict[str, Any]] = []

    # 默认供应商只在「首次播种」时注入。播种完成后配置里落下 defaults_seeded 标记，
    # 此后用户删除的默认供应商绝不复活；openai 的 enabled 也只在播种时强制打开，
    # 之后尊重用户自己的开关。老配置文件（无标记）视为首次：合并一次并落标记，升级无感。
    seed_defaults = not data.get("defaults_seeded")
    default_by_id = {dp["id"]: dp for dp in DEFAULT_PROVIDERS}
    # (ignore legacy hardcoded providers from older versions only during initial seeding if no key was configured)
    legacy_ids = {
        "siliconflow", "openrouter", "kelivoin", "tensdaq", "deepseek",
        "alhubmix", "suixiang", "dashscope", "zhipu", "grok", "volcengine"
    }

    for found in existing_providers:
        pid = found.get("id")
        if not pid:
            continue
        if seed_defaults and pid in legacy_ids and not found.get("api_key"):
            continue
        dp = default_by_id.get(pid)
        if dp:
            p_obj = copy.deepcopy(dp)
            p_obj.update(found)
            # Never overwrite models with global defaults if provider was already configured
            if "models" in found:
                p_obj["models"] = list(found.get("models", []))
            if pid == "openai":
                if not p_obj.get("api_key") and cur_key:
                    p_obj["api_key"] = cur_key
                if not p_obj.get("base_url"):
                    p_obj["base_url"] = cur_url
                if seed_defaults:
                    p_obj["enabled"] = True
            merged_providers.append(p_obj)
        else:
            merged_providers.append(found)

    if seed_defaults:
        have_ids = {p.get("id") for p in merged_providers}
        for dp in DEFAULT_PROVIDERS:
            if dp["id"] in have_ids:
                continue
            p_obj = copy.deepcopy(dp)
            if dp["id"] == "openai":
                if cur_key:
                    p_obj["api_key"] = cur_key
                if cur_url:
                    p_obj["base_url"] = cur_url
                p_obj["enabled"] = True
            merged_providers.append(p_obj)

    active_m_id = data.get("active_model_id") or cur_model or ""
    active_effort = data.get("active_reasoning_effort") or cur_effort or "high"
    cur_timeout = getattr(settings, "llm_thinking_timeout", 120.0) or float(os.getenv("LLM_THINKING_TIMEOUT", os.getenv("LLM_TIMEOUT_SECONDS", "120.0")))
    raw_timeout = data.get("thinking_timeout")
    thinking_timeout = float(raw_timeout) if raw_timeout is not None else float(cur_timeout or 120.0)

    models_map: Dict[str, Dict[str, Any]] = {}
    for p in merged_providers:
        p_id = p.get("id", "")
        p_name = p.get("name", p_id)
        p_base = p.get("base_url", "")
        p_key = p.get("api_key", "")
        p_fmt = p.get("api_format", "openai_chat")
        for m in p.get("models", []):
            mid = m.get("id", "")
            if not mid:
                continue
            models_map[mid] = {
                "id": mid,
                "name": m.get("name", mid),
                "provider_id": p_id,
                "provider_name": p_name,
                "base_url": m.get("base_url") or p_base,
                "api_key": m.get("api_key") or p_key,
                "api_format": m.get("api_format") or p_fmt,
                "api_path": m.get("api_path") or p.get("api_path", ""),
                "reasoning_type": m.get("reasoning_type", _detect_reasoning_type(mid)),
                "reasoning_effort": m.get("reasoning_effort") or m.get("default_effort", "high"),
                "capabilities": m.get("capabilities", _detect_capabilities(mid)),
                "context_length": m.get("context_length"),
                "description": m.get("description", ""),
            }

    # Preserve any custom models that were added by user or tests
    prov_by_id = {p.get("id"): p for p in merged_providers}
    for m in data.get("models", []):
        mid = m.get("id")
        if mid:
            if mid in models_map:
                fresh = models_map[mid]
                merged = dict(m)
                # 供应商凭据是唯一权威源：历史快照键/地址不得覆盖供应商当前值
                if fresh.get("api_key"):
                    merged["api_key"] = fresh["api_key"]
                if fresh.get("base_url"):
                    merged["base_url"] = fresh["base_url"]
                fresh.update(merged)
            else:
                entry = dict(m)
                prov = prov_by_id.get(entry.get("provider_id"))
                if prov:
                    # 顶层扁平模型同样按 provider_id 重挂供应商当前凭据——
                    # 否则轮换密钥后旧快照键永久粘住，模型必须删掉重加才能恢复
                    if prov.get("api_key"):
                        entry["api_key"] = prov["api_key"]
                    if prov.get("base_url"):
                        entry["base_url"] = prov["base_url"]
                    if not entry.get("api_format"):
                        entry["api_format"] = prov.get("api_format", "openai_chat")
                models_map[mid] = entry

    flat_models = list(models_map.values())
    if not any(m["id"] == active_m_id for m in flat_models) and flat_models:
        active_m_id = flat_models[0]["id"]

    # ── 主脑供应商归属：嵌套持有者为准（显式记录 > 唯一持有 > 顶层扁平缓存归属）──
    # models_map 按 id 去重（后出现的供应商覆盖先出现的），多供应商挂同名模型时
    # 顶层缓存的 base_url/api_key 会静默变成另一家的——必须把主脑条目钉回其供应商。
    active_pid = resolve_brain_provider_attribution(
        _resolve_active_provider_id=_resolve_active_provider_id,
        active_m_id=active_m_id,
        data=data,
        flat_models=flat_models,
        merged_providers=merged_providers    )

    # ── 韧性配置解析：请求次数 + 回退模型链（脏数据自愈）──
    return finalize_config_document(
        DEFAULT_REQUEST_ATTEMPTS=DEFAULT_REQUEST_ATTEMPTS,
        List=List,
        MAX_FALLBACK_MODELS=MAX_FALLBACK_MODELS,
        MAX_REQUEST_ATTEMPTS=MAX_REQUEST_ATTEMPTS,
        MIN_REQUEST_ATTEMPTS=MIN_REQUEST_ATTEMPTS,
        _atomic_write_json=_atomic_write_json,
        active_effort=active_effort,
        active_m_id=active_m_id,
        active_pid=active_pid,
        config_file=config_file,
        data=data,
        flat_models=flat_models,
        merged_providers=merged_providers,
        os=os,
        thinking_timeout=thinking_timeout    )


def load_llm_config(config: Dict[str, Any], mask_keys: bool = True) -> Dict[str, Any]:
    """Return clean model configurations and configured providers matching modern client architecture."""
    providers_list = config.get("providers", [])
    active_mid = config.get("active_model_id", "")
    active_pid = _resolve_active_provider_id(config)
    active_effort = config.get("active_reasoning_effort", "high")

    res: Dict[str, Any] = {
        "version": config.get("version", "3.2"),
        "active_model_id": active_mid,
        "active_reasoning_effort": active_effort,
        "thinking_timeout": config.get("thinking_timeout", 120.0),
        "request_attempts": config.get("request_attempts", DEFAULT_REQUEST_ATTEMPTS),
        "fallback_model_ids": config.get("fallback_model_ids", []),
        "max_request_attempts": MAX_REQUEST_ATTEMPTS,
        "max_fallback_models": MAX_FALLBACK_MODELS,
        "standard_reasoning_efforts": STANDARD_REASONING_EFFORTS,
        "supported_api_formats": SUPPORTED_API_FORMATS,
        "providers": [],
        "models": [],
        "active_provider_id": active_pid or (config.get("active_provider_id") or ""),
    }

    normalize_providers_into_result(
        _detect_capabilities=_detect_capabilities,
        _detect_reasoning_type=_detect_reasoning_type,
        active_mid=active_mid,
        active_pid=active_pid,
        mask_keys=mask_keys,
        mask_secret=mask_secret,
        providers_list=providers_list,
        res=res    )

    flatten_models_into_result(
        _detect_capabilities=_detect_capabilities,
        active_mid=active_mid,
        config=config,
        mask_keys=mask_keys,
        mask_secret=mask_secret,
        providers_list=providers_list,
        res=res    )

    return res


def get_active_llm_runtime(config: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieve active LLM credentials and configuration for runtime execution."""
    from ..config import settings
    active_mid = config.get("active_model_id", "")
    active_effort = config.get("active_reasoning_effort", "high")

    target_model = next((m for m in config.get("models", []) if m["id"] == active_mid), None)

    base_url = target_model.get("base_url") if target_model else getattr(settings, "llm_base_url", "")
    api_key = target_model.get("api_key") if target_model else getattr(settings, "llm_api_key", "")
    provider_id = target_model.get("provider_id", "") if target_model else ""
    provider_name = target_model.get("provider_name", "") if target_model else "默认"
    prov_api_path = str((target_model or {}).get("api_path", "") or "")

    if target_model:
        t_base = target_model.get("base_url", "").rstrip("/")
        prov = next(
            (
                p for p in config.get("providers", [])
                if p.get("id") == provider_id or (t_base and p.get("base_url", "").rstrip("/") == t_base)
            ),
            None,
        )
        if prov:
            if not api_key:
                api_key = prov.get("api_key", "")
            if not base_url:
                base_url = prov.get("base_url", "")
            if not provider_name or provider_name == "自定义":
                provider_name = prov.get("name", provider_name)
            if not provider_id:
                provider_id = prov.get("id", "openai")
            if not prov_api_path:
                prov_api_path = str(prov.get("api_path", "") or "")

    base_url = (base_url or os.getenv("LLM_BASE_URL", "")).rstrip("/")
    if not base_url:
        raise RuntimeError(
            "LLM 出口未配置：请在 .env 设置 LLM_BASE_URL，或在后台「LLM Providers」中选择/新建供应商。"
            "出于数据流向透明要求，系统不再内置任何默认第三方中继网关。"
        )
    api_key = api_key or os.getenv("LLM_API_KEY", "")

    model_name = active_mid or getattr(settings, "llm_model", "") or os.getenv("LLM_MODEL", "")
    api_format = target_model.get("api_format") if target_model else _detect_api_format(base_url, model_name)
    reasoning_type = target_model.get("reasoning_type", "auto") if target_model else _detect_reasoning_type(model_name)
    thinking_timeout = float(
        target_model.get("thinking_timeout")
        if target_model and target_model.get("thinking_timeout")
        else config.get("thinking_timeout")
        or os.getenv("LLM_THINKING_TIMEOUT")
        or os.getenv("LLM_TIMEOUT_SECONDS")
        or getattr(settings, "llm_thinking_timeout", 120.0)
    )

    return {
        "model": model_name,
        "name": target_model.get("name", model_name) if target_model else model_name,
        "provider_name": provider_name or "默认",
        "provider_id": provider_id or "openai",
        "base_url": base_url,
        "api_key": api_key,
        "api_format": api_format,
        "api_path": prov_api_path,
        "reasoning_effort": active_effort,
        "reasoning_type": reasoning_type,
        "thinking_timeout": thinking_timeout,
        "request_attempts": config.get("request_attempts", DEFAULT_REQUEST_ATTEMPTS),
        "fallback_model_ids": config.get("fallback_model_ids", []),
    }


def resolve_model_runtime(config: Dict[str, Any], model_id: str) -> Optional[Dict[str, Any]]:
    """Resolve a configured model (e.g. a fallback) into a callable runtime spec.
    Returns None when the model is unknown or has no usable endpoint."""
    target = next((m for m in config.get("models", []) if m.get("id") == model_id), None)
    if not target:
        return None
    base_url = (target.get("base_url") or "").rstrip("/")
    api_key = target.get("api_key") or ""
    if not api_key or not base_url:
        prov = next((p for p in config.get("providers", []) if p.get("id") == target.get("provider_id")), None)
        if prov:
            base_url = base_url or (prov.get("base_url") or "").rstrip("/")
            api_key = api_key or prov.get("api_key", "")
    if not base_url:
        return None
    mid = target.get("id", model_id)
    api_format = target.get("api_format") or _detect_api_format(base_url, mid)
    reasoning_type = target.get("reasoning_type") or _detect_reasoning_type(mid)
    effort = target.get("reasoning_effort") or target.get("default_effort") or "high"
    try:
        thinking_timeout = float(target.get("thinking_timeout") or config.get("thinking_timeout") or 120.0)
    except (TypeError, ValueError):
        thinking_timeout = float(config.get("thinking_timeout") or 120.0)
    return {
        "model": mid,
        "name": target.get("name", mid),
        "provider_id": target.get("provider_id", ""),
        "provider_name": target.get("provider_name", "自定义"),
        "base_url": base_url,
        "api_key": api_key,
        "api_format": api_format,
        "api_path": str(target.get("api_path", "") or ""),
        "reasoning_effort": effort if effort in STANDARD_REASONING_EFFORTS else "high",
        "reasoning_type": reasoning_type,
        "thinking_timeout": thinking_timeout,
    }


def activate_provider_model(config_file: Path, reload_config: Callable[[], Dict[str, Any]], provider_id: str, model_id: str, reasoning_effort: Optional[str] = None, thinking_timeout: Optional[float] = None) -> Dict[str, Any]:
    """One-click switch to activate a model. Updates config, .env, and encrypted store."""
    from ..settings_store import update_env
    from ..config import refresh_settings
    try:
        from astra_gateway.secrets import save_secrets
    except ImportError:
        save_secrets = None

    config = reload_config()
    flat_model = next((m for m in config.get("models", []) if m["id"] == model_id), None)
    target_model: Optional[Dict[str, Any]] = None
    scoped_pid = str(provider_id or "").strip()
    scoped_prov: Optional[Dict[str, Any]] = None

    if scoped_pid and scoped_pid != "custom":
        # 从指定供应商的「模型」页设为主脑：归属以本次调用的供应商为准，
        # 解决多供应商挂同名模型时顶层缓存只按 model id 记录导致的混挂。
        scoped_prov = next((p for p in config.get("providers", []) if p.get("id") == scoped_pid), None)
        if scoped_prov is None:
            raise ValueError(f"供应商 {scoped_pid} 未找到，无法激活")
        nested = next((m for m in scoped_prov.get("models", []) if m.get("id") == model_id), None)
        if nested is None and not (flat_model and str(flat_model.get("provider_id") or "") == scoped_pid):
            raise ValueError(
                f"供应商 {scoped_prov.get('name')} 名下没有模型 {model_id}；请先在该供应商下添加，再设为主脑。"
            )
        nested = nested or {}
        target_model = {
            "id": model_id,
            "name": nested.get("name") or (flat_model or {}).get("name") or model_id,
            "provider_id": scoped_prov.get("id"),
            "provider_name": scoped_prov.get("name", scoped_pid),
            "base_url": scoped_prov.get("base_url", "") or (flat_model or {}).get("base_url", ""),
            "api_key": scoped_prov.get("api_key", ""),
            "api_format": nested.get("api_format")
            or (flat_model or {}).get("api_format")
            or scoped_prov.get("api_format", "openai_chat"),
            "reasoning_type": nested.get("reasoning_type")
            or (flat_model or {}).get("reasoning_type")
            or _detect_reasoning_type(model_id),
            "reasoning_effort": nested.get("reasoning_effort")
            or nested.get("default_effort")
            or (flat_model or {}).get("reasoning_effort", "high"),
            "capabilities": nested.get("capabilities") or (flat_model or {}).get("capabilities", []),
            "context_length": nested.get("context_length") or (flat_model or {}).get("context_length"),
            "description": nested.get("description") or (flat_model or {}).get("description", ""),
        }
        # 顶层扁平缓存钉到主脑供应商的凭据上，交易引擎与全局列表随之对齐
        if flat_model is not None:
            flat_model.update(target_model)
        else:
            config.setdefault("models", []).append(target_model)

    if target_model is None:
        target_model = flat_model
    if not target_model:
        # Check providers models
        for p in config.get("providers", []):
            m_found = next((m for m in p.get("models", []) if m.get("id") == model_id), None)
            if m_found:
                target_model = {
                    "id": model_id,
                    "name": m_found.get("name", model_id),
                    "provider_id": p.get("id"),
                    "provider_name": p.get("name"),
                    "base_url": p.get("base_url"),
                    "api_key": p.get("api_key"),
                    "api_format": p.get("api_format", "openai_chat"),
                    "reasoning_type": m_found.get("reasoning_type", _detect_reasoning_type(model_id)),
                    "reasoning_effort": m_found.get("reasoning_effort", "high"),
                    "description": m_found.get("description", ""),
                }
                config.setdefault("models", []).append(target_model)
                break

    if not target_model:
        target_model = {
            "id": model_id,
            "name": model_id,
            "provider_name": "自定义",
            "base_url": os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
            "api_key": os.getenv("LLM_API_KEY", ""),
            "api_format": "openai_chat",
            "reasoning_type": _detect_reasoning_type(model_id),
            "reasoning_effort": "high",
            "description": "一键激活时自动收录",
        }
        config.setdefault("models", []).append(target_model)

    effort = reasoning_effort or target_model.get("reasoning_effort") or "high"
    if effort not in STANDARD_REASONING_EFFORTS:
        effort = "auto"

    config["active_model_id"] = model_id
    config["active_provider_id"] = str(target_model.get("provider_id") or "")
    config["active_reasoning_effort"] = effort
    if thinking_timeout is not None:
        timeout_val = max(5.0, min(float(thinking_timeout), 1800.0))
        config["thinking_timeout"] = timeout_val
    _atomic_write_json(config_file, config)

    # Sync to .env and secrets
    (base_url, api_key) = resolve_effective_endpoint(
        config=config,
        os=os,
        target_model=target_model    )

    env_values = build_env_values(
        api_key=api_key,
        base_url=base_url,
        effort=effort,
        model_id=model_id,
        save_secrets=save_secrets,
        thinking_timeout=thinking_timeout    )

    update_env(env_values)
    refresh_settings()

    return {
        "success": True,
        "active_model_id": model_id,
        "active_model_name": target_model.get("name"),
        "active_reasoning_effort": effort,
        "thinking_timeout": config.get("thinking_timeout", 120.0),
        "base_url": base_url,
        "api_format": target_model.get("api_format", "openai_chat"),
        "provider_name": target_model.get("provider_name", "自定义"),
        "active_provider_id": target_model.get("provider_id", "openai"),
        "active_provider_name": target_model.get("provider_name", "自定义"),
    }


def update_llm_settings(config_file: Path, reload_config: Callable[[], Dict[str, Any]], 
    active_model_id: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    thinking_timeout: Optional[float] = None,
    request_attempts: Optional[int] = None,
    fallback_model_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Update global LLM settings: model, reasoning effort, thinking timeout, retry attempts and fallback chain."""
    from ..settings_store import update_env
    from ..config import refresh_settings

    config = reload_config()
    env_values: Dict[str, Any] = {}

    if active_model_id:
        config["active_model_id"] = active_model_id
        env_values["LLM_MODEL"] = active_model_id
        # 主脑换了模型 → 供应商归属立即重判，防止 active_provider_id 悬在旧模型上
        config["active_provider_id"] = _resolve_active_provider_id(config)

    if reasoning_effort:
        config["active_reasoning_effort"] = reasoning_effort
        env_values["LLM_REASONING_EFFORT"] = reasoning_effort

    if thinking_timeout is not None:
        val = max(5.0, min(float(thinking_timeout), 1800.0))
        config["thinking_timeout"] = val
        env_values["LLM_THINKING_TIMEOUT"] = str(int(val) if val.is_integer() else val)

    if request_attempts is not None:
        try:
            att = int(request_attempts)
        except (TypeError, ValueError) as exc:
            raise ValueError("请求次数必须是整数") from exc
        if not (MIN_REQUEST_ATTEMPTS <= att <= MAX_REQUEST_ATTEMPTS):
            raise ValueError(f"请求次数需在 {MIN_REQUEST_ATTEMPTS}~{MAX_REQUEST_ATTEMPTS} 之间")
        config["request_attempts"] = att

    if fallback_model_ids is not None:
        known_ids = {m.get("id") for m in config.get("models", [])}
        new_active = config.get("active_model_id", "")
        cleaned: List[str] = []
        for fid in fallback_model_ids:
            fid = str(fid or "").strip()
            if not fid:
                continue
            if fid == new_active:
                continue  # 主脑模型不能同时是自己的回退
            if fid not in known_ids:
                raise ValueError(f"回退模型不存在：{fid}（请先在模型列表中添加）")
            if fid not in cleaned:
                cleaned.append(fid)
        if len(cleaned) > MAX_FALLBACK_MODELS:
            raise ValueError(f"回退模型最多 {MAX_FALLBACK_MODELS} 个，避免整轮推演超时")
        config["fallback_model_ids"] = cleaned

    _atomic_write_json(config_file, config)
    if env_values:
        update_env(env_values)
        refresh_settings()

    return {
        "success": True,
        "active_model_id": config.get("active_model_id"),
        "active_reasoning_effort": config.get("active_reasoning_effort"),
        "thinking_timeout": config.get("thinking_timeout", 120.0),
        "request_attempts": config.get("request_attempts", DEFAULT_REQUEST_ATTEMPTS),
        "fallback_model_ids": config.get("fallback_model_ids", []),
    }


def upsert_model(config_file: Path, reload_config: Callable[[], Dict[str, Any]], provider_id: str, model_data: Dict[str, Any]) -> Dict[str, Any]:
    """Add or update a custom model definition."""
    mid = str(model_data.get("id", "")).strip()
    provider_id = str(provider_id or "").strip()
    # 旧全局路由 /llm/models 不带路径参数（provider_id 恒为 "custom"），
    # 但前端 payload 一直携带归属供应商——尊重 payload，避免模型落错家。
    payload_pid = str(model_data.get("provider_id", "") or "").strip()
    if (not provider_id or provider_id == "custom") and payload_pid and payload_pid != "custom":
        provider_id = payload_pid
    name = str(model_data.get("name", "")).strip() or mid
    base_url = str(model_data.get("base_url", "")).strip().rstrip("/")
    api_key = str(model_data.get("api_key", "")).strip()
    api_format = str(model_data.get("api_format", "openai_chat")).strip()
    provider_name = str(model_data.get("provider_name", "")).strip()
    reasoning_type = str(model_data.get("reasoning_type", "auto")).strip()
    default_effort = str(model_data.get("default_effort") or model_data.get("reasoning_effort", "high")).strip()
    desc = str(model_data.get("description", "")).strip()
    caps = model_data.get("capabilities") or _detect_capabilities(mid)
    ctx_len = model_data.get("context_length")

    if not mid:
        raise ValueError("模型 ID 不能为空")

    config = reload_config()

    prov = None
    if provider_id and provider_id != "custom":
        prov = next((p for p in config.get("providers", []) if p["id"] == provider_id), None)
    if not prov and provider_name:
        prov = next((p for p in config.get("providers", []) if p.get("name") == provider_name), None)

    if prov:
        if not base_url:
            base_url = prov.get("base_url", "")
        # 不再把供应商密钥快照进模型条目：密钥唯一存放处是供应商，
        # 读取时由 init_llm_config 合并注入；轮换密钥即刻对全部模型生效
        if not provider_name:
            provider_name = prov.get("name", "自定义")
        if not provider_id:
            provider_id = prov.get("id", "openai")

    if not base_url or not base_url.startswith(("http://", "https://")):
        active = get_active_llm_runtime(reload_config())
        base_url = active.get("base_url", "https://api.openai.com/v1")

    valid_formats = [f["id"] for f in SUPPORTED_API_FORMATS]
    if api_format not in valid_formats:
        api_format = _detect_api_format(base_url, mid)

    models = config.setdefault("models", [])
    existing = next((m for m in models if m["id"] == mid), None)

    write_model_into_top_level_list(
        api_format=api_format,
        api_key=api_key,
        base_url=base_url,
        caps=caps,
        ctx_len=ctx_len,
        default_effort=default_effort,
        desc=desc,
        existing=existing,
        mid=mid,
        models=models,
        name=name,
        provider_id=provider_id,
        provider_name=provider_name,
        reasoning_type=reasoning_type    )

    write_model_into_providers_local_list(
        caps=caps,
        ctx_len=ctx_len,
        default_effort=default_effort,
        desc=desc,
        mid=mid,
        name=name,
        prov=prov,
        reasoning_type=reasoning_type    )

    if mid == config.get("active_model_id") and default_effort:
        config["active_reasoning_effort"] = default_effort
        try:
            from ..settings_store import update_env
            update_env({"LLM_REASONING_EFFORT": default_effort})
        except Exception:
            pass

    _atomic_write_json(config_file, config)
    return {
        "model_id": mid,
        "name": name,
        "base_url": base_url,
        "api_format": api_format,
        "provider_id": provider_id or "openai",
    }


def delete_model(config_file: Path, reload_config: Callable[[], Dict[str, Any]], provider_id: str, model_id: str) -> bool:
    """Delete a custom model.

    多供应商挂同名模型时的作用域规则：
    - 只有「主脑所属供应商」名下的那份不可删，其他供应商的同名副本可正常删除；
    - 顶层扁平缓存只按 (id, provider_id) 摘除对应条目，别家持有者由下次加载自动重挂；
    - 不带供应商作用域的旧路由保持全量删除语义（各供应商一并移除）。
    """
    config = reload_config()
    scoped = bool(provider_id) and provider_id != "custom"
    active_mid = config.get("active_model_id", "")

    if active_mid and model_id == active_mid:
        active_pid = _resolve_active_provider_id(config)
        if not scoped:
            raise ValueError(
                "不能删除当前正在使用的模型；请先切换到其他模型后再删除。"
                "若只想删某家供应商名下的副本，请进入该供应商的模型页操作。"
            )
        if active_pid:
            if active_pid == provider_id:
                prov_name = next(
                    (p.get("name", provider_id) for p in config.get("providers", []) if p.get("id") == provider_id),
                    provider_id,
                )
                raise ValueError(
                    f"{model_id} 是供应商「{prov_name}」名下正在使用的主脑模型；"
                    "请先切换主脑或删除其他供应商名下的同名副本。"
                )
        else:
            raise ValueError(
                f"多个供应商名下挂有同名主脑模型 {model_id}，无法判定启用的是哪一家；"
                "请先在该供应商的模型页点「设为主脑」明确归属，再执行删除。"
            )

    models = config.get("models", [])
    providers = config.get("providers", [])

    nested_removed = False
    if scoped:
        prov = next((p for p in providers if p.get("id") == provider_id), None)
        if prov is None:
            raise ValueError(f"供应商 {provider_id} 未找到")
        before = len(prov.get("models", []))
        prov["models"] = [m for m in prov.get("models", []) if m.get("id") != model_id]
        nested_removed = len(prov["models"]) < before
        # 顶层缓存只摘属于本供应商的条目；归属漂移挂在别家名下的条目留给 init 重建时自愈
        filtered = [
            m
            for m in models
            if not (m.get("id") == model_id and str(m.get("provider_id") or "") == provider_id)
        ]
    else:
        for prov in providers:
            before = len(prov.get("models", []))
            prov["models"] = [m for m in prov.get("models", []) if m.get("id") != model_id]
            nested_removed = nested_removed or len(prov["models"]) < before
        filtered = [m for m in models if m["id"] != model_id]

    if len(filtered) == len(models) and not nested_removed:
        return False

    config["models"] = filtered
    _atomic_write_json(config_file, config)
    return True


def upsert_provider(config_file: Path, reload_config: Callable[[], Dict[str, Any]], provider_data: Dict[str, Any]) -> Dict[str, Any]:
    """Add or update an LLM provider definition."""
    pid = str(provider_data.get("id", "")).strip().lower()
    name = str(provider_data.get("name", "")).strip() or pid
    p_type = str(provider_data.get("type", "")).strip() or name
    p_group = str(provider_data.get("group", "")).strip() or "其他"
    enabled = bool(provider_data.get("enabled", False)) if "enabled" in provider_data else None
    multi_key_enabled = bool(provider_data.get("multi_key_enabled", False))
    response_api_enabled = bool(provider_data.get("response_api_enabled", False))
    base_url = str(provider_data.get("base_url", "")).strip().rstrip("/")
    api_key = str(provider_data.get("api_key", "")).strip()
    api_format = str(provider_data.get("api_format", "openai_chat")).strip()
    api_path = str(provider_data.get("api_path", "/chat/completions")).strip()
    desc = str(provider_data.get("description", "")).strip()

    if not api_format:
        api_format = "claude_messages" if "claude" in pid or "anthropic" in base_url.lower() else "openai_chat"

    # Automatically synchronize api_path with selected api_format if default was provided
    if api_path in ["/chat/completions", "/messages", "/responses", ""]:
        if api_format == "claude_messages":
            api_path = "/messages"
        elif api_format == "openai_responses":
            api_path = "/responses"
        else:
            api_path = "/chat/completions"

    response_api_enabled = (api_format == "openai_responses")

    if not pid:
        pid = re.sub(r"[^a-zA-Z0-9_\-]", "", name.lower()) or f"prov-{int(time.time())}"

    if not base_url or not base_url.startswith(("http://", "https://")):
        raise ValueError("供应商 Base URL 必须以 http:// 或 https:// 开头")

    config = reload_config()
    providers = config.setdefault("providers", [])
    existing = next((p for p in providers if p["id"] == pid), None)
    if existing:
        existing["name"] = name
        existing["type"] = p_type
        existing["group"] = p_group
        if enabled is not None:
            existing["enabled"] = enabled
        existing["multi_key_enabled"] = multi_key_enabled
        existing["response_api_enabled"] = response_api_enabled
        existing["base_url"] = base_url
        if api_key:
            existing["api_key"] = api_key
        existing["api_format"] = api_format
        existing["api_path"] = api_path
        existing["description"] = desc
    else:
        providers.append({
            "id": pid,
            "name": name,
            "type": p_type,
            "group": p_group,
            "enabled": enabled if enabled is not None else False,
            "multi_key_enabled": multi_key_enabled,
            "response_api_enabled": response_api_enabled,
            "base_url": base_url,
            "api_key": api_key,
            "api_format": api_format,
            "api_path": api_path,
            "description": desc,
            "models": [],
        })

    # ── 凭据轮换联动：供应商是密钥唯一权威源 ──
    # 1) 刷新该供应商下扁平缓存中的历史快照键/地址，杜绝旧键粘住导致"改完密钥模型全连不上"；
    # 2) 激活模型属于该供应商时，把新凭据回写全局 .env 与密钥库，交易引擎运行时同步对齐。
    if existing:
        affected = [m for m in config.get("models", []) if m.get("provider_id") == pid]
        for mm in affected:
            mm["base_url"] = base_url
            if api_key:
                mm["api_key"] = api_key
        active_mid = config.get("active_model_id", "")
        if affected and any(mm.get("id") == active_mid for mm in affected):
            try:
                from ..settings_store import update_env
                from ..config import refresh_settings
                try:
                    from astra_gateway.secrets import save_secrets
                except ImportError:
                    save_secrets = None
                env_values = {"LLM_BASE_URL": base_url}
                if api_key:
                    env_values["LLM_API_KEY"] = api_key
                    if save_secrets:
                        save_secrets({"LLM_API_KEY": api_key})
                update_env(env_values)
                refresh_settings()
            except Exception:
                pass

    _atomic_write_json(config_file, config)
    return {"id": pid, "name": name, "base_url": base_url}


def toggle_provider(config_file: Path, reload_config: Callable[[], Dict[str, Any]], provider_id: str, enabled: Optional[bool] = None) -> Dict[str, Any]:
    """Toggle a provider's enabled/disabled state."""
    config = reload_config()
    providers = config.get("providers", [])
    p = next((x for x in providers if x["id"] == provider_id), None)
    if not p:
        raise ValueError(f"供应商 {provider_id} 未找到")
    if enabled is None:
        p["enabled"] = not p.get("enabled", False)
    else:
        p["enabled"] = bool(enabled)
    _atomic_write_json(config_file, config)
    return {"id": provider_id, "enabled": p["enabled"]}


def clear_provider_models(config_file: Path, reload_config: Callable[[], Dict[str, Any]], provider_id: str) -> bool:
    """Clear all models under a specific provider."""
    config = reload_config()
    providers = config.get("providers", [])
    p = next((x for x in providers if x["id"] == provider_id), None)
    if not p:
        return False
    active_mid = config.get("active_model_id", "")
    if _provider_holds_active_model(config, provider_id):
        raise ValueError(
            f"供应商 {provider_id} 名下挂着当前激活模型 {active_mid}；请先切换主脑模型再清空。"
        )
    p["models"] = []
    config["models"] = [m for m in config.get("models", []) if m.get("provider_id") != provider_id]
    _atomic_write_json(config_file, config)
    return True


def delete_provider(config_file: Path, reload_config: Callable[[], Dict[str, Any]], provider_id: str) -> bool:
    """Delete a provider definition (cascades to its models).

    保护：名下挂着当前激活模型（或顶层仍有其模型）的供应商不可删除，
    避免主脑 active_model_id 悬空或顶层残留幽灵模型。
    """
    config = reload_config()
    providers = config.get("providers", [])
    target = next((p for p in providers if p.get("id") == provider_id), None)
    if not target:
        return False
    active_mid = config.get("active_model_id", "")
    if _provider_holds_active_model(config, provider_id):
        raise ValueError(
            f"供应商 {provider_id} 名下挂着当前激活模型 {active_mid}；请先切换主脑模型再删除。"
        )
    config["providers"] = [p for p in providers if p.get("id") != provider_id]
    # 级联：顶层扁平列表里属于该供应商的模型一并移除，避免幽灵模型
    config["models"] = [
        m for m in config.get("models", []) if m.get("provider_id") != provider_id
    ]
    _atomic_write_json(config_file, config)
    return True
