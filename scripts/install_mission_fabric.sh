#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-$HOME/rscl-codrone-swarm}"
SOURCE="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$TARGET/backup_before_v051_$STAMP"

if [[ ! -d "$TARGET" ]]; then
  echo "ERROR: Target repository does not exist: $TARGET" >&2
  exit 1
fi

mkdir -p "$BACKUP"
for item in main.py pyproject.toml web src/rscl_codrone_swarm; do
  if [[ -e "$TARGET/$item" ]]; then
    mkdir -p "$BACKUP/$(dirname "$item")"
    cp -a "$TARGET/$item" "$BACKUP/$item"
  fi
done

LOGO_TMP=""
if [[ -f "$TARGET/assets/rscl_logo.png" ]]; then
  LOGO_TMP="$(mktemp)"
  cp "$TARGET/assets/rscl_logo.png" "$LOGO_TMP"
fi

mkdir -p "$TARGET/src/rscl_codrone_swarm" "$TARGET/web" "$TARGET/assets" "$TARGET/logs" "$TARGET/scripts"
cp -a "$SOURCE/main.py" "$TARGET/main.py"
cp -a "$SOURCE/pyproject.toml" "$TARGET/pyproject.toml"
cp -a "$SOURCE/src/rscl_codrone_swarm/." "$TARGET/src/rscl_codrone_swarm/"
cp -a "$SOURCE/web/." "$TARGET/web/"
cp -a "$SOURCE/scripts/." "$TARGET/scripts/"

if [[ -n "$LOGO_TMP" ]]; then
  cp "$LOGO_TMP" "$TARGET/assets/rscl_logo.png"
  rm -f "$LOGO_TMP"
elif [[ -f "/mnt/c/Users/elhad/Downloads/RSCL_emblem_outer_background_transparent.png" ]]; then
  cp "/mnt/c/Users/elhad/Downloads/RSCL_emblem_outer_background_transparent.png" "$TARGET/assets/rscl_logo.png"
elif [[ -f "$SOURCE/assets/rscl_logo.png" ]]; then
  cp "$SOURCE/assets/rscl_logo.png" "$TARGET/assets/rscl_logo.png"
fi

touch "$TARGET/logs/.gitkeep"
chmod +x "$TARGET/scripts/"*.sh

cd "$TARGET"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
python -m py_compile src/rscl_codrone_swarm/web_app.py
if command -v node >/dev/null 2>&1; then
  node --check web/app.js
fi

echo
echo "RSCL Physical LED + Advanced Mission Fabric v0.5.1 installed."
echo "Backup: $BACKUP"
echo
echo "Simulation (three virtual drones):"
echo "  cd $TARGET && source .venv/bin/activate && python main.py --simulate"
echo
echo "Live hardware:"
echo "  cd $TARGET && source .venv/bin/activate && python main.py --live"
