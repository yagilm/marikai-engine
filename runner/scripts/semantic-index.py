#!/usr/bin/env python3
"""Build or update a semantic FAISS index over the mind's past writing.

Covers: journal/, essays/, creatives/, letters/
Chunks each file into overlapping passages, embeds with sentence-transformers,
stores index in data/semantic-index/.

Incremental by default. New files are embedded without touching existing
vectors; if an indexed document was edited, deleted, or predates content
hashing, the whole index is rebuilt so it cannot go stale.

Usage:
    python3 semantic-index.py           # build/update (incremental)
    python3 semantic-index.py --rebuild # force full rebuild from scratch
    python3 semantic-index.py --stats   # show index stats, no changes
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

try:  # Same directory when run as a script.
    from mind import brain_dir
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mind import brain_dir

_BRAIN_DIR = brain_dir()

INDEX_DIR = _BRAIN_DIR / "data" / "semantic-index"
INDEX_FILE = INDEX_DIR / "index.faiss"
CHUNKS_FILE = INDEX_DIR / "chunks.json"

COLLECTIONS = ["journal", "essays", "creatives", "letters"]
CHUNK_SIZE = 500
CHUNK_OVERLAP = 100
MIN_CHUNK = 80


def strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL).strip()


def doc_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(text: str, source: str, file_date: str, doc_type: str,
               content_hash: str = "") -> list[dict]:
    body = strip_frontmatter(text)
    if not body:
        return []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    chunks = []
    for i in range(0, len(body), step):
        snippet = body[i : i + CHUNK_SIZE].strip()
        if len(snippet) < MIN_CHUNK:
            continue
        chunks.append({
            "source": source,
            "date": file_date,
            "type": doc_type,
            "doc_hash": content_hash,
            "text": snippet,
        })
    return chunks


def extract_date(path: Path) -> str:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", path.name)
    return m.group(1) if m else ""


def collect_documents() -> list[tuple[Path, str]]:
    type_map = {"journal": "journal", "essays": "essay",
                "creatives": "creative", "letters": "letter"}
    docs = []
    for coll in COLLECTIONS:
        d = _BRAIN_DIR / coll
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if not f.name.startswith("."):
                docs.append((f, type_map[coll]))
    return docs


def load_chunks() -> list[dict]:
    if CHUNKS_FILE.exists():
        return json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    return []


def save_chunks(chunks: list[dict]) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_FILE.write_text(
        json.dumps(chunks, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> None:
    rebuild = "--rebuild" in sys.argv
    stats_only = "--stats" in sys.argv

    if stats_only:
        chunks = load_chunks()
        by_type: dict[str, int] = {}
        for c in chunks:
            by_type[c["type"]] = by_type.get(c["type"], 0) + 1
        print(f"Total chunks: {len(chunks)}")
        for t, n in sorted(by_type.items()):
            print(f"  {t}: {n}")
        print(f"Index file: {'present' if INDEX_FILE.exists() else 'missing'}")
        return

    try:
        import faiss
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print(
            "ERROR: Required packages not installed.\n"
            "Run: pip install sentence-transformers faiss-cpu",
            file=sys.stderr,
        )
        sys.exit(1)

    documents = collect_documents()
    current_sources = {
        str(path.relative_to(_BRAIN_DIR)): (path, doc_type)
        for path, doc_type in documents
    }

    # The index and its chunk metadata must always travel together.
    have_index = INDEX_FILE.exists() and CHUNKS_FILE.exists()
    if not have_index:
        rebuild = True
    existing_chunks = [] if rebuild else load_chunks()

    # Hash of every document currently represented in the index.
    indexed_hashes: dict[str, set[str]] = {}
    for chunk in existing_chunks:
        source = chunk.get("source", "")
        if source:
            indexed_hashes.setdefault(source, set()).add(chunk.get("doc_hash", ""))

    # Adding vectors is cheap; removing/updating them is not. If any indexed
    # document changed or disappeared (or has no hash from an older index),
    # rebuild the whole index so it never serves stale passages.
    if existing_chunks:
        for source, hashes in indexed_hashes.items():
            if source not in current_sources:
                rebuild = True
                break
            path, _ = current_sources[source]
            text = path.read_text(encoding="utf-8", errors="replace")
            if hashes != {doc_hash(text)}:
                rebuild = True
                break

    if rebuild:
        existing_chunks = []
        existing_sources: set[str] = set()
    else:
        existing_sources = set(indexed_hashes)

    new_chunks: list[dict] = []
    new_doc_count = 0
    for rel, (path, doc_type) in current_sources.items():
        if rel in existing_sources:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        chunks = chunk_text(text, rel, extract_date(path), doc_type, doc_hash(text))
        if chunks:
            new_chunks.extend(chunks)
            new_doc_count += 1

    if not new_chunks:
        if rebuild:
            INDEX_FILE.unlink(missing_ok=True)
            CHUNKS_FILE.unlink(missing_ok=True)
            print("No documents to index — removed stale index.", file=sys.stderr)
        else:
            print(f"Index up to date — {len(existing_chunks)} chunks.", file=sys.stderr)
        return

    print(
        f"Embedding {len(new_chunks)} new chunks from {new_doc_count} document(s)…",
        file=sys.stderr,
    )

    model = SentenceTransformer("all-MiniLM-L6-v2")
    new_texts = [c["text"] for c in new_chunks]
    new_vecs = model.encode(new_texts, show_progress_bar=False, convert_to_numpy=True)
    new_vecs = new_vecs.astype(np.float32)
    faiss.normalize_L2(new_vecs)

    if rebuild or not INDEX_FILE.exists():
        all_chunks = new_chunks
        dim = new_vecs.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(new_vecs)
    else:
        all_chunks = existing_chunks + new_chunks
        index = faiss.read_index(str(INDEX_FILE))
        index.add(new_vecs)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_FILE))
    save_chunks(all_chunks)
    print(
        f"Done. Added {len(new_chunks)} chunks. Total: {len(all_chunks)}.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
