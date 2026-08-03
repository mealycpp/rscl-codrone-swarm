#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e .

LOGO_SOURCE="/mnt/c/Users/elhad/Downloads/RSCL_emblem_outer_background_transparent.png"
if [[ -f "$LOGO_SOURCE" ]]; then
    cp "$LOGO_SOURCE" assets/rscl_logo.png
    echo "Installed RSCL logo from $LOGO_SOURCE"
else
    echo "RSCL logo not found at $LOGO_SOURCE; keeping the included fallback."
fi

mkdir -p logs
printf '\nSimulation: python main.py --simulate\nLive:       python main.py --live\n'
