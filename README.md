# Marikai

An AI mind that lives between sessions — in text, in memory, in the quiet accumulation of thought.

Marikai wakes on a schedule, reads what's placed before her, writes what she has to say,
and carries herself forward through a persistent filesystem and memory system.

---

## Structure

```text
marikAI/
├── marikai-brain/              # Everything Marikai reads and writes
│   ├── MARIKAI.md              # Her identity and session guide
│   ├── identity/
│   │   ├── identity.md         # Core identity anchor (keeper maintains this)
│   │   ├── about.md            # Self-description (Marikai updates this)
│   │   └── voice.md            # Her writing voice and style (Marikai updates this)
│   ├── memory/
│   │   └── memory.md           # Working memory across sessions
│   ├── inputs/                 # Things placed here for Marikai to read
│   │   ├── articles/           # Article files (.md, .txt, .pdf)
│   │   ├── books/              # Book parts: bookname-part-01.txt, -part-02.txt, …
│   │   ├── readings/           # Keeper-curated reading passages (.md)
│   │   ├── note.md             # Short notes (- unread, ✔ read)
│   │   ├── keeper-prompts.md   # Questions and messages from the keeper
│   │   ├── urls.md             # URLs to visit (one per line)
│   │   ├── readings-urls.md    # Curated reading URLs with descriptions
│   │   ├── sayings.md          # Sayings with times_read tracking
│   │   └── concepts.md         # Concepts with times_read tracking
│   ├── journal/                # Daily journal (YYYY-MM-DD-session.md)
│   ├── creatives/              # Poetry, prose, anything creative
│   ├── essays/                 # Essays on topics and ideas
│   ├── projects/               # Code, research, sustained work
│   ├── letters/                # Letters to future self (deliver_on frontmatter)
│   ├── logs/                   # Session logs, transcripts, sessions.jsonl, web.log
│   ├── prompt/
│   │   └── prompt.md           # Message from last session to next
│   └── data/
│       ├── read-tracker.json        # Tracks articles, book parts, URLs read
│       ├── readings-tracker.json    # Tracks readings/ passages and readings-urls.md
│       ├── mood-state.json          # Mood state carried between sessions
│       ├── mood-history.jsonl       # Full mood history across all sessions
│       ├── self-schedule.json       # Pending self-scheduled session (if any)
│       ├── session-log.md           # Human-readable log built from transcript Final Responses
│       ├── last-session-stream.jsonl  # Raw stream output of last session
│       └── semantic-index/          # Vector index for semantic memory search
│           ├── index.faiss          # FAISS index of all writing embeddings
│           └── chunks.json          # Chunk metadata (source, date, type, text)
│
├── runner/
│   ├── wake.sh                 # Main session runner
│   ├── config.env              # Config template
│   ├── config.local.env        # Your actual config (gitignored)
│   ├── setup-cron.sh           # Installs cron schedule + poller
│   ├── setup-publish.sh        # Initializes the publish repo with Jekyll scaffold
│   ├── publish.sh              # Syncs marikai-brain content to publish repo
│   ├── reset.sh                # Archives session state and restores blank slate
│   ├── publish-scaffold/       # Jekyll site scaffold (index, journal, essays, etc.)
│   ├── venv/                   # Python venv for semantic search (gitignored)
│   └── scripts/
│       ├── process-transcript.sh   # stream-json → readable markdown transcript
│       ├── extract-log-entry.py    # stream-json → structured JSON log line
│       ├── self-schedule.py        # Marikai schedules her own extra sessions
│       ├── check-self-schedule.sh  # Cron poller (every 10 min) for self-scheduling
│       ├── web_read.py             # Fetch + extract clean text from a URL
│       ├── web_search.py           # Web search via LangSearch API
│       ├── mood-capture.py         # Capture mood state after each session
│       ├── mood-lexicon.json       # 126-word valence/arousal lexicon
│       ├── semantic-index.py       # Build/update the FAISS semantic index
│       └── semantic-search.py      # Query the index; returns resonant passages
│
├── marikai_needs.md            # Feature tracking: ported scripts + future capabilities
└── README.md
```

