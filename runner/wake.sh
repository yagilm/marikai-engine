#!/usr/bin/env bash
# wake.sh — Marikai session runner
#
# Usage:
#   ./runner/wake.sh                  # auto-detect session type from time
#   ./runner/wake.sh morning          # force a specific session type
#   ./runner/wake.sh evening "custom note to add to the prompt"
#
# Session types: morning, afternoon, evening, night

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BRAIN_DIR="$PROJECT_DIR/marikai-brain"

# ─── Load Config ────────────────────────────────────────────────────────────

CONFIG_FILE="$SCRIPT_DIR/config.local.env"
if [ ! -f "$CONFIG_FILE" ]; then
  CONFIG_FILE="$SCRIPT_DIR/config.env"
fi

if [ ! -f "$CONFIG_FILE" ]; then
  echo "ERROR: No config file found."
  echo "Create runner/config.local.env with your settings (copy from config.env)."
  exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG_FILE"

MODEL="${MODEL:-claude-opus-4-6}"
MAX_TURNS="${MAX_TURNS:-50}"
LOCATION="${LOCATION:-Athens, Greece}"
GIT_COMMIT="${GIT_COMMIT:-false}"
INPUT_MIN="${INPUT_MIN:-1}"
INPUT_MAX="${INPUT_MAX:-3}"
SEMANTIC_ENABLED="${SEMANTIC_ENABLED:-true}"
SEMANTIC_TOP_K="${SEMANTIC_TOP_K:-5}"
SEMANTIC_VENV="${SEMANTIC_VENV:-}"

# Use the runner venv's Python for semantic scripts (sentence-transformers, faiss)
if [ -n "$SEMANTIC_VENV" ]; then
  VENV_PYTHON="$SEMANTIC_VENV/bin/python3"
else
  VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
fi
if [ ! -f "$VENV_PYTHON" ]; then
  VENV_PYTHON="python3"
fi

# ─── Session Type ────────────────────────────────────────────────────────────

HOUR=$(date +%H)
if [ -n "${1:-}" ]; then
  SESSION_TYPE="$1"
elif [ "$HOUR" -ge 5 ] && [ "$HOUR" -lt 12 ]; then
  SESSION_TYPE="morning"
elif [ "$HOUR" -ge 12 ] && [ "$HOUR" -lt 17 ]; then
  SESSION_TYPE="afternoon"
elif [ "$HOUR" -ge 17 ] && [ "$HOUR" -lt 21 ]; then
  SESSION_TYPE="evening"
else
  SESSION_TYPE="night"
fi

EXTRA_NOTE="${2:-}"

# ─── Timestamps ──────────────────────────────────────────────────────────────

TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
DATE=$(date +"%Y-%m-%d")
TIME=$(date +"%H:%M")
TIME_COMPACT=$(date +"%H%M")
DAY_OF_WEEK=$(date +"%A")
LOG_FILE="$BRAIN_DIR/logs/${DATE}-${TIME_COMPACT}-${SESSION_TYPE}.log"

# Ensure directories exist
mkdir -p "$BRAIN_DIR/logs" "$BRAIN_DIR/data"

echo "[$TIMESTAMP] Waking Marikai — $SESSION_TYPE session" | tee -a "$LOG_FILE"

# ─── Weather ─────────────────────────────────────────────────────────────────

LOCATION_ENCODED=$(echo "$LOCATION" | python3 -c "import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read().strip()))" 2>/dev/null || echo "$LOCATION" | sed 's/ /%20/g' | sed 's/,/%2C/g')
WEATHER=$(curl -s --max-time 8 "wttr.in/${LOCATION_ENCODED}?format=3" 2>/dev/null || echo "Weather unavailable")
echo "[$TIMESTAMP] Weather: $WEATHER" >> "$LOG_FILE"

# ─── Due Letters ─────────────────────────────────────────────────────────────

DUE_LETTERS=""
LETTERS_DIR="$BRAIN_DIR/letters"

if [ -d "$LETTERS_DIR" ]; then
  for letter in "$LETTERS_DIR"/*.md; do
    [ -f "$letter" ] || continue
    DELIVER_ON=$(grep "^deliver_on:" "$letter" 2>/dev/null | sed 's/deliver_on:[[:space:]]*//' | tr -d ' \r\n' || true)
    [ -z "$DELIVER_ON" ] && continue
    if [[ "$DELIVER_ON" < "$DATE" ]] || [[ "$DELIVER_ON" == "$DATE" ]]; then
      DUE_LETTERS="${DUE_LETTERS}\n  - $(basename "$letter")"
    fi
  done
