"""仪表盘载荷装配包。

`astra_backend/dashboard_cache.py` 的 `update_cache_cycle`（拆分前 1021 行）按数据域逐步迁出到这里。
迁移是**渐进**的：本包只承载已迁出的部分，`astra_backend/dashboard_cache.py` 仍是权威实现，
直到全部迁完。

约束：
- 只依赖标准库与 `astra_backend` 下不反向依赖 `astra_backend.dashboard_cache` 的模块；
- 每个域一个纯函数（入参显式、返回 dict 片段），不带隐藏全局状态。
"""
from __future__ import annotations

from astra_backend.dashboard_payload.readers import read_json, read_text, read_text_lines

__all__ = ["read_json", "read_text", "read_text_lines"]
