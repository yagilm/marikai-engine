#!/usr/bin/env python3
"""Repair and validate YAML front matter before publishing.

Jekyll only renders a collection document when it starts with a YAML front
matter block delimited by ``---``. Local models occasionally write the block
without its opening delimiter, or leave a blank line before it. The file is
then still copied to the publish repo, but Jekyll treats it as a static file:
it never appears in the collection listing, so the content silently vanishes
from the site.

This script repairs the common mistakes and fails loudly on anything it cannot
repair, so publishing never silently drops content.

Usage:
    normalise-front-matter.py DIR [FILE ...]          # repair in place
    normalise-front-matter.py --check DIR [FILE ...]  # report only
    normalise-front-matter.py --ensure-missing FILE   # add minimal front matter
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:  # PyYAML is closely tied; use it for a real parse when available.
    import yaml
except ImportError:  # pragma: no cover - structural checks still work
    yaml = None

KEY_LINE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*\s*:")


def _is_key_line(line: str) -> bool:
    return bool(KEY_LINE_RE.match(line))


def _is_front_matter_line(line: str) -> bool:
    """True for lines that can legally appear inside a simple front-matter block."""
    if not line.strip():
        return True
    if _is_key_line(line):
        return True
    # Continuation lines (indented), list items and comments.
    return line.startswith((" ", "\t", "-", "#"))


def normalise(text: str, ensure_missing: bool = False) -> tuple[str, list[str], list[str]]:
    """Return ``(new_text, repairs, errors)`` for one Markdown document.

    With ``ensure_missing`` a file that has no front matter at all gets a
    minimal ``layout: page`` block. This is used for the flat I/O pages in the
    publish repo: ``_config.yml`` sets their layout and title defaults, but
    Jekyll only applies defaults to documents that have *some* front matter.
    """
    repairs: list[str] = []
    errors: list[str] = []

    original = text
    text = text.lstrip("\ufeff")
    if text != original:
        repairs.append("removed UTF-8 BOM")

    ends_with_newline = text.endswith("\n")
    lines = text.splitlines()

    leading = 0
    while leading < len(lines) and not lines[leading].strip():
        leading += 1
    if leading:
        del lines[:leading]
        repairs.append("removed leading blank line(s)")

    if not lines:
        return original, repairs, ["file is empty"]

    if lines[0].strip() != "---":
        # Try to recover a block whose opening delimiter is missing.
        closing = next(
            (i for i, line in enumerate(lines) if line.strip() == "---"), None
        )
        body = lines[:closing] if closing is not None else lines
        if (
            closing is not None
            and closing > 0
            and any(_is_key_line(line) for line in body)
            and all(_is_front_matter_line(line) for line in body)
        ):
            lines.insert(0, "---")
            repairs.append("added missing opening ---")
        elif ensure_missing:
            # An ordinary Markdown page with no front matter at all. Add a
            # minimal block so Jekyll processes it and applies its defaults.
            lines[:0] = ["---", "layout: page", "---", ""]
            repairs.append("added minimal front matter")
        else:
            return original, repairs, ["missing opening ---"]

    closing = next(
        (i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing is None:
        return original, repairs, ["front matter is not closed with ---"]

    block = [line for line in lines[1:closing] if line.strip()]
    if not block:
        return original, repairs, ["front-matter block is empty"]
    if not any(_is_key_line(line) for line in block):
        return original, repairs, ["front-matter block has no key: value entries"]

    bad = [line for line in block if not _is_front_matter_line(line)]
    if bad:
        return original, repairs, [f"unparsable front-matter line: {bad[0]!r}"]

    if yaml is not None:
        try:
            data = yaml.safe_load("\n".join(lines[1:closing]))
        except Exception as exc:  # yaml.YAMLError and anything exotic
            return original, repairs, [f"invalid YAML: {exc}"]
        if not isinstance(data, dict):
            return original, repairs, ["front matter is not a YAML mapping"]
        if "date" in data and data["date"] in (None, ""):
            return original, repairs, ["empty date field"]

    new_text = "\n".join(lines)
    if ends_with_newline:
        new_text += "\n"
    if new_text == original:
        repairs.clear()
    return new_text, repairs, []


def iter_files(paths: list[str]):
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*.md") if p.is_file())
        elif path.is_file():
            yield path
        else:
            print(f"front matter: WARNING not found: {raw}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair and validate YAML front matter in Markdown files"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report problems without modifying files",
    )
    parser.add_argument(
        "--ensure-missing",
        action="store_true",
        help="add a minimal layout: page front matter to files that have none",
    )
    parser.add_argument("paths", nargs="+", help="directories or Markdown files")
    args = parser.parse_args()

    checked = 0
    repaired = 0
    failed = 0

    for path in iter_files(args.paths):
        checked += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"front matter: ERROR {path}: {exc}", file=sys.stderr)
            failed += 1
            continue

        new_text, repairs, errors = normalise(text, ensure_missing=args.ensure_missing)
        if errors:
            failed += 1
            print(f"front matter: ERROR {path}: {'; '.join(errors)}", file=sys.stderr)
            continue
        if repairs:
            if args.check:
                failed += 1
                print(f"front matter: NEEDS REPAIR {path}: {'; '.join(repairs)}")
            else:
                try:
                    path.write_text(new_text, encoding="utf-8")
                except OSError as exc:
                    failed += 1
                    print(f"front matter: ERROR {path}: {exc}", file=sys.stderr)
                    continue
                repaired += 1
                print(f"front matter: repaired {path}: {'; '.join(repairs)}")

    if failed:
        print(
            f"front matter: {failed} file(s) need attention "
            f"({checked} checked, {repaired} repaired)",
            file=sys.stderr,
        )
        return 1

    if repaired:
        print(f"front matter: OK ({checked} checked, {repaired} repaired)")
    else:
        print(f"front matter: OK ({checked} checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
