#!/usr/bin/env bash
# Remove the systemd --user service and desktop launcher. Leaves your config,
# move history, and any already-sorted files untouched.
set -euo pipefail

SERVICE="downloads-sorter.service"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

systemctl --user disable --now "$SERVICE" 2>/dev/null || true
rm -f "$UNIT_DIR/$SERVICE" "$APPS_DIR/downloads-sorter.desktop"
systemctl --user daemon-reload
echo "Removed service and launcher. Config and history kept at:"
echo "  ${XDG_CONFIG_HOME:-$HOME/.config}/downloads-sorter/"
echo "  ${XDG_STATE_HOME:-$HOME/.local/state}/downloads-sorter/"
