#!/usr/bin/env bash
# Publish the progress page to the `gh-pages` branch without GitHub Actions.
# Use when Actions are unavailable; then set Settings -> Pages -> Source: "Deploy from a branch",
# branch `gh-pages`, folder `/ (root)`.
#   ./scripts/publish_pages.sh
source "$(dirname "$0")/_common.sh"
require_uv

export GITHUB_SHA="${GITHUB_SHA:-$(git rev-parse HEAD)}"
rm -rf _site  # never publish leftovers (e.g. test data) from an earlier build
uv run tension-index roadmap --out _site >/dev/null
# Public dashboard data from the local database (skipped when there is none yet).
if [[ -f data/tension.sqlite3 ]]; then
  uv run tension-index export --out _site/dashboard/scores.json
else
  log "No data/tension.sqlite3: dashboard published without scores.json"
fi

WORKTREE="$(mktemp -d)"
trap 'git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true' EXIT

if git ls-remote --exit-code --heads origin gh-pages >/dev/null 2>&1; then
  git fetch -q origin gh-pages
  git worktree add -q -B gh-pages "$WORKTREE" origin/gh-pages
else
  git worktree add -q --detach "$WORKTREE"
  git -C "$WORKTREE" checkout -q --orphan gh-pages
fi

git -C "$WORKTREE" rm -rqf --ignore-unmatch . >/dev/null
find "$WORKTREE" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R _site/. "$WORKTREE"/
git -C "$WORKTREE" add -A
if git -C "$WORKTREE" diff --cached --quiet; then
  log "Nothing changed on gh-pages"
  exit 0
fi
git -C "$WORKTREE" commit -q -m "Publish progress page from ${GITHUB_SHA:0:7}"
git -C "$WORKTREE" push -q origin gh-pages
log "Published. Page: https://fixerhack.github.io/war-predictor/"
