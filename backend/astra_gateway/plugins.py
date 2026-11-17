"""Built-in plugin registry for the ASTRA Gateway control plane."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any

from astra_backend.notifications import _env


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    plugin_type: str
    permissions: tuple[str, ...]
    enabled_key: str = ""


PLUGINS = (
    PluginManifest("astra.channel.qq", "QQ 官方 Bot", "1.0.0", "channel", ("network:api.sgroup.qq.com", "secret:qq", "event:notification"), "ASTRA_NOTIFY_QQ_ENABLED"),
    PluginManifest("astra.channel.telegram", "Telegram Bot", "1.0.0", "channel", ("network:api.telegram.org", "secret:telegram", "event:notification"), "ASTRA_NOTIFY_TELEGRAM_ENABLED"),
    PluginManifest("astra.channel.wecom", "企业微信", "1.0.0", "channel", ("network:qyapi.weixin.qq.com", "secret:wechat-webhook", "event:notification"), "ASTRA_NOTIFY_WECHAT_ENABLED"),
    PluginManifest("astra.channel.webhook", "通用 Webhook", "1.0.0", "channel", ("network:configured-host", "secret:webhook", "event:notification"), "ASTRA_NOTIFY_WEBHOOK_ENABLED"),
    PluginManifest("astra.scheduler.core", "Gateway Scheduler", "0.2.0", "scheduler", ("process:scripts", "state:gateway-db")),
    PluginManifest("astra.runtime.agents", "Agent Runtime Registry", "0.3.0", "runtime", ("state:job-runs", "data:read-only")),
    PluginManifest("astra.telemetry.models", "Model Call Telemetry", "0.3.0", "telemetry", ("metadata:model-calls", "content:none")),
    PluginManifest("astra.secrets.local", "Encrypted Secret Store", "0.3.0", "security", ("filesystem:0600", "secret:encrypted-local")),
    PluginManifest("astra.exchange.okx", "OKX Execution Bridge", "1.0.0", "exchange", ("network:okx.com", "secret:okx", "trade:read")),
)


def plugin_statuses() -> list[dict[str, Any]]:
    env = _env()
    result = []
    for manifest in PLUGINS:
        enabled = True if not manifest.enabled_key else env.get(manifest.enabled_key) == "1"
        health = "disabled" if not enabled else "healthy"
        detail = "内置插件"
        payload = asdict(manifest)
        payload.update({"enabled": enabled, "health": health, "detail": detail})
        result.append(payload)
    return result
