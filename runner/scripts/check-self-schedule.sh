#!/usr/bin/env bash
# check-self-schedule.sh — Cron poller: fires self-scheduled wake sessions when due
#
# Add to crontab via: ./runner/setup-cron.sh install
# Runs every 10 minutes, exits silently if nothing is due.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$RUNNER_DIR")"
BRAIN_DIR="$PROJECT_DIR/marikai-brain"

SCHEDULE_FILE="$BRAIN_DIR/data/self-schedule.json"
HISTORY_FILE="$BRAIN_DIR/data/self-schedule-history.jsonl"

# Exit if no schedule pending
[ -f "$SCHEDULE_FILE" ] || exit 0

# Don't fire if a session is already running
if pgrep -f "wake.sh" > /dev/null 2>&1; then
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

exec "$RUNNER_DIR/wake.sh" self "$REASON"
