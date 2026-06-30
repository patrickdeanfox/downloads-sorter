#!/usr/bin/env bash
# Install (or update) the downloads-sorter systemd --user service.
# Idempotent: safe to re-run after pulling changes.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Resolve to the real interpreter, not a pyenv/asdf shim — shims rely on shell
# environment that the minimal systemd --user session may not provide.
PYTHON="$(python3 -c 'import sys; print(sys.executable)')"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/downloads-sorter"
SERVICE="downloads-sorter.service"

echo "Repo   : $REPO"
echo "Python : $PYTHON"

# 1. Sanity-check the package imports before wiring up a service.
( cd "$REPO" && "$PYTHON" -c "import downloads_sorter; print('package OK', downloads_sorter.__version__)" )

# 2. Write a default config if the user has none yet.
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_DIR/config.toml" ]]; then
    ( cd "$REPO" && "$PYTHON" -m downloads_sorter --print-config ) > "$CONFIG_DIR/config.toml"
    echo "Wrote default config: $CONFIG_DIR/config.toml"
else
    echo "Keeping existing config: $CONFIG_DIR/config.toml"
fi

# 3. Render and install the unit file with absolute paths substituted in.
mkdir -p "$UNIT_DIR"
sed -e "s|@REPO@|$REPO|g" -e "s|@PYTHON@|$PYTHON|g" \
    "$REPO/packaging/$SERVICE.in" > "$UNIT_DIR/$SERVICE"
echo "Installed unit: $UNIT_DIR/$SERVICE"

# 4. (Optional) desktop launcher for the GUI.
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS_DIR"
sed -e "s|@REPO@|$REPO|g" -e "s|@PYTHON@|$PYTHON|g" \
    "$REPO/packaging/downloads-sorter.desktop.in" > "$APPS_DIR/downloads-sorter.desktop"
echo "Installed launcher: $APPS_DIR/downloads-sorter.desktop"

# 5. Reload, enable on login, and (re)start. Use restart (not enable --now) so
#    re-running the installer always picks up unit/config changes instead of
#    leaving a stale instance running.
systemctl --user daemon-reload
systemctl --user enable "$SERVICE"
systemctl --user restart "$SERVICE"
echo
echo "Service enabled and started. Check it with:"
echo "  systemctl --user status $SERVICE"
echo "  journalctl --user -u $SERVICE -f"
