#!/usr/bin/env bash
# setup-brain.sh — Initialize a fresh brain directory from the scaffold.
#
# Run this once to create the brain directory for a new project.
# Existing files are never overwritten — safe to re-run.
#
# Usage:
#   ./runner/setup-brain.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ─── Load Config ─────────────────────────────────────────────────────────────

CONFIG_FILE="$SCRIPT_DIR/config.local.env"
[ -f "$CONFIG_FILE" ] || CONFIG_FILE="$SCRIPT_DIR/config.env"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "ERROR: No config file found."
  echo "Create runner/config.local.env with PROJECT_NAME set."
  exit 1
fi

_EXT_NAME="${PROJECT_NAME:-}"
# shellcheck source=/dev/null
source "$CONFIG_FILE"
PROJECT_NAME="${_EXT_NAME:-${PROJECT_NAME:-marikai}}"
PROJECT_NAME_CAP="${PROJECT_NAME^}"
PROJECT_NAME_UPPER="${PROJECT_NAME^^}"
GUIDE_FILE="${PROJECT_NAME_UPPER}.md"
BRAIN_DIR="$PROJECT_DIR/${PROJECT_NAME}-brain"
SCAFFOLD_DIR="$SCRIPT_DIR/brain-scaffold"

echo "Initializing brain for: $PROJECT_NAME_CAP"
echo "Brain directory:        $BRAIN_DIR"
echo ""

mkdir -p "$BRAIN_DIR"

# Copy scaffold files recursively — skip any that already exist
while IFS= read -r -d '' src; do
  rel="${src#"$SCAFFOLD_DIR/"}"
  dest="$BRAIN_DIR/$rel"

  # GUIDE.md gets renamed to {NAME_UPPER}.md
  if [ "$(basename "$rel")" = "GUIDE.md" ]; then
    dest_final="$(dirname "$dest")/$GUIDE_FILE"
    if [ -f "$dest_final" ]; then
      echo "  skip (exists): $GUIDE_FILE"
      continue
    fi
    mkdir -p "$(dirname "$dest_final")"
    cp "$src" "$dest_final"
    sed -i \
      -e "s/__NAME_CAP__/$PROJECT_NAME_CAP/g" \
      -e "s/__NAME_UPPER__/$PROJECT_NAME_UPPER/g" \
      -e "s/__NAME__/$PROJECT_NAME/g" \
      "$dest_final"
    echo "  created:       $GUIDE_FILE"
    continue
  fi

  if [ -e "$dest" ]; then
    echo "  skip (exists): $rel"
    continue
  fi

  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"

  # Substitute name placeholders in text files
  case "$dest" in
    *.md|*.json|*.txt|*.yaml|*.yml)
      sed -i \
        -e "s/__NAME_CAP__/$PROJECT_NAME_CAP/g" \
        -e "s/__NAME_UPPER__/$PROJECT_NAME_UPPER/g" \
        -e "s/__NAME__/$PROJECT_NAME/g" \
        "$dest"
      ;;
  esac

  echo "  created:       $rel"
done < <(find "$SCAFFOLD_DIR" -type f -print0 | sort -z)

echo ""
echo "Done. Brain initialized at: $BRAIN_DIR"
echo ""
echo "Next steps:"
echo "  Edit ${PROJECT_NAME}-brain/identity/identity.md   — define who ${PROJECT_NAME_CAP} is"
echo "  Edit ${PROJECT_NAME}-brain/identity/voice.md      — define how she writes"
echo "  Add content to ${PROJECT_NAME}-brain/inputs/      — articles, books, sayings, concepts"
echo "  ./runner/wake.sh                                  — start the first session"
