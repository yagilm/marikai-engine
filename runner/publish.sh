#!/usr/bin/env bash
# publish.sh — Sync selected marikai-brain content to a Jekyll publish repository.
#
# Usage:
#   ./runner/publish.sh              # sync + commit (no push)
#   ./runner/publish.sh --push       # sync + commit + push
#   ./runner/publish.sh --dry-run    # show what would be copied

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BRAIN_DIR="$PROJECT_DIR/marikai-brain"

# ─── Load Config ─────────────────────────────────────────────────────────────

CONFIG_FILE="$SCRIPT_DIR/config.local.env"
[ -f "$CONFIG_FILE" ] || CONFIG_FILE="$SCRIPT_DIR/config.env"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "ERROR: No config file found."
  exit 1
fi

# shellcheck source=/dev/null
source "$CONFIG_FILE"

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
  echo "Set it in runner/config.local.env and run ./runner/setup-publish.sh first."
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
