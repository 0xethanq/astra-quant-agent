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
from astra_backend.llm.model_health import audit_llm_config, dead_model_ids
from astra_backend.llm.policy import SUPPORTED_API_FORMATS

#: 结构自检用的格式白名单（与运行时同一份常量）。
SUPPORTED_FORMATS = tuple(f["id"] for f in SUPPORTED_API_FORMATS)

router = APIRouter(tags=["llm"])


@router.get("/api/v1/admin/llm/providers")
@router.get("/api/v1/admin/llm/models")
def admin_get_llm_models(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    require_admin_header(x_astra_session=x_astra_session)
    payload = load_llm_config(mask_keys=True)
    # 结构自检随配置一起下发：界面要给每条模型打"可用性徽标"，否则三条并列显示、
    # 其中两条是死的（无密钥 / 供应商不存在）也看不出来（2026-09-29 实测）。
    payload["model_health"] = audit_llm_config(payload, SUPPORTED_FORMATS)
    return payload


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


@router.post("/api/v1/admin/llm/test-all")
def admin_test_all_llm_models(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    """逐条真机探测**全部**模型条目（串行、极小请求）。

    与 `/test` 的分工：`/test` 回答"我改的这一条通不通"；`/test-all` 回答
    "后台现在这张矩阵里到底哪几条能用"。结构上不可能发请求的条目（无密钥）
    直接跳过并给出理由 —— 真机请求不必浪费在已知死条目上。

    ⚠️ 真机结论**不写回配置**：一次 402 只代表"此刻余额不足"，
    写成永久状态会让配置页撒谎（充值后它仍然是死的）。
    """
    require_admin_header(x_astra_session=x_astra_session)
    raw_config = load_llm_config(mask_keys=False)
    health = audit_llm_config(raw_config, SUPPORTED_FORMATS)
    fn_test = app_attr("test_llm_connection", test_llm_connection)

    rows: list[dict[str, Any]] = []
    for model in raw_config.get("models", [])[:20]:
        model_id = str(model.get("id") or "")
        if not model_id:
            continue
        entry = (health.get("models") or {}).get(model_id) or {}
        provider = next((p for p in raw_config.get("providers", [])
                         if str(p.get("id") or "") == str(model.get("provider_id") or "")), None)
        api_key = str(model.get("api_key") or "") or str((provider or {}).get("api_key") or "")
        if entry.get("status") == "dead" or not api_key:
            rows.append({
                "model": model_id,
                "api_format": model.get("api_format") or "openai_chat",
                "role": entry.get("role", "dormant"),
                "status": entry.get("status", "dead"),
                "ok": False,
                "status_code": 0,
                "latency_ms": 0,
                "endpoint": "",
                "error": "结构上不可用：" + "；".join(
                    i.get("detail", "") for i in entry.get("issues", []) if i.get("level") == "dead"
                ) or "缺少 API Key",
                "skipped": True,
            })
            continue
        result = fn_test(
            base_url=str(model.get("base_url") or (provider or {}).get("base_url") or ""),
            api_key=api_key,
            model=model_id,
            api_format=str(model.get("api_format") or "openai_chat"),
            reasoning_effort=str(model.get("reasoning_effort") or "auto"),
            reasoning_type=str(model.get("reasoning_type") or "auto"),
            api_path=str(model.get("api_path") or ""),
            timeout=25.0,
        )
        rows.append({
            "model": model_id,
            "api_format": str(model.get("api_format") or "openai_chat"),
            "role": entry.get("role", "dormant"),
            "status": entry.get("status", "ok"),
            "ok": bool(result.get("ok")),
            "status_code": result.get("status_code"),
            "latency_ms": result.get("latency_ms"),
            "endpoint": result.get("endpoint"),
            "error": result.get("error") or result.get("response_preview") or "",
            "skipped": False,
        })

    report = {
        "rows": rows,
        "total": len(rows),
        "ok": sum(1 for r in rows if r["ok"]),
        "failed": sum(1 for r in rows if not r["ok"] and not r.get("skipped")),
        "skipped": sum(1 for r in rows if r.get("skipped")),
        "warnings": health.get("warnings") or [],
    }
    audit_record("llm.connection.test_all", "success", {
        "total": report["total"], "ok": report["ok"],
        "failed": report["failed"], "skipped": report["skipped"],
    })
    return report


@router.post("/api/v1/admin/llm/models/cleanup")
def admin_cleanup_dead_llm_models(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    """一键清理**结构死条目**（无密钥 / 供应商不存在且无密钥）。

    刻意只删 `dead`：余额不足、限流、供应商停用一律保留 —— 那些是运行态，
    删掉用户配置属于越权（充值/开启后它们本该恢复正常）。
    """
    actor = require_superadmin(x_astra_session)
    raw_config = load_llm_config(mask_keys=False)
    health = audit_llm_config(raw_config, SUPPORTED_FORMATS)
    targets = dead_model_ids(health)

    removed: list[str] = []
    failed: list[dict[str, str]] = []
    for model_id in targets:
        model = next((m for m in raw_config.get("models", []) if m.get("id") == model_id), None)
        provider_id = str((model or {}).get("provider_id") or "custom")
        try:
            delete_model(provider_id, model_id)
            removed.append(model_id)
        except ValueError as exc:          # 例如"当前正在使用的模型不可删"
            failed.append({"model": model_id, "reason": str(exc)})
        except Exception as exc:           # 单条失败不该中断整批
            failed.append({"model": model_id, "reason": f"{type(exc).__name__}: {exc}"})

    audit_record("llm.model.cleanup", "success", {
        "actor": actor["username"], "removed": removed, "failed": failed,
    })
    return {"removed": removed, "failed": failed, "scanned": targets}


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


@router.get("/api/v1/admin/llm/cache/status")
def admin_get_llm_cache_status(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    """获取大模型缓存运行状态、命中率、L1 查询缓存及节省统计。"""
    require_admin_header(x_astra_session=x_astra_session)
    from astra_gateway.publisher import DB_PATH
    from astra_gateway.store import GatewayStore
    from astra_backend.llm.query_cache import get_query_cache_stats
    from astra_gateway.cache_warmer import warmup_mode

    store = GatewayStore(DB_PATH)
    stats = store.model_stats()
    l1_stats = get_query_cache_stats()

    # 预估节约金额（基于行业平均输入缓存折扣 ~1.50 USD / 1M cached tokens）
    cached_tokens_total = int(stats.get("cached_tokens_total") or 0)
    l1_saved_tokens = int(l1_stats.get("saved_tokens_total") or 0)
    total_saved_tokens = cached_tokens_total + l1_saved_tokens
    estimated_saved_usd = round(total_saved_tokens * 0.0000015, 4)

    active_runtime = get_active_llm_runtime() or {}
    active_model = str(active_runtime.get("model") or "")
    active_format = str(active_runtime.get("api_format") or "")

    capabilities = {
        "claude_ephemeral": "claude" in active_model.lower() or active_format == "claude_messages",
        "deepseek_prefix": "deepseek" in active_model.lower(),
        "openai_prefix": active_format in ("openai_chat", "openai_responses") and not ("deepseek" in active_model.lower() or "claude" in active_model.lower()),
        "gemini_context": "gemini" in active_model.lower(),
        "session_affinity_active": True,
    }

    return {
        "ok": True,
        "model_stats": stats,
        "l1_query_cache": l1_stats,
        "warmer_mode": warmup_mode(),
        "active_model": active_model,
        "capabilities": capabilities,
        "total_saved_tokens": total_saved_tokens,
        "estimated_saved_usd": estimated_saved_usd,
    }


@router.post("/api/v1/admin/llm/cache/clear")
def admin_clear_llm_cache(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    """清除本地 L1 精确查询缓存。"""
    actor = require_superadmin(x_astra_session)
    from astra_backend.llm.query_cache import clear_query_cache
    cleared = clear_query_cache()
    audit_record("llm.cache.clear", "success", {"actor": actor["username"], "cleared_entries": cleared})
    return {"ok": True, "cleared_entries": cleared, "message": f"已成功清除 {cleared} 条本地缓存记录"}

