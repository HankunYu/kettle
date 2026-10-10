#!/usr/bin/env bash
# Install/refresh the systemd user units for kettle.
# Unit templates use @KETTLE_DIR@ / @PYTHON@ placeholders, filled in here.
set -euo pipefail
cd "$(dirname "$0")"

KETTLE_DIR="$(pwd -P)"
PYTHON="$(command -v python3)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
for unit in kettle.service kettle.timer kettle-web.service; do
    sed -e "s|@KETTLE_DIR@|$KETTLE_DIR|g" -e "s|@PYTHON@|$PYTHON|g" "systemd/$unit" > "$UNIT_DIR/$unit"
done
systemctl --user daemon-reload
systemctl --user enable --now kettle.timer
systemctl --user enable kettle-web.service
systemctl --user restart kettle-web.service
systemctl --user list-timers kettle.timer --no-pager
systemctl --user status kettle-web.service --no-pager --lines=3
