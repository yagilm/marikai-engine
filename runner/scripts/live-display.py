#!/usr/bin/env python3
"""Live display for Marikai sessions.

Reads stream-json from stdin, writes raw lines to the stream file,
and pretty-prints a human-readable view to the terminal in real time.

Usage:
    claude ... --output-format stream-json | python3 live-display.py <stream-file>
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

def _tool_summary(name: str, inp: dict) -> str:
    key = _PRIMARY_KEYS.get(name)
    if key and key in inp:
        val = str(inp[key])
        if len(val) > 80:
            val = val[:77] + "…"
        return val
    # fallback: first string value
    for v in inp.values():
        if isinstance(v, str):
            val = v[:80]
            return val if len(v) <= 80 else val[:77] + "…"
    return ""


# ── Event handlers ────────────────────────────────────────────────────────────

def handle_assistant(event: dict) -> None:
    content = event.get("message", {}).get("content", [])
    for block in content:
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "")
            if text.strip():
                print(text)
        elif btype == "tool_use":
            name = block.get("name", "?")
            inp  = block.get("input", {})
            summary = _tool_summary(name, inp)
            line = cyan(f"  [{name}]")
            if summary:
                line += f"  {dim(summary)}"
            print(line)


def handle_result(event: dict) -> None:
    subtype   = event.get("subtype", "")
    turns     = event.get("num_turns", "?")
    cost      = event.get("cost_usd")
    duration  = event.get("duration_ms")

    print()
    print("─" * 60)
    if subtype == "success":
        result_text = event.get("result", "")
        if result_text:
            print(bold("Session complete"))
            print()
            print(result_text)
    elif subtype == "error_max_turns":
        print(yellow("Max turns reached."))

    parts = [f"turns: {turns}"]
    if cost is not None:
        parts.append(f"cost: ${cost:.4f}")
    if duration is not None:
        parts.append(f"time: {duration / 1000:.1f}s")
    print()
    print(grey("  " + "  ·  ".join(parts)))
    print()


def handle_system(event: dict) -> None:
    session_id = event.get("session_id", "")
    model      = event.get("tools", [{}])  # not actually here, just guard
    if session_id:
        print(grey(f"  session: {session_id}"))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: live-display.py <stream-file>\n")
        sys.exit(1)

    stream_path = Path(sys.argv[1])
    stream_path.parent.mkdir(parents=True, exist_ok=True)

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


if __name__ == "__main__":
    main()
