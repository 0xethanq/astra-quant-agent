"""Shared dependencies, context vars, and auth utilities for ASTRA backend."""
from __future__ import annotations
import hmac
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from contextvars import ContextVar

from fastapi import HTTPException
from astra_backend.config import settings, refresh_settings
from astra_backend.admin_auth import AdminAuthStore
from astra_backend.okx_client import OKXClient

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SCRIPTS_DIR = ROOT / "scripts"
VUE_DIST = ROOT / "frontend" / "dist"
BACKUP_LOG_FILE = ROOT / "logs" / "astra_backup_manual.log"
PROMPT_OVERRIDE_FILE = DATA_DIR / "system_prompt_override.txt"

MAX_POOL_SIZE = int(os.getenv("ASTRA_MAX_POOL_SIZE", "20"))
MIN_POOL_SIZE = int(os.getenv("ASTRA_MIN_POOL_SIZE", "1"))
STARTED_AT = time.time()
REQUEST_SESSION: ContextVar[str] = ContextVar("astra_admin_session", default="")

okx = OKXClient()
admin_auth = AdminAuthStore()


def app_attr(name: str, default: Any = None) -> Any:
    app_mod = sys.modules.get("astra_backend.app")
    if app_mod and hasattr(app_mod, name):
        return getattr(app_mod, name)
    return default


def get_auth_store() -> AdminAuthStore:
    app_mod = sys.modules.get("astra_backend.app")
    if app_mod and hasattr(app_mod, "admin_auth"):
        return app_mod.admin_auth
    return admin_auth


def require_admin_token(token: str) -> None:
    expected = settings.admin_token or settings.setup_token
    if not expected:
        raise HTTPException(status_code=503, detail="后台尚未设置 ASTRA_SETUP_TOKEN 或 ASTRA_ADMIN_TOKEN")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="管理员令牌无效")


def current_admin(x_astra_session: str | None = None, x_astra_admin_token: str | None = None) -> dict[str, Any]:
    auth_store = get_auth_store()
    user = auth_store.validate_session(x_astra_session or "")
    if user:
        return user
    if x_astra_admin_token and not auth_store.has_users():
        require_admin_token(x_astra_admin_token)
        return {"id": 0, "username": "legacy-token", "role": "legacy", "enabled": 1}
    raise HTTPException(status_code=401, detail="管理员会话已失效，请重新登录")


def require_admin_header(x_astra_admin_token: Any = None, x_astra_session: Any = None) -> dict[str, Any]:
    app_mod = sys.modules.get("astra_backend.app")
    session_tok = x_astra_session if isinstance(x_astra_session, str) else REQUEST_SESSION.get()
    admin_tok = x_astra_admin_token if isinstance(x_astra_admin_token, str) else None
    if app_mod and hasattr(app_mod, "require_admin_header") and app_mod.require_admin_header is not require_admin_header:
        try:
            return app_mod.require_admin_header(admin_tok, session_tok)
        except TypeError:
            return app_mod.require_admin_header(admin_tok)
    return current_admin(session_tok, admin_tok)


def require_superadmin(x_astra_session: Any = None) -> dict[str, Any]:
    app_mod = sys.modules.get("astra_backend.app")
    if app_mod and hasattr(app_mod, "require_superadmin") and app_mod.require_superadmin is not require_superadmin:
        return app_mod.require_superadmin(x_astra_session)
    session_tok = x_astra_session if isinstance(x_astra_session, str) else REQUEST_SESSION.get()
    auth_store = get_auth_store()
    user = auth_store.validate_session(session_tok)
    if not user:
        raise HTTPException(status_code=401, detail="管理员会话已失效，请重新登录")
    if user["role"] != "superadmin":
        raise HTTPException(status_code=403, detail="仅超级管理员可以执行此操作")
    return user


def read_json(filename: str, default: Any) -> Any:
    path = DATA_DIR / filename
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        # 审计③(2026-09-13)：损坏与缺失从此不同权——返回 default 保持服务不炸，
        # 但必须在日志吼出来（旧实现同路静默，前端把「数据损坏」渲染成「确实没有」）。
        print(f"[read_json] CRITICAL data/{filename} 损坏不可解析，已按默认值降级展示: {exc}",
              file=sys.stderr)
        return default
    except OSError as exc:
        print(f"[read_json] warn data/{filename} 读取失败: {exc}", file=sys.stderr)
        return default


def script_state(script_name: str) -> dict[str, Any]:
    path = SCRIPTS_DIR / script_name
    return {"name": script_name, "exists": path.exists(), "path": str(path)}
