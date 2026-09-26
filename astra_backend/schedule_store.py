"""Persistent Beijing-time schedules shared by the admin plane and scheduler."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEDULE_FILE = ROOT / "data" / "notification_schedule.json"
DEFAULT_SCHEDULE = {
    "timezone": "Asia/Shanghai",
    "briefing_times": ["08:00", "20:00"],
    "self_improvement_times": ["02:00", "08:00", "14:00", "20:00"],
    "self_improvement_time": "20:00",  # backward compatibility fallback
    "backup_time": "02:00",
}


def load_schedule() -> dict[str, Any]:
    if not SCHEDULE_FILE.exists():
        return dict(DEFAULT_SCHEDULE)
    try:
        payload = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        return {**DEFAULT_SCHEDULE, **payload}
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SCHEDULE)


def save_schedule(schedule: dict[str, Any]) -> None:
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".notification-schedule-", suffix=".tmp", dir=SCHEDULE_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(schedule, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, SCHEDULE_FILE)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