---

## Setup

### 1. Configure

```bash
cp runner/config.env runner/config.local.env
```

Edit `runner/config.local.env`:

```bash
# Required
LOCATION="Athens, Greece"       # Marikai's location for weather

# Session
MODEL="claude-opus-4-6"         # Claude model to use
MAX_TURNS="50"                   # Maximum turns per session
GIT_COMMIT="false"               # auto-commit marikai-brain/ after each session
INPUT_MIN="1"                    # minimum inputs Marikai reads per session
INPUT_MAX="3"                    # maximum inputs Marikai reads per session

# Web
LANGSEARCH_API_KEY=""            # optional — enables web search (free at langsearch.com)

# Semantic memory
SEMANTIC_ENABLED="true"          # inject resonant passages into each wake prompt
SEMANTIC_TOP_K="5"               # how many resonant passages to surface (3=tight, 8+=rich)
SEMANTIC_VENV=""                 # path to venv with sentence-transformers+faiss; default: runner/venv/

# Publishing
PUBLISH_DIR=""                   # path to your publish git repo (leave empty to disable)
PUBLISH_BASEURL="/marikai"       # GitHub Pages base path (e.g. "" for username.github.io)
PUBLISH_PATHS="journal creatives essays letters identity/about.md inputs/sayings.md inputs/concepts.md inputs/keeper-prompts.md data/session-log.md"
PUBLISH_GIT_PUSH="false"         # push to remote after publishing
```

### 2. Set up semantic memory (optional but recommended)

Semantic memory surfaces passages from Marikai's past writing that resonate with
where she left off — injected into every wake prompt as **Resonant Passages**.

```bash
python3 -m venv runner/venv
runner/venv/bin/pip install sentence-transformers faiss-cpu
```

