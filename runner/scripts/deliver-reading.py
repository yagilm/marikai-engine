#!/usr/bin/env python3
"""Pick a reading for the current session.

Selects from two pools:
  1. File readings: marikai-brain/inputs/readings/*.md
  2. URL readings:  marikai-brain/inputs/readings-urls.md

Preference order:
  - Unread items (file or URL) come first
  - Among unread, files are tried before URLs (more reliable, no network needed)
  - When everything has been read at least once, picks the least-read URL
    or the least-recently-read file

Prints the full text to stdout. The wake prompt includes it as a reading.

Usage:
    python3 deliver-reading.py
    python3 deliver-reading.py --list     # show all readings with read status
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

_BRAIN_DIR = Path(os.environ.get("MARIKAI_BRAIN_DIR",
                  Path(__file__).parent.parent.parent / "marikai-brain"))

READINGS_DIR = _BRAIN_DIR / "inputs" / "readings"
READINGS_URLS_FILE = _BRAIN_DIR / "inputs" / "readings-urls.md"
TRACKER_FILE = _BRAIN_DIR / "data" / "readings-tracker.json"

URL_MAX_CHARS = 6000


# ─── File readings ────────────────────────────────────────────────────────────

def load_tracker() -> dict:
    if TRACKER_FILE.exists():
        return json.loads(TRACKER_FILE.read_text(encoding="utf-8"))
    return {}


def save_tracker(tracker: dict) -> None:
    TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACKER_FILE.write_text(json.dumps(tracker, indent=2), encoding="utf-8")


def get_file_readings() -> list[Path]:
    if not READINGS_DIR.exists():
        return []
    return sorted(READINGS_DIR.glob("*.md"))


def pick_file_reading(readings: list[Path], tracker: dict) -> Path | None:
    if not readings:
        return None
    unread = [r for r in readings if r.name not in tracker]
    if unread:
        return unread[0]
    return None  # all read — handled by caller


def least_recently_read_file(readings: list[Path], tracker: dict) -> Path | None:
    if not readings:
        return None
    return min(readings, key=lambda r: tracker.get(r.name, ""))


# ─── URL readings ─────────────────────────────────────────────────────────────

def parse_readings_urls() -> list[dict]:
    """Parse readings-urls.md into a list of entries with read_count."""
    if not READINGS_URLS_FILE.exists():
        return []
    entries = []
    for line in READINGS_URLS_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        read_count = 0
        url = None
        note = ""

        if stripped.startswith("- "):
            rest = stripped[2:].strip()
            url_part, _, note_raw = rest.partition("<!--")
            url = url_part.strip()
            note = note_raw.rstrip("->").strip() if note_raw else ""
            read_count = 0

        elif stripped.startswith("✔"):
            rest = stripped[1:].strip()
            url_part, _, note_raw = rest.partition("<!--")
            url = url_part.strip()
            if note_raw:
                note_content = note_raw.rstrip("->").strip()
                m = re.search(r"read:\s*(\d+)", note_content)
                read_count = int(m.group(1)) if m else 1
                note = re.sub(r"\s*[—–-]+\s*read:\s*\d+", "", note_content).strip()

        if url and url.startswith("http"):
            entries.append({
                "url": url,
                "note": note,
                "read_count": read_count,
            })
    return entries


def mark_url_read(url: str, note: str, current_count: int) -> None:
    """Update readings-urls.md: change - to ✔ and increment read count."""
    if not READINGS_URLS_FILE.exists():
        return
    new_count = current_count + 1
    suffix = f" — read: {new_count}" if note else f"read: {new_count}"
    note_part = f"{note}{suffix}" if note else suffix
    new_line = f"✔ {url}  <!-- {note_part} -->"

    lines = READINGS_URLS_FILE.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if url in line:
            lines[i] = new_line
            break
    READINGS_URLS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fetch_url(url: str) -> str:
    """Fetch a URL and return clean readable text (stdlib only)."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Marikai/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        raw = resp.read().decode("utf-8", errors="replace")

    # Remove non-content blocks
    raw = re.sub(
        r"<(script|style|head|nav|footer|header)[^>]*>.*?</\1>",
        " ", raw, flags=re.DOTALL | re.IGNORECASE,
    )
    # Strip all tags
    text = re.sub(r"<[^>]+>", " ", raw)
    # Decode HTML entities
    text = html.unescape(text)
    # Normalise whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:URL_MAX_CHARS]


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    file_readings = get_file_readings()
    url_readings = parse_readings_urls()
    tracker = load_tracker()

    if "--list" in sys.argv:
        print("── File readings ──")
        for r in file_readings:
            status = tracker.get(r.name, "unread")
            print(f"  {'✔' if status != 'unread' else '·'} {r.name}  ({status})")
        print("── URL readings ──")
        for e in url_readings:
            mark = "✔" if e["read_count"] > 0 else "·"
            count = f"read: {e['read_count']}" if e["read_count"] > 0 else "unread"
            label = f"{e['note']}  " if e["note"] else ""
            print(f"  {mark} {label}{e['url']}  ({count})")
        return

    # 1. Prefer unread file readings
    chosen_file = pick_file_reading(file_readings, tracker)
    if chosen_file:
        tracker[chosen_file.name] = datetime.now().isoformat(timespec="seconds")
        save_tracker(tracker)
        print(chosen_file.read_text(encoding="utf-8"))
        return

    # 2. Prefer unread URL readings
    unread_urls = [e for e in url_readings if e["read_count"] == 0]
    if unread_urls:
        entry = unread_urls[0]
        try:
            text = fetch_url(entry["url"])
        except Exception as exc:
            print(f"(Could not fetch {entry['url']}: {exc})", file=sys.stderr)
            # Fall through to file fallback below
        else:
            mark_url_read(entry["url"], entry["note"], 0)
            header = f"**Source:** {entry['note'] + '  ' if entry['note'] else ''}<{entry['url']}>\n\n"
            print(header + text)
            return

    # 3. All read — pick least-recently-read file, or least-read URL
    if file_readings:
        chosen_file = least_recently_read_file(file_readings, tracker)
        if chosen_file:
            tracker[chosen_file.name] = datetime.now().isoformat(timespec="seconds")
            save_tracker(tracker)
            print(chosen_file.read_text(encoding="utf-8"))
            return

    if url_readings:
        entry = min(url_readings, key=lambda e: e["read_count"])
        try:
            text = fetch_url(entry["url"])
        except Exception as exc:
            print(f"(Could not fetch {entry['url']}: {exc})", file=sys.stderr)
            sys.exit(0)
        mark_url_read(entry["url"], entry["note"], entry["read_count"])
        header = f"**Source:** {entry['note'] + '  ' if entry['note'] else ''}<{entry['url']}>\n\n"
        print(header + text)
        return

    print("(No readings available.)", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
