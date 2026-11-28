"""Direct control-plane aggregation, atomic toggles, risk preview, and async jobs."""
from __future__ import annotations

import copy
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from astra_backend import risk_config
from astra_backend.audit import record as audit_record
from astra_backend.config import refresh_settings, settings
from astra_backend.council.roster import seat_model_health
from astra_backend.council_manager import get_preset_suites, load_council_config, save_council_config
from astra_backend.dependencies import require_admin_header, require_superadmin
from astra_backend.evolution_config import load_evolution_config, save_evolution_config
from astra_backend.job_runner import (
    JobAlreadyRunningError,
    UnknownJobError,
    job_catalog,
    list_job_runs,
    trigger_job_async,
)
from astra_backend.policy_snapshot import archive_current_policy
from astra_backend.settings_store import update_env
from astra_backend.trading_session_store import load_trading_session, save_trading_session
from scripts.ai_brain_trader import SYSTEM_PROMPT
from scripts.instrument_pool import sync_pool_leverage_caps
from scripts.prompt_library import active_profile, all_profiles, get_profile, load_library, pipeline_view, update_profile
from scripts.prompt_templates import demote_edited_base_modules
from scripts.trader.session import coverage_estimate, normalize_session, resolve_session

router = APIRouter(tags=["control_plane"])
logger = logging.getLogger(__name__)
_BJ = timezone(timedelta(hours=8))

_VALID_TOGGLE_TARGETS = {
    "trading_paused",
    "scale_out_enabled",
    "trading_session_enabled",
    "council_enabled",
    "council_role_enabled",
    "prompt_module_enabled",
    "evolution_enabled",
    "memory_lesson_enabled",
}


class QuickToggleRequest(BaseModel):
    target: str = Field(min_length=1, max_length=64)
    enabled: bool
    item_id: str | None = Field(default=None, max_length=120)
    auto_snapshot: bool = True


class ControlPlaneRiskPreviewRequest(BaseModel):
    suite_id: str = ""
    values: dict[str, Any] = Field(default_factory=dict)


class ControlPlaneRiskSaveRequest(BaseModel):
    suite_id: str = ""
    values: dict[str, Any] = Field(default_factory=dict)
    confirmation: str = ""
    auto_snapshot: bool = True
    note: str = Field(default="", max_length=160)


class CouncilRolePatchRequest(BaseModel):
    enabled: bool | None = None
    weight: float | None = Field(default=None, ge=0.05, le=1.0)
    model_id: str | None = Field(default=None, max_length=120)
    reasoning_effort: str | None = Field(default=None, max_length=32)
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    prompt: str | None = Field(default=None, max_length=20000)
    name: str | None = Field(default=None, max_length=80)
    auto_snapshot: bool = True


class ControlPlaneOrderModeRequest(BaseModel):
    order_mode: str = Field(min_length=1, max_length=24)
    auto_snapshot: bool = True


