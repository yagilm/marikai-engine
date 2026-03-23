#!/usr/bin/env python3
"""Live display for Marikai sessions.

Reads stream-json from stdin, writes raw lines to the stream file,
and pretty-prints a human-readable view to the terminal in real time.
Optionally appends plain-text output to a log file.

Usage:
    claude ... --output-format stream-json | python3 live-display.py <stream-file> [log-file]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── ANSI colours (gracefully disabled if not a tty) ──────────────────────────

_IS_TTY = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _IS_TTY else text

def dim(t: str) -> str:    return _c("2", t)
def bold(t: str) -> str:   return _c("1", t)
def cyan(t: str) -> str:   return _c("36", t)
def green(t: str) -> str:  return _c("32", t)
def yellow(t: str) -> str: return _c("33", t)
def grey(t: str) -> str:   return _c("90", t)


# ── Tool input summary ────────────────────────────────────────────────────────

_PRIMARY_KEYS: dict[str, str] = {
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "Glob": "pattern",
    "Grep": "pattern",
    "Bash": "command",
    "WebFetch": "url",
    "Agent": "description",
    "TodoWrite": "todos",
}

def _shorten(s: str) -> str:
    return s if len(s) <= 80 else s[:77] + "…"

def _tool_summary(name: str, inp: dict) -> str:
    key = _PRIMARY_KEYS.get(name)
    if key and key in inp:
        raw = str(inp[key])
        val = _relativize(raw)
        # If stripping removed all meaningful content, show the original truncated
        if not val.strip() or val.strip() in (".", "~"):
            val = _shorten(raw)
        return _shorten(val)
    # fallback: first string value
    for v in inp.values():
        if isinstance(v, str):
            val = _relativize(v)
            if not val.strip() or val.strip() in (".", "~"):
                val = v
            return _shorten(val)
    return ""


# ── Output (terminal + optional log) ─────────────────────────────────────────

import os
import re as _re

_log_file = None
_brain_dir = os.environ.get("BRAIN_DIR", "").rstrip("/")
_project_dir = str(Path(_brain_dir).parent) if _brain_dir else ""
_home_dir = str(Path.home())


def _relativize(text: str) -> str:
    """Strip machine-specific path prefixes from tool summaries."""
    # Most specific first: brain dir, then project dir, then home dir
    if _brain_dir and _brain_dir in text:
        text = text.replace(_brain_dir + "/", "")
        text = text.replace(_brain_dir, ".")
    if _project_dir and _project_dir in text:
        text = text.replace(_project_dir + "/", "")
        text = text.replace(_project_dir, ".")
    if _home_dir and _home_dir in text:
        text = text.replace(_home_dir + "/", "~/")
        text = text.replace(_home_dir, "~")
    # Claude internal files — match any prefix before .claude/projects/
    # so it works regardless of where the project lives on disk
    text = _re.sub(r"[^\s]*\.claude/projects/\S*", "[claude memory]", text)
    return text

def _emit(line: str) -> None:
    print(line)
    if _log_file:
        plain = _re.sub(r"\033\[[0-9;]*m", "", line)
        _log_file.write(plain + "\n")
        _log_file.flush()


# ── Event handlers ────────────────────────────────────────────────────────────

def handle_assistant(event: dict) -> None:
    content = event.get("message", {}).get("content", [])
    for block in content:
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "")
            if text.strip():
                _emit(text)
        elif btype == "tool_use":
            name = block.get("name", "?")
            inp  = block.get("input", {})
            summary = _tool_summary(name, inp)
            line = cyan(f"  [{name}]")
            if summary:
                line += f"  {dim(summary)}"
            _emit(line)


def handle_result(event: dict) -> None:
    subtype   = event.get("subtype", "")
    turns     = event.get("num_turns", "?")
    cost      = event.get("cost_usd")
    duration  = event.get("duration_ms")

    _emit("")
    _emit("─" * 60)
    if subtype == "success":
        _emit(bold("Session complete"))
    elif subtype == "error_max_turns":
        _emit(yellow("Max turns reached."))

    parts = [f"turns: {turns}"]
    if cost is not None:
        parts.append(f"cost: ${cost:.4f}")
    if duration is not None:
        parts.append(f"time: {duration / 1000:.1f}s")
    _emit("")
    _emit(grey("  " + "  ·  ".join(parts)))
    _emit("")


def handle_system(event: dict) -> None:
    session_id = event.get("session_id", "")
    if session_id:
        _emit(grey(f"  session: {session_id}"))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: live-display.py <stream-file> [log-file]\n")
        sys.exit(1)

    stream_path = Path(sys.argv[1])
    stream_path.parent.mkdir(parents=True, exist_ok=True)

    global _log_file
    log_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else None
    _log_file = log_path.open("a", encoding="utf-8") if log_path else None

    with stream_path.open("w", encoding="utf-8") as stream_file:
        for raw_line in sys.stdin:
            # Always write raw line to stream file
            stream_file.write(raw_line)
            stream_file.flush()

            raw_line = raw_line.strip()
            if not raw_line:
                continue

            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")

            if etype == "system":
                handle_system(event)
            elif etype == "assistant":
                handle_assistant(event)
            elif etype == "result":
                handle_result(event)
            # user (tool results) and other types: silent

    if _log_file:
        _log_file.close()


if __name__ == "__main__":
    main()
