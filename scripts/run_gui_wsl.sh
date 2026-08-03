#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate

export QT_QUICK_BACKEND=software
export QSG_RENDER_LOOP=basic

exec python main.py "$@"
