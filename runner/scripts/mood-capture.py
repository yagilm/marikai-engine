#!/usr/bin/env python3
"""Capture mood state after a session ends.

Reads the mood from the journal's frontmatter, derives sentiment from body text,
blends with the decayed previous state, and writes mood-state.json for the next
session's context injection.

Usage:
    python3 mood-capture.py <session_type>
    python3 mood-capture.py morning
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

_BRAIN_DIR = Path(os.environ.get("MARIKAI_BRAIN_DIR",
                  Path(__file__).parent.parent.parent / "marikai-brain"))

JOURNAL_DIR = _BRAIN_DIR / "journal"
DATA_DIR = _BRAIN_DIR / "data"
MOOD_STATE_PATH = DATA_DIR / "mood-state.json"
MOOD_HISTORY_PATH = DATA_DIR / "mood-history.jsonl"
LEXICON_PATH = Path(__file__).parent / "mood-lexicon.json"

SESSION_WEIGHTS: dict[str, float] = {
    "morning": 1.0,
    "afternoon": 1.0,
    "evening": 1.0,
    "night": 1.0,
    "self": 0.9,
}

DECAY_BASE = 0.7
DECAY_PERIOD_HOURS = 6.0  # Marikai has 4 sessions/day (~6h apart), vs 8 in claude-runner

log = logging.getLogger(__name__)


def load_lexicon() -> dict[str, list[float]]:
    """Load the mood word → [valence, arousal] mapping."""
    if not LEXICON_PATH.exists():
        log.warning("Lexicon not found at %s", LEXICON_PATH)
        return {}
    return json.loads(LEXICON_PATH.read_text(encoding="utf-8"))


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Extract key: value frontmatter and body from a markdown file.

    No external deps — handles the simple key: value format Marikai writes.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, parts[2]


def find_journal(session_type: str, today: str) -> Path | None:
    """Find the most recently modified journal entry for today."""
    candidates = sorted(
        JOURNAL_DIR.glob(f"{today}-*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    _ = session_type  # reserved for future per-type filtering
    return candidates[0] if candidates else None


def extract_mood_words(meta: dict[str, str]) -> list[str]:
    """Extract mood words from frontmatter `mood:` field."""
    mood = meta.get("mood", "")
    return [w.strip().lower() for w in mood.split(",") if w.strip()] if mood else []


def score_mood_words(
    words: list[str], lexicon: dict[str, list[float]]
) -> dict[str, float] | None:
    """Average valence/arousal for a list of mood words."""
    scores = [lexicon[w] for w in words if w in lexicon]
    if not scores:
        return None
    return {
        "valence": round(sum(s[0] for s in scores) / len(scores), 2),
        "arousal": round(sum(s[1] for s in scores) / len(scores), 2),
    }


def derive_from_text(text: str, lexicon: dict[str, list[float]]) -> dict[str, float]:
    """Derive simple sentiment from body text by matching lexicon words."""
    matched = [lexicon[w] for w in text.lower().split() if w in lexicon]
    if not matched:
        return {"valence": 0.0, "arousal": 0.0}
    return {
        "valence": round(sum(s[0] for s in matched) / len(matched), 2),
        "arousal": round(sum(s[1] for s in matched) / len(matched), 2),
    }


def read_previous_state() -> dict[str, object] | None:
    """Read the saved mood state from the last session."""
    if not MOOD_STATE_PATH.exists():
        return None
    try:
        return json.loads(MOOD_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def blend_mood(
    previous: dict[str, object] | None,
    new_score: dict[str, float],
    new_weight: float,
) -> tuple[dict[str, float], dict[str, float] | None]:
    """Blend new mood with the decayed previous mood.

    Returns (blended_score, previous_residual).
    """
    if previous is None:
        return new_score, None

    prev_ts = previous.get("timestamp", "")
    if not prev_ts:
        return new_score, None

    try:
        prev_time = datetime.fromisoformat(str(prev_ts))
    except (ValueError, TypeError):
        return new_score, None

    hours_elapsed = (datetime.now(UTC) - prev_time).total_seconds() / 3600.0
    decay = DECAY_BASE ** (hours_elapsed / DECAY_PERIOD_HOURS)

    prev_blended = previous.get("blended") or previous.get("self_report")
    if not prev_blended or not isinstance(prev_blended, dict):
        return new_score, None

    prev_v = float(prev_blended.get("valence", 0)) * decay
    prev_a = float(prev_blended.get("arousal", 0)) * decay
    complement = 1.0 - new_weight

    blended = {
        "valence": round(prev_v * complement + new_score["valence"] * new_weight, 2),
        "arousal": round(prev_a * complement + new_score["arousal"] * new_weight, 2),
    }
    residual = {
        "valence": round(prev_v, 2),
        "arousal": round(prev_a, 2),
        "from": str(previous.get("session_type", "unknown")),
    }
    return blended, residual


def main() -> None:
    """Capture mood from the most recent journal and write mood-state.json."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    session_type = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    today = datetime.now().astimezone().strftime("%Y-%m-%d")

    lexicon = load_lexicon()
    journal = find_journal(session_type, today)

    mood_words: list[str] = []
    body_text = ""
    journal_length = 0

    if journal:
        raw = journal.read_text(encoding="utf-8")
        meta, body_text = parse_frontmatter(raw)
        mood_words = extract_mood_words(meta)
        journal_length = len(body_text.split())
    else:
        log.warning("No journal entry found for %s-%s", today, session_type)

    self_report = score_mood_words(mood_words, lexicon)
    derived = derive_from_text(body_text, lexicon)
    primary_score = self_report if self_report else derived

    weight = SESSION_WEIGHTS.get(session_type, 1.0)
    if journal_length > 3000:
        weight = min(1.0, weight + 0.2)
    elif journal_length < 200:
        weight = max(0.1, weight - 0.2)

    previous = read_previous_state()
    blended, prev_residual = blend_mood(previous, primary_score, weight)

    state: dict[str, object] = {
        "session": f"{today}-{session_type}",
        "session_type": session_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "mood_words": mood_words,
        "self_report": self_report,
        "derived": derived,
        "blended": blended,
        "weight": weight,
        "journal_length": journal_length,
        "previous_residual": prev_residual,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MOOD_STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with MOOD_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(state, ensure_ascii=False) + "\n")

    log.info("Mood: %s → blended %s", mood_words or "(derived)", blended)


if __name__ == "__main__":
    main()
