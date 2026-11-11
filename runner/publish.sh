#!/usr/bin/env bash
# publish.sh — Sync the brain content to a Jekyll publish repository.
#
# Usage:
#   ./runner/publish.sh                       # sync + commit (no push)
#   ./runner/publish.sh --push                # sync + commit + push
#   ./runner/publish.sh --dry-run             # show what would be copied
#   ./runner/publish.sh --mind nova           # publish 'nova' mind
#   ./runner/publish.sh --mind nova --push    # publish + push

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ─── Parse --mind (needed before config load) ────────────────────────────────

MIND_NAME=""
_NEXT_IS_MIND=false
for _arg in "$@"; do
  if $_NEXT_IS_MIND; then
    MIND_NAME="$_arg"
    _NEXT_IS_MIND=false
    continue
  fi
  case "$_arg" in
    --mind)   _NEXT_IS_MIND=true ;;
    --mind=*) MIND_NAME="${_arg#--mind=}" ;;
  esac
done
unset _arg _NEXT_IS_MIND

# ─── Load Config ─────────────────────────────────────────────────────────────

if [ -n "$MIND_NAME" ]; then
  CONFIG_FILE="$SCRIPT_DIR/config.${MIND_NAME}.env"
  if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: No config found for mind '$MIND_NAME': $CONFIG_FILE"
    exit 1
  fi
else
  CONFIG_FILE="$SCRIPT_DIR/config.local.env"
  [ -f "$CONFIG_FILE" ] || CONFIG_FILE="$SCRIPT_DIR/config.env"
  if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: No config file found."
    exit 1
  fi
fi

_EXT_NAME="${PROJECT_NAME:-}"
# shellcheck source=/dev/null
source "$CONFIG_FILE"
PROJECT_NAME="${_EXT_NAME:-${PROJECT_NAME:-marikai}}"
BRAIN_DIR="$PROJECT_DIR/${PROJECT_NAME}-brain"

PUBLISH_DIR="${PUBLISH_DIR:-}"
PUBLISH_GIT_PUSH="${PUBLISH_GIT_PUSH:-false}"

# ─── Flags ───────────────────────────────────────────────────────────────────

DRY_RUN=false
FORCE_PUSH=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --push)    FORCE_PUSH=true ;;
  esac
done

[ "$FORCE_PUSH" = "true" ] && PUBLISH_GIT_PUSH="true"

# ─── Validate ────────────────────────────────────────────────────────────────

if [ -z "$PUBLISH_DIR" ]; then
  echo "ERROR: PUBLISH_DIR is not set."
  echo "Set it in runner/$(basename "$CONFIG_FILE") and run ./runner/setup-publish.sh first."
  exit 1
fi

if [ ! -d "$PUBLISH_DIR" ]; then
  echo "ERROR: PUBLISH_DIR does not exist: $PUBLISH_DIR"
  echo "Clone your publish repo there, then run ./runner/setup-publish.sh"
  exit 1
fi

# ─── Path mapping (brain path → Jekyll path in publish repo) ─────────────────
#
# Collections must live in _dirname/ for Jekyll to pick them up.
# Single files get mapped to a flat location.

dest_for() {
  local src="$1"
  case "$src" in
    journal)            echo "_journal" ;;
    essays)             echo "_essays" ;;
    creatives)          echo "_creatives" ;;
    letters)            echo "_letters" ;;
    projects)           echo "_projects" ;;
    identity/about.md)  echo "about.md" ;;
    inputs/sayings.md)          echo "sayings.md" ;;
    inputs/concepts.md)         echo "concepts.md" ;;
    inputs/keeper-prompts.md)   echo "keeper-prompts.md" ;;
    data/session-log.md)        echo "log.md" ;;
    *)                  echo "$src" ;;
  esac
}

# ─── Build session log ────────────────────────────────────────────────────────

python3 "$SCRIPT_DIR/scripts/build-log.py" 2>/dev/null || true

