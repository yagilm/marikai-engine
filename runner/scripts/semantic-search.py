#!/usr/bin/env python3
"""Search the semantic index for passages resonant with a query.

Returns formatted markdown suitable for injection into the wake prompt.
Exits silently (no output) if the index doesn't exist or deps are missing.

Usage:
    python3 semantic-search.py "a query string"
    python3 semantic-search.py --query-file path/to/file.md
    python3 semantic-search.py --top 5 "query"
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_BRAIN_DIR = Path(os.environ.get("BRAIN_DIR",
                  Path(__file__).parent.parent.parent / (os.environ.get("PROJECT_NAME", "marikai") + "-brain")))

INDEX_DIR = _BRAIN_DIR / "data" / "semantic-index"
INDEX_FILE = INDEX_DIR / "index.faiss"
CHUNKS_FILE = INDEX_DIR / "chunks.json"


def strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL).strip()


def load_query_from_file(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    # Use stripped body, capped at 1000 chars for embedding
    return strip_frontmatter(text)[:1000]


def format_result(chunk: dict) -> str:
    source = chunk.get("source", "")
    date = chunk.get("date", "")
    doc_type = chunk.get("type", "")
    text = chunk["text"].replace("\n", " ").strip()
    if len(text) > 220:
        text = text[:220].rsplit(" ", 1)[0] + "…"
    label = f"{date} ({doc_type})" if date else source
    return f'> "{text}"\n— *{label}*'


def main() -> None:
    args = sys.argv[1:]
    top_k = 5
    query_file = None
    query_text = None

    i = 0
    while i < len(args):
        if args[i] == "--top" and i + 1 < len(args):
            top_k = int(args[i + 1])
            i += 2
        elif args[i] == "--query-file" and i + 1 < len(args):
            query_file = args[i + 1]
            i += 2
        else:
            query_text = args[i]
            i += 1

    if query_file:
        query_text = load_query_from_file(query_file)

    if not query_text or not query_text.strip():
        sys.exit(0)

    if not INDEX_FILE.exists() or not CHUNKS_FILE.exists():
        sys.exit(0)

    try:
        import faiss
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError:
        sys.exit(0)  # silent — not installed

    chunks = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    if not chunks:
        sys.exit(0)

    index = faiss.read_index(str(INDEX_FILE))
    model = SentenceTransformer("all-MiniLM-L6-v2")

    query_vec = model.encode([query_text], convert_to_numpy=True).astype("float32")
    faiss.normalize_L2(query_vec)

    k = min(top_k, len(chunks))
    distances, indices = index.search(query_vec, k)

    results = []
    seen_sources: set[str] = set()
    for dist, idx in zip(distances[0], indices[0]):
        if idx < 0 or idx >= len(chunks):
            continue
        chunk = chunks[idx]
        # Deduplicate by source file — one passage per document
        src = chunk.get("source", "")
        if src in seen_sources:
            continue
        seen_sources.add(src)
        results.append(chunk)

    if not results:
        sys.exit(0)

    print("\n\n".join(format_result(c) for c in results))


if __name__ == "__main__":
    main()
