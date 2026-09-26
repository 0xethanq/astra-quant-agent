"""策略域路由的**聚合入口**（B8 结构整理）。

`routers/strategy.py`（775 行 / 35 端点）按资源拆成子模块，本文件只做**按原顺序**聚合：

    council → interceptors → policy → prompts

## 为什么顺序必须保留

子路由内存在前缀包含关系（如 `/admin/interceptors/{filename}` 与
`/admin/interceptors/reorder`）—— FastAPI 按注册顺序匹配，**顺序变了就换处理器**。
聚合顺序 = 拆分前文件内的出现顺序；对拍门逐条比对路由表。

## 兼容性

`from astra_backend.routers.strategy import router` **照旧可用**（本包同名导出）；
35 条 URL、HTTP 方法、处理器名与 tags 一字未改。

## 本包 tags 的归属

子路由各自 `APIRouter(tags=["strategy"])`，本聚合器**不再加 tags**
（两处都加会得到 `["strategy","strategy"]` —— 首版即踩，OpenAPI 指纹当场抓到）。
"""
from __future__ import annotations

from fastapi import APIRouter

from astra_backend.routers.strategy import council, interceptors, policy, prompts

router = APIRouter()

for _sub in (council, interceptors, policy, prompts):
    router.include_router(_sub.router)

__all__ = ["router"]
