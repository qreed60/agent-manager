#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: scripts/install_nightly_timer.sh [--run-now] <project_id>" >&2
}

RUN_NOW=0
if [[ "${1:-}" == "--run-now" ]]; then
  RUN_NOW=1
  shift
fi

if [[ $# -ne 1 ]]; then
  usage
  exit 2
fi

PROJECT_ID="$1"
ROOT_DIR="/home/qreed/agent-manager"
PYTHON="$ROOT_DIR/.venv/bin/python"
RUNNER="$ROOT_DIR/scripts/run_nightly_window.py"
USER_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
TIMER_NAME="agent-manager-nightly@${PROJECT_ID}.timer"
SERVICE_NAME="agent-manager-nightly@${PROJECT_ID}.service"

if [[ ! -f "$RUNNER" ]]; then
  echo "Missing nightly runner: $RUNNER" >&2
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing executable venv python: $PYTHON" >&2
  exit 1
fi

mkdir -p "$USER_UNIT_DIR"
cp "$ROOT_DIR/systemd/agent-manager-nightly@.service" "$USER_UNIT_DIR/"
cp "$ROOT_DIR/systemd/agent-manager-nightly@.timer" "$USER_UNIT_DIR/"

systemctl --user daemon-reload
systemctl --user enable "$TIMER_NAME"

if [[ "$RUN_NOW" -eq 1 ]]; then
  systemctl --user start "$SERVICE_NAME"
else
  echo "Timer enabled. No immediate nightly run was started."
fi

echo "Check timer status:"
echo "  systemctl --user status $TIMER_NAME"
echo "List timers:"
echo "  systemctl --user list-timers 'agent-manager-nightly@*.timer'"
echo "Check recent logs:"
echo "  journalctl --user -u $SERVICE_NAME -n 100 --no-pager"
echo "Run once now, explicitly:"
echo "  scripts/install_nightly_timer.sh --run-now $PROJECT_ID"
