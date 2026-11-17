#!/usr/bin/env bash
set -e

# ==============================================================================
# AstraQuant - Docker One-click Launcher
# ==============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# 目录收敛后本脚本位于 backend/deploy/，ROOT_DIR=backend/；compose 文件仍在仓库根。
REPO_ROOT="$(cd "$ROOT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "🐳 [ASTRA Docker Launcher] Pre-flight checks..."

# 1. 确保运行时挂载目录存在
mkdir -p "$ROOT_DIR/data" "$ROOT_DIR/logs" "$ROOT_DIR/backups"

# 2. 检查 .env 配置文件（防范 docker mount 把 .env 误当作目录创建）
if [ -d "$ROOT_DIR/.env" ]; then
    echo "⚠️ Warning: .env was found as a directory. Correcting..."
    rm -rf "$ROOT_DIR/.env"
fi

if [ ! -f "$ROOT_DIR/.env" ]; then
    if [ -f "$ROOT_DIR/env.example" ]; then
        echo "📝 Creating initial .env from env.example..."
        cp "$ROOT_DIR/env.example" "$ROOT_DIR/.env"
        chmod 600 "$ROOT_DIR/.env"
        echo "⚠️ Note: Default .env created. Please configure your API keys if needed."
    else
        echo "❌ Error: Neither .env nor env.example found."
        exit 1
    fi
else
    chmod 600 "$ROOT_DIR/.env"
fi

# 2.5 双容器调度所有权：backend 必须关闭内置网关看护，否则它会在自己的 PID
#     命名空间里拉起 worker，独立 gateway 容器看不到该进程 ⇒ 健康检查永远失败、
#     每 60s 重试并争抢同一个 flock。`.env` 是应用配置 SSOT（会覆盖 compose 的
#     environment），故这里直接保证 .env 中的取值。
if grep -q '^ASTRA_STANDALONE_GATEWAY=' "$ROOT_DIR/.env"; then
    if sed --version >/dev/null 2>&1; then
        sed -i 's/^ASTRA_STANDALONE_GATEWAY=.*/ASTRA_STANDALONE_GATEWAY=true/' "$ROOT_DIR/.env"
    else
        sed -i '' 's/^ASTRA_STANDALONE_GATEWAY=.*/ASTRA_STANDALONE_GATEWAY=true/' "$ROOT_DIR/.env"
    fi
else
    printf '\nASTRA_STANDALONE_GATEWAY=true\n' >> "$ROOT_DIR/.env"
fi

# 3. 检查 Docker 与 Docker Compose 命令
if command -v docker &> /dev/null && docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo "❌ Error: Neither 'docker compose' nor 'docker-compose' is installed."
    echo "Please install Docker and Docker Compose plugin first."
    exit 1
fi

echo "🚀 Building and starting AstraQuant stack..."
$COMPOSE_CMD up -d --build

echo "✅ ASTRA Docker Stack successfully launched!"
echo "--------------------------------------------------------"
echo "🖥️  Web Dashboard:  http://localhost:8080"
echo "⚙️  Admin Console:  http://localhost:8080/admin/login"
echo "📜 View Logs:      $COMPOSE_CMD logs -f"
echo "🛑 Stop Stack:     $COMPOSE_CMD down"
echo "--------------------------------------------------------"
