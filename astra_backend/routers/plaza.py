"""Strategy Plaza (策略广场) endpoints: public telemetry & admin configuration."""
from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from astra_backend.config import refresh_settings
from astra_backend.dependencies import require_admin_header
from astra_backend.plaza_share import (
    assemble_plaza_public_profile,
    is_live_trading_node,
    load_plaza_settings,
    save_plaza_settings,
)

router = APIRouter(tags=["plaza"])


class PlazaSettingsUpdate(BaseModel):
    enabled: bool | None = None
    nickname: str | None = Field(default=None, max_length=40)
    show_performance: bool | None = None
    show_balance: bool | None = None
    show_model: bool | None = None
    show_strategy_params: bool | None = None
    plaza_hub_url: str | None = None


@router.get("/api/v1/public/plaza/profile")
def get_plaza_public_profile() -> Dict[str, Any]:
    """Public read-only telemetry for Astra Strategy Plaza.

    Fail-closed:
    - Disabled by user -> status: 'disabled'
    - Demo / Simulated node -> status: 'rejected', code: 'LIVE_ONLY'
    - Live node with sharing enabled -> returns sanitized performance, model specs, and cloneable parameters.
    """
    return assemble_plaza_public_profile()


@router.get("/api/v1/admin/plaza/settings")
def get_plaza_admin_settings(
    x_astra_admin_token: str | None = Header(default=None),
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> Dict[str, Any]:
    """Admin-only endpoint to view current plaza share configuration and live eligibility."""
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    settings = load_plaza_settings()
    is_live = is_live_trading_node()
    return {
        "settings": settings,
        "is_live": is_live,
        "public_url_path": "/api/v1/public/plaza/profile",
    }


@router.post("/api/v1/admin/plaza/settings")
def update_plaza_admin_settings(
    payload: PlazaSettingsUpdate,
    x_astra_admin_token: str | None = Header(default=None),
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> Dict[str, Any]:
    """Admin-only endpoint to update plaza share configuration."""
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    update_data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    updated = save_plaza_settings(update_data)
    is_live = is_live_trading_node()
    return {
        "ok": True,
        "settings": updated,
        "is_live": is_live,
        "message": "策略广场分享设置已保存",
    }
