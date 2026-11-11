#!/usr/bin/env bash
# setup-cron.sh — Install the scheduled session cron jobs for a mind
#
# Usage:
#   ./runner/setup-cron.sh install --mind nova               # Add cron jobs for 'nova'
#   ./runner/setup-cron.sh install --mind nova --no-publish  # No auto-publish
#   ./runner/setup-cron.sh remove  --mind nova               # Remove nova's cron jobs
#   ./runner/setup-cron.sh show                              # Show full current crontab
#
# Without --mind, falls back to config.local.env / config.env (backward compat).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WAKE_SCRIPT="$SCRIPT_DIR/wake.sh"
SELF_SCHED_SCRIPT="$SCRIPT_DIR/scripts/check-self-schedule.sh"

# ─── Parse flags ─────────────────────────────────────────────────────────────

ACTION="${1:-show}"
shift || true

MIND_NAME=""
AUTO_PUBLISH_FLAG="--publish"
_NEXT_IS_MIND=false

for arg in "$@"; do
  if $_NEXT_IS_MIND; then
    MIND_NAME="$arg"
    _NEXT_IS_MIND=false
    continue
  fi
  case "$arg" in
    --mind)     _NEXT_IS_MIND=true ;;
    --mind=*)   MIND_NAME="${arg#--mind=}" ;;
    --no-publish) AUTO_PUBLISH_FLAG="" ;;
  esac
done
unset arg _NEXT_IS_MIND

# ─── Load config ─────────────────────────────────────────────────────────────

if [ -n "$MIND_NAME" ]; then
  CONFIG_FILE="$SCRIPT_DIR/config.${MIND_NAME}.env"
  if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: No config found for mind '$MIND_NAME': $CONFIG_FILE"
    exit 1
  fi
else
  CONFIG_FILE="$SCRIPT_DIR/config.local.env"
  [ -f "$CONFIG_FILE" ] || CONFIG_FILE="$SCRIPT_DIR/config.env"
fi

_EXT_NAME="${PROJECT_NAME:-}"
# shellcheck source=/dev/null
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"
PROJECT_NAME="${_EXT_NAME:-${PROJECT_NAME:-}}"
if [ -z "$PROJECT_NAME" ]; then
  echo "ERROR: PROJECT_NAME is not set in $CONFIG_FILE." >&2
  echo "Set PROJECT_NAME to this mind's name (a single lowercase word)." >&2
  exit 1
fi

# Only named minds get an explicit --mind flag. The default mind loads
# config.local.env, so passing --mind <name> would look for a config file
# that does not exist.
if [ -n "$MIND_NAME" ]; then
  MIND_FLAG="--mind $MIND_NAME"
else
  MIND_FLAG=""
fi

# ─── Ensure scripts are executable ───────────────────────────────────────────

[ -x "$WAKE_SCRIPT" ]      || chmod +x "$WAKE_SCRIPT"
[ -x "$SELF_SCHED_SCRIPT" ] || chmod +x "$SELF_SCHED_SCRIPT"

# ─── Helpers ─────────────────────────────────────────────────────────────────

# Print the current crontab with only this mind's jobs removed.
# Default-mind jobs have no --mind flag, while named-mind jobs do.
filter_crontab() {
  awk -v wake="$WAKE_SCRIPT" -v self="$SELF_SCHED_SCRIPT" -v mind="$MIND_NAME" '
    {
      if (index($0, wake) == 0 && index($0, self) == 0) { print; next }
      if (mind != "") {
        if (match($0, "--mind[= ]" mind "([ \t]|$)")) next
        print; next
      }
      if (index($0, "--mind ") == 0 && index($0, "--mind=") == 0) next
      print
    }'
}

# ─── Actions ─────────────────────────────────────────────────────────────────

case "$ACTION" in
  install)
    echo "Installing cron schedule for $PROJECT_NAME${AUTO_PUBLISH_FLAG:+ (auto-publish enabled)}..."

    LOG="$SCRIPT_DIR/../${PROJECT_NAME}-brain/logs/cron.log"

    # Remove any existing cron jobs for this mind before re-adding
    crontab -l 2>/dev/null | filter_crontab | crontab - 2>/dev/null || true

    (crontab -l 2>/dev/null; cat <<EOF
# $PROJECT_NAME — scheduled sessions
0  7  * * * $WAKE_SCRIPT $MIND_FLAG morning   $AUTO_PUBLISH_FLAG >> $LOG 2>&1
0  13 * * * $WAKE_SCRIPT $MIND_FLAG afternoon $AUTO_PUBLISH_FLAG >> $LOG 2>&1
0  19 * * * $WAKE_SCRIPT $MIND_FLAG evening   $AUTO_PUBLISH_FLAG >> $LOG 2>&1
0  23 * * * $WAKE_SCRIPT $MIND_FLAG night     $AUTO_PUBLISH_FLAG >> $LOG 2>&1
# $PROJECT_NAME — self-schedule poller
*/10 * * * * $SELF_SCHED_SCRIPT $MIND_FLAG    >> $LOG 2>&1
EOF
    ) | crontab -

    echo "Cron schedule installed:"
    crontab -l | grep "$PROJECT_NAME"
    echo ""
    echo "To check logs: tail -f ${PROJECT_NAME}-brain/logs/cron.log"
    ;;

  remove)
    echo "Removing $PROJECT_NAME cron jobs..."
    crontab -l 2>/dev/null | filter_crontab | crontab - 2>/dev/null || true
    echo "Done."
    ;;

  show)
    echo "Current crontab:"
    crontab -l 2>/dev/null || echo "(no crontab)"
    ;;

  *)
    echo "Usage: $0 [install|remove|show] [--mind <name>] [--no-publish]"
    exit 1
    ;;
esac
