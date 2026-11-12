#!/usr/bin/env python3
"""Backfill a ``time: "HH:MM"`` field into essays, creatives and letters.

Times are recovered from three sources, in order:

1. ``logs/sessions.jsonl`` — the earliest session whose ``files_written`` list
   contains the file. Its ``t`` timestamp gives an approximate writing time.
2. The file's modification time, but only when its local date matches the
   document's front-matter date (``date`` for essays/creatives, ``written_on``
   for letters). Files touched later by unrelated edits are ignored.
3. The file's birth time, when the platform exposes one and its date matches.
   This recovers items whose modification time was changed by a later edit.

Documents whose time cannot be established are left untouched, and existing
``time:`` values are never overwritten.

Usage:
    python3 backfill-times.py --dry-run
    python3 backfill-times.py
    python3 backfill-times.py --brain /path/to/brain --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

try:  # Same directory when run as a script.
    from mind import brain_dir
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mind import brain_dir

COLLECTIONS = (("essays", "date"), ("creatives", "date"), ("letters", "written_on"))
TIME_LINE_RE = re.compile(r"^time\s*:")
VALUE_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s*:\s*(?P<value>.*?)\s*$")


def _front_matter(text: str) -> tuple[list[str], int] | None:
    """Return ``(lines, closing_index)`` for a valid leading front-matter block."""
    clean = text.lstrip("\ufeff")
    lines = clean.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    closing = next(
        (i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing is None:
        return None
    return lines, closing


def _value(lines: list[str], closing: int, key: str) -> str:
    for line in lines[1:closing]:
        match = VALUE_RE.match(line)
        if match and match.group("key") == key:
            return match.group("value").strip().strip("\"'")
    return ""


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _session_times(log_file: Path) -> dict[str, datetime]:
    """Map ``collection/filename`` to the earliest session timestamp."""
    index: dict[str, list[datetime]] = {}
    if not log_file.is_file():
        return {}

    for lineno, line in enumerate(log_file.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            print(f"warning: {log_file}:{lineno}: skipping invalid JSON", file=sys.stderr)
            continue
        raw_time = row.get("t")
        if not raw_time:
            continue
        try:
            timestamp = datetime.fromisoformat(raw_time)
        except ValueError:
            continue
        for written in row.get("files_written") or []:
            parts = str(written).replace("\\", "/").split("/")
            for collection, _ in COLLECTIONS:
                if collection not in parts:
                    continue
                start = parts.index(collection)
                key = "/".join(parts[start:])
                index.setdefault(key, []).append(timestamp)
                break

    return {key: min(values) for key, values in index.items()}


def _birth_time(path: Path) -> datetime | None:
    """Return the file's birth time when the platform exposes one."""
    try:
        result = subprocess.run(
            ["stat", "-c", "%W", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        epoch = int(result.stdout.strip())
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None
    if epoch <= 0:
        return None
    return datetime.fromtimestamp(epoch)


def _insert_time(text: str, lines: list[str], closing: int, value: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    updated = list(lines)
    updated.insert(closing, f'time: "{value}"')
    result = newline.join(updated)
    if text.endswith(("\n", "\r")):
        result += newline
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add a time: \"HH:MM\" field to essays, creatives and letters"
    )
    parser.add_argument(
        "--brain",
        default=None,
        help="Brain directory (default: resolved from PROJECT_NAME/BRAIN_DIR)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would change without writing files",
    )
    args = parser.parse_args()

    root = Path(args.brain).expanduser() if args.brain else brain_dir()
    if not root.is_dir():
        print(f"ERROR: brain directory not found: {root}", file=sys.stderr)
        return 1

    sessions = _session_times(root / "logs" / "sessions.jsonl")

    added = 0
    already = 0
    skipped = 0

    for collection, date_key in COLLECTIONS:
        folder = root / collection
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="replace")
            parsed = _front_matter(text)
            if parsed is None:
                print(f"skip (no front matter): {path.relative_to(root)}")
                skipped += 1
                continue
            lines, closing = parsed
            if any(TIME_LINE_RE.match(line) for line in lines[1:closing]):
                already += 1
                continue

            item_date = _parse_date(_value(lines, closing, date_key))
            if item_date is None:
                print(f"skip (no usable {date_key}:): {path.relative_to(root)}")
                skipped += 1
                continue

            key = f"{collection}/{path.name}"
            stamp = sessions.get(key)
            source = "session log"
            if stamp is None:
                modified = datetime.fromtimestamp(path.stat().st_mtime)
                if modified.date() == item_date:
                    stamp = modified
                    source = "mtime"
                else:
                    born = _birth_time(path)
                    if born is not None and born.date() == item_date:
                        stamp = born
                        source = "birth time"
            if stamp is None:
                print(f"skip (no matching time): {path.relative_to(root)}")
                skipped += 1
                continue

            value = stamp.strftime("%H:%M")
            print(
                f"{'[dry-run] ' if args.dry_run else ''}"
                f"{path.relative_to(root)}  time: \"{value}\"  ({source})"
            )
            if not args.dry_run:
                path.write_text(
                    _insert_time(text, lines, closing, value), encoding="utf-8"
                )
            added += 1

    verb = "would add" if args.dry_run else "added"
    print(
        f"\ntime backfill: {verb} {added}, already present {already}, skipped {skipped}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
