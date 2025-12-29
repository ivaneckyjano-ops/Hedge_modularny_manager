#!/bin/bash
# Register tws:// URL scheme handler for current user.
# Usage: ./scripts/register_tws_scheme.sh

set -euo pipefail

DEST_DIR="$HOME/.local/share/applications"
mkdir -p "$DEST_DIR"

DESKTOP_NAME="tws-handler.desktop"
DESKTOP_PATH="$DEST_DIR/$DESKTOP_NAME"
LAUNCHER_PATH="$(pwd)/scripts/launch_tws.sh"

cat > "$DESKTOP_PATH" <<EOF
[Desktop Entry]
Name=TWS URL Handler
Exec=$LAUNCHER_PATH %u
Type=Application
Terminal=false
NoDisplay=true
MimeType=x-scheme-handler/tws;
EOF

# Update database and register handler
xdg-mime default "$DESKTOP_NAME" x-scheme-handler/tws || true
update-desktop-database "$DEST_DIR" || true

echo "Registered tws:// handler as $DESKTOP_PATH"
echo "Now clicking tws:// links in your browser should open TWS (if browser supports custom protocols)."
