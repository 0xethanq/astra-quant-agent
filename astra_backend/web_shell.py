"""Web 外壳：静态资源挂载与 SPA 壳渲染。

## 为什么有这个模块

`astra_backend/dashboard_cache.py` 原先**自己** `FastAPI()` 建了一个应用、自己挂静态目录、自己注册
`/`、`/doc`、`/login`、`/favicon.svg` 四条路由；而 `astra_backend/app.py` 又把这个
子应用 `mount("/", dashboard_app)` 挂到真正的应用上。于是线上是**双层路由**：
请求先过 8 个 router，再落进这个子应用。

阶段 1 已经拆掉了 15 条「被 router 遮蔽、永不命中」的重复注册；阶段的收尾（结构优化
阶段 2·B2 收尾）把剩下的**外壳本身**也搬出来，让 `astra_backend/dashboard_cache.py` 彻底降为纯库
（只提供 `get_all_data` / `get_overview` / `update_cache_cycle` 等实现，不再持有 app）。

## 边界

- 本模块只依赖 FastAPI/Starlette 与标准库，不 import `astra_backend.dashboard_cache`，
  也不被 `astra_backend.dashboard_cache` import（避免又把外壳绑回库文件）。
- 路径常量从本文件位置推导（`parents[1]` = 仓库根），不 import `astra_backend.dependencies`，
  以免与 config/settings 的导入链互相牵扯。
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

__all__ = [
    "WORKSPACE_DIR", "WEB_ROOT_DIR", "VUE_DIST_DIR", "VUE_ASSETS_DIR",
    "DOCS_IMAGES_DIR", "VUE_ADMIN_DIST_DIR", "VUE_ADMIN_LEGACY_FILE",
    "CachedStaticFiles", "templates", "serve_vue_spa", "mount_static_assets",
]

WORKSPACE_DIR = str(Path(__file__).resolve().parents[1])
# 第 143 刀：dashboard/ 目录并入本包（该常量原先指向仓库根的 dashboard/）
WEB_ROOT_DIR = str(Path(__file__).resolve().parent)
VUE_DIST_DIR = os.path.join(WORKSPACE_DIR, "frontend", "dist")
VUE_ASSETS_DIR = os.path.join(VUE_DIST_DIR, "assets")
VUE_COINS_DIR = os.path.join(VUE_DIST_DIR, "coins")
DOCS_IMAGES_DIR = os.path.join(WORKSPACE_DIR, "docs", "images")

VUE_ADMIN_DIST_DIR = VUE_DIST_DIR  # Same SPA build handles both / and /admin/*
VUE_ADMIN_LEGACY_FILE = os.path.join(VUE_DIST_DIR, "admin", "legacy.html")

templates = Jinja2Templates(directory=os.path.join(WEB_ROOT_DIR, "templates"))


class CachedStaticFiles(StaticFiles):
    """注入 Cloudflare/浏览器长缓存的静态文件处理器。"""

    def __init__(self, *args, cache_control: str = "public, max-age=31536000, immutable", **kwargs):
        self.cache_control = cache_control
        super().__init__(*args, **kwargs)

    def file_response(self, *args, **kwargs) -> Response:
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = self.cache_control
        return resp


def serve_vue_spa(html_path: str, is_public: bool = True) -> HTMLResponse:
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    # HTML 外壳严格不缓存（浏览器与边缘都不缓存），确保用户立刻拿到最新 Vite 包
    cache_header = "no-cache, no-store, must-revalidate, max-age=0"
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": cache_header,
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def mount_static_assets(app) -> None:
    """把静态目录挂到**真正的**应用对象上（原先挂在 dashboard 子应用里）。

    条件挂载与顺序逐条保留原样：`/static` 无条件；`/assets`、`/docs/images`、`/images`
    仅在目录存在时挂载（镜像/裸仓库里没有 dist 时不报错）。
    """
    app.mount("/static", StaticFiles(directory=os.path.join(WEB_ROOT_DIR, "static")), name="static")
    if os.path.isdir(VUE_ASSETS_DIR):
        app.mount(
            "/assets",
            CachedStaticFiles(directory=VUE_ASSETS_DIR, cache_control="public, max-age=31536000, immutable"),
            name="vue_assets",
        )
    if os.path.isdir(VUE_COINS_DIR):
        app.mount(
            "/coins",
            CachedStaticFiles(directory=VUE_COINS_DIR, cache_control="public, max-age=604800, stale-while-revalidate=86400"),
            name="vue_coins",
        )
    if os.path.isdir(DOCS_IMAGES_DIR):
        app.mount(
            "/docs/images",
            CachedStaticFiles(directory=DOCS_IMAGES_DIR, cache_control="public, max-age=604800, stale-while-revalidate=86400"),
            name="docs_images",
        )
        app.mount(
            "/images",
            CachedStaticFiles(directory=DOCS_IMAGES_DIR, cache_control="public, max-age=604800, stale-while-revalidate=86400"),
            name="images",
        )
