#!/usr/bin/env python3
"""Self-scheduling for Marikai.

Schedule extra wake sessions outside the 4 cron slots.

Usage:
    python3 self-schedule.py --at 14:30 --reason "finish the essay"
    python3 self-schedule.py --in 2h --reason "check on something"
    python3 self-schedule.py --in 30m --reason "short check"
    python3 self-schedule.py --cancel
    python3 self-schedule.py --status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

_BRAIN_DIR = Path(os.environ.get("BRAIN_DIR", Path(__file__).parent.parent.parent / (os.environ.get("PROJECT_NAME", "marikai") + "-brain")))
SCHEDULE_FILE = _BRAIN_DIR / "data" / "self-schedule.json"
HISTORY_FILE = _BRAIN_DIR / "data" / "self-schedule-history.jsonl"

DAILY_CAP = 3
BUFFER_MINUTES = 30

# Must match the cron schedule in setup-cron.sh
CRON_HOURS = (7, 13, 19, 23)
CRON_SESSION_NAMES: dict[int, str] = {
    7: "morning",
    13: "afternoon",
    19: "evening",
    23: "night",
}

log = logging.getLogger(__name__)


def now_local() -> datetime:
    """Current local time."""
    return datetime.now().astimezone()


def check_cron_collision(wake_at: datetime) -> str | None:
    """Return an error message if wake_at falls within BUFFER_MINUTES of a cron slot."""
    wake_minutes = wake_at.hour * 60 + wake_at.minute
    for hour in CRON_HOURS:
        cron_minutes = hour * 60
        diff = abs(wake_minutes - cron_minutes)
        diff = min(diff, 1440 - diff)
        if diff < BUFFER_MINUTES:
            name = CRON_SESSION_NAMES[hour]
            return (
                f"Too close to the {name} session ({hour:02d}:00). "
                f"Need at least {BUFFER_MINUTES} min buffer."
            )
    return None


def count_sessions_on_date(target_date: str) -> int:
    """Count self-scheduled sessions that already fired on the given date."""
    if not HISTORY_FILE.exists():
        return 0
    count = 0
    for line in HISTORY_FILE.read_text(encoding="utf-8").strip().split("\n"):
        if not line:
            continue
        try:
            if json.loads(line).get("date") == target_date:
                count += 1
        except json.JSONDecodeError:
            continue
    return count


def read_pending() -> dict[str, str] | None:
    """Read the pending schedule file, if any."""
    if not SCHEDULE_FILE.exists():
        return None
    try:
        data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def parse_duration(value: str) -> timedelta | None:
    """Parse a duration string like '2h', '30m', '1h30m'."""
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", value)
    if not match or (not match.group(1) and not match.group(2)):
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return timedelta(hours=hours, minutes=minutes) if hours or minutes else None


def parse_time(value: str) -> datetime | None:
    """Parse HH:MM and return a local datetime for today or tomorrow if already past."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    current = now_local()
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return target


def cmd_schedule(wake_at: datetime, reason: str) -> int:
    """Validate and write a self-scheduled session."""
    current = now_local()
    if wake_at <= current:
        log.error("Cannot schedule in the past: %s", wake_at.strftime("%H:%M"))
        return 1

    collision = check_cron_collision(wake_at)
    if collision:
        log.error("%s", collision)
        return 1

    target_date = wake_at.date().isoformat()
    fired = count_sessions_on_date(target_date)
    pending = read_pending()
    pending_same_day = 1 if (pending and pending.get("wake_at", "")[:10] == target_date) else 0

    if fired + pending_same_day >= DAILY_CAP:
        log.error("Daily cap reached for %s (%d/%d)", target_date, fired + pending_same_day, DAILY_CAP)
        return 1

    if pending:
        sys.stdout.write(f"Replacing existing schedule ({pending.get('wake_at', '?')[:16]})\n")

    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(
        json.dumps({
            "wake_at": wake_at.isoformat(),
            "reason": reason,
            "created_at": current.isoformat(),
        }, indent=2) + "\n",
        encoding="utf-8",
    )

    sys.stdout.write(f"Scheduled: {wake_at.strftime('%H:%M on %A, %d %B')}\n")
    sys.stdout.write(f"Reason: {reason}\n")
    remaining = DAILY_CAP - fired - pending_same_day - 1
    if remaining > 0:
        sys.stdout.write(f"Remaining slots today: {remaining}\n")
    return 0


def cmd_cancel() -> int:
    """Cancel the pending schedule."""
    pending = read_pending()
    if not pending:
        sys.stdout.write("Nothing scheduled.\n")
        return 0
    SCHEDULE_FILE.unlink(missing_ok=True)
    sys.stdout.write(f"Cancelled: {pending.get('wake_at', '?')[:16]}\n")
    sys.stdout.write(f"Reason was: {pending.get('reason', '?')}\n")
    return 0


def cmd_status() -> int:
    """Show current schedule status."""
    current = now_local()
    today = current.date().isoformat()
    fired = count_sessions_on_date(today)
    pending = read_pending()

    sys.stdout.write(f"Self-scheduled sessions today: {fired}/{DAILY_CAP}\n")
    if pending:
        sys.stdout.write(f"Pending: {pending.get('wake_at', '?')[:16]}\n")
        sys.stdout.write(f"Reason: {pending.get('reason', '?')}\n")
    else:
        sys.stdout.write("No session currently scheduled.\n")

    remaining = DAILY_CAP - fired - (1 if pending and pending.get("wake_at", "")[:10] == today else 0)
    if remaining > 0:
        sys.stdout.write(f"Remaining slots today: {remaining}\n")
    return 0


def main() -> int:
    """Entry point."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Schedule an extra Marikai wake session outside the 4 cron slots."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--at", metavar="HH:MM", help="Schedule at a specific time (local)")
    group.add_argument("--in", metavar="DURATION", dest="in_duration",
                       help="Schedule relative to now (e.g. 2h, 30m, 1h30m)")
    group.add_argument("--cancel", action="store_true", help="Cancel the pending schedule")
    group.add_argument("--status", action="store_true", help="Show schedule status")
    parser.add_argument("--reason", help="Why (required for --at / --in)")

    args = parser.parse_args()

    if args.cancel:
        return cmd_cancel()
    if args.status:
        return cmd_status()

    if not args.reason:
        log.error("--reason is required when scheduling.")
        return 1

    if args.at:
        wake_at = parse_time(args.at)
        if wake_at is None:
            log.error("Invalid time: %s — use HH:MM (24-hour)", args.at)
            return 1
    else:
        duration = parse_duration(args.in_duration)
        if duration is None:
            log.error("Invalid duration: %s — use e.g. 2h, 30m, 1h30m", args.in_duration)
            return 1
        wake_at = now_local() + duration

    return cmd_schedule(wake_at, args.reason)


if __name__ == "__main__":
    sys.exit(main())
