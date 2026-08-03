#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
PORTS=(/dev/ttyACM* /dev/ttyUSB*)
if [[ ! -e "${PORTS[0]}" ]]; then
    echo "No /dev/ttyACM* or /dev/ttyUSB* controllers found." >&2
    exit 1
fi
sudo chmod a+rw /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || true
exec python main.py --live "$@"
