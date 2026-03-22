#!/usr/bin/env python3
"""Fetch and extract readable text from a web page.

Uses trafilatura for content extraction when available,
with a stdlib-only fallback parser.

Usage:
    python3 web_read.py "https://example.com/article"
    python3 web_read.py --max-chars 30000 "https://example.com/article"
"""

from __future__ import annotations

import html.parser
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from socket import getaddrinfo

_BRAIN_DIR = Path(os.environ.get("BRAIN_DIR",
                  Path(__file__).parent.parent.parent / (os.environ.get("PROJECT_NAME", "marikai") + "-brain")))
LOG_FILE = _BRAIN_DIR / "logs" / "web.log"

DEFAULT_MAX_CHARS = 15_000
ABSOLUTE_MAX_CHARS = 50_000
REQUEST_TIMEOUT = 15
USER_AGENT = os.environ.get("PROJECT_NAME", "llmbrain").capitalize() + "/1.0"
ALLOWED_SCHEMES = frozenset({"https"})


def _log(url: str, success: bool, error: str = "") -> None:
    """Append a JSON line to the web activity log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, object] = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "url": url,
        "success": success,
    }
    if error:
        entry["error"] = error
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        sys.stderr.write(f"Log write failed: {exc}\n")


def validate_url(url: str) -> str:
    """Validate URL for safety — HTTPS only, no private IPs.

    Raises ValueError if invalid or unsafe.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"Only HTTPS URLs allowed, got: {parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError("URL has no hostname")

    hostname = parsed.hostname
    try:
        addr = ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ValueError(f"Private/loopback address blocked: {hostname}")
    except ValueError as exc:
        if any(kw in str(exc) for kw in ("Private", "loopback", "blocked")):
            raise
        # Hostname — resolve and check
        try:
            for entry in getaddrinfo(hostname, None):
                addr = ip_address(entry[4][0])
                if addr.is_private or addr.is_loopback or addr.is_link_local:
                    raise ValueError(f"URL resolves to private address: {hostname} -> {addr}")
        except OSError as dns_exc:
            raise ValueError(f"DNS resolution failed for {hostname}: {dns_exc}") from dns_exc
    return url


def fetch_page(url: str) -> str:
    """Fetch a web page via HTTPS GET and return HTML as a string."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT, context=ctx) as resp:
        content_type = resp.headers.get("Content-Type", "")
        encoding = "utf-8"
        if "charset=" in content_type:
            encoding = content_type.split("charset=")[-1].split(";")[0].strip()
        return resp.read().decode(encoding, errors="replace")


class _TextExtractor(html.parser.HTMLParser):
    """Minimal stdlib HTML-to-text extractor."""

    SKIP_TAGS = frozenset({"script", "style", "nav", "header", "footer",
                           "noscript", "svg", "iframe", "form"})
    BLOCK_TAGS = frozenset({"p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"})

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in self.BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in self.BLOCK_TAGS - {"br", "li"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        """Return extracted text with collapsed whitespace."""
        text = "".join(self._chunks)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def extract_text(html_content: str, url: str) -> str:
    """Extract readable text from HTML — trafilatura if available, stdlib fallback."""
    try:
        import trafilatura  # type: ignore[import-not-found]
        result: str | None = trafilatura.extract(html_content, url=url,
                                                  include_links=True, include_tables=True)
        if result:
            return result
    except ImportError:
        pass
    extractor = _TextExtractor()
    extractor.feed(html_content)
    return extractor.get_text()


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate at a paragraph boundary, with a notice."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_break = truncated.rfind("\n\n")
    if last_break > max_chars // 2:
        truncated = truncated[:last_break]
    return truncated + f"\n\n[Truncated at {len(truncated)} chars. Use --max-chars to read more.]"


def main() -> None:
    """Fetch a URL, extract text, print to stdout."""
    args = list(sys.argv[1:])
    max_chars = DEFAULT_MAX_CHARS

    if "--max-chars" in args:
        idx = args.index("--max-chars")
        if idx + 1 >= len(args):
            sys.stderr.write("--max-chars requires a value\n")
            sys.exit(1)
        try:
            max_chars = min(int(args[idx + 1]), ABSOLUTE_MAX_CHARS)
        except ValueError:
            sys.stderr.write(f"Invalid --max-chars: {args[idx + 1]}\n")
            sys.exit(1)
        args = args[:idx] + args[idx + 2:]

    if not args:
        sys.stderr.write("Usage: web_read.py [--max-chars N] <url>\n")
        sys.exit(1)

    url = args[0]

    try:
        validated = validate_url(url)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        _log(url, success=False, error=str(exc))
        sys.exit(1)

    try:
        html_content = fetch_page(validated)
    except urllib.error.HTTPError as exc:
        sys.stderr.write(f"HTTP {exc.code}: {url}\n")
        _log(url, success=False, error=f"http_{exc.code}")
        sys.exit(1)
    except urllib.error.URLError as exc:
        sys.stderr.write(f"Fetch failed: {exc.reason}\n")
        _log(url, success=False, error=str(exc.reason))
        sys.exit(1)
    except (ssl.SSLError, TimeoutError) as exc:
        sys.stderr.write(f"Connection error: {exc}\n")
        _log(url, success=False, error=type(exc).__name__)
        sys.exit(1)

    text = extract_text(html_content, validated)
    if not text:
        sys.stdout.write(f"No readable content extracted from: {url}\n")
        _log(url, success=True, error="empty_extraction")
        return

    sys.stdout.write(f"Source: {url}\n{'=' * 60}\n\n")
    sys.stdout.write(truncate_text(text, max_chars) + "\n")
    _log(url, success=True)


if __name__ == "__main__":
    main()