# ─── Sync ────────────────────────────────────────────────────────────────────

TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
CHANGED=0

# Use PUBLISH_PATHS from config, default to the standard set
PUBLISH_PATHS="${PUBLISH_PATHS:-journal creatives essays letters identity/about.md inputs/sayings.md inputs/concepts.md}"

# ─── Normalise front matter ──────────────────────────────────────────────────
#
# Jekyll only renders a document that begins with a YAML front-matter block.
# A generated file with a leading blank line or a missing opening `---` is
# copied but never listed, so it silently disappears from the site. Repair the
# common mistakes here and abort on anything still malformed.

FRONT_MATTER_PATHS=()
for rel_path in $PUBLISH_PATHS; do
  src="$BRAIN_DIR/$rel_path"
  if [ -d "$src" ]; then
    FRONT_MATTER_PATHS+=("$src")
  fi
done
# Flat pages that already carry front matter in the brain.
for rel_path in identity/about.md data/session-log.md; do
  src="$BRAIN_DIR/$rel_path"
  if [ -f "$src" ]; then
    FRONT_MATTER_PATHS+=("$src")
  fi
done

if [ "${#FRONT_MATTER_PATHS[@]}" -gt 0 ]; then
  python3 "$SCRIPT_DIR/scripts/normalise-front-matter.py" "${FRONT_MATTER_PATHS[@]}"
fi

for rel_path in $PUBLISH_PATHS; do
  src="$BRAIN_DIR/$rel_path"
  dest_rel="$(dest_for "$rel_path")"
  dest="$PUBLISH_DIR/$dest_rel"

  if [ ! -e "$src" ]; then
    echo "  skip (not found): $rel_path"
    continue
  fi

  if [ "$DRY_RUN" = true ]; then
    echo "[dry-run] $rel_path  →  $dest_rel"
    continue
  fi

  mkdir -p "$(dirname "$dest")"

  if [ -d "$src" ]; then
    rsync -a --delete "$src/" "$dest/"
    echo "  synced: $rel_path/ → $dest_rel/"
  else
    cp "$src" "$dest"
    echo "  synced: $rel_path → $dest_rel"
  fi
  CHANGED=1
done

[ "$DRY_RUN" = true ] && exit 0

# ─── Ensure front matter on flat I/O pages ───────────────────────────────────
#
# inputs/*.md are synced as plain Markdown. Jekyll only applies the
# _config.yml defaults (layout/title) to documents that have front matter;
# without it they are copied as static files and the header links serve raw
# Markdown. Add a minimal block to the published copies (not the brain files,
# which Marikai edits as data).

IO_PAGES=()
for rel_path in inputs/sayings.md inputs/concepts.md inputs/keeper-prompts.md; do
  dest_rel="$(dest_for "$rel_path")"
  dest="$PUBLISH_DIR/$dest_rel"
  if [ -f "$dest" ]; then
    IO_PAGES+=("$dest")
  fi
done

if [ "${#IO_PAGES[@]}" -gt 0 ]; then
  python3 "$SCRIPT_DIR/scripts/normalise-front-matter.py" --ensure-missing "${IO_PAGES[@]}"
fi

# ─── Git commit ───────────────────────────────────────────────────────────────

if [ "$CHANGED" -eq 0 ]; then
  echo "Nothing to sync."
  exit 0
fi

if [ ! -d "$PUBLISH_DIR/.git" ]; then
  echo "PUBLISH_DIR is not a git repository — skipping commit."
  exit 0
fi

cd "$PUBLISH_DIR"

if git diff --quiet && git diff --cached --quiet; then
  echo "No git changes after sync."
else
  git add -A
  git commit -m "publish: $TIMESTAMP"
  echo "Committed: $TIMESTAMP"

  if [ "$PUBLISH_GIT_PUSH" = "true" ]; then
    git push
    echo "Pushed to remote."
  fi
fi