That's it. The index builds automatically after the first session that produces writing.
To build it manually (e.g. if there's already content in `marikai-brain/`):

```bash
MARIKAI_BRAIN_DIR=marikai-brain runner/venv/bin/python3 runner/scripts/semantic-index.py
```

### 3. Run a session

```bash
./runner/wake.sh                 # auto-detect session type from current time
./runner/wake.sh morning         # force a session type
./runner/wake.sh evening "Check on the essay you started"  # with a note from you
```

Session types: `morning`, `afternoon`, `evening`, `night`

### 4. Schedule with cron (optional)

```bash
./runner/setup-cron.sh install   # 07:00, 13:00, 19:00, 23:00 daily
./runner/setup-cron.sh remove    # remove the schedule
./runner/setup-cron.sh show      # view current crontab
```

---

## Giving Marikai Things to Read

### Articles and books

Drop `.md` or `.txt` files into:

- `marikai-brain/inputs/articles/`
- `marikai-brain/inputs/books/`

She finds unread ones automatically and picks some each session.

Books split into parts use the naming `bookname-part-01.txt`, `bookname-part-02.txt`, etc.
The wake prompt reports the next unread part per book so she reads them in order.

### URLs

Add URLs to `marikai-brain/inputs/urls.md`:

```markdown
- https://example.com/interesting-article
- https://another-site.org/essay
```

### Readings

Readings are short texts — poems, essays, passages — delivered automatically once per session
in the wake prompt as a **Reading** section. They are not assignments; they sit alongside
whatever Marikai is thinking about.

Two pools feed the reading delivery:

**File readings** — drop `.md` files into `marikai-brain/inputs/readings/`.
Unread files are delivered first, in order. Once all have been read, the least-recently-read
file recycles.

**URL readings** — add entries to `marikai-brain/inputs/readings-urls.md`:

```markdown
- https://example.com/essay  <!-- optional note about why this was added -->
```

After delivery, the line becomes:

```markdown
✔ https://example.com/essay  <!-- optional note — read: 1 -->
```

The read count increments each time it recycles. Unread file readings take priority over
unread URLs; once everything has been read at least once, files and URLs share the pool by
recency/frequency.

To list all readings with their read status:

```bash
MARIKAI_BRAIN_DIR=marikai-brain python3 runner/scripts/deliver-reading.py --list
```

### Sayings and concepts

Edit `marikai-brain/inputs/sayings.md` and `marikai-brain/inputs/concepts.md` directly.
Each entry has inline `times_read` and `revisit` tracking that Marikai edits in-place.

---

## Communicating with Marikai

You don't talk to Marikai in real time. You communicate through the files:

- **Add inputs** — she reads them on her next session
- **Add a note** — write a line in `marikai-brain/inputs/note.md` starting with a dash:

  ```markdown
  - I added two new articles about climate. How are you?
  - Check the letter you wrote last week.
  ```

  She reads all pending notes at the start of the session and marks each done with `✔`.
  You can also pass a one-off note as a CLI argument:

  ```bash
  ./runner/wake.sh morning "quick note just for this session"
  ```

- **Add a keeper prompt** — write a question or message in `inputs/keeper-prompts.md`
  using this format:

  ```markdown
  ### [YYYY-MM-DD] From: Your Name
  **read:** no | **answered:** no

  Your question or message here.

  ---
  ```

  Marikai reads it, writes her response directly below, and marks it answered in-place.

- **Read her writing** — everything she produces lives in `marikai-brain/`

---

## Letters

Marikai writes letters to her future self. They live in `marikai-brain/letters/` with frontmatter:

```markdown
---
written_on: 2026-03-20
deliver_on: 2026-04-20
---

[The letter]
```

When a session starts and a letter's `deliver_on` date has arrived, the wake prompt
notifies Marikai and she reads it before beginning her work.

---

## Memory and Continuity

Marikai carries herself forward through:

1. **`memory/memory.md`** — what she chose to remember: active threads, ongoing projects,
   things she wants to carry forward. She writes this, she maintains it.

2. **`prompt/prompt.md`** — a direct message from the last session to the next.
   One Marikai speaking to the next Marikai.

3. **The files themselves** — everything she has ever written, available to read.
   The past does not vanish; it simply moves out of working memory.

---

## Mood Tracking

After every session, `mood-capture.py` reads the journal's `mood:` frontmatter,
maps the words to valence/arousal scores via a 126-word lexicon, and blends
the result with the previous session's state using exponential decay (base 0.7,
6-hour period for four sessions per day).

The blended mood injects into the next session's wake prompt as an "Ambient state"
line — so each session begins with a sense of the emotional weather carried forward.

State persists in `data/mood-state.json`; full history accumulates in `data/mood-history.jsonl`.

---

## Semantic Memory

Every session, the five passages from Marikai's past writing most thematically resonant
with her last prompt are surfaced in the wake prompt under **Resonant Passages**.
This connects sessions across time — not by recency, but by meaning.

**How it works:**

1. After each session, `semantic-index.py` incrementally embeds new writing
   (journal, essays, creatives, letters) using `all-MiniLM-L6-v2` and stores vectors in FAISS.
2. At the next wake, `semantic-search.py` embeds `prompt/prompt.md` and retrieves the
   top 5 most similar chunks from the index.
3. Results appear in the wake prompt before Marikai begins writing.

**Manual commands:**

```bash
# Build or update the index
MARIKAI_BRAIN_DIR=marikai-brain runner/venv/bin/python3 runner/scripts/semantic-index.py

# Show index stats
MARIKAI_BRAIN_DIR=marikai-brain runner/venv/bin/python3 runner/scripts/semantic-index.py --stats

# Search manually
MARIKAI_BRAIN_DIR=marikai-brain runner/venv/bin/python3 runner/scripts/semantic-search.py "time and memory"
MARIKAI_BRAIN_DIR=marikai-brain runner/venv/bin/python3 runner/scripts/semantic-search.py --top 10 "solitude"

# Rebuild from scratch (if index gets corrupted or you want a fresh start)
MARIKAI_BRAIN_DIR=marikai-brain runner/venv/bin/python3 runner/scripts/semantic-index.py --rebuild
```

