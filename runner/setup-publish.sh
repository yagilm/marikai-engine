#!/usr/bin/env bash
# setup-publish.sh — Initialize the publish repository with the Jekyll scaffold.
#
# Run this once after cloning your publish repo.
# It copies the scaffold files without overwriting anything already there.
#
# Usage:
#   ./runner/setup-publish.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ─── Load Config ─────────────────────────────────────────────────────────────

CONFIG_FILE="$SCRIPT_DIR/config.local.env"
[ -f "$CONFIG_FILE" ] || CONFIG_FILE="$SCRIPT_DIR/config.env"

# shellcheck source=/dev/null
source "$CONFIG_FILE"

PUBLISH_DIR="${PUBLISH_DIR:-}"
PUBLISH_BASEURL="${PUBLISH_BASEURL:-}"

if [ -z "$PUBLISH_DIR" ]; then
  echo "ERROR: PUBLISH_DIR is not set in config.local.env"
  echo ""
  echo "Steps to set up a publish repo:"
  echo "  1. Create a GitHub repository (e.g. github.com/you/marikai)"
  echo "  2. Enable GitHub Pages: Settings → Pages → Deploy from branch → main / root"
  echo "  3. Clone it locally: git clone git@github.com:you/marikai.git ~/marikai-site"
  echo "  4. Add to config.local.env: PUBLISH_DIR=\"\$HOME/marikai-site\""
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

# Copy scaffold files — skip any that already exist
for f in "$SCAFFOLD_DIR"/{_config.yml,index.md,journal.md,essays.md,creatives.md,letters.md,sayings.md,.gitignore}; do
  filename="$(basename "$f")"
  dest="$PUBLISH_DIR/$filename"
  if [ -f "$dest" ]; then
    echo "  skip (exists): $filename"
  else
    cp "$f" "$dest"
    # Substitute baseurl placeholder in _config.yml
    if [ "$filename" = "_config.yml" ]; then
      sed -i "s|__PUBLISH_BASEURL__|$PUBLISH_BASEURL|g" "$dest"
      echo "  created:       $filename  (baseurl: \"$PUBLISH_BASEURL\")"
    else
      echo "  created:       $filename"
    fi
  fi
done

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
echo "  ./runner/publish.sh             # sync Marikai's content"
echo "  ./runner/publish.sh --push      # sync and push to GitHub"
