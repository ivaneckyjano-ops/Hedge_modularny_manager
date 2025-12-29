#!/usr/bin/env bash
# Runner for tws_hedge_finder.py
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
PY="$ROOT_DIR/venv/bin/python3"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ]; then
  echo "ERROR: No python3 found" >&2
  exit 2
fi
LOG="/tmp/tws_hedge_finder_runner.log"
echo "Running: $PY $ROOT_DIR/scripts/tws_hedge_finder.py $@" >> "$LOG"
"$PY" "$ROOT_DIR/scripts/tws_hedge_finder.py" "$@" >> "$LOG" 2>&1
EXIT=$?
echo "Exit: $EXIT" >> "$LOG"
exit $EXIT
