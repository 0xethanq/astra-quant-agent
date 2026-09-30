"""Base module skeletons and rendered prompt snapshots for the admin editor."""
from __future__ import annotations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# EVOLUTION_USER_TEMPLATE：正文已迁出代码（2026-09-30）—— 提示词只存 `data/prompt_library.json`。
# 保留空常量是为了**引用稳定**（既有 import 面不因重构而断），不代表"这里有基座"。
EVOLUTION_USER_TEMPLATE = ""

# TRADING_USER_TEMPLATE：正文已迁出代码（2026-09-30）—— 提示词只存 `data/prompt_library.json`。
# 保留空常量是为了**引用稳定**（既有 import 面不因重构而断），不代表"这里有基座"。
TRADING_USER_TEMPLATE = ""


def _split_snapshot(path: Path) -> dict[str, str]:
    if not path.exists(): return {"system": "", "user": "", "updated": ""}
    text = path.read_text(encoding="utf-8", errors="replace"); marker = "【USER PROMPT"; index = text.find(marker)
    system = text[:index].strip() if index >= 0 else ""; user = text[index:].strip() if index >= 0 else text.strip()
    return {"system": system, "user": user, "updated": str(int(path.stat().st_mtime))}


def rendered_snapshots() -> dict[str, Any]:
    return {"trading": _split_snapshot(DATA / "ai_brain_last_prompt.txt"), "evolution": _split_snapshot(DATA / "self_improvement_last_prompt.txt")}
