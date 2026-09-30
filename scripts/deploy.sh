#!/usr/bin/env bash
# Update the server checkout to the latest commit of a branch and restart services.
#   ./scripts/deploy.sh            # deploys main
#   ./scripts/deploy.sh dev-tg-bot # deploy a feature branch for testing
source "$(dirname "$0")/_common.sh"
require_uv
BRANCH="${1:-main}"

[[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "Local changes in the checkout; refusing to deploy"

log "Fetching $BRANCH"
git fetch --prune origin "$BRANCH"
git checkout -q "$BRANCH"
git merge --ff-only "origin/$BRANCH"

log "Syncing dependencies"
uv sync --frozen --no-dev

log "Migrating database"
uv run --frozen --no-dev tension-index init-db

if command -v systemctl >/dev/null 2>&1 && systemctl cat tension-bot.service >/dev/null 2>&1; then
  log "Restarting bot"
  sudo systemctl restart tension-bot.service
  sleep 3
fi

log "Health check"
./scripts/healthcheck.sh || true
log "Deployed $(git rev-parse --short HEAD) from $BRANCH"
