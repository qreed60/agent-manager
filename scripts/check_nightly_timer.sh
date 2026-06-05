#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: scripts/check_nightly_timer.sh <project_id>" >&2
  exit 2
fi

PROJECT_ID="$1"
TIMER_NAME="agent-manager-nightly@${PROJECT_ID}.timer"
SERVICE_NAME="agent-manager-nightly@${PROJECT_ID}.service"

systemctl --user status "$TIMER_NAME" --no-pager
systemctl --user list-timers 'agent-manager-nightly@*.timer' --no-pager
journalctl --user -u "$SERVICE_NAME" -n 100 --no-pager
