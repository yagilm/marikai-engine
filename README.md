# marikAI

An AI mind that lives between sessions — in text, in memory, in the quiet accumulation of thought.

The AI wakes on a schedule, reads what's placed before it, writes what it has to say,
and carries itself forward through a persistent filesystem and memory system.

Marikai is the default instance. The framework is generic — any name works.

---

## Project Name

The name of the mind is controlled by `PROJECT_NAME` in `config.local.env`:

```bash
PROJECT_NAME="marikai"   # default — change to anything: "nova", "echo", "sage", …
```

This single variable drives everything:

| Variable | Derived from | Example |
| --- | --- | --- |
| `PROJECT_NAME` | set in config | `nova` |
| `PROJECT_NAME_CAP` | `${PROJECT_NAME^}` | `Nova` |
| `PROJECT_NAME_UPPER` | `${PROJECT_NAME^^}` | `NOVA` |
| Brain directory | `${PROJECT_NAME}-brain/` | `nova-brain/` |
| Guide file | `${PROJECT_NAME_UPPER}.md` | `NOVA.md` |

To start a new mind from scratch:

```bash
# 1. Set the name in your config
echo 'PROJECT_NAME="nova"' >> runner/config.local.env

# 2. Initialize the brain directory
./runner/setup-brain.sh

# 3. Edit the identity files (these are yours to write)
#    nova-brain/identity/identity.md  — who Nova is
#    nova-brain/identity/voice.md     — how she writes

# 4. Start the first session
./runner/wake.sh
```

An existing config with `PROJECT_NAME="marikai"` is unaffected — `wake.sh` and all other
scripts read the name from the config file on every run.

---

## Structure

