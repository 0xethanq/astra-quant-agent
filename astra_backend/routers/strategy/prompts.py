"""提示词库与档案（prompt library / profiles / override）端点。

从 `routers/strategy.py` 按域拆出（B8）；URL/方法/处理器名一字未改。
"""
from __future__ import annotations

import os
import re
from typing import Any
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field
from astra_backend.config import refresh_settings
from astra_backend.audit import record as audit_record
from astra_backend.dependencies import PROMPT_OVERRIDE_FILE, require_admin_header, require_superadmin
from astra_backend.prompt_views import EVOLUTION_USER_TEMPLATE, TRADING_USER_TEMPLATE, rendered_snapshots
from astra_backend.schemas import PromptLibraryUpdate, PromptProfileCreateRequest, PromptProfileUpdateRequest, PromptImportRequest, PromptRollbackRequest, PromptOverrideRequest
from scripts.prompt_library import active_profile, activate_profile, all_profiles, apply_module_layout, create_profile, delete_profile, export_profile, import_profile, load_library, pipeline_view, profile_history, rollback_profile, save_library, update_profile, validate_profile

from fastapi import APIRouter

router = APIRouter(tags=["strategy"])


@router.get("/api/v1/prompt-library")
@router.get("/api/v1/admin/prompt-library")
def prompt_library(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"), x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    from scripts.ai_brain_trader import SYSTEM_PROMPT
    from scripts.self_improvement_engine import EVOLUTION_SYSTEM_PROMPT
    try:
        library = load_library()
        profile = active_profile()
        return {
            "active_style": library["active_style"],
            "active_profile_id": library["active_profile_id"],
            "profiles": [{**item, "pipeline_views": {
                "trading_system": pipeline_view(SYSTEM_PROMPT, item, "trading_system"),
                "trading_user": pipeline_view(TRADING_USER_TEMPLATE, item, "trading_user"),
                "evolution_system": pipeline_view(EVOLUTION_SYSTEM_PROMPT, item, "evolution_system"),
                "evolution_user": pipeline_view(EVOLUTION_USER_TEMPLATE, item, "evolution_user"),
            }} for item in all_profiles()],
            "base_templates": {
                "trading_system": SYSTEM_PROMPT,
                "trading_user": TRADING_USER_TEMPLATE,
                "evolution_system": EVOLUTION_SYSTEM_PROMPT,
                "evolution_user": EVOLUTION_USER_TEMPLATE,
            },
            "pipelines": {
                "trading_system": pipeline_view(SYSTEM_PROMPT, profile, "trading_system"),
                "trading_user": pipeline_view(TRADING_USER_TEMPLATE, profile, "trading_user"),
                "evolution_system": pipeline_view(EVOLUTION_SYSTEM_PROMPT, profile, "evolution_system"),
                "evolution_user": pipeline_view(EVOLUTION_USER_TEMPLATE, profile, "evolution_user"),
            },
            "preview_mode": "template_only_not_runtime",
            "effective_templates": {
                "trading_system": apply_module_layout(SYSTEM_PROMPT, profile, "trading_system", "交易 System"),
                "trading_user": apply_module_layout(TRADING_USER_TEMPLATE, profile, "trading_user", "交易 User"),
                "evolution_system": apply_module_layout(EVOLUTION_SYSTEM_PROMPT, profile, "evolution_system", "自进化 System"),
                "evolution_user": apply_module_layout(EVOLUTION_USER_TEMPLATE, profile, "evolution_user", "自进化 User"),
            },
            "snapshots": rendered_snapshots(),
            "template_variables": __import__("scripts.prompt_library", fromlist=["TEMPLATE_VARIABLES_METADATA"]).TEMPLATE_VARIABLES_METADATA,
            "transport": "python-direct",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取提示词库失败: {exc}")


@router.put("/api/v1/admin/prompt-library")
def update_prompt_library(
    payload: PromptLibraryUpdate,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    try:
        library = load_library()
        library["active_style"] = payload.active_style
        library["custom"] = {
            "id": "custom", "name": "自定义", "description": "管理员自定义风格附加层。", "editable": True,
            "trading_system": payload.trading_system.strip(), "trading_user": payload.trading_user.strip(),
            "evolution_system": payload.evolution_system.strip(), "evolution_user": payload.evolution_user.strip(),
        }
        save_library(library)
        audit_record("prompt.library.update", "success", {
            "actor": actor.get("username", "admin"),
            "active_style": payload.active_style,
            "custom_characters": sum(len(getattr(payload, key)) for key in ("trading_system", "trading_user", "evolution_system", "evolution_user"))
        })
        return {"saved": True, "active_style": payload.active_style, "restart_note": "下一次 Python 交易主脑与自进化进程自动读取选中风格。"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"更新提示词库失败: {exc}")


@router.get("/api/v1/admin/prompt-profiles")
def prompt_profiles(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"), x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token, x_astra_session)
    try:
        library = load_library()
        prompts_mod = __import__("scripts.prompt_library", fromlist=["ALLOWED_VARIABLES", "TEMPLATE_VARIABLES_METADATA"])
        return {
            "active_profile_id": library["active_profile_id"],
            "profiles": all_profiles(),
            "allowed_variables": sorted(list(prompts_mod.ALLOWED_VARIABLES)),
            "template_variables": prompts_mod.TEMPLATE_VARIABLES_METADATA,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取提示词方案列表失败: {exc}")


@router.post("/api/v1/admin/prompt-profiles")
def create_prompt_profile_api(
    payload: PromptProfileCreateRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        profile = create_profile(payload.name, payload.description, payload.source_id)
        audit_record("prompt.profile.create", "success", {"actor": actor["username"], "profile_id": profile["id"]})
        return {"profile": profile}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建提示词方案失败: {exc}") from exc


@router.put("/api/v1/admin/prompt-profiles/{profile_id}")
def update_prompt_profile_api(
    profile_id: str,
    payload: PromptProfileUpdateRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    if not profile_id or not re.match(r"^[a-zA-Z0-9_-]+$", profile_id):
        raise HTTPException(status_code=400, detail=f"无效的提示词方案标识: {profile_id}")
    changes = {k: v for k, v in payload.model_dump(exclude={"note"}, exclude_unset=True).items() if v is not None}
    try:
        profile = update_profile(profile_id, changes, payload.note)
        audit_record("prompt.profile.update", "success", {"actor": actor["username"], "profile_id": profile_id})
        return {"profile": profile, "validation": validate_profile(profile)}
    except ValueError as exc:
        if "不存在" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"更新提示词方案失败: {exc}") from exc


@router.post("/api/v1/admin/prompt-profiles/{profile_id}/activate")
def activate_prompt_profile_api(
    profile_id: str,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    if not profile_id or not re.match(r"^[a-zA-Z0-9_-]+$", profile_id):
        raise HTTPException(status_code=400, detail=f"无效的提示词方案标识: {profile_id}")
    try:
        profile = activate_profile(profile_id)
        audit_record("prompt.profile.activate", "success", {"actor": actor["username"], "profile_id": profile_id})
        return {"active_profile_id": profile_id, "profile": profile}
    except ValueError as exc:
        if "不存在" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"启用提示词方案失败: {exc}") from exc


@router.delete("/api/v1/admin/prompt-profiles/{profile_id}")
def delete_prompt_profile_api(
    profile_id: str,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    if not profile_id or not re.match(r"^[a-zA-Z0-9_-]+$", profile_id):
        raise HTTPException(status_code=400, detail=f"无效的提示词方案标识: {profile_id}")
    try:
        delete_profile(profile_id)
        audit_record("prompt.profile.delete", "success", {"actor": actor["username"], "profile_id": profile_id})
        return {"deleted": True}
    except ValueError as exc:
        if "不存在" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"删除提示词方案失败: {exc}") from exc


@router.post("/api/v1/admin/prompt-profiles/validate")
def validate_prompt_profile_api(
    payload: PromptProfileUpdateRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token, x_astra_session)
    try:
        return validate_profile({k: v for k, v in payload.model_dump(exclude={"note"}).items() if v is not None})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"提示词方案校验失败: {exc}") from exc


@router.get("/api/v1/admin/prompt-profiles/{profile_id}/history")
def prompt_profile_history_api(
    profile_id: str,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token, x_astra_session)
    if not profile_id or not re.match(r"^[a-zA-Z0-9_-]+$", profile_id):
        raise HTTPException(status_code=400, detail=f"无效的提示词方案标识: {profile_id}")
    try:
        return {"history": profile_history(profile_id)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取方案历史失败: {exc}") from exc


@router.post("/api/v1/admin/prompt-profiles/{profile_id}/rollback")
def rollback_prompt_profile_api(
    profile_id: str,
    payload: PromptRollbackRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    if not profile_id or not re.match(r"^[a-zA-Z0-9_-]+$", profile_id):
        raise HTTPException(status_code=400, detail=f"无效的提示词方案标识: {profile_id}")
    try:
        profile = rollback_profile(profile_id, payload.revision_id)
        audit_record("prompt.profile.rollback", "success", {"actor": actor["username"], "profile_id": profile_id, "revision_id": payload.revision_id})
        return {"profile": profile}
    except ValueError as exc:
        if "不存在" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"回滚提示词方案失败: {exc}") from exc


@router.get("/api/v1/admin/prompt-profiles/{profile_id}/export")
def export_prompt_profile_api(
    profile_id: str,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token, x_astra_session)
    if not profile_id or not re.match(r"^[a-zA-Z0-9_-]+$", profile_id):
        raise HTTPException(status_code=400, detail=f"无效的提示词方案标识: {profile_id}")
    try:
        return export_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"导出提示词方案失败: {exc}") from exc


@router.post("/api/v1/admin/prompt-profiles/import")
def import_prompt_profile_api(
    payload: PromptImportRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        profile = import_profile(payload.payload, payload.name_override)
        audit_record("prompt.profile.import", "success", {"actor": actor["username"], "profile_id": profile["id"]})
        return {"profile": profile}
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"导入提示词方案失败: {exc}") from exc


@router.get("/api/v1/admin/prompts")
def prompt_override(
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    try:
        from scripts.ai_brain_trader import SYSTEM_PROMPT, get_effective_system_prompt
        content = PROMPT_OVERRIDE_FILE.read_text(encoding="utf-8") if PROMPT_OVERRIDE_FILE.exists() else ""
        # 审计 P1-3：这里必须与推演时**同一条代码路径**（模块布局 → 之后追加覆盖层）。
        # 旧实现返回 SYSTEM_PROMPT + 覆盖层，而推演侧布局会把覆盖层丢掉 —— 接口在骗人。
        effective = get_effective_system_prompt()
        return {
            "content": content,
            "enabled": bool(content.strip()),
            "base_prompt": SYSTEM_PROMPT,
            "effective_prompt": effective,
            "override_applied": bool(content.strip()) and content.strip() in effective,
            "path": str(PROMPT_OVERRIDE_FILE),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取提示词覆盖配置失败: {exc}")


@router.put("/api/v1/admin/prompts")
def update_prompt_override(
    payload: PromptOverrideRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    try:
        content = payload.content.strip()
        if content:
            temp = PROMPT_OVERRIDE_FILE.with_suffix(".tmp")
            temp.write_text(content + "\n", encoding="utf-8")
            os.replace(temp, PROMPT_OVERRIDE_FILE)
        elif PROMPT_OVERRIDE_FILE.exists():
            PROMPT_OVERRIDE_FILE.unlink()
        audit_record("prompt.update", "success", {
            "actor": actor.get("username", "admin"),
            "enabled": bool(content),
            "characters": len(content)
        })
        return {"saved": True, "enabled": bool(content), "restart_note": "下一次 AI 推演循环将自动叠加此提示词覆盖层。"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"更新提示词覆盖失败: {exc}")


class EvolutionConfigUpdate(BaseModel):
    start_time: str | None = Field(default=None, max_length=30)
    model_id: str | None = Field(default=None, max_length=100)
    reasoning_effort: str | None = Field(default=None, max_length=20)
    thinking_timeout: float | None = Field(default=None, ge=60.0, le=600.0)
    analysis_depth: str | None = Field(default=None, max_length=20)


class EvolutionTestModelRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=100)
    reasoning_effort: str | None = Field(default="high", max_length=20)
    thinking_timeout: float | None = Field(default=60.0, ge=10.0, le=120.0)


@router.get("/api/v1/admin/evolution/config")
def get_evolution_config(
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    from astra_backend.evolution_config import load_evolution_config
    from astra_backend.llm_manager import init_llm_config
    from scripts.self_improvement_engine import load_closed_trades

    evo_cfg = load_evolution_config()
    evo_start = evo_cfg.get("start_time", "2026-09-01 00:00:00")
    trades = load_closed_trades(evo_start)

    llm_cfg = init_llm_config()
    raw_models = llm_cfg.get("models") or []
    available = [
        {
            "id": m.get("id"),
            "name": m.get("name") or m.get("id"),
            "provider_name": m.get("provider_name") or m.get("provider_id") or "custom",
            "capabilities": m.get("capabilities") or ["chat"],
            "reasoning_effort": m.get("reasoning_effort") or "high",
            "has_key": bool(m.get("api_key")),
        }
        for m in raw_models if isinstance(m, dict) and m.get("id")
    ]

    return {
        "ok": True,
        "evolution_start_time": evo_start,
        "active_trades_count": len(trades),
        "model_id": evo_cfg.get("model_id", "auto"),
        "effective_model_id": evo_cfg.get("effective_model_id", "auto"),
        "reasoning_effort": evo_cfg.get("reasoning_effort", "high"),
        "thinking_timeout": evo_cfg.get("thinking_timeout", 300.0),
        "analysis_depth": evo_cfg.get("analysis_depth", "deep"),
        "available_models": available,
        "updated_at": evo_cfg.get("updated_at", ""),
        "note": "早于此时间的历史人工合约订单将被自动过滤，仅复盘此时间之后的量化实盘单。"
    }


@router.put("/api/v1/admin/evolution/config")
def update_evolution_config(
    payload: EvolutionConfigUpdate,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    from astra_backend.evolution_config import save_evolution_config
    from scripts.self_improvement_engine import load_closed_trades

    raw_dict = payload.model_dump(exclude_none=True)
    res = save_evolution_config(raw_dict)
    evo_start = res.get("start_time", "2026-09-01 00:00:00")
    trades = load_closed_trades(evo_start)

    audit_record("evolution.config.update", "success", {
        "actor": actor.get("username", "admin"),
        "evolution_start_time": evo_start,
        "active_trades_count": len(trades),
        "model_id": res.get("model_id"),
        "reasoning_effort": res.get("reasoning_effort"),
        "thinking_timeout": res.get("thinking_timeout"),
    })

    return {
        "ok": True,
        "evolution_start_time": evo_start,
        "active_trades_count": len(trades),
        "model_id": res.get("model_id"),
        "effective_model_id": res.get("effective_model_id"),
        "reasoning_effort": res.get("reasoning_effort"),
        "thinking_timeout": res.get("thinking_timeout"),
        "analysis_depth": res.get("analysis_depth"),
        "updated_at": res.get("updated_at"),
        "effect": f"自进化配置已成功更新，下次复盘将使用模型 {res.get('effective_model_id')}（思考上限 {res.get('thinking_timeout')}s）进行深度复盘。"
    }


@router.post("/api/v1/admin/evolution/test-model")
def test_evolution_model(
    payload: EvolutionTestModelRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    from astra_backend.llm_manager import resolve_model_runtime, get_active_llm_runtime, execute_llm_request
    import time

    target_id = payload.model_id.strip()
    runtime = {}
    if target_id and target_id != "auto":
        runtime = resolve_model_runtime(target_id) or {}
    if not runtime:
        runtime = get_active_llm_runtime() or {}

    if not runtime or not runtime.get("model"):
        raise HTTPException(status_code=400, detail=f"无法解析模型 {target_id} 的凭证与接入端点")

    t0 = time.time()
    try:
        content, _, usage, _ = execute_llm_request(
            messages=[
                {"role": "system", "content": "You are a quantitative trading system engine probe. Respond strictly with: {\"status\": \"ok\"}"},
                {"role": "user", "content": "Ping: Verify reasoning and connection."}
            ],
            model=runtime.get("model"),
            base_url=runtime.get("base_url"),
            api_key=runtime.get("api_key"),
            api_format=runtime.get("api_format", "openai_chat"),
            reasoning_effort=payload.reasoning_effort or "medium",
            temperature=0.1,
            response_format={"type": "json_object"},
            timeout=float(payload.thinking_timeout or 60.0),
        )
        latency_ms = int((time.time() - t0) * 1000)
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "model": runtime.get("model"),
            "provider": runtime.get("provider_name") or runtime.get("provider_id"),
            "message": f"模型 {runtime.get('model')} 连通探测成功（耗时 {latency_ms}ms）",
            "reply_sample": (content or "").strip()[:80],
        }
    except Exception as exc:
        latency_ms = int((time.time() - t0) * 1000)
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "model": runtime.get("model"),
            "message": f"模型连通失败: {exc}",
        }
