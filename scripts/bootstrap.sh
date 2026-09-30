#!/usr/bin/env bash
# Local setup (macOS / Linux): install deps, create .env and the database, run tests.
#   ./scripts/bootstrap.sh
source "$(dirname "$0")/_common.sh"
require_uv

log "Installing Python (from .python-version) and dependencies"
uv sync

if [[ ! -f .env ]]; then
  cp .env.example .env
  log "Created .env from .env.example — fill in TELEGRAM_* before running the bot"
fi

log "Initialising database"
uv run tension-index init-db

log "Running lint and tests"
uv run ruff check .
uv run pytest -q

log "Done. Next: ./scripts/run.sh health  |  ./scripts/run.sh collect  |  ./scripts/run.sh bot"
