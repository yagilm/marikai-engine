#!/usr/bin/env python3
"""Extract a structured log entry from a Claude Code stream-json JSONL file."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Brain dir is passed via environment so paths stay portable
_BRAIN_DIR: str = os.environ.get("BRAIN_DIR", "")
_BRAIN_PREFIX: str = _BRAIN_DIR.rstrip("/") + "/" if _BRAIN_DIR else ""

SUMMARY_MAX_LENGTH: int = 200
COMPACT_SEPARATORS: tuple[str, str] = (",", ":")

FILTERED_READ_PREFIXES: tuple[str, ...] = tuple(
    p for p in (
        _BRAIN_PREFIX + "memory/",
        _BRAIN_PREFIX + "prompt/",
        _BRAIN_PREFIX + "MARIKAI.md",
    )
    if p.strip("/")
)


WRITE_TOOLS: frozenset[str] = frozenset({"Write", "Edit"})
READ_TOOL: str = "Read"

_LOG: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenUsage:
    """Token counts from the session result."""

    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_create: int

    def to_dict(self) -> dict[str, int]:
        """Serialize to compact key names."""
        return {
            "in": self.input_tokens,
            "out": self.output_tokens,
            "cache_read": self.cache_read,
            "cache_create": self.cache_create,
        }


@dataclass(frozen=True)
class LogEntry:
    """Structured session log entry."""

    timestamp: str
    session: str
    session_id: str
    duration_s: int
    turns: int
    cost_usd: float
    tokens: TokenUsage
    tools: dict[str, int]
    files_written: list[str]
    files_read: list[str]
    summary: str

    def to_dict(self) -> dict[str, object]:
        """Serialize to the sessions.jsonl line format."""
        return {
            "t": self.timestamp,
            "session": self.session,
            "session_id": self.session_id,
            "duration_s": self.duration_s,
            "turns": self.turns,
            "cost_usd": round(self.cost_usd, 4),
            "tokens": self.tokens.to_dict(),
            "tools": self.tools,
            "files_written": self.files_written,
            "files_read": self.files_read,
            "summary": self.summary,
        }


def _parse_jsonl(stream_path: Path) -> list[dict[str, Any]]:
    """Read JSONL, skip malformed lines."""
    lines: list[dict[str, Any]] = []
    with stream_path.open("r", encoding="utf-8") as fh:
        for line_num, raw in enumerate(fh, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                lines.append(json.loads(stripped))
            except json.JSONDecodeError:
                _LOG.warning("Skipping malformed JSON at line %d", line_num)
    return lines


def _relativize(path: str) -> str:
    """Strip brain dir prefix for readability."""
    if _BRAIN_PREFIX and path.startswith(_BRAIN_PREFIX):
        return path[len(_BRAIN_PREFIX):]
    return path


def _is_filtered_read(path: str) -> bool:
    """Return True if a read path should be excluded from the log."""
    return any(path.startswith(prefix) for prefix in FILTERED_READ_PREFIXES)


def _extract_tool_usage(
    lines: list[dict[str, Any]],
) -> tuple[dict[str, int], list[str], list[str]]:
    """Extract tool counts, files written, and files read."""
    tool_counts: dict[str, int] = {}
    written: set[str] = set()
    read: set[str] = set()

    for line in lines:
        if line.get("type") != "assistant":
            continue
        for block in line.get("message", {}).get("content", []):
            if block.get("type") != "tool_use":
                continue
            name: str = block.get("name", "Unknown")
            tool_counts[name] = tool_counts.get(name, 0) + 1
            file_path: str = block.get("input", {}).get("file_path", "")
            if not file_path:
                continue
            if name in WRITE_TOOLS:
                written.add(_relativize(file_path))
            elif name == READ_TOOL and not _is_filtered_read(file_path):
                read.add(_relativize(file_path))

    return tool_counts, sorted(written), sorted(read)


def _find_result(lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the last result-type line."""
    for line in reversed(lines):
        if line.get("type") == "result":
            return line
    return None


def _find_session_id(lines: list[dict[str, Any]]) -> str:
    """Extract session_id from the system init line."""
    for line in lines:
        if line.get("type") == "system":
            return str(line.get("session_id", ""))
    return ""


def _collapse_summary(text: str) -> str:
    """Collapse whitespace and truncate."""
    collapsed = " ".join(text.split())
    if len(collapsed) > SUMMARY_MAX_LENGTH:
        return collapsed[:SUMMARY_MAX_LENGTH] + "..."
    return collapsed


def build_log_entry(stream_path: Path, session_type: str) -> LogEntry:
    """Parse stream-json and build a structured log entry."""
    lines = _parse_jsonl(stream_path)
    result = _find_result(lines)
    tool_counts, files_written, files_read = _extract_tool_usage(lines)
    timestamp = datetime.now(UTC).astimezone().isoformat(timespec="seconds")

    if result is not None:
        session_id = str(result.get("session_id", "")) or _find_session_id(lines)
        duration_s = int(result.get("duration_ms", 0)) // 1000
        turns = int(result.get("num_turns", 0))
        cost_usd = float(result.get("total_cost_usd", 0.0))
        usage = result.get("usage", {})
        tokens = TokenUsage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read=usage.get("cache_read_input_tokens", 0),
            cache_create=usage.get("cache_creation_input_tokens", 0),
        )
        summary = _collapse_summary(str(result.get("result", "")))
    else:
        _LOG.warning("No result line found in %s", stream_path)
        session_id = _find_session_id(lines)
        duration_s = turns = 0
        cost_usd = 0.0
        tokens = TokenUsage(0, 0, 0, 0)
        summary = "(no result line)"

    return LogEntry(
        timestamp=timestamp,
        session=session_type,
        session_id=session_id,
        duration_s=duration_s,
        turns=turns,
        cost_usd=cost_usd,
        tokens=tokens,
        tools=tool_counts,
        files_written=files_written,
        files_read=files_read,
        summary=summary,
    )


def main() -> None:
    """Parse stream-json and write a JSON log line to stdout."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s",
                        stream=sys.stderr)

    parser = argparse.ArgumentParser(
        description="Extract structured log entry from a Claude Code stream-json file."
    )
    parser.add_argument("stream_file", type=Path, help="Path to the stream-json JSONL.")
    parser.add_argument("session_type", help="Session type (morning, evening, …).")
    args = parser.parse_args()

    if not args.stream_file.is_file():
        sys.stderr.write(f"Stream file not found: {args.stream_file}\n")
        sys.exit(1)

    entry = build_log_entry(args.stream_file, args.session_type)
    sys.stdout.write(
        json.dumps(entry.to_dict(), separators=COMPACT_SEPARATORS, ensure_ascii=False)
        + "\n"
    )


if __name__ == "__main__":
    main()
