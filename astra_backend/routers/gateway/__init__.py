"""gateway 域路由的**聚合入口**。

`routers/gateway.py`（977 行 / 34 路由）按资源拆成子模块，本文件只做**按原顺序**聚合：

    channels → gateway_ops → notifications → backups

顺序 = 拆分前文件内的出现顺序（FastAPI 按注册顺序匹配；对拍门逐条比对路由表）。
`from astra_backend.routers.gateway import router` 照旧可用；34 条 URL、方法、
处理器名与 tags 一字未改。子路由各自带 `tags=["gateway"]`，本聚合器**不再加 tags**。
"""
from __future__ import annotations

from fastapi import APIRouter

from astra_backend.routers.gateway import backups, channels, gateway_ops, notifications

router = APIRouter()

for _sub in (channels, gateway_ops, notifications, backups):
    router.include_router(_sub.router)

__all__ = ["router"]
