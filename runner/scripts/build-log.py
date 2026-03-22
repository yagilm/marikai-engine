#!/usr/bin/env python3
"""Build a combined session log from transcript Final Response sections.

Reads all *-transcript.md files from marikai-brain/logs/,
extracts the ## Final Response section from each,
and writes a single log.md sorted newest-first.

Duration is read from the transcript frontmatter (duration_s field) if present,
with fallback to sessions.jsonl for older transcripts that predate the field.

Usage:
    python3 build-log.py            # writes to marikai-brain/data/session-log.md
    python3 build-log.py --out /path/to/log.md
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

_BRAIN_DIR = Path(os.environ.get("MARIKAI_BRAIN_DIR",
                  Path(__file__).parent.parent.parent / "marikai-brain"))

LOGS_DIR = _BRAIN_DIR / "logs"
DEFAULT_OUT = _BRAIN_DIR / "data" / "session-log.md"


def format_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def load_sessions_index() -> dict[str, dict]:
    """Load sessions.jsonl keyed by session_id → {label, duration_s}."""
    sessions_path = LOGS_DIR / "sessions.jsonl"
    index: dict[str, dict] = {}
    if not sessions_path.exists():
        return index
    for line in sessions_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = entry.get("session_id", "")
        if sid:
            index[sid] = {
                "label": entry.get("session", ""),
                "duration_s": entry.get("duration_s"),
            }
    return index


def parse_transcript(path: Path) -> tuple[datetime | None, str, str, int | None, str]:
    """Return (datetime, final_response_text, duration_s, session_id, date_str)."""
    raw = path.read_text(encoding="utf-8")

    # Extract frontmatter fields
    dt: datetime | None = None
    session_id = ""
    duration_s: int | None = None

    date_match = re.search(r"^date:\s*(.+)$", raw, re.MULTILINE)
    if date_match:
        try:
            dt = datetime.fromisoformat(date_match.group(1).strip())
        except ValueError:
            pass

    sid_match = re.search(r"^session_id:\s*(.+)$", raw, re.MULTILINE)
    if sid_match:
        session_id = sid_match.group(1).strip()

    dur_match = re.search(r"^duration_s:\s*(\d+)$", raw, re.MULTILINE)
    if dur_match:
        duration_s = int(dur_match.group(1))

    # Fallback date from filename
    name = path.stem.replace("-transcript", "")
    parts = name.split("-")
    date_str = "-".join(parts[:3]) if len(parts) >= 3 else name

    if dt is None and len(parts) >= 3:
        try:
            dt = datetime.fromisoformat(date_str)
        except ValueError:
            pass

    # Extract Final Response section
    final = ""
    match = re.search(r"^##\s+Final Response\s*\n(.*)", raw, re.MULTILINE | re.DOTALL)
    if match:
        final = match.group(1).strip()

    return dt, final, duration_s, session_id, date_str


def build_log(out_path: Path) -> None:
    transcripts = sorted(LOGS_DIR.glob("*-transcript.md"))
    if not transcripts:
        print("No transcripts found.", file=sys.stderr)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "---\nlayout: page\ntitle: Log\npermalink: /log/\n---\n\n*No sessions yet.*\n",
            encoding="utf-8",
        )
        return

    sessions_index = load_sessions_index()

    entries: list[tuple[datetime, str, str, int | None]] = []
    for path in transcripts:
        dt, final, duration_s, session_id, date_str = parse_transcript(path)
        if not final:
            continue
        if dt is None:
            dt = datetime.fromtimestamp(path.stat().st_mtime)

        session_entry = sessions_index.get(session_id, {})
        if duration_s is None:
            duration_s = session_entry.get("duration_s")
        session_label = session_entry.get("label", "")

        time_str = dt.strftime("%H:%M")
        if session_label:
            label = f"{date_str} {time_str} — {session_label}"
        else:
            label = f"{date_str} {time_str}"

        entries.append((dt, label, final, duration_s))

    # Newest first
    entries.sort(key=lambda e: e[0], reverse=True)

    lines = [
        "---",
        "layout: page",
        "title: Log",
        "permalink: /log/",
        "render_with_liquid: false",
        "---",
        "",
    ]

    for i, (_, label, final, duration_s) in enumerate(entries):
        dur_str = f"  ·  {format_duration(duration_s)}" if duration_s else ""
        lines.append(f"### {label}{dur_str}")
        lines.append("")
        lines.append(final)
        if i < len(entries) - 1:
            lines.append("")
            lines.append("---")
            lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Log built: {len(entries)} entries → {out_path}", file=sys.stderr)


def main() -> None:
    out = DEFAULT_OUT
    args = sys.argv[1:]
    if "--out" in args:
        idx = args.index("--out")
        out = Path(args[idx + 1])

    build_log(out)


if __name__ == "__main__":
    main()
