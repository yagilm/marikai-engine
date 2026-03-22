#!/usr/bin/env bash
# setup-cron.sh — Install the scheduled session cron jobs
#
# Usage:
#   ./runner/setup-cron.sh install    # Add cron jobs
#   ./runner/setup-cron.sh remove     # Remove cron jobs
#   ./runner/setup-cron.sh show       # Show current crontab

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WAKE_SCRIPT="$SCRIPT_DIR/wake.sh"
SELF_SCHED_SCRIPT="$SCRIPT_DIR/scripts/check-self-schedule.sh"

CONFIG_FILE="$SCRIPT_DIR/config.local.env"
[ -f "$CONFIG_FILE" ] || CONFIG_FILE="$SCRIPT_DIR/config.env"
_EXT_NAME="${PROJECT_NAME:-}"
# shellcheck source=/dev/null
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"
PROJECT_NAME="${_EXT_NAME:-${PROJECT_NAME:-marikai}}"

if [ ! -x "$WAKE_SCRIPT" ]; then
  echo "Making wake.sh executable..."
  chmod +x "$WAKE_SCRIPT"
fi
if [ ! -x "$SELF_SCHED_SCRIPT" ]; then
  chmod +x "$SELF_SCHED_SCRIPT"
fi

ACTION="${1:-show}"

case "$ACTION" in
  install)
    echo "Installing cron schedule for $PROJECT_NAME..."

    LOG="$SCRIPT_DIR/../${PROJECT_NAME}-brain/logs/cron.log"

    # Remove any existing cron jobs for this project
    crontab -l 2>/dev/null | grep -v "$WAKE_SCRIPT" | grep -v "$SELF_SCHED_SCRIPT" | crontab - 2>/dev/null || true

    # Add sessions (4x daily) + self-schedule poller (every 10 min)
    (crontab -l 2>/dev/null; cat <<EOF
# $PROJECT_NAME — scheduled sessions
0  7  * * * $WAKE_SCRIPT morning   >> $LOG 2>&1
0  13 * * * $WAKE_SCRIPT afternoon >> $LOG 2>&1
0  19 * * * $WAKE_SCRIPT evening   >> $LOG 2>&1
0  23 * * * $WAKE_SCRIPT night     >> $LOG 2>&1
# $PROJECT_NAME — self-schedule poller
*/10 * * * * $SELF_SCHED_SCRIPT    >> $LOG 2>&1
EOF
    ) | crontab -

    echo "Cron schedule installed:"
    crontab -l | grep "$WAKE_SCRIPT\|$SELF_SCHED_SCRIPT"
    echo ""
    echo "To check logs: tail -f ${PROJECT_NAME}-brain/logs/cron.log"
    ;;

  remove)
    echo "Removing $PROJECT_NAME cron jobs..."
    crontab -l 2>/dev/null | grep -v "$WAKE_SCRIPT" | grep -v "$SELF_SCHED_SCRIPT" | crontab - 2>/dev/null || true
    echo "Done."
    ;;

  show)
    echo "Current crontab:"
    crontab -l 2>/dev/null || echo "(no crontab)"
    ;;

  *)
    echo "Usage: $0 [install|remove|show]"
    exit 1
    ;;
esac
