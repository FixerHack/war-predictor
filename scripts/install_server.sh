#!/usr/bin/env bash
# One-time server setup (Debian/Ubuntu with systemd). Run as the user that will own the app,
# from inside the cloned repo:
#   git clone https://github.com/FixerHack/war-predictor.git ~/war-predictor
#   cd ~/war-predictor && ./scripts/install_server.sh
# Needs sudo for installing systemd units.
source "$(dirname "$0")/_common.sh"

if ! command -v uv >/dev/null 2>&1; then
  log "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
require_uv

log "Installing dependencies"
uv sync --frozen --no-dev

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  log "Created .env — edit it now (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ADMIN_IDS), then re-run"
  exit 0
fi

uv run --frozen --no-dev tension-index init-db

APP_USER="$(id -un)"
UV_BIN="$(command -v uv)"
log "Installing systemd units for user $APP_USER in $ROOT_DIR"
for unit in deploy/systemd/*.service deploy/systemd/*.timer; do
  sed -e "s|@APP_DIR@|$ROOT_DIR|g" -e "s|@APP_USER@|$APP_USER|g" -e "s|@UV@|$UV_BIN|g" "$unit" \
    | sudo tee "/etc/systemd/system/$(basename "$unit")" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now tension-bot.service
sudo systemctl enable --now tension-collect.timer tension-health.timer tension-backup.timer tension-warcheck.timer

log "Status"
systemctl list-timers 'tension-*' --no-pager || true
./scripts/healthcheck.sh || true
