#!/usr/bin/env python3
"""Pick a reading for the current session.

Selects from marikai-brain/inputs/readings/ — prefers unread files,
falls back to least-recently-read. Prints the full text to stdout.

Usage:
    python3 deliver-reading.py
    python3 deliver-reading.py --list     # show all readings with read status
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

_BRAIN_DIR = Path(os.environ.get("MARIKAI_BRAIN_DIR",
                  Path(__file__).parent.parent.parent / "marikai-brain"))

READINGS_DIR = _BRAIN_DIR / "inputs" / "readings"
TRACKER_FILE = _BRAIN_DIR / "data" / "readings-tracker.json"


def load_tracker() -> dict:
    if TRACKER_FILE.exists():
        return json.loads(TRACKER_FILE.read_text())
    return {}


def save_tracker(tracker: dict) -> None:
    TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACKER_FILE.write_text(json.dumps(tracker, indent=2))


def get_readings() -> list[Path]:
    if not READINGS_DIR.exists():
        return []
    return sorted(READINGS_DIR.glob("*.md"))


def pick_reading(readings: list[Path], tracker: dict) -> Path | None:
    if not readings:
        return None
    # Prefer never-read files
    unread = [r for r in readings if r.name not in tracker]
    if unread:
        return unread[0]
    # Fall back to least recently read
    return min(readings, key=lambda r: tracker.get(r.name, ""))


def main() -> None:
    readings = get_readings()

    if "--list" in sys.argv:
        tracker = load_tracker()
        for r in readings:
            status = tracker.get(r.name, "unread")
            print(f"{'✔' if status != 'unread' else '·'} {r.name}  ({status})")
        return

    if not readings:
        print("(No readings available.)", file=sys.stderr)
        sys.exit(0)

    tracker = load_tracker()
    chosen = pick_reading(readings, tracker)
    if chosen is None:
        sys.exit(0)

    # Mark as read
    tracker[chosen.name] = datetime.now().isoformat(timespec="seconds")
    save_tracker(tracker)

    print(chosen.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
