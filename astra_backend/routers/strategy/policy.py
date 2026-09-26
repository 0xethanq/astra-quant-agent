"""策略快照（policy snapshot）当前/归档/还原端点。

从 `routers/strategy.py` 按域拆出（B8）；URL/方法/处理器名一字未改。
"""
from __future__ import annotations

import re
from typing import Any
from fastapi import Header, HTTPException
from astra_backend.audit import record as audit_record
from astra_backend.dependencies import require_admin_header, require_superadmin
from astra_backend.schemas import PolicyArchiveRequest, PolicyRestoreRequest

from fastapi import APIRouter

router = APIRouter(tags=["strategy"])


@router.get("/api/v1/admin/policy/current-snapshot")
def admin_get_policy_current_snapshot(
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token, x_astra_session)
    from astra_backend.policy_snapshot import capture_full_strategy_package, generate_policy_snapshot, package_identity
    try:
        snapshot = generate_policy_snapshot()
        # 审计 P0-3：四单元 policy_hash 看不到风控/路由——只差风控的两个归档会同 hash，
        # 「● 当前正在运行」若只比 policy_hash 就会同时点亮两个版本（UI 谎报）。
        # 这里补一个整包标识，前端据此精确判定哪一份真的在运行。
        try:
            package_hash = package_identity(capture_full_strategy_package().get("package") or {})
        except Exception:
            package_hash = ""
        return {
            "ok": True,
            "policy_version": snapshot.get("policy_version"),
            "policy_hash": snapshot.get("policy_hash"),
            "package_hash": package_hash,
            "snapshot": snapshot,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取策略快照失败: {exc}")


@router.get("/api/v1/admin/policy/archives")
def admin_get_policy_archives(
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token, x_astra_session)
    from astra_backend.policy_snapshot import load_archive_index
    try:
        archives = load_archive_index()
        return {"ok": True, "archives": archives}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取策略归档列表失败: {exc}")


@router.post("/api/v1/admin/policy/archive")
def admin_archive_policy(
    payload: PolicyArchiveRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    from astra_backend.policy_snapshot import archive_current_policy
    author = actor.get("username", "admin")
    try:
        entry = archive_current_policy(name=payload.name, description=payload.description, author=author)
        audit_record("policy.archive", "success", {
            "actor": actor["username"], "name": payload.name,
            "policy_hash": entry.get("policy_hash"), "package_hash": entry.get("package_hash"),
        })
        return {"ok": True, "entry": entry}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建策略归档失败: {exc}")


@router.post("/api/v1/admin/policy/restore")
def admin_restore_policy(
    payload: PolicyRestoreRequest,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    from astra_backend.policy_snapshot import restore_archived_policy
    try:
        # 审计 P0-4(2026-09-13)：此处原写 `payload` 的 hash 属性——PolicyRestoreRequest
        # 只有 policy_hash 字段（pydantic 不产生该属性），于是**回滚已把 6 个存储全部
        # 改完之后**在审计行抛 AttributeError，被下方 except 兜成 HTTP 500
        # 「恢复策略版本失败」：管理员看到失败、系统实际已回滚、policy.restore 审计
        # 永不落库。改用真实字段并按同族路由补 actor。
        p_hash = payload.policy_hash or ""
        res = restore_archived_policy(policy_hash=p_hash)
        audit_record("policy.restore", "success", {
            "actor": actor["username"], "policy_hash": p_hash,
            "target_policy_hash": res.get("target_policy_hash", p_hash),
        })
        return {"ok": True, **res}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"恢复策略版本失败: {exc}")


@router.delete("/api/v1/admin/policy/archive/{policy_hash}")
def admin_delete_policy_archive(
    policy_hash: str,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
    x_astra_admin_token: str | None = Header(default=None)
) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    if not policy_hash or not re.match(r"^[a-zA-Z0-9_-]+$", policy_hash):
        raise HTTPException(status_code=400, detail=f"无效的策略哈希标识: {policy_hash}")
    from astra_backend.policy_snapshot import delete_archived_policy
    try:
        res = delete_archived_policy(policy_hash=policy_hash)
        audit_record("policy.delete", "success", {"actor": actor["username"], "policy_hash": policy_hash})
        return {"ok": True, **res}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"删除策略归档失败: {exc}")
