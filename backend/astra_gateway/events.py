"""Immutable event model used by the ASTRA Gateway."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

BJ_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class GatewayEvent:
    event_type: str
    title: str
    message: str
    priority: int = 50
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "title": self.title,
            "message": self.message,
            "priority": self.priority,
            "payload": self.payload,
            "created_at": self.created_at,
        }
