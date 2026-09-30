#!/usr/bin/env bash
# Run any CLI command from the repo root with the locked environment.
#   ./scripts/run.sh bot
#   ./scripts/run.sh collect --countries PL,EE --notify
#   ./scripts/run.sh health --json
source "$(dirname "$0")/_common.sh"
require_uv
[[ $# -gt 0 ]] || die "usage: $0 <bot|collect|health|init-db|roadmap> [args...]"
exec uv run --frozen --no-dev tension-index "$@"
