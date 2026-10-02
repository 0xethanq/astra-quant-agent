#!/usr/bin/env bash
# ==============================================================================
# AstraQuant - Quick Start Script
# ==============================================================================

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "🚀 [AstraQuant] Initializing system environment..."

# 1. 解释器自适应：专用 venv 优先，回退系统 python3
#    （与 scripts/astra_watchdog.sh 同一范式，2026-09-30 统一）
#
#    ⚠️ 旧实现硬要求 PATH 里有 `python3`，没有就 "python3 is not installed" 退出。
#    但本仓**刻意不依赖全局 Python**（AGENTS.md：所有 Python 命令走 .venv），
#    实测在只有 .venv、没有全局 python3 的机器上，`./start.sh` 会**直接起不来**，
#    而它给出的报错还是错的（解释器明明就在 .venv 里）—— 用户看到的是
#    "依赖装好了却启动不了"，且被指向去装一个本不需要的全局 Python。
#
#    注意本脚本下面三处（迁移检查 / 建标的池 / 起服务）此前都写死 `python3`，
#    同一文件里却有一处已经用了 .venv ⇒ 本身就是不一致的。
PY="${PYTHON_BIN:-}"
if [ -z "$PY" ]; then
    for cand in "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/.venv/bin/python3"; do
        [ -x "$cand" ] && { PY="$cand"; break; }
    done
fi
[ -n "$PY" ] || PY="$(command -v python3 2>/dev/null || true)"
if [ -z "$PY" ] || [ ! -x "$PY" ]; then
    echo "❌ Error: 找不到 Python 解释器（既无 .venv/bin/python，PATH 里也没有 python3）。"
    echo "   请先执行：./deploy/install.sh   —— 它会创建 .venv 并装好依赖。"
    exit 1
fi
echo "🐍 使用解释器: $PY"

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
    "$PY" "$ROOT_DIR/scripts/migrate_r20_to_astra.py" --check || {
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
    "$PY" -c "from scripts.instrument_pool import save_instruments, DEFAULT_INSTRUMENTS; save_instruments(DEFAULT_INSTRUMENTS)" 2>/dev/null || true
fi

# 4. Check Node.js and build frontend if dist doesn't exist or if src was updated
NEED_BUILD=0
if [ ! -d "frontend/dist" ] || [ ! -f "frontend/dist/index.html" ]; then
    NEED_BUILD=1
elif [ -d "frontend/src" ] && [ "frontend/src" -nt "frontend/dist/index.html" ]; then
    NEED_BUILD=1
fi

if [ "$NEED_BUILD" = "1" ]; then
    echo "📦 Frontend production bundle needs build/update. Building Vue 3 SPA..."
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
exec "$PY" -m uvicorn astra_backend.app:app --host 0.0.0.0 --port 8080
