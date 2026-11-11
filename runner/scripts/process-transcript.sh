#!/usr/bin/env bash
# process-transcript.sh — Convert stream-json session output to a readable transcript
#
# Usage: process-transcript.sh <stream-json-file> <output-transcript-file>
#
# Read tool results are normally shown as a short preview. Letters are special:
# the preview would expose the whole private letter, so the transcript records
# only which letter was read (and how much text the model received), never the
# letter text. Writes and edits to letters are redacted the same way.

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

# Tool calls are emitted before their results, so remember each call's name and
# arguments until the matching tool_result arrives.
declare -A TOOL_NAME=()
declare -A TOOL_PATH=()
declare -A TOOL_OFFSET=()
declare -A TOOL_LIMIT=()
declare -A TOOL_INPUT=()

while IFS= read -r line; do
  type=$(echo "$line" | jq -r '.type // empty' 2>/dev/null)

  if [ "$type" = "assistant" ]; then
    while IFS=$'\x1f' read -r tid tname tpath toffset tlimit tinput; do
      [ -z "$tid" ] && continue
      TOOL_NAME["$tid"]="$tname"
      TOOL_PATH["$tid"]="$tpath"
      TOOL_OFFSET["$tid"]="$toffset"
      TOOL_LIMIT["$tid"]="$tlimit"
      TOOL_INPUT["$tid"]="$tinput"
    done < <(echo "$line" | jq -r '
      .message.content[]? |
      select(.type == "tool_use") |
      [.id, .name,
       (.input.file_path // .input.path // .input.url // .input.pattern // ""),
       ((.input.offset // "") | tostring),
       ((.input.limit // "") | tostring),
       (.input | tojson)] | join("\u001f")
    ' 2>/dev/null || true)

    echo "$line" | jq -r '
      .message.content[]? |
      select(.type == "tool_use") |
      if (.name == "Write" or .name == "Edit")
         and ((.input.file_path // .input.path // "") | contains("letters")) then
        if .name == "Write" then
          "### Tool: \(.name)\n**Input:**\n```json\n{\"file_path\": \(.input.file_path | tojson), \"content\": \"<redacted — \(.input.content | tostring | length) characters>\"}\n```\n"
        else
          "### Tool: \(.name)\n**Input:**\n```json\n{\"file_path\": \(.input.file_path | tojson), \"old_string\": \"<redacted — \(.input.old_string | tostring | length) characters>\", \"new_string\": \"<redacted — \(.input.new_string | tostring | length) characters>\"}\n```\n"
        end
      else
        "### Tool: \(.name)\n**Input:**\n```json\n\(.input | tojson)\n```\n"
      end
    ' 2>/dev/null >> "$OUTPUT_FILE" || true

  elif [ "$type" = "user" ]; then
    mapfile -t result_ids < <(echo "$line" | jq -r '
      .message.content[]? |
      select(.type == "tool_result") |
      .tool_use_id
    ' 2>/dev/null || true)

    for rid in "${result_ids[@]:-}"; do
      [ -z "$rid" ] && continue
      tname="${TOOL_NAME[$rid]:-}"
      tpath="${TOOL_PATH[$rid]:-}"
      toffset="${TOOL_OFFSET[$rid]:-}"
      tlimit="${TOOL_LIMIT[$rid]:-}"
      tinput="${TOOL_INPUT[$rid]:-}"

      is_letter=false
      case "$tinput" in
        *letters*) is_letter=true ;;
      esac
      case "$tpath" in
        *letters*) is_letter=true ;;
      esac

      read_like=false
      case "$tname" in
        Read|Bash|Grep) read_like=true ;;
      esac

      if [ "$read_like" = true ] && [ "$is_letter" = true ]; then
        detail=""
        if [ "$tname" = "Read" ]; then
          if [ -n "$toffset" ] || [ -n "$tlimit" ]; then
            label="partial letter read"
          else
            label="full letter read"
          fi
          detail=" — letters/$(basename "$tpath")"
        else
          label="letter content read via $tname"
        fi
        echo "$line" | jq -r --arg id "$rid" --arg label "$label" --arg detail "$detail" '
          .message.content[]? |
          select(.type == "tool_result" and .tool_use_id == $id) |
          .content as $content |
          "**Result:** \($label)\($detail) (\($content | tostring | length) characters delivered to the model; content not shown)\n---"
        ' >> "$OUTPUT_FILE" || true
      else
        echo "$line" | jq -r --arg id "$rid" '
          .message.content[]? |
          select(.type == "tool_result" and .tool_use_id == $id) |
          "**Result:** (truncated)
```
\(.content | tostring | .[0:500])
```
---
"
        ' >> "$OUTPUT_FILE" || true
      fi
    done
  fi
done < "$INPUT_FILE"

# Extract text blocks the mind output during the session, excluding the last
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
