#!/usr/bin/env python3
"""Rotate the session's input focus so every input kind is eventually visited.

The mind may read several inputs per session, but it chooses freely and can
ignore whole kinds for a long time. This module keeps one kind in focus until
the session actually engages with it, then advances to the next kind. Over
sessions the focus cycles through:

    articles -> books -> urls -> sayings -> concepts -> keeper_prompts -> notes

Kinds with no available material are skipped. Readings are not part of the
rotation: one is delivered automatically every session, so that kind is
already covered.

Usage:
    input_rotation.py --begin              # select/increment focus, print kind
    input_rotation.py --section            # print the wake-prompt section
    input_rotation.py --check STREAM.jsonl # advance focus if the session engaged
    input_rotation.py --status             # show rotation state and availability
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:  # Same directory when run as a script.
    from url_tracker import entries as url_entries
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from url_tracker import entries as url_entries

FOCUS_ORDER = [
    "articles",
    "books",
    "urls",
    "sayings",
    "concepts",
    "keeper_prompts",
    "notes",
]

LABELS = {
    "articles": "articles",
    "books": "book parts",
    "urls": "URLs",
    "sayings": "sayings",
    "concepts": "concepts",
    "keeper_prompts": "keeper prompts",
    "notes": "keeper notes",
}

# Substrings that prove the session touched a kind. They are matched against
# every tool call's serialised input (file paths, Bash commands, URLs, ...).
MARKERS = {
    "articles": ("inputs/articles",),
    "books": ("inputs/books",),
    "urls": ("inputs/urls.md", "web_read.py", "url_tracker.py"),
    "sayings": ("inputs/sayings.md",),
    "concepts": ("inputs/concepts.md",),
    "keeper_prompts": ("inputs/keeper-prompts.md",),
    "notes": ("inputs/note.md",),
}


def brain_dir() -> Path:
    configured = os.environ.get("BRAIN_DIR")
    if configured:
        return Path(configured)
    project_name = os.environ.get("PROJECT_NAME", "marikai")
    return Path(__file__).resolve().parent.parent.parent / f"{project_name}-brain"


def state_file() -> Path:
    return brain_dir() / "data" / "input-rotation.json"


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_state() -> dict:
    path = state_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("focus", None)
    data.setdefault("sessions_on_focus", 0)
    data.setdefault("started_on", None)
    data.setdefault("last_engaged", {})
    data.setdefault("next_index", 0)
    return data


def save_state(state: dict) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


# ─── Input inventories ───────────────────────────────────────────────────────

def _files(directory: Path, *, parts_only: bool = False) -> list[Path]:
    if not directory.is_dir():
        return []
    files = [
        path for path in sorted(directory.iterdir())
        if path.is_file() and path.name != ".gitkeep"
    ]
    if parts_only:
        files = [path for path in files if "-part-" in path.name]
    return files


def _read_tracker() -> dict:
    path = brain_dir() / "data" / "read-tracker.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _article_stats() -> dict:
    files = _files(brain_dir() / "inputs" / "articles")
    tracked = _read_tracker().get("articles", {})
    unread = [
        path for path in files
        if f"inputs/articles/{path.name}" not in tracked
    ]
    return {"total": len(files), "unread": len(unread), "available": bool(files)}


def _book_stats() -> dict:
    files = _files(brain_dir() / "inputs" / "books", parts_only=True)
    tracked = _read_tracker().get("books", {})
    unread = [
        path for path in files
        if f"inputs/books/{path.name}" not in tracked
    ]
    next_part = unread[0].name if unread else ""
    return {
        "total": len(files),
        "unread": len(unread),
        "next": next_part,
        "available": bool(files),
    }


def _url_stats() -> dict:
    try:
        entries = url_entries()
    except Exception:
        entries = []
    unread = sum(1 for entry in entries if not entry.get("read"))
    return {"total": len(entries), "unread": unread, "available": bool(entries)}


def _text_stats(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"total": 0, "unread": 0, "revisit": 0, "available": False}
    times = [int(value) for value in re.findall(r"times_read:\s*(\d+)", text, re.I)]
    revisits = re.findall(r"revisit:\s*(yes|no)", text, re.I)
    return {
        "total": len(times),
        "unread": sum(1 for value in times if value == 0),
        "revisit": sum(1 for value in revisits if value.lower() == "yes"),
        "available": bool(times),
    }


def _prompt_stats() -> dict:
    path = brain_dir() / "inputs" / "keeper-prompts.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"total": 0, "unanswered": 0, "available": False}
    total = len(re.findall(r"^###\s+\[", text, re.MULTILINE))
    unanswered = len(re.findall(r"\*\*answered:\*\*\s*no", text, re.I))
    return {
        "total": total,
        "unanswered": unanswered,
        "available": unanswered > 0,
    }


def _note_stats() -> dict:
    path = brain_dir() / "inputs" / "note.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"total": 0, "pending": 0, "available": False}
    pending = sum(1 for line in text.splitlines() if line.startswith("- "))
    return {"total": pending, "pending": pending, "available": pending > 0}


def stats(kind: str) -> dict:
    if kind == "articles":
        return _article_stats()
    if kind == "books":
        return _book_stats()
    if kind == "urls":
        return _url_stats()
    if kind == "sayings":
        return _text_stats(brain_dir() / "inputs" / "sayings.md")
    if kind == "concepts":
        return _text_stats(brain_dir() / "inputs" / "concepts.md")
    if kind == "keeper_prompts":
        return _prompt_stats()
    if kind == "notes":
        return _note_stats()
    return {"available": False}


def _available(kind: str) -> bool:
    return bool(stats(kind).get("available"))


def _next_kind(after: str | None) -> str | None:
    """Return the next available kind after ``after``, cycling around."""
    start = 0
    if after in FOCUS_ORDER:
        start = FOCUS_ORDER.index(after) + 1
    for offset in range(len(FOCUS_ORDER)):
        kind = FOCUS_ORDER[(start + offset) % len(FOCUS_ORDER)]
        if _available(kind):
            return kind
    return None


# ─── Engagement detection ────────────────────────────────────────────────────

def _stream_inputs(stream_path: Path):
    """Yield the serialised input of every tool call in a stream-json file."""
    try:
        lines = stream_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                yield json.dumps(block.get("input") or {}, ensure_ascii=False)


def engaged(stream_path: Path, kind: str) -> bool:
    markers = MARKERS.get(kind, ())
    if not markers:
        return False
    for payload in _stream_inputs(stream_path):
        if any(marker in payload for marker in markers):
            return True
    return False


# ─── Commands ────────────────────────────────────────────────────────────────

def _detail(kind: str) -> str:
    data = stats(kind)
    if kind == "articles":
        return (
            f"{data['total']} article file(s), {data['unread']} unread. "
            "Use pdf_read.py for PDFs."
        )
    if kind == "books":
        if data["unread"]:
            return (
                f"Next unread part: `{data['next']}` "
                f"({data['unread']} unread of {data['total']})."
            )
        return f"All {data['total']} part(s) have been read; revisit one if you like."
    if kind == "urls":
        return (
            f"{data['unread']} unread URL(s) in `inputs/urls.md` "
            f"({data['total']} total). Read one with web_read.py."
        )
    if kind in ("sayings", "concepts"):
        return (
            f"{data['unread']} unread, {data['revisit']} marked revisit "
            f"({data['total']} total)."
        )
    if kind == "keeper_prompts":
        return f"{data['unanswered']} unanswered prompt(s) of {data['total']}."
    if kind == "notes":
        return f"{data['pending']} pending note(s)."
    return ""


def section(state: dict) -> str:
    kind = state.get("focus")
    if not kind or not _available(kind):
        return (
            "## This Session's Input Focus\n\n"
            "All input kinds are currently empty or complete. Read anything you like."
        )

    label = LABELS[kind]
    attempts = int(state.get("sessions_on_focus") or 0)
    lines = [
        "## This Session's Input Focus",
        "",
        "Your inputs rotate so every kind is eventually visited. "
        f"This session's focus is **{label}**:",
        "",
        f"- {_detail(kind)}",
        "",
        f"Engage with at least one item from {label} before you finish. "
        "After that, the rest of the session is still yours.",
    ]
    if attempts > 1:
        lines.append("")
        lines.append(
            f"This focus has been waiting for {attempts} sessions. "
            "Make it the first input you open today."
        )
    return "\n".join(lines)


def begin() -> None:
    state = load_state()
    kind = state.get("focus")
    if not kind or not _available(kind):
        kind = _next_kind(kind)
    state["focus"] = kind
    if kind:
        state["sessions_on_focus"] = int(state.get("sessions_on_focus") or 0) + 1
        if not state.get("started_on"):
            state["started_on"] = _today()
        state["last_begun"] = _now()
    save_state(state)
    if kind:
        print(kind)


def check(stream_path: Path) -> None:
    state = load_state()
    kind = state.get("focus")
    if not kind:
        print("No input focus is active.")
        return

    if engaged(stream_path, kind):
        state.setdefault("last_engaged", {})[kind] = _today()
        next_kind = _next_kind(kind)
        state["focus"] = next_kind
        state["sessions_on_focus"] = 0
        state["started_on"] = None
        save_state(state)
        print(f"Input focus '{kind}' engaged; next focus: {next_kind or '(none)'}.")
    else:
        save_state(state)
        print(f"Input focus '{kind}' not engaged; it stays for the next session.")


def status() -> None:
    state = load_state()
    print(f"focus: {state.get('focus') or '(none)'}")
    print(f"sessions on focus: {state.get('sessions_on_focus') or 0}")
    print(f"started on: {state.get('started_on') or '(none)'}")
    print("availability:")
    for kind in FOCUS_ORDER:
        data = stats(kind)
        mark = "●" if kind == state.get("focus") else " "
        print(f"  {mark} {kind}: {json.dumps(data, sort_keys=True)}")
    last = state.get("last_engaged") or {}
    if last:
        print("last engaged:")
        for kind in FOCUS_ORDER:
            if last.get(kind):
                print(f"  {kind}: {last[kind]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--begin", action="store_true", help="select focus, print its kind")
    group.add_argument("--section", action="store_true", help="print the wake-prompt section")
    group.add_argument("--check", metavar="STREAM", help="advance focus if the stream engaged it")
    group.add_argument("--status", action="store_true", help="show rotation state")
    args = parser.parse_args()

    if args.begin:
        begin()
    elif args.section:
        print(section(load_state()))
    elif args.check:
        check(Path(args.check))
    elif args.status:
        status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
