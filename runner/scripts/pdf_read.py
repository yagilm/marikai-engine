#!/usr/bin/env python3
"""Extract readable text from a PDF file or URL.

Tries extraction libraries in order of quality:
  1. pymupdf (fitz)   — best quality, handles complex layouts
  2. pdfminer.six     — good for text-heavy PDFs
  3. pypdf            — basic fallback, pure Python

If none are installed, prints an install hint and exits.

Usage:
    python3 pdf_read.py path/to/file.pdf
    python3 pdf_read.py https://example.com/paper.pdf
    python3 pdf_read.py --max-chars 20000 path/to/file.pdf
"""

from __future__ import annotations

import os
import ssl
import sys
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_MAX_CHARS = 15_000
ABSOLUTE_MAX_CHARS = 100_000


def _is_url(s: str) -> bool:
    return s.startswith("https://") or s.startswith("http://")


def _download(url: str) -> Path:
    """Download a PDF URL to a temp file and return its path."""
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS URLs are supported.")
    ctx = ssl.create_default_context()
    # Follow redirects manually to stay on HTTPS
    current_url = url
    for _ in range(5):
        req = urllib.request.Request(current_url, headers={"User-Agent": os.environ.get("PROJECT_NAME", "llmbrain").capitalize() + "/1.0"})
        try:
            resp = urllib.request.urlopen(req, timeout=30, context=ctx)
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                location = exc.headers.get("Location", "")
                if not location.startswith("https://"):
                    raise ValueError(f"Redirect to non-HTTPS URL blocked: {location}") from exc
                current_url = location
            else:
                raise
    else:
        raise ValueError("Too many redirects.")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    try:
        with resp:
            tmp.write(resp.read())
        tmp.close()
        return Path(tmp.name)
    except Exception:
        tmp.close()
        Path(tmp.name).unlink(missing_ok=True)
        raise


def extract_pymupdf(path: Path) -> str:
    import fitz  # type: ignore[import-not-found]
    doc = fitz.open(str(path))
    pages = []
    for page in doc:
        pages.append(page.get_text())
    return "\n\n".join(pages)


def extract_pdfminer(path: Path) -> str:
    from pdfminer.high_level import extract_text  # type: ignore[import-not-found]
    return extract_text(str(path))


def extract_pypdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore[import-not-found]
    reader = PdfReader(str(path))
    return "\n\n".join(
        page.extract_text() or "" for page in reader.pages
    )


def extract(path: Path) -> str:
    for fn, name in [
        (extract_pymupdf,  "pymupdf"),
        (extract_pdfminer, "pdfminer.six"),
        (extract_pypdf,    "pypdf"),
    ]:
        try:
            text = fn(path)
            if text and text.strip():
                sys.stderr.write(f"[pdf_read] extracted with {name}\n")
                return text
        except ImportError:
            continue
        except Exception as exc:
            sys.stderr.write(f"[pdf_read] {name} failed: {exc}\n")
            continue

    sys.stderr.write(
        "No PDF extraction library found. Install one of:\n"
        "  pip install pymupdf\n"
        "  pip install pdfminer.six\n"
        "  pip install pypdf\n"
    )
    sys.exit(1)


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_break = cut.rfind("\n\n")
    if last_break > max_chars // 2:
        cut = cut[:last_break]
    return cut + f"\n\n[Truncated at {len(cut)} chars. Use --max-chars to read more.]"


def main() -> None:
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
        sys.stderr.write("Usage: pdf_read.py [--max-chars N] <file.pdf|https://...>\n")
        sys.exit(1)

    source = args[0]
    tmp_path: Path | None = None

    try:
        if _is_url(source):
            sys.stderr.write(f"[pdf_read] downloading {source}\n")
            tmp_path = _download(source)
            pdf_path = tmp_path
            label = source
        else:
            pdf_path = Path(source)
            label = source
            if not pdf_path.exists():
                sys.stderr.write(f"File not found: {source}\n")
                sys.exit(1)

        text = extract(pdf_path)
        sys.stdout.write(f"Source: {label}\n{'=' * 60}\n\n")
        sys.stdout.write(truncate(text.strip(), max_chars) + "\n")

    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


if __name__ == "__main__":
    main()
