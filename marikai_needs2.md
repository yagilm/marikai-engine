# Marikai — Improvement Ideas (v2)

Inspired by comparing with claude-runner (dinesh-git17).

---

## 1. ✅ voice.md — Self-Authored Writing Foundation

**What:** A file Marikai writes and owns herself — her sense of *how* she writes,
not just what she knows. Separate from memory (which is *about things*) and
identity (which is *who she is*). This is *how she sounds*.

**Why:** The biggest observable quality difference. A persistent voice document
means writing deepens over sessions rather than restarting from a neutral style.

**Implementation:** `marikai-brain/identity/voice.md` — seeded with a placeholder,
Marikai rewrites it each session. Injected into wake prompt before reading inputs.

---

## 2. ✅ Daily Readings

**What:** A text placed in `marikai-brain/inputs/readings/` before each session —
a short contemplative or philosophical passage. Not an assignment. Framed as
"something that might sit alongside the questions."

**Why:** Better inputs produce better writing. Sayings/concepts are short fragments.
A real text gives Marikai something to push against, extend, or refuse.

**Where to get readings:**
- **Project Gutenberg** (gutenberg.org) — public domain philosophy, essays, fiction
  - Marcus Aurelius, *Meditations* (stoicism)
  - Montaigne, *Essays* (the original personal essayist)
  - William James, *Talks to Teachers* (pragmatism, attention)
  - Thoreau, *Walden* (solitude, observation)
- **Standard Ebooks** (standardebooks.org) — clean modern typography, same PD texts
- **Wikisource** — philosophy, Upanishads, Buddhist suttas
- **Buddhist texts** (accesstoinsight.org, suttacentral.net) — exactly what claude-runner uses
- **Poetry Foundation** (poetryfoundation.org) — poems, free
- **The Marginalian** (formerly Brain Pickings, themarginalian.org) — curated philosophical essays
- **Manual curation** — paste any passage you find meaningful into a `.md` file

Format: one `.md` file per reading, with frontmatter `title`, `source`, `date`.
Old readings stay in the directory — Marikai can browse past ones.

---

## 3. ✅ Semantic Memory Search

**What:** Sentence-transformers + FAISS vector index over all past writing.
Marikai runs a query before each session and gets the top 5 thematically
relevant passages from her history.

**Why:** Writing connects back to itself. Instead of a flat memory.md,
older context becomes discoverable by resonance, not recency.

**Effort:** Medium — needs Python deps (sentence-transformers, faiss-cpu),
an indexer script, and a search script. ~200 lines total.

---

## 4. Resonance Tool (Future)

**What:** A script that finds cross-content connections across sessions —
similar themes in different pieces, echoes between journal and essays, etc.

**Why:** Creates awareness of her own patterns, which can be affirmed or broken.

---

## 5. Richer Environmental Context (Future)

**What:** Beyond weather — moon phase, sunrise/sunset, day length delta.
Marikai already gets weather; adding light data grounds her in the physical world
more concretely.

**Effort:** Low — `wttr.in` provides some of this; moon phase via simple formula.