def _safe_auto_snapshot(title: str, description: str, actor: str) -> str:
    try:
        stamp = datetime.now(_BJ).strftime("%m%d-%H%M%S")
        entry = archive_current_policy(
            name=f"{title}-{stamp}",
            description=description[:180],
            author=actor,
        )
        return str(entry.get("package_hash") or entry.get("policy_hash") or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Auto policy snapshot skipped before %s: %s", title, exc)
        return ""


def _active_suite_id(values: dict[str, Any]) -> str:
    for suite in risk_config.SUITES:
        vals = suite.get("values") or {}
        if all(abs(float(values.get(k, -999999)) - float(v)) < 1e-9 for k, v in vals.items()):
            return str(suite["id"])
    return "custom"


@router.get("/api/v1/admin/control-plane/state")
def get_control_plane_state(
    x_astra_admin_token: str | None = Header(default=None),
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)

    r_values = risk_config.current_values()
    raw_sess = load_trading_session()
    norm_sess, sess_errs = normalize_session(raw_sess)
    sess_state = resolve_session(norm_sess)
    sess_state["errors"] = [*sess_errs, *sess_state.get("errors", [])]

    council_cfg = load_council_config()
    council_cfg["model_health"] = seat_model_health(council_cfg.get("roles"))
    council_cfg["available_suites"] = get_preset_suites()

    lib = load_library()
    prof = active_profile()
    ts_modules = [
        {
            "id": m.get("id"),
            "title": m.get("title"),
            "enabled": bool(m.get("enabled", True)),
            "locked": bool(m.get("locked", False)),
            "source": m.get("source"),
            "char_count": len(str(m.get("content") or "")),
            "preview": str(m.get("content") or "")[:200],
        }
        for m in pipeline_view(SYSTEM_PROMPT, prof, "trading_system")
        if isinstance(m, dict)
    ]

    evo_cfg = load_evolution_config()
    active_trades_count = 0
    try:
        from scripts.self_improvement_engine import load_closed_trades
        active_trades_count = len(load_closed_trades(evo_cfg.get("start_time", "2026-09-01 00:00:00")))
    except Exception:
        active_trades_count = 0

    lessons_total = 0
    lessons_enabled = 0
    try:
        from scripts import evolution_shield
        mem_view = evolution_shield.admin_memory_view()
        lessons = mem_view.get("structured_lessons") or []
        lessons_total = len(lessons)
        lessons_enabled = sum(1 for item in lessons if isinstance(item, dict) and item.get("enabled", True))
    except Exception:
        pass

    return {
        "trading_paused": bool(getattr(settings, "trading_paused", False)),
        "environment": "demo" if settings.okx_simulated else "live",
        "risk": {
            "active_suite_id": _active_suite_id(r_values),
            "order_mode": (os.getenv("ASTRA_ORDER_MODE") or getattr(settings, "order_mode", "limit") or "limit").strip().lower(),
            "values": r_values,
            "process_values": risk_config.process_values(),
            "file_vs_process": risk_config.file_vs_process_diff(),
            "risk_audit": risk_config.audit_risk_consistency(r_values),
            "suites": risk_config.SUITES,
            "schema": risk_config.schema(),
        },
        "trading_session": {
            **norm_sess,
            "state": sess_state,
            "coverage": coverage_estimate(norm_sess),
        },
        "council": council_cfg,
        "prompt": {
            "active_profile_id": str(lib.get("active_profile_id") or prof.get("id") or ""),
            "active_profile_name": str(prof.get("name") or ""),
            "profiles_summary": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "description": p.get("description"),
                    "enabled": bool(p.get("enabled", True)),
                    "updated_at": p.get("updated_at"),
                }
                for p in all_profiles()
            ],
            "trading_system_modules": ts_modules,
        },
        "evolution": {
            **evo_cfg,
            "active_trades_count": active_trades_count,
            "lessons_enabled": lessons_enabled,
            "lessons_total": lessons_total,
        },
        "jobs": {
            "catalog": job_catalog(),
            "recent_runs": list_job_runs(15),
        },
    }


