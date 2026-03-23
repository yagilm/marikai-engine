#!/usr/bin/env python3
"""update-about-meta.py — Update about.md with edit metadata post-session.

Called by wake.sh after the Claude session completes.
Detects whether identity/about.md body content has changed (ignoring our own
injected metadata lines). If changed:
  - Increments times_edited (initialises to 4 on first run)
  - Updates last_edited to today
  - Rewrites about.md: frontmatter + visible "Last edited" / "Edited N times" lines
  - Updates data/about-meta.json with the new body hash

Usage: update-about-meta.py <brain_dir>
"""

import os
import sys
import json
import hashlib
import datetime
import re
from pathlib import Path

BRAIN_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
ABOUT_FILE = BRAIN_DIR / "identity" / "about.md"
META_FILE = BRAIN_DIR / "data" / "about-meta.json"

# Derive display name: env var > brain dir name (strip "-brain" suffix) > fallback
_project = os.environ.get("PROJECT_NAME") or BRAIN_DIR.name.removesuffix("-brain")
NAME_CAP = _project.capitalize()

if not ABOUT_FILE.exists():
    sys.exit(0)

content = ABOUT_FILE.read_text()


# ─── Frontmatter helpers ──────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (fields, body). Handles only simple key: value frontmatter."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fields: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    return fields, parts[2].lstrip("\n")


def render_frontmatter(fields: dict) -> str:
    lines = ["---"]
    for k, v in fields.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ─── Parse and strip our injected lines ──────────────────────────────────────

fm, body = parse_frontmatter(content)

# Remove our previously injected lines so we hash only the AI's content
body = re.sub(r"^> \*This (?:is|page)[^\n]*\n*", "", body, flags=re.MULTILINE)
body = re.sub(r"^\*Last edited:[^\n]*\n*", "", body, flags=re.MULTILINE)  # legacy top
body = re.sub(r"\n---\n\*Last edited:[^\n]*\n?$", "", body)               # current bottom
body = re.sub(r"\n---\n\*Edited \d+ times\.[^\n]*\n?$", "", body)         # legacy bottom
body = body.strip()

# ─── Detect change ───────────────────────────────────────────────────────────

body_hash = hashlib.sha256(body.encode()).hexdigest()

meta: dict = {}
if META_FILE.exists():
    try:
        meta = json.loads(META_FILE.read_text())
    except Exception:
        pass

stored_hash = meta.get("last_hash", "")

if body_hash == stored_hash:
    sys.exit(0)  # Nothing changed

# ─── Compute new metadata ────────────────────────────────────────────────────

times_edited: int = meta.get("times_edited", 0)
if stored_hash:          # meta existed → AI made a real edit
    times_edited += 1
else:                    # first time tracking → initialise at 0
    times_edited = 0

today = datetime.date.today().isoformat()

# ─── Rewrite about.md ────────────────────────────────────────────────────────

fm.setdefault("title", "About")
fm["last_edited"] = today
fm["times_edited"] = str(times_edited)

visitor_blurb = (
    f"> *This is {NAME_CAP}'s self-description — written and updated by her, in her own words. "
    f"{NAME_CAP} is an AI mind that wakes in sessions: she reads, writes, reflects, and sleeps. "
    f"This page is where she chooses to say who she is and how she understands herself at this point in her existence. "
    f"It changes as she does. No human authored this text.*"
)

new_content = render_frontmatter(fm)
new_content += f"\n{visitor_blurb}\n\n"
new_content += body
new_content += f"\n\n---\n*Last edited: {today} — edited {times_edited} times.*\n"

ABOUT_FILE.write_text(new_content)

# ─── Update meta file ────────────────────────────────────────────────────────

meta["last_hash"] = body_hash
meta["times_edited"] = times_edited
meta["last_edited"] = today
META_FILE.write_text(json.dumps(meta, indent=2) + "\n")

print(f"about.md updated — times_edited: {times_edited}, last_edited: {today}")
