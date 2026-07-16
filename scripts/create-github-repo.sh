#!/usr/bin/env bash
set -euo pipefail

REPO_NAME="${1:-tmhi-watchdog}"
VISIBILITY="${2:-public}"
DESCRIPTION="Automatic internet watchdog and local reboot controller for supported T-Mobile Home Internet gateways."

if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is not installed." >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: GitHub CLI (gh) is not installed." >&2
  echo "Install it from https://cli.github.com/ and run: gh auth login" >&2
  exit 1
fi

gh auth status >/dev/null

case "$VISIBILITY" in
  public|private|internal) ;;
  *)
    echo "Usage: $0 [repository-name] [public|private|internal]" >&2
    exit 1
    ;;
esac

if [[ ! -d .git ]]; then
  git init -b main
fi

git add .
if ! git diff --cached --quiet; then
  git commit -m "Initial release: TMHI Gateway Watchdog"
fi

if git remote get-url origin >/dev/null 2>&1; then
  echo "An origin remote already exists: $(git remote get-url origin)"
  echo "Pushing the current main branch instead of creating another repository."
  git push -u origin main
  exit 0
fi

visibility_flag="--${VISIBILITY}"
gh repo create "$REPO_NAME" \
  "$visibility_flag" \
  --source=. \
  --remote=origin \
  --push \
  --description "$DESCRIPTION"

gh repo edit \
  --add-topic t-mobile \
  --add-topic tmhi \
  --add-topic home-internet \
  --add-topic watchdog \
  --add-topic docker \
  --add-topic python \
  --add-topic fastapi

echo
echo "Repository created successfully:"
gh repo view --web
