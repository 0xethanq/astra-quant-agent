#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_DIR="$ROOT/backend"
PYTHON_BIN="$APP_DIR/.venv/bin/python"

if [ ! -f "$PYTHON_BIN" ]; then
    echo "Python 虚拟环境未就绪，正在安装基础依赖..."
    sh "$APP_DIR/deploy/install.sh"
fi

"$PYTHON_BIN" "$APP_DIR/scripts/setup_wizard.py" "$@"
