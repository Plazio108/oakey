#!/usr/bin/env bash
# Exit immediately if any command fails
set -e

# Check if a commit message was passed as an argument
if [ -z "$1" ]; then
  echo "Error: Commit message is required."
  echo "Usage: $0 \"Your commit message\""
  exit 1
fi

COMMIT_MSG="$1"

echo "==> Running uv build..."
uv build

echo "==> Staging all changes..."
git add .

echo "==> Committing with message: '$COMMIT_MSG'..."
git commit -m "$COMMIT_MSG"

echo "==> Pushing to remote..."
git push

echo "==> Successfully built, committed, and pushed!"
