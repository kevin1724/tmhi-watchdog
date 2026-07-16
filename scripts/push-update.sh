#!/usr/bin/env bash
set -euo pipefail

MESSAGE="${1:-Update TMHI Gateway Watchdog}"

if [[ ! -d .git ]]; then
  echo "Error: this directory is not a Git repository." >&2
  echo "Run ./scripts/create-github-repo.sh first." >&2
  exit 1
fi

git add .

if git diff --cached --quiet; then
  echo "No changes to commit."
  exit 0
fi

git commit -m "$MESSAGE"
git push
