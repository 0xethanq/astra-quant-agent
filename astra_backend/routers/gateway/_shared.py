"""gateway 域路由的共享助手（拆包时从 `routers/gateway.py` 原样搬出）。

`_get_root()` 通过 `app_attr("ROOT", ROOT)` 取根 —— 这是既有的**注入缝**
（`app_attr` 读 `sys.modules["astra_backend.app"]` 上的属性），拆包不影响该语义。
"""
from __future__ import annotations

from pathlib import Path

from astra_backend.dependencies import ROOT, app_attr


def _get_root() -> Path:
    return Path(app_attr("ROOT", ROOT))