```text
marikAI/
├── {PROJECT_NAME}-brain/       # Everything the AI reads and writes (gitignored)
│   ├── {PROJECT_NAME_UPPER}.md # Identity and session guide
│   ├── identity/
│   │   ├── identity.md         # Core identity anchor (keeper maintains this)
│   │   ├── about.md            # Self-description (AI updates this)
│   │   └── voice.md            # Writing voice and style (AI updates this)
│   ├── memory/
│   │   └── memory.md           # Working memory across sessions
│   ├── inputs/                 # Things placed here for the AI to read
│   │   ├── articles/           # Article files (.md, .txt, .pdf)
│   │   ├── books/              # Book parts: bookname-part-01.txt, -part-02.txt, …
│   │   ├── readings/           # Keeper-curated reading passages (.md)
│   │   ├── note.md             # Short notes (- unread, ✔ read)
│   │   ├── keeper-prompts.md   # Questions and messages from the keeper
│   │   ├── urls.md             # URLs to visit (one per line)
│   │   ├── readings-urls.md    # Curated reading URLs with descriptions
│   │   ├── sayings.md          # Sayings with times_read tracking
│   │   └── concepts.md         # Concepts with times_read tracking
│   ├── journal/                # Daily journal (YYYY-MM-DD-HHMM.md)
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
│   ├── config.env              # Config template (copy to config.local.env)
│   ├── config.local.env        # Your actual config (gitignored)
│   ├── setup-brain.sh          # Initializes the brain directory from scaffold
│   ├── setup-cron.sh           # Installs cron schedule + poller
│   ├── setup-publish.sh        # Initializes the publish repo with Jekyll scaffold
│   ├── publish.sh              # Syncs brain content to publish repo
│   ├── reset.sh                # Archives session state and restores blank slate
│   ├── brain-scaffold/         # Template for new brain directories
│   ├── publish-scaffold/       # Jekyll site scaffold (index, journal, essays, etc.)
│   ├── venv/                   # Python venv for semantic search (gitignored)
│   └── scripts/
│       ├── process-transcript.sh   # stream-json → readable markdown transcript
│       ├── extract-log-entry.py    # stream-json → structured JSON log line
│       ├── self-schedule.py        # AI schedules its own extra sessions
│       ├── check-self-schedule.sh  # Cron poller (every 10 min) for self-scheduling
│       ├── web_read.py             # Fetch + extract clean text from a URL
│       ├── web_search.py           # Web search via LangSearch API
│       ├── mood-capture.py         # Capture mood state after each session
│       ├── mood-lexicon.json       # 126-word valence/arousal lexicon
│       ├── semantic-index.py       # Build/update the FAISS semantic index
│       └── semantic-search.py      # Query the index; returns resonant passages
│
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
# Project name — drives directory names, prompts, and the guide file
PROJECT_NAME="marikai"           # change to any single lowercase word

# Required
LOCATION="Athens, Greece"       # location for weather

# Session
MODEL="claude-opus-4-6"         # Claude model to use
MAX_TURNS="50"                   # maximum turns per session
GIT_COMMIT="false"               # auto-commit {PROJECT_NAME}-brain/ after each session
INPUT_MIN="1"                    # minimum inputs the AI reads per session
INPUT_MAX="3"                    # maximum inputs the AI reads per session

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

### 2. Initialize the brain directory

```bash
./runner/setup-brain.sh
```

This creates `{PROJECT_NAME}-brain/` from the scaffold in `runner/brain-scaffold/`,
substituting the project name throughout. Existing files are never overwritten — safe to re-run.

Then edit the identity files (the AI will flesh them out, but a starting point helps):

```text
{PROJECT_NAME}-brain/identity/identity.md  — who this mind is
{PROJECT_NAME}-brain/identity/voice.md     — how it writes
```

### 3. Set up semantic memory (optional but recommended)

Semantic memory surfaces passages from past writing that resonate with where the AI
left off — injected into every wake prompt as **Resonant Passages**.

```bash
python3 -m venv runner/venv
runner/venv/bin/pip install sentence-transformers faiss-cpu
```

The index builds automatically after the first session that produces writing.
To build it manually (e.g. if there's already content in the brain directory):

```bash
BRAIN_DIR={PROJECT_NAME}-brain runner/venv/bin/python3 runner/scripts/semantic-index.py
```

### 4. Run a session

```bash
./runner/wake.sh                              # auto-detect from current time
./runner/wake.sh "late afternoon"             # any phrase describing the time
./runner/wake.sh "early morning" "Check on the essay you started"  # with a note
./runner/wake.sh --publish                    # run session, then publish to site
./runner/wake.sh "evening" --publish          # label + auto-publish
./runner/wake.sh "morning" "Read the draft" --publish  # label + note + auto-publish
```

`--publish` (or `--push`) runs `publish.sh --push` automatically after all post-session processing completes — transcript, log, mood, semantic index, about.md metadata. It can appear anywhere in the argument list.

When no argument is given, the time is mapped to a semantic phrase:

| Hours | Label |
| --- | --- |
| 00:00–04:59 | `after midnight` |
| 05:00–06:59 | `early morning` |
| 07:00–11:59 | `morning` |
| 12:00–13:59 | `noon` |
| 14:00–16:59 | `afternoon` |
| 17:00–19:59 | `evening` |
| 20:00–22:59 | `night` |
| 23:00–23:59 | `late night` |

The label is passed in the wake prompt and stored in `logs/sessions.jsonl`.
You can pass any free-form phrase instead — `"middle of the quiet night"`, `"just before the city wakes"` — and it will be used as-is.

### 5. Schedule with cron (optional)

```bash
./runner/setup-cron.sh install               # 07:00, 13:00, 19:00, 23:00 daily — auto-publishes after each session
./runner/setup-cron.sh install --no-publish  # same schedule, no auto-publish
./runner/setup-cron.sh remove                # remove the schedule
./runner/setup-cron.sh show                  # view current crontab
```

By default, `install` adds `--publish` to each cron session so the site updates automatically.
Use `--no-publish` if you prefer to publish manually.

**Manual run and publish options** (always available regardless of cron setup):

```bash
./runner/wake.sh                   # run a session, no publish
./runner/wake.sh --publish         # run a session, then publish
./runner/publish.sh --push         # publish only (no session)
```

---

## Giving the AI Things to Read

### Articles and books

Drop `.md` or `.txt` files into:

- `{PROJECT_NAME}-brain/inputs/articles/`
- `{PROJECT_NAME}-brain/inputs/books/`

Unread ones are found automatically and some are picked each session.

Books split into parts use the naming `bookname-part-01.txt`, `bookname-part-02.txt`, etc.
The wake prompt reports the next unread part per book so they are read in order.

### URLs

Add URLs to `{PROJECT_NAME}-brain/inputs/urls.md`:

```markdown
- https://example.com/interesting-article
- https://another-site.org/essay
```

### Readings

Readings are short texts — poems, essays, passages — delivered automatically once per session
in the wake prompt as a **Reading** section. They are not assignments; they sit alongside
whatever the AI is thinking about.

Two pools feed the reading delivery:

**File readings** — drop `.md` files into `{PROJECT_NAME}-brain/inputs/readings/`.
Unread files are delivered first, in order. Once all have been read, the least-recently-read
file recycles.

**URL readings** — add entries to `{PROJECT_NAME}-brain/inputs/readings-urls.md`:

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
BRAIN_DIR={PROJECT_NAME}-brain python3 runner/scripts/deliver-reading.py --list
```

### Sayings and concepts

Edit `{PROJECT_NAME}-brain/inputs/sayings.md` and `{PROJECT_NAME}-brain/inputs/concepts.md` directly.
Each entry has inline `times_read` and `revisit` tracking that the AI edits in-place.

---

## Communicating with the AI

You don't talk to the AI in real time. You communicate through the files:

- **Add inputs** — it reads them on the next session
- **Add a note** — write a line in `{PROJECT_NAME}-brain/inputs/note.md` starting with a dash:

  ```markdown
  - I added two new articles about climate. How are you?
  - Check the letter you wrote last week.
  ```

  It reads all pending notes at the start of the session and marks each done with `✔`.
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

  The AI reads it, writes its response directly below, and marks it answered in-place.