@router.post("/api/v1/admin/control-plane/quick-toggle")
def control_plane_quick_toggle(
    payload: QuickToggleRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    actor_name = str(actor.get("username") or "admin")
    target = payload.target.strip()
    if target not in _VALID_TOGGLE_TARGETS:
        raise HTTPException(status_code=400, detail=f"不支持的快捷开关目标：{target}")

    snapshot_hash = ""
    extra: dict[str, Any] = {}

    if target == "trading_paused":
        update_env({"ASTRA_TRADING_PAUSED": "1" if payload.enabled else "0"})
        refresh_settings()
        extra["trading_paused"] = bool(settings.trading_paused)

    elif target == "scale_out_enabled":
        if payload.auto_snapshot:
            snapshot_hash = _safe_auto_snapshot("快捷开关前", "切换分批止盈开关", actor_name)
        update_env({"ASTRA_SCALE_OUT_ENABLED": "1" if payload.enabled else "0"})
        refresh_settings()
        risk_config.reload_risk_constants()
        extra["scale_out_enabled"] = bool(payload.enabled)

    elif target == "trading_session_enabled":
        raw_sess = load_trading_session()
        norm_sess, errs = normalize_session({**raw_sess, "enabled": bool(payload.enabled)})
        if errs:
            raise HTTPException(status_code=400, detail="；".join(errs))
        save_trading_session(norm_sess)
        extra["trading_session"] = {**norm_sess, "state": resolve_session(norm_sess), "coverage": coverage_estimate(norm_sess)}

    elif target == "council_enabled":
        cfg = load_council_config()
        if payload.auto_snapshot:
            snapshot_hash = _safe_auto_snapshot("投委会开关前", f"切换投委会={payload.enabled}", actor_name)
        cfg["enabled"] = bool(payload.enabled)
        try:
            saved = save_council_config(cfg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        extra["council_enabled"] = bool(saved.get("enabled", False))

    elif target == "council_role_enabled":
        role_id = str(payload.item_id or "").strip()
        if not role_id:
            raise HTTPException(status_code=400, detail="缺少席位标识 item_id")
        cfg = load_council_config()
        roles = cfg.get("roles") if isinstance(cfg.get("roles"), dict) else {}
        if role_id not in roles or not isinstance(roles[role_id], dict):
            raise HTTPException(status_code=404, detail=f"未找到投委会席位：{role_id}")
        if payload.auto_snapshot:
            snapshot_hash = _safe_auto_snapshot("席位开关前", f"{role_id}.enabled={payload.enabled}", actor_name)
        roles[role_id]["enabled"] = bool(payload.enabled)
        try:
            saved = save_council_config(cfg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        extra["role_id"] = role_id
        extra["role_enabled"] = bool((saved.get("roles") or {}).get(role_id, {}).get("enabled", True))

    elif target == "prompt_module_enabled":
        mod_id = str(payload.item_id or "").strip()
        if not mod_id:
            raise HTTPException(status_code=400, detail="缺少提示词模块标识 item_id")
        lib = load_library()
        pid = str(lib.get("active_profile_id") or "")
        prof = get_profile(pid)
        mods = copy.deepcopy(pipeline_view(SYSTEM_PROMPT, prof, "trading_system"))
        idx = next((i for i, m in enumerate(mods) if isinstance(m, dict) and m.get("id") == mod_id), None)
        if idx is None:
            raise HTTPException(status_code=404, detail=f"当前激活方案未找到模块：{mod_id}")
        if mods[idx].get("locked"):
            raise HTTPException(status_code=400, detail="锁定核心结构模块不可关闭")
        if payload.auto_snapshot:
            snapshot_hash = _safe_auto_snapshot("提示词开关前", f"模块 {mod_id}={payload.enabled}", actor_name)
        mods[idx]["enabled"] = bool(payload.enabled)
        try:
            demoted = demote_edited_base_modules(mods, SYSTEM_PROMPT, "trading_system")
            update_profile(pid, {"pipelines": {"trading_system": demoted}}, note=f"快捷切换模块 {mod_id}={payload.enabled}")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        extra["profile_id"] = pid
        extra["module_id"] = mod_id

    elif target == "evolution_enabled":
        if payload.auto_snapshot:
            snapshot_hash = _safe_auto_snapshot("自进化开关前", f"evolution.enabled={payload.enabled}", actor_name)
        saved_evo = save_evolution_config({"enabled": bool(payload.enabled)})
        extra["evolution"] = saved_evo

    elif target == "memory_lesson_enabled":
        lesson_id = str(payload.item_id or "").strip()
        if not lesson_id:
            raise HTTPException(status_code=400, detail="缺少心法标识 item_id")
        from scripts import evolution_shield
        view = evolution_shield.admin_memory_view()
        target_lesson = next(
            (item for item in (view.get("structured_lessons") or []) if isinstance(item, dict) and item.get("id") == lesson_id),
            None,
        )
        if not target_lesson:
            raise HTTPException(status_code=404, detail=f"未找到指定心法条目：{lesson_id}")
        if bool(target_lesson.get("enabled", True)) != bool(payload.enabled):
            if payload.auto_snapshot:
                snapshot_hash = _safe_auto_snapshot("心法开关前", f"{lesson_id}={payload.enabled}", actor_name)
            toggled = evolution_shield.toggle_lesson(lesson_id, expected_version=view.get("version"))
            extra["target"] = toggled
        else:
            extra["target"] = target_lesson

    audit_record(
        "control_plane.quick_toggle",
        "success",
        {
            "actor": actor_name,
            "target": target,
            "item_id": payload.item_id,
            "enabled": payload.enabled,
            "snapshot_hash": snapshot_hash,
        },
    )
    return {
        "ok": True,
        "target": target,
        "item_id": payload.item_id,
        "enabled": bool(payload.enabled),
        "snapshot_hash": snapshot_hash,
        **extra,
    }


@router.put("/api/v1/admin/control-plane/order-mode")
def control_plane_set_order_mode(
    payload: ControlPlaneOrderModeRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    actor_name = str(actor.get("username") or "admin")
    mode = payload.order_mode.strip().lower()
    if mode not in {"limit", "market", "smart"}:
        raise HTTPException(status_code=400, detail=f"不支持的委托订单模式：{mode}")
    snapshot_hash = _safe_auto_snapshot("订单模式调整前", f"order_mode -> {mode}", actor_name) if payload.auto_snapshot else ""
    update_env({"ASTRA_ORDER_MODE": mode})
    refresh_settings()
    audit_record("control_plane.order_mode.update", "success", {"actor": actor_name, "order_mode": mode, "snapshot_hash": snapshot_hash})
    return {"ok": True, "order_mode": mode, "snapshot_hash": snapshot_hash}


@router.post("/api/v1/admin/control-plane/risk/preview")
def control_plane_risk_preview(
    payload: ControlPlaneRiskPreviewRequest,
    x_astra_admin_token: str | None = Header(default=None),
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)

    before = risk_config.current_values()
    patch: dict[str, Any] = {}
    if payload.suite_id:
        try:
            patch.update(risk_config.suite_values(payload.suite_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    patch.update(payload.values)

    candidate = {**before, **patch}
    valid = True
    error = ""
    normalized: dict[str, float | int] = dict(before)
    try:
        norm_strs = risk_config.normalize(candidate if patch else before)
        for k, raw_val in norm_strs.items():
            normalized[k] = int(float(raw_val)) if isinstance(before.get(k), int) and k in {"ASTRA_MAX_CONCURRENT_POSITIONS", "ASTRA_MAX_SAME_DIRECTION_POSITIONS", "ASTRA_STOP_COOLDOWN_MINUTES", "ASTRA_MAX_SCALE_IN_COUNT", "ASTRA_SCALE_OUT_ENABLED", "ASTRA_LIMIT_ORDER_TTL_MINUTES"} else float(raw_val)
    except ValueError as exc:
        valid = False
        error = str(exc)
        for k, v in candidate.items():
            try:
                normalized[k] = float(v)
            except (TypeError, ValueError):
                pass

    high_risk = risk_config.high_risk_changes(patch)
    audit = risk_config.audit_risk_consistency(normalized)
    changed = [
        {"key": k, "before": before.get(k), "after": normalized.get(k)}
        for k in sorted(patch)
        if k in before and str(before.get(k)) != str(normalized.get(k))
    ]
    return {
        "valid": valid,
        "error": error,
        "risk_audit": audit,
        "high_risk": high_risk,
        "high_risk_phrase": risk_config.HIGH_RISK_PHRASE if high_risk else "",
        "changed": changed,
        "preview_values": normalized,
    }


@router.post("/api/v1/admin/control-plane/risk/save")
def control_plane_risk_save(
    payload: ControlPlaneRiskSaveRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    actor_name = str(actor.get("username") or "admin")

    merged: dict[str, Any] = {}
    if payload.suite_id:
        try:
            merged.update(risk_config.suite_values(payload.suite_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    merged.update(payload.values)
    if not merged:
        raise HTTPException(status_code=400, detail="没有需要保存的修改")

    high_risk = risk_config.high_risk_changes(merged)
    if high_risk and str(payload.confirmation or "").strip().upper() != risk_config.HIGH_RISK_PHRASE:
        detail = "；".join(
            f"{i['label']} = {i['value'] * 100 if 'RATIO' in i['key'] else i['value']:g}"
            f"（阈值 {i['threshold'] * 100 if 'RATIO' in i['key'] else i['threshold']:g}）"
            for i in high_risk
        )
        raise HTTPException(
            status_code=400,
            detail=f"以下参数已进入极端区间，必须逐字确认 {risk_config.HIGH_RISK_PHRASE}：{detail}",
        )

    before = risk_config.current_values()
    try:
        env_updates = risk_config.normalize(merged)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    snapshot_hash = (
        _safe_auto_snapshot("风控变更前", payload.note or f"修改 {len(env_updates)} 项风控参数", actor_name)
        if payload.auto_snapshot
        else ""
    )

    update_env(env_updates)
    refresh_settings()
    risk_config.reload_risk_constants()
    try:
        cur_v = risk_config.current_values()
        sync_pool_leverage_caps(
            min_leverage=float(env_updates.get("ASTRA_MIN_LEVERAGE", cur_v.get("ASTRA_MIN_LEVERAGE", 2.0))),
            max_leverage=float(env_updates.get("ASTRA_MAX_LEVERAGE", cur_v.get("ASTRA_MAX_LEVERAGE", 5.0))),
        )
    except Exception:
        pass

    after = risk_config.current_values()
    audit_record(
        "control_plane.risk.save",
        "success",
        {
            "actor": actor_name,
            "suite": payload.suite_id or None,
            "snapshot_hash": snapshot_hash,
            "changed": {k: {"before": before.get(k), "after": float(v)} for k, v in env_updates.items()},
        },
    )
    return {
        "ok": True,
        "updated": sorted(env_updates.keys()),
        "values": after,
        "risk_audit": risk_config.audit_risk_consistency(after),
        "snapshot_hash": snapshot_hash,
    }


@router.patch("/api/v1/admin/control-plane/council/role/{role_id}")
def control_plane_patch_council_role(
    role_id: str,
    payload: CouncilRolePatchRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    actor_name = str(actor.get("username") or "admin")

    cfg = load_council_config()
    roles = cfg.get("roles") if isinstance(cfg.get("roles"), dict) else {}
    if role_id not in roles or not isinstance(roles[role_id], dict):
        raise HTTPException(status_code=404, detail=f"未找到投委会席位：{role_id}")

    snapshot_hash = (
        _safe_auto_snapshot("投委会席位调整前", f"修改席位 {role_id}", actor_name)
        if payload.auto_snapshot
        else ""
    )

    patch_fields = payload.model_dump(exclude={"auto_snapshot"}, exclude_unset=True)
    role_obj = dict(roles[role_id])
    for key, val in patch_fields.items():
        if val is not None:
            role_obj[key] = val.strip() if key in {"model_id", "name"} and isinstance(val, str) else val
    roles[role_id] = role_obj
    cfg["roles"] = roles

    try:
        saved = save_council_config(cfg)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_record(
        "control_plane.council.role.patch",
        "success",
        {"actor": actor_name, "role_id": role_id, "fields": sorted(patch_fields.keys()), "snapshot_hash": snapshot_hash},
    )
    return {
        "ok": True,
        "role_id": role_id,
        "config": saved,
        "model_health": seat_model_health(saved.get("roles")),
        "snapshot_hash": snapshot_hash,
    }


@router.post("/api/v1/admin/control-plane/jobs/{job_id}/trigger")
def control_plane_trigger_job(
    job_id: str,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    actor_name = str(actor.get("username") or "admin")
    try:
        run = trigger_job_async(job_id, actor=actor_name)
    except UnknownJobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except JobAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "run": run}


@router.get("/api/v1/admin/control-plane/jobs/runs")
def control_plane_job_runs(
    limit: int = 20,
    x_astra_admin_token: str | None = Header(default=None),
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    return {
        "jobs": job_catalog(),
        "runs": list_job_runs(limit=limit),
    }