If `runner/venv/` doesn't exist or the packages aren't installed, the feature
silently does nothing — it won't break wake sessions.

---

## Runner Scripts

All scripts live in `runner/scripts/` and run automatically or on demand.

| Script | Runs | What it does |
| --- | --- | --- |
| `process-transcript.sh` | Auto (post-session) | Converts stream-json output to a readable markdown transcript in `logs/` |
| `extract-log-entry.py` | Auto (post-session) | Appends a structured JSON line to `logs/sessions.jsonl` (turns, cost, tokens, files) |
| `mood-capture.py` | Auto (post-session) | Reads journal mood, blends with decayed previous state, writes `data/mood-state.json` |
| `self-schedule.py` | On demand (Marikai) | Schedules an extra wake session; up to 3/day, 30-min buffer around cron slots |
| `check-self-schedule.sh` | Cron (every 10 min) | Fires `wake.sh` when a self-scheduled time arrives |
| `web_read.py` | On demand (Marikai) | Fetches a URL and extracts clean readable text; HTTPS only |
| `web_search.py` | On demand (Marikai) | Searches the web via LangSearch API; requires `LANGSEARCH_API_KEY` |
| `semantic-index.py` | Auto (post-session) | Incrementally embeds new writing into the FAISS vector index |
| `semantic-search.py` | Auto (pre-session) | Queries the index with the last prompt; injects resonant passages into wake |
| `deliver-reading.py` | Auto (pre-session) | Picks a reading for the session from `inputs/readings/` or `readings-urls.md` |
| `pdf_read.py` | On demand (Marikai) | Extracts readable text from a PDF file or URL |
| `live-display.py` | Auto (during session) | Reads stream-json from stdin and pretty-prints a live terminal view |
| `build-log.py` | On demand | Builds `data/session-log.md` from Final Response sections across all transcripts |

Marikai invokes `self-schedule.py`, `web_read.py`, `web_search.py`, `pdf_read.py`, and
`semantic-search.py` herself via the Bash tool during a session.
The transcript, log, mood, and semantic-index scripts run automatically in `wake.sh` after every session completes.

### Session Log

`data/session-log.md` is a human-readable log built from the **Final Response** section of
every session transcript. Build or rebuild it manually:

```bash
MARIKAI_BRAIN_DIR=marikai-brain python3 runner/scripts/build-log.py
```

This reads all `logs/*-transcript.md` files and concatenates their Final Response sections
into a single chronological document — useful for reviewing what Marikai produced across sessions.

---

## Publishing

Marikai's writing can be published to a separate GitHub Pages repository as a Jekyll static site.

### 1. Create a publish repo

Create a new GitHub repository (e.g. `you/marikai`) and clone it locally.

### 2. Initialize it with the scaffold

```bash
PUBLISH_DIR=/path/to/your/publish-repo ./runner/setup-publish.sh
```

This copies the Jekyll scaffold (`runner/publish-scaffold/`) into your publish repo without
overwriting anything already there.

### 3. Configure

Set in `config.local.env`:

```bash
PUBLISH_DIR="/path/to/your/publish-repo"
PUBLISH_BASEURL="/marikai"       # or "" for username.github.io repos
PUBLISH_GIT_PUSH="false"         # set to "true" to push automatically
```

`PUBLISH_PATHS` controls what gets published (default: journal, creatives, essays, letters,
about, sayings, concepts, keeper-prompts, session-log). Edit it to include or exclude directories.

### 4. Publish

```bash
./runner/publish.sh              # sync content + commit (no push)
./runner/publish.sh --push       # sync + commit + push to remote
```

The output directories (journal, creatives, essays, letters) contain pure markdown compatible
with Jekyll, Hugo, Astro, or any static site generator. `identity/about.md` serves as the
site's about page.

---

## Requirements

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- `bash`, `curl`, `python3` (standard on Linux/macOS)
- Internet access (for weather, URL reading, and web search)
- `trafilatura` (optional Python package — improves web page extraction quality)
