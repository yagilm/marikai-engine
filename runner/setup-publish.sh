#!/usr/bin/env bash
# setup-publish.sh — Initialize the publish repository with the Jekyll scaffold.
#
# Run this once after cloning your publish repo.
# It copies the scaffold files without overwriting anything already there.
#
# Usage:
#   ./runner/setup-publish.sh               # uses config.local.env
#   ./runner/setup-publish.sh --mind nova   # uses config.nova.env

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Parse --mind ─────────────────────────────────────────────────────────────

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
fi

_EXT_NAME="${PROJECT_NAME:-}"
# shellcheck source=/dev/null
source "$CONFIG_FILE"
PROJECT_NAME="${_EXT_NAME:-${PROJECT_NAME:-marikai}}"
PROJECT_NAME_CAP="${PROJECT_NAME^}"
PUBLISH_DIR="${PUBLISH_DIR:-}"
PUBLISH_BASEURL="${PUBLISH_BASEURL:-}"

if [ -z "$PUBLISH_DIR" ]; then
  echo "ERROR: PUBLISH_DIR is not set in $(basename "$CONFIG_FILE")"
  echo ""
  echo "Steps to set up a publish repo:"
  echo "  1. Create a GitHub repository (e.g. github.com/you/${PROJECT_NAME})"
  echo "  2. Enable GitHub Pages: Settings → Pages → Deploy from branch → main / root"
  echo "  3. Clone it locally: git clone git@github.com:you/${PROJECT_NAME}.git ~/${PROJECT_NAME}-site"
  echo "  4. Add to $(basename "$CONFIG_FILE"): PUBLISH_DIR=\"\$HOME/${PROJECT_NAME}-site\""
  echo "  5. Run this script again."
  exit 1
fi

if [ ! -d "$PUBLISH_DIR" ]; then
  echo "ERROR: PUBLISH_DIR does not exist: $PUBLISH_DIR"
  echo "Clone your GitHub repo there first."
  exit 1
fi

SCAFFOLD_DIR="$SCRIPT_DIR/publish-scaffold"

echo "Initializing publish repo at: $PUBLISH_DIR"
echo ""

# Copy scaffold files recursively — skip any that already exist
while IFS= read -r -d '' src; do
  rel="${src#"$SCAFFOLD_DIR/"}"
  dest="$PUBLISH_DIR/$rel"
  if [ -f "$dest" ]; then
    echo "  skip (exists): $rel"
  else
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
    # Substitute placeholders
    sed -i \
      -e "s|__PUBLISH_BASEURL__|$PUBLISH_BASEURL|g" \
      -e "s|__NAME_CAP__|$PROJECT_NAME_CAP|g" \
      "$dest"
    if [ "$rel" = "_config.yml" ]; then
      echo "  created:       $rel  (title: $PROJECT_NAME_CAP, baseurl: \"$PUBLISH_BASEURL\")"
    else
      echo "  created:       $rel"
    fi
  fi
done < <(find "$SCAFFOLD_DIR" -type f -print0)

# Initial git commit if the repo is empty
if [ -d "$PUBLISH_DIR/.git" ]; then
  cd "$PUBLISH_DIR"
  if git diff --quiet && git diff --cached --quiet && [ -z "$(git log --oneline 2>/dev/null | head -1)" ]; then
    git add -A
    git commit -m "init: Jekyll scaffold"
    echo ""
    echo "Initial commit created."
  else
    git add -A
    if ! git diff --cached --quiet; then
      git commit -m "scaffold: add Jekyll config and index pages"
      echo ""
      echo "Scaffold committed."
    fi
  fi
fi

echo ""
echo "Done. Your publish repo is ready."
echo ""
echo "Next steps:"
echo "  ./runner/publish.sh --dry-run   # preview what will be synced"
echo "  ./runner/publish.sh             # sync ${PROJECT_NAME_CAP}'s content"
echo "  ./runner/publish.sh --push      # sync and push to GitHub"
