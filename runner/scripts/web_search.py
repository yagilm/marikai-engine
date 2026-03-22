#!/usr/bin/env python3
"""Search the web using the LangSearch API.

Requires LANGSEARCH_API_KEY environment variable (or in config.local.env).

Usage:
    python3 web_search.py "your query"
    python3 web_search.py --count 5 "your query"
    python3 web_search.py --freshness oneWeek "your query"

Options:
    --count N           Number of results, 1–10 (default: 5)
    --freshness PERIOD  oneDay | oneWeek | oneMonth | oneYear | noLimit (default: noLimit)
    --summary           Request full-text summaries per result (uses more quota)
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

_BRAIN_DIR = Path(os.environ.get("BRAIN_DIR",
                  Path(__file__).parent.parent.parent / (os.environ.get("PROJECT_NAME", "marikai") + "-brain")))
LOG_FILE = _BRAIN_DIR / "logs" / "web.log"

API_URL = "https://api.langsearch.com/v1/web-search"
FRESHNESS_OPTIONS = frozenset({"oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit"})
DEFAULT_COUNT = 5
MAX_COUNT = 10
REQUEST_TIMEOUT = 20


def _log(query: str, success: bool, count: int = 0, error: str = "") -> None:
    """Append a JSON line to the web activity log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, object] = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "type": "search",
        "query": query,
        "success": success,
    }
    if count:
        entry["results"] = count
    if error:
        entry["error"] = error
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        sys.stderr.write(f"Log write failed: {exc}\n")


def search(
    query: str,
    api_key: str,
    count: int = DEFAULT_COUNT,
    freshness: str = "noLimit",
    summary: bool = False,
) -> list[dict[str, str]]:
    """Call the LangSearch API and return a list of result dicts."""
    payload = json.dumps({
        "query": query,
        "count": count,
        "freshness": freshness,
        "summary": summary,
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": os.environ.get("PROJECT_NAME", "llmbrain").capitalize() + "/1.0",
        },
    )

    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    pages = data.get("data", {}).get("webPages", {}).get("value", [])
    return [
        {
            "title": p.get("name", ""),
            "url": p.get("url", ""),
            "snippet": p.get("snippet", ""),
            "summary": p.get("summary", ""),
            "date": p.get("datePublished", "")[:10] if p.get("datePublished") else "",
        }
        for p in pages
    ]


def format_results(query: str, results: list[dict[str, str]]) -> str:
    """Format results as readable text for Marikai."""
    lines = [f"Search: {query}", f"Results: {len(results)}", "=" * 60, ""]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}")
        lines.append(f"   {r['url']}")
        if r["date"]:
            lines.append(f"   Published: {r['date']}")
        if r["summary"]:
            lines.append(f"   {r['summary'][:500]}")
        elif r["snippet"]:
            lines.append(f"   {r['snippet']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = list(sys.argv[1:])

    # Parse flags
    count = DEFAULT_COUNT
    freshness = "noLimit"
    summary = False

    if "--count" in args:
        idx = args.index("--count")
        if idx + 1 >= len(args):
            sys.stderr.write("--count requires a value\n")
            sys.exit(1)
        try:
            count = max(1, min(MAX_COUNT, int(args[idx + 1])))
        except ValueError:
            sys.stderr.write(f"Invalid --count: {args[idx + 1]}\n")
            sys.exit(1)
        args = args[:idx] + args[idx + 2:]

    if "--freshness" in args:
        idx = args.index("--freshness")
        if idx + 1 >= len(args):
            sys.stderr.write("--freshness requires a value\n")
            sys.exit(1)
        freshness = args[idx + 1]
        if freshness not in FRESHNESS_OPTIONS:
            sys.stderr.write(f"Invalid --freshness: {freshness}. "
                             f"Choose from: {', '.join(sorted(FRESHNESS_OPTIONS))}\n")
            sys.exit(1)
        args = args[:idx] + args[idx + 2:]

    if "--summary" in args:
        summary = True
        args.remove("--summary")

    if not args:
        sys.stderr.write(
            "Usage: web_search.py [--count N] [--freshness PERIOD] [--summary] <query>\n"
        )
        sys.exit(1)

    query = " ".join(args)

    api_key = os.environ.get("LANGSEARCH_API_KEY", "").strip()
    if not api_key:
        # Try loading from config.local.env or config.env
        for config_name in ("config.local.env", "config.env"):
            config_path = Path(__file__).parent.parent / config_name
            if config_path.exists():
                for line in config_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("LANGSEARCH_API_KEY="):
                        api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
            if api_key:
                break

    if not api_key:
        sys.stderr.write(
            "LANGSEARCH_API_KEY not set. Add it to runner/config.local.env or "
            "export it as an environment variable.\n"
            "Get a free key at: https://langsearch.com/dashboard\n"
        )
        sys.exit(1)

    try:
        results = search(query, api_key, count=count, freshness=freshness, summary=summary)
    except urllib.error.HTTPError as exc:
        err = f"HTTP {exc.code}"
        sys.stderr.write(f"Search failed: {err}\n")
        _log(query, success=False, error=err)
        sys.exit(1)
    except urllib.error.URLError as exc:
        err = str(exc.reason)
        sys.stderr.write(f"Search failed: {err}\n")
        _log(query, success=False, error=err)
        sys.exit(1)
    except (KeyError, json.JSONDecodeError) as exc:
        err = f"Unexpected response: {exc}"
        sys.stderr.write(f"{err}\n")
        _log(query, success=False, error=err)
        sys.exit(1)

    _log(query, success=True, count=len(results))
    sys.stdout.write(format_results(query, results) + "\n")


if __name__ == "__main__":
    main()
