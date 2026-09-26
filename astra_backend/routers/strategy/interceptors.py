"""拦截器（interceptors）文件级 CRUD 与试跑端点。

从 `routers/strategy.py` 按域拆出（B8）；URL/方法/处理器名一字未改。
"""
from __future__ import annotations

from typing import Any
from fastapi import Header, HTTPException
from astra_backend.audit import record as audit_record
from astra_backend.dependencies import require_admin_header, require_superadmin
from astra_backend.schemas import InterceptorToggleRequest, InterceptorCodeRequest, InterceptorCreateRequest, InterceptorReorderRequest, InterceptorTestRequest

from fastapi import APIRouter

router = APIRouter(tags=["strategy"])


@router.get("/api/v1/admin/interceptors")
def admin_list_interceptors(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    require_admin_header(x_astra_session=x_astra_session)
    from astra_backend.interceptor_manager import list_plugins
    return {"plugins": list_plugins()}


@router.get("/api/v1/admin/interceptors/{filename}")
def admin_get_interceptor(filename: str, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    require_admin_header(x_astra_session=x_astra_session)
    from astra_backend.interceptor_manager import get_plugin_detail
    try:
        return get_plugin_detail(filename)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/api/v1/admin/interceptors/{filename}/toggle")
def admin_toggle_interceptor(filename: str, payload: InterceptorToggleRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    from astra_backend.interceptor_manager import toggle_plugin
    res = toggle_plugin(filename, payload.enabled)
    audit_record("interceptor.toggle", "success", {"actor": actor["username"], "filename": filename, "enabled": payload.enabled})
    return res


@router.put("/api/v1/admin/interceptors/{filename}/code")
def admin_save_interceptor_code(filename: str, payload: InterceptorCodeRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    from astra_backend.interceptor_manager import save_plugin_code
    try:
        res = save_plugin_code(filename, payload.code)
        audit_record("interceptor.code.update", "success", {"actor": actor["username"], "filename": filename})
        return res
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/api/v1/admin/interceptors")
def admin_create_interceptor(payload: InterceptorCreateRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    from astra_backend.interceptor_manager import create_plugin
    try:
        res = create_plugin(payload.filename, payload.code)
        audit_record("interceptor.create", "success", {"actor": actor["username"], "filename": payload.filename})
        return res
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.delete("/api/v1/admin/interceptors/{filename}")
def admin_delete_interceptor(filename: str, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    from astra_backend.interceptor_manager import delete_plugin
    try:
        delete_plugin(filename)
        audit_record("interceptor.delete", "success", {"actor": actor["username"], "filename": filename})
        return {"deleted": True, "filename": filename}
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


@router.post("/api/v1/admin/interceptors/reorder")
def admin_reorder_interceptors(payload: InterceptorReorderRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    from astra_backend.interceptor_manager import reorder_plugins
    res = reorder_plugins(payload.pipeline_order)
    audit_record("interceptor.reorder", "success", {"actor": actor["username"]})
    return {"plugins": res}


@router.post("/api/v1/admin/interceptors/test")
def admin_test_interceptors(payload: InterceptorTestRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    require_admin_header(x_astra_session=x_astra_session)
    from astra_backend.interceptor_manager import run_sandbox_test
    return run_sandbox_test(payload.scenario)
