"""LLM 配置文档的**归一化与定稿**（B4 收尾抽取，从 `llm/store.py` 搬出）。

| 函数 | 内容 |
|---|---|
| `resolve_brain_provider_attribution` | 主脑供应商归属：嵌套持有者为准（显式记录 > 唯一持有 > 顶层扁平缓存），把主脑条目**钉回**其供应商（`models_map` 按 id 去重时，同名模型的 `base_url/api_key` 会静默变成另一家的） |
| `finalize_config_document` | 韧性配置解析（请求次数夹取 + 回退链去重/截断、脏数据自愈）→ 组装 `config` 文档 → 原子写盘 → 返回 |

## 安全属性

- 段体 **AST 逐字**（对拍门 `tests/extraction/test_llm_store_normalize_extraction.py`）；
- 自由名**同名 kw-only 入参** ⇒ 调用期解析，`patch.object(store, X)` 类接缝照常生效；
- `resolve_brain_provider_attribution` 会**原地修改** `flat_models` 里的 dict（设计如此）
  ⇒ 门里用 `assertIs` 钉住"改的是同一个对象"，防有人改成返回新列表（那是行为变更）。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def resolve_brain_provider_attribution(*,
        _resolve_active_provider_id,
        active_m_id,
        data,
        flat_models,
        merged_providers):
    raw_active_pid = str(data.get("active_provider_id") or "").strip()
    active_pid = _resolve_active_provider_id(
        {
            "active_model_id": active_m_id,
            "active_provider_id": raw_active_pid,
            "providers": merged_providers,
            "models": flat_models,
        }
    )
    if active_pid and active_m_id:
        ap = next((p for p in merged_providers if str(p.get("id", "")) == active_pid), None)
        if ap:
            for m in flat_models:
                if m.get("id") != active_m_id:
                    continue
                m["provider_id"] = active_pid
                m["provider_name"] = ap.get("name", active_pid)
                if ap.get("base_url"):
                    m["base_url"] = ap["base_url"]
                if ap.get("api_key"):
                    m["api_key"] = ap["api_key"]
                if not m.get("api_format"):
                    m["api_format"] = ap.get("api_format", "openai_chat")
                break
    return active_pid


def finalize_config_document(*,
        DEFAULT_REQUEST_ATTEMPTS,
        List,
        MAX_FALLBACK_MODELS,
        MAX_REQUEST_ATTEMPTS,
        MIN_REQUEST_ATTEMPTS,
        _atomic_write_json,
        active_effort,
        active_m_id,
        active_pid,
        config_file,
        data,
        flat_models,
        merged_providers,
        os,
        thinking_timeout):
    raw_attempts = data.get("request_attempts")
    try:
        env_attempts = int(os.getenv("LLM_REQUEST_ATTEMPTS", "") or 0)
    except ValueError:
        env_attempts = 0
    try:
        request_attempts = int(raw_attempts) if raw_attempts is not None else (env_attempts or DEFAULT_REQUEST_ATTEMPTS)
    except (TypeError, ValueError):
        request_attempts = DEFAULT_REQUEST_ATTEMPTS
    request_attempts = max(MIN_REQUEST_ATTEMPTS, min(MAX_REQUEST_ATTEMPTS, request_attempts))

    known_model_ids = {m["id"] for m in flat_models}
    raw_fallbacks = data.get("fallback_model_ids")
    fallback_model_ids: List[str] = []
    if isinstance(raw_fallbacks, list):
        for fid in raw_fallbacks:
            fid = str(fid or "").strip()
            if not fid or fid == active_m_id or fid not in known_model_ids:
                continue
            if fid not in fallback_model_ids:
                fallback_model_ids.append(fid)
    fallback_model_ids = fallback_model_ids[:MAX_FALLBACK_MODELS]

    config = {
        "version": "3.2",
        "defaults_seeded": True,
        "active_model_id": active_m_id,
        "active_provider_id": active_pid,
        "active_reasoning_effort": active_effort,
        "thinking_timeout": thinking_timeout,
        "request_attempts": request_attempts,
        "fallback_model_ids": fallback_model_ids,
        "providers": merged_providers,
        "models": flat_models,
    }
    _atomic_write_json(config_file, config)
    return config

def normalize_providers_into_result(*,
        _detect_capabilities,
        _detect_reasoning_type,
        active_mid,
        active_pid,
        mask_keys,
        mask_secret,
        providers_list,
        res):
    for p in providers_list:
        pid = p.get("id", "")
        # ONLY return models that are explicitly registered under this specific provider
        models_in_p = list(p.get("models", []))
        formatted_p_models = []
        for m in models_in_p:
            m_id = m.get("id", "")
            formatted_p_models.append({
                "id": m_id,
                "name": m.get("name") or m_id,
                "capabilities": m.get("capabilities") or _detect_capabilities(m_id),
                "reasoning_type": m.get("reasoning_type") or _detect_reasoning_type(m_id),
                "reasoning_effort": m.get("reasoning_effort") or "high",
                "context_length": m.get("context_length"),
                "description": m.get("description", ""),
                # 同名模型挂多家供应商时，主脑徽标只打给归属供应商的那一份；
                # 归属无法判定（active_pid 为空）时保留全打，避免误导为"没启用"
                "is_active": bool(m_id == active_mid and (not active_pid or pid == active_pid)),
            })

        p_copy = {
            "id": pid,
            "name": p.get("name", pid),
            "type": p.get("type", p.get("name", pid)),
            "group": p.get("group", "其他"),
            "enabled": bool(p.get("enabled", False)),
            "multi_key_enabled": bool(p.get("multi_key_enabled", False)),
            "response_api_enabled": bool(p.get("response_api_enabled", False)),
            "base_url": p.get("base_url", ""),
            "api_format": p.get("api_format", "openai_chat"),
            "api_path": p.get("api_path", "/chat/completions"),
            "description": p.get("description", ""),
            "has_key": bool(p.get("api_key")),
            "models_count": len(models_in_p),
            "models": formatted_p_models,
        }
        if mask_keys:
            p_copy["api_key_masked"] = mask_secret(p.get("api_key", ""))
        else:
            p_copy["api_key"] = p.get("api_key", "")
        res["providers"].append(p_copy)


def flatten_models_into_result(*,
        _detect_capabilities,
        active_mid,
        config,
        mask_keys,
        mask_secret,
        providers_list,
        res):
    # Flattened models for backward compatibility
    for m in config.get("models", []):
        m_pid = m.get("provider_id", "openai")
        p_entry = next((p for p in providers_list if p.get("id") == m_pid), None)
        m_key = m.get("api_key", "")
        has_key = bool(m_key or (p_entry and p_entry.get("api_key")))

        m_copy = {
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "provider_id": m_pid,
            "provider_name": m.get("provider_name") or (p_entry.get("name") if p_entry else "自定义"),
            "base_url": m.get("base_url", "") or (p_entry.get("base_url", "") if p_entry else ""),
            "api_format": m.get("api_format", "openai_chat"),
            "reasoning_type": m.get("reasoning_type", "auto"),
            "reasoning_effort": m.get("reasoning_effort", "high"),
            "capabilities": m.get("capabilities") or _detect_capabilities(m["id"]),
            "context_length": m.get("context_length"),
            "description": m.get("description", ""),
            "has_key": has_key,
            "is_active": m["id"] == active_mid,
        }
        if mask_keys:
            m_copy["api_key_masked"] = mask_secret(m_key) if m_key else (mask_secret(p_entry.get("api_key", "")) if p_entry and p_entry.get("api_key") else "")
        else:
            m_copy["api_key"] = m_key
        res["models"].append(m_copy)

