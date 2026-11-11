#!/usr/bin/env python3
"""Track reads of URLs listed in ``inputs/urls.md``.

The queue is a Markdown list. Unread entries start with ``-``; read entries
start with ``✔``. Each read entry records how many times the URL was read, the
last read time, and the full read history:

    - https://example.com/article  <!-- why it is here -->
    ✔ https://example.com/article  <!-- why it is here — read: 2 — last: 2026-11-11T22:05:00+02:00 — history: 2026-03-22T13:35:00+02:00, 2026-11-11T22:05:00+02:00 -->

``web_read.py`` calls :func:`record_attempt` for every fetch. Successful reads
mark the URL in ``inputs/urls.md``; failed attempts are written to
``logs/web.log`` as JSON lines and leave the URL unread so it can be retried.

The CLI is mainly for inspection and manual repairs:

    url-tracker.py --list
    url-tracker.py --count-unread
    url-tracker.py --mark-read URL
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

READ_MARKERS = ("✔", "✓")
_META_RE = re.compile(
    r"^read:\s*(?P<count>\d+)"
    r"(?:\s+—\s+last:\s*(?P<last>\S+))?"
    r"(?:\s+—\s+history:\s*(?P<history>.*))?$"
)


def brain_dir() -> Path:
    """Return the brain directory, honouring ``BRAIN_DIR``."""
    configured = os.environ.get("BRAIN_DIR")
    if configured:
        return Path(configured)
    project_name = os.environ.get("PROJECT_NAME", "marikai")
    return Path(__file__).resolve().parent.parent.parent / f"{project_name}-brain"


def urls_file() -> Path:
    return brain_dir() / "inputs" / "urls.md"


def log_file() -> Path:
    return brain_dir() / "logs" / "web.log"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_line(line: str) -> dict | None:
    """Parse one URL entry. Return ``None`` for non-entry lines."""
    stripped = line.strip()
    if not stripped:
        return None

    is_read = False
    if stripped.startswith("- "):
        rest = stripped[2:].strip()
    elif stripped.startswith(READ_MARKERS):
        is_read = True
        rest = stripped[1:].strip()
    else:
        return None

    url_part, marker, comment = rest.partition("<!--")
    url = url_part.strip()
    if not url.startswith(("http://", "https://")):
        return None

    comment = comment.rsplit("-->", 1)[0].strip() if marker else ""

    # The metadata is appended after the optional human note. Split on the
    # last " — read: " so a note that happens to contain the word "read" is
    # preserved.
    note = comment
    meta = ""
    if " — read: " in comment:
        note, meta_tail = comment.rsplit(" — read: ", 1)
        meta = "read: " + meta_tail
    elif comment.startswith("read: "):
        note = ""
        meta = comment

    count = 1 if is_read else 0
    last = ""
    history: list[str] = []
    if meta:
        match = _META_RE.match(meta)
        if match:
            count = int(match.group("count"))
            last = match.group("last") or ""
            history = [item.strip() for item in (match.group("history") or "").split(",")
                       if item.strip()]

    return {
        "url": url,
        "note": note.strip(),
        "read": is_read,
        "count": count,
        "last": last,
        "history": history,
    }


def _iter_entry_lines(lines: list[str]):
    """Yield ``(index, line)`` for lines outside fenced blocks and HTML comments.

    Documentation examples in ``urls.md`` must never be mistaken for queue
    entries, or reading a real URL could update the example line instead.
    """
    in_fence = False
    in_comment = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if in_fence:
            if stripped.startswith(("```", "~~~")):
                in_fence = False
            continue
        if stripped.startswith(("```", "~~~")):
            in_fence = True
            continue
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue
        yield index, line


def entries() -> list[dict]:
    path = urls_file()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    result = []
    for _, line in _iter_entry_lines(lines):
        parsed = parse_line(line)
        if parsed:
            result.append(parsed)
    return result


def unread_count() -> int:
    return sum(1 for entry in entries() if not entry["read"])


def _format_line(entry: dict) -> str:
    parts = [f"read: {entry['count']}"]
    if entry["last"]:
        parts.append(f"last: {entry['last']}")
    if entry["history"]:
        parts.append(f"history: {', '.join(entry['history'])}")
    meta = " — ".join(parts)
    comment = f"{entry['note']} — {meta}" if entry["note"] else meta
    return f"✔ {entry['url']}  <!-- {comment} -->"


def mark_read(url: str, when: str | None = None) -> bool:
    """Mark ``url`` read, increment its count and append the read time."""
    path = urls_file()
    if not path.exists():
        return False

    timestamp = when or _now()
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in _iter_entry_lines(lines):
        entry = parse_line(line)
        if not entry or entry["url"] != url:
            continue
        was_read = entry["read"]
        entry["read"] = True
        entry["count"] = entry["count"] + 1 if was_read else max(entry["count"], 1)
        entry["last"] = timestamp
        entry["history"] = [*entry["history"], timestamp]
        lines[index] = _format_line(entry)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    return False


def log_attempt(url: str, success: bool, error: str = "") -> None:
    """Append one fetch attempt to ``logs/web.log``."""
    path = log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, object] = {
        "timestamp": _now(),
        "url": url,
        "success": success,
    }
    if error:
        record["error"] = error
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        sys.stderr.write(f"Log write failed: {exc}\n")


def record_attempt(url: str, success: bool, error: str = "") -> None:
    """Log a fetch attempt; on success also mark the URL read."""
    log_attempt(url, success, error)
    if success:
        mark_read(url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect or update inputs/urls.md")
    parser.add_argument("--list", action="store_true", help="list every URL and its read state")
    parser.add_argument("--count-unread", action="store_true", help="print the number of unread URLs")
    parser.add_argument("--mark-read", metavar="URL", help="mark URL as read now")
    args = parser.parse_args()

    if args.count_unread:
        print(unread_count())
        return

    if args.mark_read:
        if mark_read(args.mark_read):
            print(f"Marked read: {args.mark_read}")
        else:
            sys.stderr.write(f"URL not found in {urls_file()}: {args.mark_read}\n")
            sys.exit(1)
        return

    if args.list:
        for entry in entries():
            status = f"read: {entry['count']}" if entry["read"] else "unread"
            last = f"  last: {entry['last']}" if entry["last"] else ""
            note = f"  ({entry['note']})" if entry["note"] else ""
            print(f"{entry['url']}  [{status}]{last}{note}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
