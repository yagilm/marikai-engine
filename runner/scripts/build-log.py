#!/usr/bin/env python3
"""Build a combined session log from transcript Final Response sections.

Reads all *-transcript.md files from marikai-brain/logs/,
extracts the ## Final Response section from each,
and writes a single log.md sorted newest-first.

Usage:
    python3 build-log.py            # writes to marikai-brain/data/session-log.md
    python3 build-log.py --out /path/to/log.md
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

_BRAIN_DIR = Path(os.environ.get("MARIKAI_BRAIN_DIR",
                  Path(__file__).parent.parent.parent / "marikai-brain"))

LOGS_DIR = _BRAIN_DIR / "logs"
DEFAULT_OUT = _BRAIN_DIR / "data" / "session-log.md"


def parse_transcript(path: Path) -> tuple[datetime | None, str, str]:
    """Return (datetime, session_label, final_response_text)."""
    raw = path.read_text(encoding="utf-8")

    # Extract date from frontmatter
    dt: datetime | None = None
    date_match = re.search(r"^date:\s*(.+)$", raw, re.MULTILINE)
    if date_match:
        try:
            dt = datetime.fromisoformat(date_match.group(1).strip())
        except ValueError:
            pass

    # Fall back to filename date: 2026-03-21-midnight-transcript.md
    if dt is None:
        name = path.stem.replace("-transcript", "")
        parts = name.split("-")
        if len(parts) >= 3:
            try:
                dt = datetime.fromisoformat("-".join(parts[:3]))
            except ValueError:
                pass

    # Session label from filename
    name = path.stem.replace("-transcript", "")
    parts = name.split("-")
    session = parts[3] if len(parts) > 3 else "session"
    date_str = "-".join(parts[:3]) if len(parts) >= 3 else name

    # Extract Final Response section
    final = ""
    match = re.search(r"^##\s+Final Response\s*\n(.*)", raw, re.MULTILINE | re.DOTALL)
    if match:
        final = match.group(1).strip()

    label = f"{date_str} — {session}"
    return dt, label, final


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

    entries: list[tuple[datetime, str, str]] = []
    for path in transcripts:
        dt, label, final = parse_transcript(path)
        if not final:
            continue
        if dt is None:
            dt = datetime.fromtimestamp(path.stat().st_mtime)
        entries.append((dt, label, final))

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

    for i, (_, label, final) in enumerate(entries):
        lines.append(f"### {label}")
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
