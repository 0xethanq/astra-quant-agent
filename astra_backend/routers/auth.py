"""Authentication and user management routes."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Header, HTTPException, Request

from astra_backend.audit import record as audit_record
from astra_backend.client_ip import client_ip as resolve_client_ip, user_agent as resolve_user_agent
from astra_backend import login_guard
from astra_backend.dependencies import (
    app_attr, get_auth_store, current_admin, require_superadmin,
)
from astra_backend.schemas import (
    AdminLoginRequest,
    AdminCreateRequest,
    AdminPasswordRequest,
    AdminEnabledRequest,
    AdminUnlockRequest,
)

router = APIRouter(tags=["auth"])


@router.get("/api/v1/admin/auth/status")
def admin_auth_status() -> dict[str, Any]:
    return {"initialized": get_auth_store().has_users(), "mode": "account-password", "session_hours": 12}


@router.post("/api/v1/admin/login", include_in_schema=False)
@router.post("/api/v1/admin/auth/login")
def admin_login(request: Request, payload: AdminLoginRequest) -> dict[str, Any]:
    ip = resolve_client_ip(request)
    ua = resolve_user_agent(request)
    rec_audit = app_attr("audit_record", audit_record)

    allowed, retry_after = login_guard.check(ip)
    if not allowed:
        rec_audit("admin.login", "rate_limited", {"username": payload.username, "ip": ip},
                  ip=ip, user_agent=ua)
        raise HTTPException(
            status_code=429,
            detail=f"该来源 IP 登录过于频繁，请 {retry_after} 秒后重试",
            headers={"Retry-After": str(retry_after)},
        )

    login_guard.note_attempt(ip)
    try:
        result = get_auth_store().login(payload.username, payload.password)
    except PermissionError as exc:
        login_guard.note_failure(ip)
        rec_audit("admin.login", "failed", {"username": payload.username, "ip": ip},
                  ip=ip, user_agent=ua)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    rec_audit("admin.login", "success", {"username": result["user"]["username"]},
              ip=ip, user_agent=ua)
    return result


@router.post("/api/v1/admin/logout", include_in_schema=False)
@router.post("/api/v1/admin/auth/logout")
def admin_logout(request: Request, x_astra_session: str | None = Header(default=None)) -> dict[str, Any]:
    auth_store = get_auth_store()
    rec_audit = app_attr("audit_record", audit_record)
    user = auth_store.validate_session(x_astra_session or "")
    auth_store.logout(x_astra_session or "")
    if user:
        rec_audit("admin.logout", "success", {"username": user["username"]},
                  ip=resolve_client_ip(request), user_agent=resolve_user_agent(request))
    return {"logged_out": True}


@router.get("/api/v1/admin/auth/me")
def admin_me(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    user = current_admin(x_astra_session, None)
    if user.get("role") == "legacy":
        raise HTTPException(status_code=401, detail="请使用管理员账号密码登录")
    return {"user": user}


@router.get("/api/v1/admin/users")
def admin_users(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    return {"users": get_auth_store().list_users(), "current_user_id": actor["id"]}


@router.post("/api/v1/admin/users")
def create_admin_user(payload: AdminCreateRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    rec_audit = app_attr("audit_record", audit_record)
    try:
        user = get_auth_store().create_user(payload.username, payload.password, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rec_audit("admin.user.create", "success", {"actor": actor["username"], "username": user["username"], "role": user["role"]})
    return {"created": user}


@router.put("/api/v1/admin/users/{user_id}/enabled")
def update_admin_enabled(user_id: int, payload: AdminEnabledRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    rec_audit = app_attr("audit_record", audit_record)
    auth_store = get_auth_store()
    try:
        auth_store.set_enabled(user_id, payload.enabled, actor["id"])
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    rec_audit("admin.user.enabled", "success", {"actor": actor["username"], "user_id": user_id, "enabled": payload.enabled})
    return {"user": auth_store.get_user(user_id)}


@router.post("/api/v1/admin/users/{user_id}/unlock")
def unlock_admin_user(user_id: int, payload: AdminUnlockRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    rec_audit = app_attr("audit_record", audit_record)
    expected = f"UNLOCK ADMIN {user_id}"
    if payload.confirmation.strip().upper() != expected:
        raise HTTPException(status_code=400, detail=f"确认短语必须精确为：{expected}")
    auth_store = get_auth_store()
    try:
        auth_store.unlock_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    rec_audit("admin.user.unlock", "success", {"actor": actor["username"], "user_id": user_id})
    return {"user": auth_store.get_user(user_id)}


@router.put("/api/v1/admin/users/{user_id}/password")
def update_admin_password(user_id: int, payload: AdminPasswordRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = current_admin(x_astra_session, None)
    rec_audit = app_attr("audit_record", audit_record)
    auth_store = get_auth_store()
    if actor.get("role") == "legacy":
        raise HTTPException(status_code=401, detail="请使用管理员账号密码登录")
    if actor["id"] != user_id and actor["role"] != "superadmin":
        raise HTTPException(status_code=403, detail="只能修改自己的密码")
    if actor["id"] == user_id and not auth_store.verify_password(actor["id"], payload.current_password):
        raise HTTPException(status_code=403, detail="当前密码不正确")
    try:
        auth_store.change_password(user_id, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rec_audit("admin.password.update", "success", {"actor": actor["username"], "user_id": user_id})
    return {"changed": True, "reauthenticate": True}
