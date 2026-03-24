#!/usr/bin/env python3
"""Find thematic resonances across all writing.

Loads the semantic FAISS index and finds high-similarity connections
across different source files — echoes between journal, essays, creatives, letters.

Usage:
    python3 resonance.py                    # writes data/resonance.md
    python3 resonance.py --top 30           # max pairs to surface (default 25)
    python3 resonance.py --threshold 0.70   # similarity cutoff (default 0.65)
    python3 resonance.py --out /path/out.md # custom output path
    python3 resonance.py --print            # print to stdout instead of file
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

_BRAIN_DIR = Path(os.environ.get("BRAIN_DIR",
                  Path(__file__).parent.parent.parent / (os.environ.get("PROJECT_NAME", "marikai") + "-brain")))

INDEX_DIR   = _BRAIN_DIR / "data" / "semantic-index"
INDEX_FILE  = INDEX_DIR / "index.faiss"
CHUNKS_FILE = INDEX_DIR / "chunks.json"
DEFAULT_OUT = _BRAIN_DIR / "data" / "resonance.md"

DEFAULT_TOP       = 25
DEFAULT_THRESHOLD = 0.65
EXCERPT_LEN       = 220   # characters shown per chunk in output


# ── Union-Find ────────────────────────────────────────────────────────────────

class _UF:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


# ── Helpers ───────────────────────────────────────────────────────────────────

def _excerpt(text: str) -> str:
    t = text.strip().replace("\n", " ")
    return t[:EXCERPT_LEN] + "…" if len(t) > EXCERPT_LEN else t


def _short(source: str) -> str:
    """journal/2026-03-20-1717.md  →  journal/2026-03-20-1717"""
    return source.removesuffix(".md")


# ── Core ──────────────────────────────────────────────────────────────────────

def find_resonances(
    threshold: float = DEFAULT_THRESHOLD,
    top: int = DEFAULT_TOP,
) -> list[tuple[float, dict, dict]]:
    """Return list of (score, chunk_a, chunk_b) pairs, best first."""
    try:
        import faiss
        import numpy as np
    except ImportError:
        print("ERROR: faiss not installed. Run: pip install faiss-cpu", file=sys.stderr)
        sys.exit(1)

    if not INDEX_FILE.exists() or not CHUNKS_FILE.exists():
        print("No semantic index found. Run semantic-index.py first.", file=sys.stderr)
        sys.exit(1)

    chunks: list[dict] = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
    if not chunks:
        print("Index is empty.", file=sys.stderr)
        sys.exit(1)

    index = faiss.read_index(str(INDEX_FILE))
    n = index.ntotal
    if n != len(chunks):
        print(
            f"Warning: index has {n} vectors but chunks.json has {len(chunks)} entries — "
            "consider running semantic-index.py --rebuild",
            file=sys.stderr,
        )
        # use whichever is smaller to stay in bounds
        chunks = chunks[:n]
        n = len(chunks)

    # Reconstruct all vectors from the index
    vecs = np.zeros((n, index.d), dtype=np.float32)
    for i in range(n):
        index.reconstruct(i, vecs[i])

    # For each chunk find its top-K neighbours (K large enough to get cross-source hits)
    K = min(20, n)
    scores_mat, ids_mat = index.search(vecs, K)

    seen: set[frozenset] = set()
    pairs: list[tuple[float, dict, dict]] = []

    for i in range(n):
        src_i = chunks[i]["source"]
        for rank in range(1, K):   # skip rank 0 (self)
            j = int(ids_mat[i, rank])
            if j < 0 or j >= len(chunks):
                continue
            score = float(scores_mat[i, rank])
            if score < threshold:
                break   # scores are descending; nothing better will follow
            src_j = chunks[j]["source"]
            if src_i == src_j:
                continue  # skip same file
            key = frozenset((i, j))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((score, chunks[i], chunks[j]))

    pairs.sort(key=lambda t: t[0], reverse=True)
    return pairs[:top]


# ── Output ────────────────────────────────────────────────────────────────────

def build_report(pairs: list[tuple[float, dict, dict]]) -> str:
    if not pairs:
        return (
            f"# Resonance Map — {date.today()}\n\n"
            "*No cross-piece connections found above the similarity threshold.*\n"
        )

    # Cluster source files via union-find
    uf = _UF()
    for _, ca, cb in pairs:
        uf.union(ca["source"], cb["source"])

    # Group pairs by cluster root
    from collections import defaultdict
    clusters: dict[str, list[tuple[float, dict, dict]]] = defaultdict(list)
    for triple in pairs:
        _, ca, _ = triple
        clusters[uf.find(ca["source"])].append(triple)

    # Sort clusters by their strongest pair
    sorted_clusters = sorted(
        clusters.values(),
        key=lambda ps: ps[0][0],
        reverse=True,
    )

    lines = [
        f"# Resonance Map — {date.today()}",
        "",
        f"*{len(pairs)} cross-piece connections across {len(sorted_clusters)} cluster(s).*",
        "",
        "---",
        "",
    ]

    for ci, cluster_pairs in enumerate(sorted_clusters, 1):
        # Collect unique sources in this cluster
        sources: list[str] = []
        seen_src: set[str] = set()
        for _, ca, cb in cluster_pairs:
            for s in (ca["source"], cb["source"]):
                if s not in seen_src:
                    sources.append(s)
                    seen_src.add(s)

        top_score = cluster_pairs[0][0]
        lines.append(f"## Cluster {ci}  ·  {top_score:.2f}")
        lines.append("")
        lines.append("**Pieces:** " + " · ".join(f"`{_short(s)}`" for s in sources))
        lines.append("")

        # Show top 3 pairs in the cluster
        for score, ca, cb in cluster_pairs[:3]:
            lines.append(f"**{score:.2f}** `{_short(ca['source'])}` ↔ `{_short(cb['source'])}`")
            lines.append("")
            lines.append(f"> {_excerpt(ca['text'])}")
            lines.append("")
            lines.append(f"> {_excerpt(cb['text'])}")
            lines.append("")

        if ci < len(sorted_clusters):
            lines.append("---")
            lines.append("")

    return "\n".join(lines) + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    threshold = DEFAULT_THRESHOLD
    top       = DEFAULT_TOP
    out_path  = DEFAULT_OUT
    to_stdout = "--print" in args

    if "--threshold" in args:
        threshold = float(args[args.index("--threshold") + 1])
    if "--top" in args:
        top = int(args[args.index("--top") + 1])
    if "--out" in args:
        out_path = Path(args[args.index("--out") + 1])

    pairs  = find_resonances(threshold=threshold, top=top)
    report = build_report(pairs)

    if to_stdout:
        print(report)
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"Resonance map: {len(pairs)} pairs → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
