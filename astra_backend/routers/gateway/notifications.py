"""通知配置、诊断、QQ 绑定与通知计划端点。

从 `routers/gateway.py` 按域拆出；URL/方法/处理器名/tags 一字未改。
"""
from __future__ import annotations

import time
from typing import Any
from fastapi import Header, HTTPException
from astra_backend.config import refresh_settings
from astra_backend.settings_store import update_env, remove_env, mask, mask_url, is_masked
from astra_gateway.secrets import save_secrets
from astra_backend.audit import record as audit_record
from astra_backend.notifications import _env as notification_env, diagnose_channel, test_channel
from astra_backend.dependencies import app_attr, require_admin_header, require_superadmin
from astra_backend.schemas import NotificationConfigUpdate, QQOpenIDCaptureStartRequest, NotificationTestRequest, NotificationScheduleUpdate
from astra_backend.schedule_store import load_schedule, save_schedule

from fastapi import APIRouter

router = APIRouter(tags=["gateway"])


@router.get("/api/v1/admin/notifications")
def admin_notifications(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"), x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    """频道配置读取：嵌套形状 + 凭证脱敏是 NotifyPage 的硬契约（拆分时曾被改写为
    扁平明文导致整页开关失效 + 明文外泄，2026-09-13 还原 @33cc95d^ 旧契约）。"""
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    env = notification_env()
    return {
        "webhook": {"enabled": env.get("ASTRA_NOTIFY_WEBHOOK_ENABLED", "0") == "1", "url": mask_url(env.get("ASTRA_NOTIFICATION_WEBHOOK", ""))},
        "wechat": {"enabled": env.get("ASTRA_NOTIFY_WECHAT_ENABLED", "0") == "1", "webhook": mask_url(env.get("ASTRA_WECHAT_WEBHOOK", ""))},
        "telegram": {"enabled": env.get("ASTRA_NOTIFY_TELEGRAM_ENABLED", "0") == "1", "bot_token": mask(env.get("ASTRA_TELEGRAM_BOT_TOKEN", "")), "chat_id": env.get("ASTRA_TELEGRAM_CHAT_ID", ""), "api_base": env.get("ASTRA_TELEGRAM_API_BASE", "")},
        "qq": {"enabled": env.get("ASTRA_NOTIFY_QQ_ENABLED", "0") == "1", "app_id": env.get("ASTRA_QQ_APP_ID", ""), "client_secret": mask(env.get("ASTRA_QQ_CLIENT_SECRET", "")), "openid": env.get("ASTRA_QQ_OPENID", "")},
    }


@router.put("/api/v1/admin/notifications")
def admin_update_notifications(
    payload: NotificationConfigUpdate,
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    require_superadmin(x_astra_session)
    current_env = notification_env()

    # 审计修复A2(2026-09-13)：GET 端返回 mask()/mask_url() 脱敏串，前端表单原样回传时
    # 掩码值=「用户未改动」，一律置 None 跳过写回（readiness 自然回退 current_env）。
    for _mf in ("webhook_url", "wechat_webhook", "telegram_bot_token", "qq_client_secret"):
        _mv = getattr(payload, _mf, None)
        if _mv is not None and is_masked(_mv):
            setattr(payload, _mf, None)

    env_update = {}
    if payload.webhook_url is not None:
        env_update["ASTRA_NOTIFICATION_WEBHOOK"] = payload.webhook_url.strip()
    if payload.wechat_webhook is not None:
        env_update["ASTRA_WECHAT_WEBHOOK"] = payload.wechat_webhook.strip()
    if payload.telegram_bot_token is not None:
        env_update["ASTRA_TELEGRAM_BOT_TOKEN"] = payload.telegram_bot_token.strip()
    if payload.telegram_chat_id is not None:
        env_update["ASTRA_TELEGRAM_CHAT_ID"] = payload.telegram_chat_id.strip()
    if payload.telegram_api_base is not None:
        env_update["ASTRA_TELEGRAM_API_BASE"] = payload.telegram_api_base.strip()
    if payload.qq_app_id is not None:
        env_update["ASTRA_QQ_APP_ID"] = payload.qq_app_id.strip()
    if payload.qq_client_secret is not None:
        env_update["ASTRA_QQ_CLIENT_SECRET"] = payload.qq_client_secret.strip()
    if payload.qq_openid is not None:
        env_update["ASTRA_QQ_OPENID"] = payload.qq_openid.strip()

    readiness = {
        "qq": bool((payload.qq_app_id or current_env.get("ASTRA_QQ_APP_ID")) and (payload.qq_openid or current_env.get("ASTRA_QQ_OPENID"))),
        "telegram": bool((payload.telegram_bot_token or current_env.get("ASTRA_TELEGRAM_BOT_TOKEN")) and payload.telegram_chat_id),
        "wechat": bool(payload.wechat_webhook or current_env.get("ASTRA_WECHAT_WEBHOOK")),
        "webhook": bool(payload.webhook_url or current_env.get("ASTRA_NOTIFICATION_WEBHOOK")),
    }

    warnings = []
    eff_qq = payload.qq_enabled
    if payload.qq_enabled and not readiness["qq"]:
        eff_qq = False
        warnings.append("QQ 频道因缺少 OpenID 暂未开启（请点击「⚡ 自动获取 OpenID」绑定）")

    eff_tg = payload.telegram_enabled
    if payload.telegram_enabled and not readiness["telegram"]:
        eff_tg = False
        warnings.append("Telegram 频道因缺少 Token 或 Chat ID 暂未开启")

    eff_wx = payload.wechat_enabled
    if payload.wechat_enabled and not readiness["wechat"]:
        eff_wx = False
        warnings.append("企业微信频道因缺少 Webhook 暂未开启")

    eff_wh = payload.webhook_enabled
    if payload.webhook_enabled and not readiness["webhook"]:
        eff_wh = False
        warnings.append("通用 Webhook 因缺少 URL 暂未开启")

    env_update.update({
        "ASTRA_NOTIFY_WEBHOOK_ENABLED": "1" if eff_wh else "0",
        "ASTRA_NOTIFY_WECHAT_ENABLED": "1" if eff_wx else "0",
        "ASTRA_NOTIFY_TELEGRAM_ENABLED": "1" if eff_tg else "0",
        "ASTRA_NOTIFY_QQ_ENABLED": "1" if eff_qq else "0",
    })

    # 审计修复A2补充(2026-09-13)：对称性——toggle 把凭证写加密库(save_secrets)且 remove_env，
    # 而整页 PUT 曾把含密钥 webhook URL/token 明文落 .env（update_env），形成第二落盘。
    # 现同 toggle 一样分流：密钥性字段进密文库并从 env 拔除，env 只留开关与非敏感 ID。
    _secrets_put = {}
    for _attr, _key in (("webhook_url", "ASTRA_NOTIFICATION_WEBHOOK"),
                        ("wechat_webhook", "ASTRA_WECHAT_WEBHOOK"),
                        ("telegram_bot_token", "ASTRA_TELEGRAM_BOT_TOKEN"),
                        ("qq_client_secret", "ASTRA_QQ_CLIENT_SECRET")):
        _val = getattr(payload, _attr, None)
        if _val:
            _secrets_put[_key] = _val.strip()
            env_update.pop(_key, None)
    if _secrets_put:
        save_secrets(_secrets_put)
        remove_env(list(_secrets_put))
    for _k in [k for k, v in env_update.items() if not v.strip()]:
        remove_env({_k})
        del env_update[_k]

    update_env(env_update)
    refresh_settings()

    audit_record("notifications.update", "success", {
        "webhook": eff_wh,
        "wechat": eff_wx,
        "telegram": eff_tg,
        "qq": eff_qq,
        "warnings": warnings,
    })
    msg = "全部通知配置已成功保存"
    if warnings:
        msg += f"（提示：{'；'.join(warnings)}）"
    return {"saved": True, "message": msg, "warnings": warnings}


@router.post("/api/v1/admin/notifications/diagnose")
def diagnose_notification(payload: NotificationTestRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"), x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    fn_diag = app_attr("diagnose_channel", diagnose_channel)
    result = fn_diag(payload.channel)
    audit_record("notifications.diagnose", "completed", {"channel": payload.channel, "status": result.get("status")})
    return {"channel": payload.channel, "result": result, "sent": False}


@router.post("/api/v1/admin/notifications/test")
def send_notification_test(payload: NotificationTestRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    refresh_settings()
    require_superadmin(x_astra_session)
    if payload.confirmation.strip().upper() != f"SEND TEST {payload.channel.upper()}":
        raise HTTPException(status_code=400, detail=f"确认短语必须为：SEND TEST {payload.channel.upper()}")
    fn_test = app_attr("test_channel", test_channel)
    result = fn_test(payload.channel)
    audit_record("notifications.test", "completed", {"channel": payload.channel, "result": result})
    return {"channel": payload.channel, "result": result, "sent": True, "meaning": "远端接口已受理不等于用户客户端已读"}


@router.post("/api/v1/admin/notifications/qq/capture-openid/start")
def qq_capture_openid_start(payload: QQOpenIDCaptureStartRequest | None = None, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    refresh_settings()
    require_superadmin(x_astra_session)
    from astra_backend.qq_bind import start_openid_capture
    app_id = payload.app_id if payload else None
    secret = payload.client_secret if payload else None
    timeout = payload.timeout if payload else 60
    try:
        res = start_openid_capture(app_id=app_id, client_secret=secret, timeout=timeout)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"启动 QQ OpenID 监听网关失败：{exc}") from exc
    audit_record("qq.capture_openid.start", "success", {"capture_id": res.get("capture_id"), "app_id": res.get("app_id")})
    return res


@router.get("/api/v1/admin/notifications/qq/capture-openid/{capture_id}")
def qq_capture_openid_poll(capture_id: str, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    refresh_settings()
    require_superadmin(x_astra_session)
    from astra_backend.qq_bind import poll_openid_capture
    res = poll_openid_capture(capture_id)
    if res.get("status") == "captured":
        audit_record("qq.capture_openid.complete", "success", {"capture_id": capture_id, "openid": res.get("openid")})
    return res


@router.post("/api/v1/admin/notifications/qq/bind/start")
def qq_bind_start(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    refresh_settings()
    require_superadmin(x_astra_session)
    from astra_backend.qq_bind import create_bind_task
    try:
        task = create_bind_task()
    except Exception as exc:
        audit_record("qq.bind.start", "failed", {"error": str(exc)[:200]})
        raise HTTPException(status_code=502, detail=f"QQ 绑定任务创建失败：{exc}")
    qr_data_uri = ""
    try:
        import segno
        qr_data_uri = segno.make(task["connect_url"], error="M").png_data_uri(scale=6, border=2)
    except Exception:
        pass
    audit_record("qq.bind.start", "success", {"task_id": task["task_id"]})
    return {"task_id": task["task_id"], "qr_data_uri": qr_data_uri, "connect_url": task["connect_url"], "expires_in": task["expires_in"]}


@router.get("/api/v1/admin/notifications/qq/bind/{task_id}")
def qq_bind_poll(task_id: str, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    refresh_settings()
    require_superadmin(x_astra_session)
    from astra_backend.qq_bind import poll_bind_task
    try:
        result = poll_bind_task(task_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    if result["status"] == "bound" or result["status"] == "awaiting_message":
        audit_record("qq.bind.complete", "success", {"app_id": result["app_id"], "status": result["status"], "openid_present": bool(result.get("openid"))})
    return result


@router.get("/api/v1/admin/notifications/schedule")
def notification_schedule(x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token)
    schedule = load_schedule()
    return {
        **schedule,
        "event_notifications": "开仓、平仓与风险事件实时推送，不受每日简报时间限制",
        "restart_note": "保存后调度器将在 60 秒内读取新时间，无需重启。",
    }


@router.put("/api/v1/admin/notifications/schedule")
def update_notification_schedule(payload: NotificationScheduleUpdate, x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token)
    normalized: list[str] = []
    for value in payload.briefing_times:
        value = value.strip()
        try:
            parsed = time.strptime(value, "%H:%M")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"无效时间：{value}；必须使用 HH:MM 24 小时格式") from exc
        canonical = f"{parsed.tm_hour:02d}:{parsed.tm_min:02d}"
        if canonical not in normalized:
            normalized.append(canonical)
    normalized.sort()
    schedule = load_schedule()
    schedule["briefing_times"] = normalized
    save_schedule(schedule)
    audit_record("notifications.schedule", "success", {"briefing_times": normalized, "timezone": "Asia/Shanghai"})
    return {**schedule, "saved": True, "restart_note": "调度器将在 60 秒内读取新时间。"}
