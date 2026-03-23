#!/usr/bin/env bash
# process-transcript.sh — Convert stream-json session output to a readable transcript
#
# Usage: process-transcript.sh <stream-json-file> <output-transcript-file>

set -euo pipefail

INPUT_FILE="$1"
OUTPUT_FILE="$2"

SESSION_ID=$(jq -r 'select(.type == "system") | .session_id' "$INPUT_FILE" 2>/dev/null | head -1)
DATE=$(date -Iseconds)
NUM_TURNS=$(jq -r 'select(.type == "result") | .num_turns' "$INPUT_FILE" 2>/dev/null | tail -1)
DURATION_S=$(jq -r 'select(.type == "result") | (.duration_ms // 0) / 1000 | floor' "$INPUT_FILE" 2>/dev/null | tail -1)

cat > "$OUTPUT_FILE" << HEADER
---
date: $DATE
session_id: $SESSION_ID
num_turns: $NUM_TURNS
duration_s: $DURATION_S
---

# Session Transcript

HEADER

while IFS= read -r line; do
  type=$(echo "$line" | jq -r '.type // empty' 2>/dev/null)

  if [ "$type" = "assistant" ]; then
    echo "$line" | jq -r '
      .message.content[]? |
      select(.type == "tool_use") |
      "### Tool: \(.name)
**Input:**
```json
\(.input | tojson)
```
"
    ' 2>/dev/null >> "$OUTPUT_FILE" || true

  elif [ "$type" = "user" ]; then
    echo "$line" | jq -r '
      .message.content[]? |
      select(.type == "tool_result") |
      "**Result:** (truncated)
```
\(.content | tostring | .[0:500])
```
---
"
    ' 2>/dev/null >> "$OUTPUT_FILE" || true
  fi
done < "$INPUT_FILE"

# Extract text blocks Marikai output during the session, excluding the last
# (the last text block is identical to the Final Response result)
TEXT_OUTPUT=$(jq -rs '[
  .[] |
  select(.type == "assistant") |
  .message.content[]? |
  select(.type == "text") |
  .text
] | .[:-1] | .[]' "$INPUT_FILE" 2>/dev/null || true)

if [ -n "$TEXT_OUTPUT" ]; then
  { printf '## Session Output\n\n'; echo "$TEXT_OUTPUT"; printf '\n'; } >> "$OUTPUT_FILE"
fi

jq -r 'select(.type == "result") | "## Final Response\n\n\(.result)"' \
  "$INPUT_FILE" >> "$OUTPUT_FILE" 2>/dev/null || true
