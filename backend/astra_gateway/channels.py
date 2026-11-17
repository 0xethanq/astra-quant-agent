"""Notification channel adapter backed by existing ASTRA-native connectors."""
from __future__ import annotations
from dataclasses import dataclass

from astra_backend.notifications import send_channel


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    detail: str
    status: str = "delivered"


class NotificationChannelAdapter:
    def __init__(self, channel_id: str):
        self.channel_id = channel_id

    def send(self, message: str) -> DeliveryResult:
        ok, detail = send_channel(self.channel_id, message)
        return DeliveryResult(ok, detail)
