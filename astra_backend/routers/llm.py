"""LLM providers, models, activation, and failover management routes."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Header, HTTPException

from astra_backend.audit import record as audit_record
from astra_backend.dependencies import app_attr, require_admin_header, require_superadmin
from astra_backend.schemas import (
    LLMActivateRequest,
    LLMSettingsUpdateRequest,
    LLMTestRequest,
    LLMProviderUpsertRequest,
    LLMProviderToggleRequest,
    LLMModelUpsertRequest,
    LLMFetchModelsRequest,
)
from astra_backend.llm_manager import (
    load_llm_config,
    get_active_llm_runtime,
    activate_provider_model,
    update_llm_settings,
    upsert_provider,
    delete_provider,
    toggle_provider,
    clear_provider_models,
    upsert_model,
    delete_model,
    test_llm_connection,
    fetch_remote_models,
    recent_failover_events,
)

router = APIRouter(tags=["llm"])


@router.get("/api/v1/admin/llm/providers")
@router.get("/api/v1/admin/llm/models")
def admin_get_llm_models(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    require_admin_header(x_astra_session=x_astra_session)
    return load_llm_config(mask_keys=True)


@router.post("/api/v1/admin/llm/activate")
def admin_activate_llm_model(payload: LLMActivateRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        result = activate_provider_model(payload.provider_id or "custom", payload.model_id, payload.reasoning_effort, payload.thinking_timeout)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_record("llm.model.activate", "success", {
        "actor": actor["username"],
        "model_id": payload.model_id,
        "reasoning_effort": result.get("active_reasoning_effort"),
        "thinking_timeout": result.get("thinking_timeout"),
    })
    return result


@router.post("/api/v1/admin/llm/settings")
@router.put("/api/v1/admin/llm/settings")
def admin_update_llm_settings(
    payload: LLMSettingsUpdateRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        result = update_llm_settings(
            active_model_id=payload.active_model_id,
            reasoning_effort=payload.reasoning_effort,
            thinking_timeout=payload.thinking_timeout,
            request_attempts=payload.request_attempts,
            fallback_model_ids=payload.fallback_model_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_record("llm.settings.update", "success", {
        "actor": actor["username"],
        "thinking_timeout": payload.thinking_timeout,
        "active_model_id": payload.active_model_id,
        "reasoning_effort": payload.reasoning_effort,
        "request_attempts": payload.request_attempts,
        "fallback_model_ids": payload.fallback_model_ids,
    })
    return result


@router.get("/api/v1/admin/llm/failover-events")
def admin_llm_failover_events(
    limit: int = 30,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    require_admin_header(x_astra_session=x_astra_session)
    return {"events": recent_failover_events(limit)}


@router.post("/api/v1/admin/llm/test")
def admin_test_llm(payload: LLMTestRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    require_admin_header(x_astra_session=x_astra_session)
    base_url = payload.base_url
    api_key = payload.api_key
    api_format = payload.api_format or "openai_chat"

    raw_config = load_llm_config(mask_keys=False)
    m_entry = next((m for m in raw_config.get("models", []) if m["id"] == payload.model), None)
    if m_entry:
        if not base_url:
            base_url = m_entry.get("base_url")
        if not api_key:
            api_key = m_entry.get("api_key")
        if not payload.api_format or payload.api_format == "openai_chat":
            api_format = m_entry.get("api_format", "openai_chat")

    if not base_url:
        active_runtime = get_active_llm_runtime()
        base_url = active_runtime.get("base_url")
        if not api_key:
            api_key = active_runtime.get("api_key")
        if not payload.api_format:
            api_format = active_runtime.get("api_format", "openai_chat")

    fn_test = app_attr("test_llm_connection", test_llm_connection)
    result = fn_test(
        base_url=base_url or "",
        api_key=api_key or "",
        model=payload.model,
        api_format=api_format,
        reasoning_effort=payload.reasoning_effort,
        reasoning_type=payload.reasoning_type,
        timeout=25.0,
    )
    audit_record("llm.connection.test", "success" if result.get("ok") else "failed", {
        "model": payload.model,
        "api_format": api_format,
        "latency_ms": result.get("latency_ms"),
        "status_code": result.get("status_code"),
        "reasoning_detected": result.get("reasoning_detected"),
        "endpoint": result.get("endpoint"),
    })
    return result


@router.post("/api/v1/admin/llm/models")
@router.post("/api/v1/admin/llm/providers/{provider_id}/models")
def admin_upsert_llm_model(payload: LLMModelUpsertRequest, provider_id: str = "custom", x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        res = upsert_model(provider_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_record("llm.model.upsert", "success", {"actor": actor["username"], "model_id": payload.id, "api_format": res.get("api_format")})
    return res


@router.delete("/api/v1/admin/llm/models/{model_id}")
@router.delete("/api/v1/admin/llm/providers/{provider_id}/models/{model_id}")
def admin_delete_llm_model(model_id: str, provider_id: str = "custom", x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        deleted = delete_model(provider_id, model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到该模型")
    audit_record("llm.model.delete", "success", {"actor": actor["username"], "model_id": model_id})
    return {"deleted": True, "model_id": model_id}


@router.post("/api/v1/admin/llm/providers")
def admin_upsert_llm_provider(payload: LLMProviderUpsertRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        res = upsert_provider(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_record("llm.provider.upsert", "success", {"actor": actor["username"], "provider_id": res.get("id")})
    return res


@router.post("/api/v1/admin/llm/fetch-models")
def admin_fetch_remote_models(payload: LLMFetchModelsRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    require_admin_header(x_astra_session=x_astra_session)
    fn_fetch = app_attr("fetch_remote_models", fetch_remote_models)
    res = fn_fetch(
        base_url=payload.base_url or "",
        api_key=payload.api_key or "",
        provider_id=payload.provider_id,
    )
    audit_record("llm.remote.fetch", "success" if res.get("ok") else "failed", {
        "provider_id": payload.provider_id,
        "base_url": payload.base_url,
        "total": res.get("total", 0),
    })
    return res


@router.post("/api/v1/admin/llm/providers/{provider_id}/toggle")
def admin_toggle_llm_provider(provider_id: str, payload: LLMProviderToggleRequest | None = None, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        enabled_val = payload.enabled if payload else None
        res = toggle_provider(provider_id, enabled=enabled_val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_record("llm.provider.toggle", "success", {"actor": actor["username"], "provider_id": provider_id, "enabled": res["enabled"]})
    return res


@router.delete("/api/v1/admin/llm/providers/{provider_id}/models")
def admin_clear_llm_provider_models(provider_id: str, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        cleared = clear_provider_models(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not cleared:
        raise HTTPException(status_code=404, detail="未找到该供应商")
    audit_record("llm.provider.clear_models", "success", {"actor": actor["username"], "provider_id": provider_id})
    return {"cleared": True, "provider_id": provider_id}


@router.delete("/api/v1/admin/llm/providers/{provider_id}")
def admin_delete_llm_provider(provider_id: str, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        deleted = delete_provider(provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到该模型供应商")
    audit_record("llm.provider.delete", "success", {"actor": actor["username"], "provider_id": provider_id})
    return {"deleted": True, "provider_id": provider_id}
