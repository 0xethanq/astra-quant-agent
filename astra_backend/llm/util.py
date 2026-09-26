"""仪表盘/LLM 通用小工具：原子写与密钥打码。

结构优化阶段 2（B4）从 astra_backend/llm_manager.py 迁出，
llm_manager 保留同名重导出以维持既有导入路径。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from astra_backend.redact import mask as _redact_mask


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def mask_secret(value: str, visible: int = 4) -> str:
    """凭证脱敏 —— **转发到单一事实源** `astra_backend.redact.mask`。

    结构优化阶段 4·B3 第四十九刀：与 `astra_backend.settings_store.mask`
    原先各有一份逐字节相同的实现，现已收敛。

    ⚠️ 名字**必须**保留在 `astra_backend/llm/util.py` 并继续被
    `llm_manager` 再导出：`tests/test_llm_seam_discipline.py` 的公开面清单里
    钉着 `"mask_secret"`（它按门面导出名断言）。
    """
    return _redact_mask(value, visible)
