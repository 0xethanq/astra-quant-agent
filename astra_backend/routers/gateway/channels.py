"""通知渠道开关端点（`/api/v1/admin/channels/{channel}/toggle`）。

从 `routers/gateway.py`（977 行 / 34 路由）按域拆出；URL/方法/处理器名/tags 一字未改。
"""
from __future__ import annotations

from typing import Any
from fastapi import Header, HTTPException
from astra_backend.config import refresh_settings
from astra_backend.settings_store import update_env, remove_env, is_masked
from astra_gateway.secrets import save_secrets
from astra_backend.audit import record as audit_record
from astra_backend.notifications import _env as notification_env
from astra_backend.dependencies import require_admin_header
from astra_backend.schemas import ChannelToggleRequest

from fastapi import APIRouter

router = APIRouter(tags=["gateway"])


@router.put("/api/v1/admin/channels/{channel}/toggle")
def toggle_channel(channel: str, payload: ChannelToggleRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"), x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    """通知频道开关（含开关时顺带保存凭证）；33cc95d 拆分时丢失，2026-09-13 按旧体还原。"""
    from astra_gateway.secrets import save_secrets
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    keys = {
        "qq": "ASTRA_NOTIFY_QQ_ENABLED",
        "telegram": "ASTRA_NOTIFY_TELEGRAM_ENABLED",
        "wechat": "ASTRA_NOTIFY_WECHAT_ENABLED",
        "webhook": "ASTRA_NOTIFY_WEBHOOK_ENABLED",
    }
    channel_names = {
        "qq": "QQ 官方 Bot",
        "telegram": "Telegram Bot",
        "wechat": "企业微信",
        "webhook": "通用 Webhook",
    }
    if channel not in keys:
        raise HTTPException(status_code=404, detail="未知频道")

    # If the user provided inputs while toggling, save them immediately
    # 审计修复A2：toggle 同样拒绝掩码回写（含 secrets 通道——优先级高于 .env，写坏即告警死亡）
    if channel == "wechat" and payload.wechat_webhook is not None and not is_masked(payload.wechat_webhook):
        val = payload.wechat_webhook.strip()
        if val:
            save_secrets({"ASTRA_WECHAT_WEBHOOK": val})
            remove_env({"ASTRA_WECHAT_WEBHOOK"})
    elif channel == "webhook" and payload.webhook_url is not None and not is_masked(payload.webhook_url):
        val = payload.webhook_url.strip()
        if val:
            save_secrets({"ASTRA_NOTIFICATION_WEBHOOK": val})
            remove_env({"ASTRA_NOTIFICATION_WEBHOOK"})
    elif channel == "telegram":
        if payload.telegram_bot_token is not None and payload.telegram_bot_token.strip() and not is_masked(payload.telegram_bot_token):
            save_secrets({"ASTRA_TELEGRAM_BOT_TOKEN": payload.telegram_bot_token.strip()})
            remove_env({"ASTRA_TELEGRAM_BOT_TOKEN"})
        tg_env = {}
        if payload.telegram_chat_id is not None:
            tg_env["ASTRA_TELEGRAM_CHAT_ID"] = payload.telegram_chat_id.strip()
        if payload.telegram_api_base is not None:
            tg_env["ASTRA_TELEGRAM_API_BASE"] = payload.telegram_api_base.strip()
        if tg_env:
            update_env(tg_env)
    elif channel == "qq":
        if payload.qq_client_secret is not None and payload.qq_client_secret.strip() and not is_masked(payload.qq_client_secret):
            save_secrets({"ASTRA_QQ_CLIENT_SECRET": payload.qq_client_secret.strip()})
            remove_env({"ASTRA_QQ_CLIENT_SECRET"})
        qq_env = {}
        if payload.qq_app_id is not None:
            qq_env["ASTRA_QQ_APP_ID"] = payload.qq_app_id.strip()
        if payload.qq_openid is not None:
            qq_env["ASTRA_QQ_OPENID"] = payload.qq_openid.strip()
        if qq_env:
            update_env(qq_env)

    name = channel_names.get(channel, channel)
    if payload.enabled:
        env = notification_env()
        readiness = {
            "qq": bool(env.get("ASTRA_QQ_APP_ID") and env.get("ASTRA_QQ_CLIENT_SECRET") and env.get("ASTRA_QQ_OPENID")),
            "telegram": bool(env.get("ASTRA_TELEGRAM_BOT_TOKEN") and env.get("ASTRA_TELEGRAM_CHAT_ID")),
            "wechat": bool(env.get("ASTRA_WECHAT_WEBHOOK")),
            "webhook": bool(env.get("ASTRA_NOTIFICATION_WEBHOOK")),
        }
        if not readiness[channel]:
            if channel == "qq":
                if not env.get("ASTRA_QQ_OPENID"):
                    raise HTTPException(status_code=400, detail="QQ 缺少目标用户 OpenID，请先点击「⚡ 自动获取 OpenID」向 Bot 发送消息完成绑定")
                raise HTTPException(status_code=400, detail="QQ App ID 或 Client Secret 尚未配置完整")
            elif channel == "wechat":
                raise HTTPException(status_code=400, detail="企业微信尚未配置 Webhook URL，请先填入有效 Webhook 地址再开启")
            elif channel == "webhook":
                raise HTTPException(status_code=400, detail="通用 Webhook 尚未配置 URL，请先填入有效 Webhook 地址再开启")
            elif channel == "telegram":
                raise HTTPException(status_code=400, detail="Telegram 缺少 Bot Token 或 Chat ID，请填写完整后再开启")
            raise HTTPException(status_code=400, detail=f"{name} 凭证或目标未配置完整，请先填写有效配置再开启")

    update_env({keys[channel]: "1" if payload.enabled else "0"})
    audit_record("channel.toggle", "success", {"channel": channel, "enabled": payload.enabled})
    return {"channel": channel, "enabled": payload.enabled, "message": f"{name} 通道已成功{'开启' if payload.enabled else '关闭'}"}
