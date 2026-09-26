"""回退事件读取。

注：record_failover_event 因 tests/core/test_beijing_time_producers.py 的 isolated()
按 AST 从 llm_manager.py 取同名函数而**必须留在门面**，故写入端与读取端分处两文件。
读取端为纯函数（路径由薄壳传入），结构优化阶段 2（B4）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def recent_failover_events(events_file: Path, limit: int = 30) -> List[Dict[str, Any]]:
    if events_file.exists():
        try:
            with open(events_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                return loaded[: max(1, min(int(limit), 200))]
        except Exception:
            pass
    return []
