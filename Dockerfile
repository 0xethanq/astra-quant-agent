# ==============================================================================
# AstraQuant - Multi-stage Production Dockerfile
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build Vue 3 Production Frontend
# ------------------------------------------------------------------------------
FROM node:24-slim AS frontend-builder

WORKDIR /build

ENV NODE_ENV=development

# 先安装依赖利用 Docker 缓存层
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --prefer-offline || npm install

# 复制前端源码并构建
COPY frontend/ ./
# 若 public/images 为外部软链接则解绑防范构建断链
RUN rm -rf public/images && mkdir -p public/images
# 落地页以 /images/dashboard_preview.png 引用该图（本地由软链接指向 docs/images），
# 解绑软链接后必须从构建上下文补回，否则 Vite 构建报 UNRESOLVED_IMPORT
COPY backend/docs/images/dashboard_preview.png ./public/images/dashboard_preview.png
RUN npm run build

# ------------------------------------------------------------------------------
# Stage 2: Python 3.11 Runtime Container
# ------------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

WORKDIR /app

# 安装必要的运行时工具与时区数据
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tzdata \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 设置环境变量：Python 输出直冲控制台、时区默认北京时间、PYTHONPATH 指向 backend/ 包根
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend \
    TZ=Asia/Shanghai

# 安装 Python 后端核心依赖
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 从 Stage 1 复制已编译好的静态资源（FastAPI 会自动在 frontend/dist 挂载）
COPY --from=frontend-builder /build/dist /app/frontend/dist

# 复制应用代码（2026-10：策略插件系统裁撤 ⇒ 不再拷贝 plugins/）
COPY backend/astra_backend/ /app/backend/astra_backend/
COPY backend/astra_gateway/ /app/backend/astra_gateway/
COPY backend/scripts/ /app/backend/scripts/
COPY backend/deploy/ /app/backend/deploy/
COPY backend/docs/ /app/backend/docs/
COPY backend/env.example /app/backend/env.example
COPY backend/data/prompt_library.json /app/backend/data/prompt_library.json

# 预先创建持久化数据目录
RUN mkdir -p /app/backend/data /app/backend/logs /app/backend/backups

# 入口脚本赋予可执行权限
RUN chmod +x /app/backend/deploy/docker-entrypoint.sh

# 暴露 FastAPI 控制面端口
EXPOSE 8080

ENTRYPOINT ["/app/backend/deploy/docker-entrypoint.sh"]
CMD ["backend"]