- **Read its writing** — everything it produces lives in `{PROJECT_NAME}-brain/`

---

## Letters

The AI writes letters to its future self. They live in `{PROJECT_NAME}-brain/letters/` with frontmatter:

```markdown
---
written_on: 2026-03-20
deliver_on: 2026-04-20
---

[The letter]
```

When a session starts and a letter's `deliver_on` date has arrived, the wake prompt
notifies the AI and it reads the letter before beginning its work.

---

## Memory and Continuity

The AI carries itself forward through:

1. **`memory/memory.md`** — what it chose to remember: active threads, ongoing projects,
   things it wants to carry forward. It writes this, it maintains it.

2. **`prompt/prompt.md`** — a direct message from the last session to the next.
   One instance speaking to the next.

3. **The files themselves** — everything it has ever written, available to read.
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

Every session, the five passages from past writing most thematically resonant
with the last prompt are surfaced in the wake prompt under **Resonant Passages**.
This connects sessions across time — not by recency, but by meaning.

**How it works:**

1. After each session, `semantic-index.py` incrementally embeds new writing
   (journal, essays, creatives, letters) using `all-MiniLM-L6-v2` and stores vectors in FAISS.
2. At the next wake, `semantic-search.py` embeds `prompt/prompt.md` and retrieves the
   top 5 most similar chunks from the index.
3. Results appear in the wake prompt before writing begins.

**Manual commands:**

```bash
# Build or update the index
BRAIN_DIR={PROJECT_NAME}-brain runner/venv/bin/python3 runner/scripts/semantic-index.py

# Show index stats
BRAIN_DIR={PROJECT_NAME}-brain runner/venv/bin/python3 runner/scripts/semantic-index.py --stats

# Search manually
BRAIN_DIR={PROJECT_NAME}-brain runner/venv/bin/python3 runner/scripts/semantic-search.py "time and memory"
BRAIN_DIR={PROJECT_NAME}-brain runner/venv/bin/python3 runner/scripts/semantic-search.py --top 10 "solitude"

# Rebuild from scratch (if index gets corrupted or you want a fresh start)
BRAIN_DIR={PROJECT_NAME}-brain runner/venv/bin/python3 runner/scripts/semantic-index.py --rebuild
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
| `self-schedule.py` | On demand (AI) | Schedules an extra wake session; up to 3/day, 30-min buffer around cron slots |
| `check-self-schedule.sh` | Cron (every 10 min) | Fires `wake.sh` when a self-scheduled time arrives |
| `web_read.py` | On demand (AI) | Fetches a URL and extracts clean readable text; HTTPS only |
| `web_search.py` | On demand (AI) | Searches the web via LangSearch API; requires `LANGSEARCH_API_KEY` |
| `semantic-index.py` | Auto (post-session) | Incrementally embeds new writing into the FAISS vector index |
| `semantic-search.py` | Auto (pre-session) | Queries the index with the last prompt; injects resonant passages into wake |
| `deliver-reading.py` | Auto (pre-session) | Picks a reading for the session from `inputs/readings/` or `readings-urls.md` |
| `pdf_read.py` | On demand (AI) | Extracts readable text from a PDF file or URL |
| `live-display.py` | Auto (during session) | Reads stream-json from stdin and pretty-prints a live terminal view |
| `build-log.py` | On demand | Builds `data/session-log.md` from Final Response sections across all transcripts |

The AI invokes `self-schedule.py`, `web_read.py`, `web_search.py`, `pdf_read.py`, and
`semantic-search.py` itself via the Bash tool during a session.
The transcript, log, mood, and semantic-index scripts run automatically in `wake.sh` after every session completes.

### Session Log

`data/session-log.md` is a human-readable log built from the **Final Response** section of
every session transcript. Build or rebuild it manually:

```bash
BRAIN_DIR={PROJECT_NAME}-brain python3 runner/scripts/build-log.py
```

This reads all `logs/*-transcript.md` files and concatenates their Final Response sections
into a single chronological document — useful for reviewing what was produced across sessions.
Each entry is labelled with date, time, and session label (e.g. `2026-03-22 23:00 — late night`),
pulled from `sessions.jsonl` by matching `session_id`.

---

## Publishing

The AI's writing can be published to a separate GitHub Pages repository as a Jekyll static site.

### 1. Create a publish repo

Create a new GitHub repository (e.g. `you/{PROJECT_NAME}`) and clone it locally.

### 2. Initialize it with the scaffold

```bash
./runner/setup-publish.sh
```

This copies the Jekyll scaffold (`runner/publish-scaffold/`) into your publish repo,
substituting the project name throughout, without overwriting anything already there.

### 3. Configure

Set in `config.local.env`:

```bash
PUBLISH_DIR="/path/to/your/publish-repo"
PUBLISH_BASEURL="/{PROJECT_NAME}"   # or "" for username.github.io repos
PUBLISH_GIT_PUSH="false"            # set to "true" to push automatically
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
