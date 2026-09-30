#!/usr/bin/env bash
# Health check for the server (run by tension-health.timer) or by hand.
# Exit: 0 OK, 1 WARN, 2 FAIL.
#   ./scripts/healthcheck.sh            # human-readable
#   ./scripts/healthcheck.sh --json     # machine-readable
#   ./scripts/healthcheck.sh --notify   # alert Telegram on FAIL
source "$(dirname "$0")/_common.sh"
require_uv

status=0
if command -v systemctl >/dev/null 2>&1 && systemctl cat tension-bot.service >/dev/null 2>&1; then
  if systemctl is-active --quiet tension-bot.service; then
    echo "✅ systemd: tension-bot.service active"
  else
    echo "❌ systemd: tension-bot.service NOT active"
    status=2
  fi
fi

set +e
uv run --frozen --no-dev tension-index health "$@"
app_status=$?
set -e

(( app_status > status )) && status=$app_status
exit "$status"
