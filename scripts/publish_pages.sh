#!/usr/bin/env bash
# Publish the progress page and the public map (scores from data/tension.sqlite3) to the
# `gh-pages` branch. Run every 30 min on the server by tension-pages.timer; by hand: make pages.
# GitHub: Settings -> Pages -> Source: "Deploy from a branch", branch `gh-pages`, folder `/`.
#
# gh-pages keeps a single commit (the current site), force-pushed only when the site changed,
# so publishing every 30 minutes does not grow the repository.
# PAGES_REMOTE (env or .env) is where to push: default `origin`; on the server an SSH URL that
# uses a deploy key with write access (see docs/owner-steps.md).
#   ./scripts/publish_pages.sh
source "$(dirname "$0")/_common.sh"
require_uv

PAGES_REMOTE="${PAGES_REMOTE:-$(grep -E '^PAGES_REMOTE=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)}"
PAGES_REMOTE="${PAGES_REMOTE:-origin}"
export GITHUB_SHA="${GITHUB_SHA:-$(git rev-parse HEAD)}"
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git log -1 --format=%ct)}"

BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

# PLAN*.md go to the temp dir: the checkout must stay clean for `git pull` in deploy.sh.
uv run --frozen tension-index roadmap --out "$BUILD/site" --plan-dir "$BUILD" >/dev/null
if [[ -f data/tension.sqlite3 ]]; then
  uv run --frozen tension-index export --out "$BUILD/site/dashboard/scores.json" >/dev/null
else
  log "No data/tension.sqlite3: the map is published without scores.json"
fi

# Commit the built site with a private index: no worktree, no local branch.
GIT_DIR_ABS="$(git rev-parse --absolute-git-dir)"
export GIT_INDEX_FILE="$BUILD/index"
git --git-dir="$GIT_DIR_ABS" --work-tree="$BUILD/site" -C "$BUILD/site" add -A .
new_tree="$(git write-tree)"
unset GIT_INDEX_FILE

if git fetch -q "$PAGES_REMOTE" gh-pages 2>/dev/null \
  && [[ "$(git rev-parse 'FETCH_HEAD^{tree}')" == "$new_tree" ]]; then
  log "Nothing changed on gh-pages"
  exit 0
fi

if [[ -z "$(git config user.email || true)" ]]; then
  export GIT_AUTHOR_NAME="Tension Index" GIT_COMMITTER_NAME="Tension Index"
  export GIT_AUTHOR_EMAIL="tension-index@users.noreply.github.com"
  export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
fi
commit="$(git commit-tree "$new_tree" -m "Publish site from ${GITHUB_SHA:0:7}")"
git push -q --force "$PAGES_REMOTE" "$commit:refs/heads/gh-pages"
log "Published. Page: https://fixerhack.github.io/war-predictor/"
