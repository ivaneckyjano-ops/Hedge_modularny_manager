#!/bin/bash
# Unregister tws:// URL scheme handler for current user.
# Usage: ./scripts/unregister_tws_scheme.sh

set -euo pipefail

DEST_DIR="$HOME/.local/share/applications"
DESKTOP_NAME="tws-handler.desktop"
DESKTOP_PATH="$DEST_DIR/$DESKTOP_NAME"

if [ -f "$DESKTOP_PATH" ]; then
    rm -f "$DESKTOP_PATH"
    update-desktop-database "$DEST_DIR" || true
    echo "Unregistered $DESKTOP_PATH"
else
    echo "No handler file found at $DESKTOP_PATH"
fi

echo "If your browser cached handler settings, you may need to restart it."
