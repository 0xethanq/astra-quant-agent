#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON_BIN="$ROOT/.venv/bin/python"

if [ ! -f "$PYTHON_BIN" ]; then
    echo "Python 虚拟环境未就绪，正在安装基础依赖..."
    sh "$ROOT/deploy/install.sh"
fi

"$PYTHON_BIN" "$ROOT/scripts/setup_wizard.py" "$@"
