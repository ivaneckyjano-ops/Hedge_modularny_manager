#!/usr/bin/env bash
# Runner for tws_option_search.py - ensures correct venv python is used
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
PY="$ROOT_DIR/venv/bin/python3"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ]; then
  echo "ERROR: No python3 found (expected $ROOT_DIR/venv/bin/python3)" >&2
  exit 2
fi
# log file for debugging
LOG="/tmp/tws_option_search_runner.log"
echo "Running: $PY $ROOT_DIR/scripts/tws_option_search.py $@" >> "$LOG"
"$PY" "$ROOT_DIR/scripts/tws_option_search.py" "$@" >> "$LOG" 2>&1
EXIT=$?
echo "Exit: $EXIT" >> "$LOG"
exit $EXIT
