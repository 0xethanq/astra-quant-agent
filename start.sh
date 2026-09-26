#!/usr/bin/env bash
# ==============================================================================
# AstraQuant - Quick Start Script
# ==============================================================================

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "🚀 [AstraQuant] Initializing system environment..."

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is not installed."
    exit 1
fi

# 2. Check or create .env
if [ ! -f .env ]; then
    if [ -f env.example ]; then
        echo "📝 Creating .env from env.example..."
        cp env.example .env
    else
        echo "⚠️ Warning: env.example not found, please configure .env manually."
    fi
fi

# 3. Create required runtime directories
mkdir -p data logs backups

# ---------------------------------------------------------------------------
# 2.5 改名前置检查（fail-closed）：`r20` → `astra` 的运行态数据是否已迁移。
#
# 2026-09-27 把内部代号全量改名。**配置契约是硬切**（旧的 `R20_*` 不再被读取），
# 但运行态数据不能硬切：库名/凭证库/锁/心跳还叫 `r20_*` 时直接启动，
# 系统会"认不出自己的台账与凭证"—— 表现为**空的持仓台账 + 三所全部 NOT READY**，
# 而且不报错、只是安静地用新库跑起来。这是最难排查的一类事故。
#
# 故在此 fail-closed：检测到未迁移就停在这里，并把该敲的命令原样打出来。
# 退出码 3 = 检测到遗留；0 = 无需迁移；其它 = 检查本身出问题（同样停下）。
# 全新安装与已迁移实例都返回 0，不受影响。
# ---------------------------------------------------------------------------
if [ -f "$ROOT_DIR/scripts/migrate_r20_to_astra.py" ]; then
    python3 "$ROOT_DIR/scripts/migrate_r20_to_astra.py" --check || {
        rc=$?
        if [ "$rc" != "0" ]; then
            echo "❌ [Entrypoint] 启动前检查未通过（退出码 $rc）：拒绝在未迁移的数据上启动。" >&2
            exit 1
        fi
    }
fi


# 3.1 Initialize default instrument pool if not present (prevents untrusted pool blocking entry)
if [ ! -f "data/instrument_pool.json" ]; then
    echo "📋 Initializing default instrument pool..."
    if [ -x ".venv/bin/python" ]; then
        .venv/bin/python -c "from scripts.instrument_pool import save_instruments, DEFAULT_INSTRUMENTS; save_instruments(DEFAULT_INSTRUMENTS)" 2>/dev/null || true
    fi
fi

# 4. Check Node.js and build frontend if dist doesn't exist
if [ ! -d "frontend/dist" ]; then
    echo "📦 Frontend production bundle not detected. Building Vue 3 SPA..."
    if command -v npm &> /dev/null; then
        cd frontend
        npm install
        npm run build
        cd "$ROOT_DIR"
    else
        echo "⚠️ Warning: npm is not installed. Please build frontend manually via 'cd frontend && npm install && npm run build'."
    fi
fi

# 5. Start Backend Engine
echo "✨ Launching AstraQuant on http://0.0.0.0:8080 ..."
exec python3 -m uvicorn astra_backend.app:app --host 0.0.0.0 --port 8080
