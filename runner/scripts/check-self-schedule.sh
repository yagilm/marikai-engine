#!/usr/bin/env bash
# check-self-schedule.sh — Cron poller: fires self-scheduled wake sessions when due
#
# Usage:
#   ./runner/scripts/check-self-schedule.sh --mind nova   # poll for 'nova'
#   ./runner/scripts/check-self-schedule.sh               # uses config.local.env (legacy)
#
# Add to crontab via: ./runner/setup-cron.sh install --mind <name>
# Runs every 10 minutes, exits silently if nothing is due.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$RUNNER_DIR")"

# ─── Parse --mind ─────────────────────────────────────────────────────────────

MIND_NAME=""
_NEXT_IS_MIND=false
for _arg in "$@"; do
  if $_NEXT_IS_MIND; then
    MIND_NAME="$_arg"
    _NEXT_IS_MIND=false
    continue
  fi
  case "$_arg" in
    --mind)   _NEXT_IS_MIND=true ;;
    --mind=*) MIND_NAME="${_arg#--mind=}" ;;
  esac
done
unset _arg _NEXT_IS_MIND

# ─── Load config ──────────────────────────────────────────────────────────────

if [ -n "$MIND_NAME" ]; then
  CONFIG_FILE="$RUNNER_DIR/config.${MIND_NAME}.env"
  if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: No config found for mind '$MIND_NAME': $CONFIG_FILE" >&2
    exit 1
  fi
else
  CONFIG_FILE="$RUNNER_DIR/config.local.env"
  [ -f "$CONFIG_FILE" ] || CONFIG_FILE="$RUNNER_DIR/config.env"
fi

_EXT_NAME="${PROJECT_NAME:-}"
# shellcheck source=/dev/null
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"
PROJECT_NAME="${_EXT_NAME:-${PROJECT_NAME:-marikai}}"
BRAIN_DIR="$PROJECT_DIR/${PROJECT_NAME}-brain"

SCHEDULE_FILE="$BRAIN_DIR/data/self-schedule.json"
HISTORY_FILE="$BRAIN_DIR/data/self-schedule-history.jsonl"

# Exit if no schedule pending
[ -f "$SCHEDULE_FILE" ] || exit 0

# Don't fire if a session for this mind is already running
if pgrep -f "wake.sh --mind $PROJECT_NAME" > /dev/null 2>&1; then
  exit 0
fi

# Parse scheduled time
WAKE_AT=$(jq -r '.wake_at // empty' "$SCHEDULE_FILE" 2>/dev/null)
[ -z "$WAKE_AT" ] && exit 0

# Compare to current time
WAKE_EPOCH=$(date -d "$WAKE_AT" +%s 2>/dev/null) || exit 1
NOW_EPOCH=$(date +%s)
[ "$NOW_EPOCH" -lt "$WAKE_EPOCH" ] && exit 0

# Time to fire — record to history before running (prevents double-fire)
REASON=$(jq -r '.reason // ""' "$SCHEDULE_FILE" 2>/dev/null)
TODAY=$(date +%Y-%m-%d)
printf '{"date":"%s","wake_at":"%s","reason":"%s","fired_at":"%s"}\n' \
  "$TODAY" "$WAKE_AT" "$REASON" "$(date -Iseconds)" >> "$HISTORY_FILE"

rm -f "$SCHEDULE_FILE"

exec "$RUNNER_DIR/wake.sh" --mind "$PROJECT_NAME" self "$REASON"