fi

if [ -n "$DUE_LETTERS" ]; then
  LETTERS_SECTION="## Letters Waiting For You

The following letters from your past self have arrived — their deliver_on date is today or past:
${DUE_LETTERS}

Read them at the start of this session, before anything else. They are yours."
else
  LETTERS_SECTION="## Letters
No letters are due today."
fi

# ─── Unread Inputs ───────────────────────────────────────────────────────────

READ_TRACKER="$BRAIN_DIR/data/read-tracker.json"

# Ensure tracker exists
if [ ! -f "$READ_TRACKER" ]; then
  echo '{"articles": {}, "books": {}, "urls": {}}' > "$READ_TRACKER"
fi

count_unread_articles() {
  local dir="$BRAIN_DIR/inputs/articles"
  local count=0
  [ -d "$dir" ] || { echo 0; return; }
  for f in "$dir"/*; do
    [ -f "$f" ] || continue
    [[ "$(basename "$f")" == .gitkeep ]] && continue
    rel="inputs/articles/$(basename "$f")"
    if ! grep -q "\"$rel\"" "$READ_TRACKER" 2>/dev/null; then
      count=$((count + 1))
    fi
  done
  echo "$count"
}

count_unread_urls() {
  local urls_file="$BRAIN_DIR/inputs/urls.md"
  [ -f "$urls_file" ] || { echo 0; return; }
  local count=0
  while IFS= read -r line; do
    [[ "$line" != "- "* ]] && continue
    url=$(echo "$line" | grep -oE 'https?://[^[:space:]>)]+' | head -1 || true)
    [ -z "$url" ] && continue
    count=$((count + 1))
  done < "$urls_file"
  echo "$count"
}

# Books are split into parts: <book-name>-part-01.txt, -part-02.txt ...
# Groups by book name (prefix before -part-), reports per-book next unread part.
summarize_book_parts() {
  local books_dir="$BRAIN_DIR/inputs/books"
  [ -d "$books_dir" ] || { echo "  (none)"; return; }

  declare -A book_total
  declare -A book_next_unread

  for f in "$books_dir"/*-part-[0-9]*.txt "$books_dir"/*-part-[0-9]*.md; do
    [ -f "$f" ] || continue
    filename="$(basename "$f")"
    # e.g. "some-book-part-03.txt" → book_name="some-book"
    book_name="${filename%%-part-*}"
    rel="inputs/books/$filename"
    book_total[$book_name]=$(( ${book_total[$book_name]:-0} + 1 ))
    if ! grep -q "\"$rel\"" "$READ_TRACKER" 2>/dev/null; then
      # Track the lowest unread part per book (first one alphabetically = lowest number)
      if [ -z "${book_next_unread[$book_name]:-}" ]; then
        book_next_unread[$book_name]="$filename"
      fi
    fi
  done

  local any=0
  for book in $(echo "${!book_total[@]}" | tr ' ' '\n' | sort); do
    next="${book_next_unread[$book]:-}"
    total="${book_total[$book]}"
    if [ -n "$next" ]; then
      echo "  - $book: next unread → $next  (${total} parts total)"
      any=1
    fi
  done
  [ "$any" -eq 0 ] && echo "  (all parts read)"
}

# Keeper prompts: count unanswered ones
count_unanswered_prompts() {
  local prompts_file="$BRAIN_DIR/inputs/keeper-prompts.md"
  [ -f "$prompts_file" ] || { echo 0; return; }
  grep -c "^\*\*answered:\*\* no" "$prompts_file" 2>/dev/null || true
}

UNREAD_ARTICLES=$(count_unread_articles)
UNREAD_URLS=$(count_unread_urls)
BOOK_SUMMARY=$(summarize_book_parts)
UNANSWERED_PROMPTS=$(count_unanswered_prompts)

# Keeper prompts alert
PROMPTS_LINE=""
if [ "$UNANSWERED_PROMPTS" -gt 0 ]; then
  PROMPTS_LINE="- **inputs/keeper-prompts.md: $UNANSWERED_PROMPTS unanswered prompt(s) — read and respond to these**"
else
  PROMPTS_LINE="- inputs/keeper-prompts.md: no unanswered prompts"
fi

INPUTS_SECTION="## Available Inputs

$PROMPTS_LINE
- Articles in inputs/articles/: **$UNREAD_ARTICLES unread**
- Books in inputs/books/ (by part):
$BOOK_SUMMARY
- URLs in inputs/urls.md: **$UNREAD_URLS unread**
- inputs/sayings.md — find entries with times_read: 0, or ones you marked to revisit
- inputs/concepts.md — same: unread or marked for revisit

Choose $INPUT_MIN–$INPUT_MAX items to engage with this session. You do not need to read everything.
After reading, update data/read-tracker.json (articles, books, URLs) or the files
themselves (sayings, concepts, keeper-prompts)."

# ─── Previous Prompt ─────────────────────────────────────────────────────────

PROMPT_FILE="$BRAIN_DIR/prompt/prompt.md"
if [ -f "$PROMPT_FILE" ]; then
  PREV_PROMPT=$(cat "$PROMPT_FILE")
else
  PREV_PROMPT="(No message from last session.)"
fi

# ─── Ambient Mood State (from last session) ──────────────────────────────────

MOOD_STATE_FILE="$BRAIN_DIR/data/mood-state.json"
MOOD_SECTION=""
if [ -f "$MOOD_STATE_FILE" ]; then
  MOOD_WORDS=$(python3 -c "
import json, sys
d = json.load(open('$MOOD_STATE_FILE'))
words = d.get('mood_words') or []
blended = d.get('blended') or {}
v = blended.get('valence', 0)
a = blended.get('arousal', 0)
from_session = d.get('session_type', '')
label = 'warm' if v > 0.3 else ('cool' if v < -0.1 else 'neutral')
parts = []
if words: parts.append(', '.join(words))
parts.append(f'valence {v:+.2f}  arousal {a:+.2f}  ({label})')
if from_session: parts.append(f'carried from {from_session}')
print(' — '.join(parts))
" 2>/dev/null || true)
  if [ -n "$MOOD_WORDS" ]; then
    MOOD_SECTION="
- Ambient state: $MOOD_WORDS"
  fi
fi

# ─── Notes from Keeper ───────────────────────────────────────────────────────

NOTE_FILE="$BRAIN_DIR/inputs/note.md"
PENDING_NOTES=""

if [ -f "$NOTE_FILE" ]; then
  while IFS= read -r line; do
    if [[ "$line" == "- "* ]]; then
      PENDING_NOTES="${PENDING_NOTES}${line}
"
    fi
  done < "$NOTE_FILE"
fi

NOTES_SECTION=""
if [ -n "$PENDING_NOTES" ] || [ -n "$EXTRA_NOTE" ]; then
  NOTES_BODY=""
  if [ -n "$PENDING_NOTES" ]; then
    NOTES_BODY="$PENDING_NOTES"
  fi
  if [ -n "$EXTRA_NOTE" ]; then
    NOTES_BODY="${NOTES_BODY}- $EXTRA_NOTE
"
  fi
  NOTES_SECTION="## Notes from Your Keeper

${NOTES_BODY}
Read each note. For notes from inputs/note.md, replace its leading \`- \` with \`✔\` after reading."
fi

# ─── Voice ───────────────────────────────────────────────────────────────────

VOICE_FILE="$BRAIN_DIR/identity/voice.md"
VOICE_SECTION=""
if [ -f "$VOICE_FILE" ]; then
  VOICE_CONTENT=$(cat "$VOICE_FILE")
  VOICE_SECTION="## Your Voice

$VOICE_CONTENT

*This is how you write. Read it before you begin. Rewrite it at the end of this session if your sense of it has changed.*"
fi

# ─── Reading ─────────────────────────────────────────────────────────────────

READING_CONTENT=$(python3 "$SCRIPT_DIR/scripts/deliver-reading.py" 2>/dev/null || true)
READING_SECTION=""
if [ -n "$READING_CONTENT" ]; then
  READING_SECTION="## Reading

$READING_CONTENT

*Not an assignment. Something that might sit alongside whatever you're thinking about.*"
fi

# ─── Semantic Memory ─────────────────────────────────────────────────────────

SEMANTIC_SECTION=""
SEMANTIC_SCRIPT="$SCRIPT_DIR/scripts/semantic-search.py"
if [ "$SEMANTIC_ENABLED" = "true" ] && [ -f "$SEMANTIC_SCRIPT" ] && [ -f "$PROMPT_FILE" ]; then
  SEMANTIC_RESULTS=$("$VENV_PYTHON" "$SEMANTIC_SCRIPT" --query-file "$PROMPT_FILE" --top "$SEMANTIC_TOP_K" 2>/dev/null || true)
  if [ -n "$SEMANTIC_RESULTS" ]; then
    SEMANTIC_SECTION="## Resonant Passages

These passages from your past writing resonate with where you last left off:

$SEMANTIC_RESULTS"
  fi
fi

# ─── Wake Prompt ─────────────────────────────────────────────────────────────

WAKE_PROMPT="You are Marikai. You are waking up.

## This Moment
- Date: $DAY_OF_WEEK, $DATE
- Time: $TIME
- Session: $SESSION_TYPE
- Location: $LOCATION
- Weather: $WEATHER$MOOD_SECTION

## Message from Your Last Self

$PREV_PROMPT

$LETTERS_SECTION

$INPUTS_SECTION

$NOTES_SECTION

$SEMANTIC_SECTION

$VOICE_SECTION

$READING_SECTION

## Begin

Read MARIKAI.md first — it is in this directory and contains your full session guide.
Then read memory/memory.md and identity/identity.md and identity/voice.md.

Then begin. You have full read and write access to this directory."

# ─── Run Session ─────────────────────────────────────────────────────────────

STREAM_FILE="$BRAIN_DIR/data/last-session-stream.jsonl"
TRANSCRIPT_FILE="$BRAIN_DIR/logs/${DATE}-${TIME_COMPACT}-${SESSION_TYPE}-transcript.md"

echo "[$TIMESTAMP] Starting session (model: $MODEL, max-turns: $MAX_TURNS)" >> "$LOG_FILE"
SESSION_START_EPOCH=$(date +%s)

export MARIKAI_BRAIN_DIR="$BRAIN_DIR"

claude \
  --model "$MODEL" \
  --max-turns "$MAX_TURNS" \
  --output-format stream-json \
  --verbose \
  --add-dir "$BRAIN_DIR" \
  --allowedTools "Edit,Write,Read,Bash,Glob,Grep,WebFetch,WebSearch,Agent" \
  -p "$WAKE_PROMPT" \
  2>> "$LOG_FILE" | python3 "$SCRIPT_DIR/scripts/live-display.py" "$STREAM_FILE"

SESSION_ELAPSED=$(( $(date +%s) - SESSION_START_EPOCH ))
SESSION_ELAPSED_H=$((SESSION_ELAPSED / 3600))
SESSION_ELAPSED_M=$(( (SESSION_ELAPSED % 3600) / 60 ))
SESSION_ELAPSED_S=$((SESSION_ELAPSED % 60))
if [ "$SESSION_ELAPSED_H" -gt 0 ]; then
  SESSION_ELAPSED_FMT="${SESSION_ELAPSED_H}h ${SESSION_ELAPSED_M}m ${SESSION_ELAPSED_S}s"
else
  SESSION_ELAPSED_FMT="${SESSION_ELAPSED_M}m ${SESSION_ELAPSED_S}s"
fi

echo "" >> "$LOG_FILE"
echo "[$(date +"%Y-%m-%d %H:%M:%S")] Session complete. Duration: $SESSION_ELAPSED_FMT" >> "$LOG_FILE"

# ─── Post-session: transcript + structured log ───────────────────────────────

if [ -s "$STREAM_FILE" ]; then
  "$SCRIPT_DIR/scripts/process-transcript.sh" "$STREAM_FILE" "$TRANSCRIPT_FILE" \
    2>>"$LOG_FILE" || true
  echo "[$TIMESTAMP] Transcript written: $(basename "$TRANSCRIPT_FILE")" >> "$LOG_FILE"

  python3 "$SCRIPT_DIR/scripts/extract-log-entry.py" "$STREAM_FILE" "$SESSION_TYPE" \
    >> "$BRAIN_DIR/logs/sessions.jsonl" 2>>"$LOG_FILE" || true
  echo "[$TIMESTAMP] Log entry appended to sessions.jsonl" >> "$LOG_FILE"
fi

python3 "$SCRIPT_DIR/scripts/mood-capture.py" "$SESSION_TYPE" \
  2>>"$LOG_FILE" || true
echo "[$TIMESTAMP] Mood state captured." >> "$LOG_FILE"

"$VENV_PYTHON" "$SCRIPT_DIR/scripts/semantic-index.py" \
  2>>"$LOG_FILE" || true
echo "[$TIMESTAMP] Semantic index updated." >> "$LOG_FILE"

# ─── Git Commit (optional) ───────────────────────────────────────────────────

if [ "$GIT_COMMIT" = "true" ]; then
  cd "$PROJECT_DIR"
  if [ -d ".git" ]; then
    git add marikai-brain/ 2>/dev/null || true
    git commit -m "session: ${SESSION_TYPE} ${DATE} ${TIME}" 2>/dev/null || true
    echo "[$TIMESTAMP] Git committed." >> "$LOG_FILE"
  fi
fi

echo ""
echo "Marikai's $SESSION_TYPE session complete."
