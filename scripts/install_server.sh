#!/usr/bin/env bash
# One-time server setup (Debian/Ubuntu with systemd); safe to re-run. Run as the user that will
# own the app, from inside the cloned repo:
#   git clone https://github.com/FixerHack/war-predictor.git ~/war-predictor
#   cd ~/war-predictor && ./scripts/install_server.sh
# Needs sudo for installing systemd units. Installs uv, the bot and its timers. The bot classifies
# through claude-gateway, a separate service from its own repository (FixerHack/claude-gateway,
# see docs/deploy-agent.md): put its URL and a token into .env (GATEWAY_URL, GATEWAY_TOKEN).
source "$(dirname "$0")/_common.sh"

# set_env FILE KEY VALUE - replace KEY=... or append it
set_env() {
  local file="$1" key="$2" value="$3"
  if grep -q "^${key}=" "$file"; then
    local tmp; tmp="$(mktemp)"
    awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' "$file" >"$tmp"
    cat "$tmp" >"$file" && rm -f "$tmp"
  else
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}
get_env() { grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- || true; }

# --- uv and the bot -------------------------------------------------------------------------
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
  set_env .env CLASSIFIER_PROVIDER gateway
  set_env .env GATEWAY_URL http://127.0.0.1:8787
  set_env .env CLASSIFIER_MAX_CALLS 30
  log "Created .env — fill in TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ADMIN_IDS, then re-run"
  exit 0
fi
[[ -n "$(get_env .env TELEGRAM_BOT_TOKEN)" ]] || die "TELEGRAM_BOT_TOKEN is empty in .env"

# --- Connection to claude-gateway (a separate service) ---------------------------------------
[[ -n "$(get_env .env GATEWAY_URL)" ]] || set_env .env GATEWAY_URL http://127.0.0.1:8787
if [[ "$(get_env .env CLASSIFIER_PROVIDER)" == "gateway" && -z "$(get_env .env GATEWAY_TOKEN)" ]]; then
  log "GATEWAY_TOKEN is empty: until it is set (a token from the gateway's GATEWAY_TOKENS)"
  log "the bot classifies with keyword rules only."
fi

# --- systemd --------------------------------------------------------------------------------
uv run --frozen --no-dev tension-index init-db

APP_USER="$(id -un)"
UV_BIN="$(command -v uv)"
render() {
  sed -e "s|@APP_DIR@|$ROOT_DIR|g" -e "s|@APP_USER@|$APP_USER|g" -e "s|@UV@|$UV_BIN|g" \
    -e "s|@HOME@|$HOME|g" "$1" | sudo tee "/etc/systemd/system/$(basename "$1")" >/dev/null
}
log "Installing systemd units for user $APP_USER in $ROOT_DIR"
for unit in deploy/systemd/*.service deploy/systemd/*.timer; do
  render "$unit"
done
sudo systemctl daemon-reload

sudo systemctl enable --now tension-bot.service
sudo systemctl restart tension-bot.service
sudo systemctl enable --now tension-collect.timer tension-health.timer tension-backup.timer \
  tension-warcheck.timer tension-digest.timer tension-gdelt.timer
# The public map needs push access to GitHub (a deploy key, docs/owner-steps.md).
if [[ -n "$(get_env .env PAGES_REMOTE)" ]]; then
  sudo systemctl enable --now tension-pages.timer
else
  log "PAGES_REMOTE is empty: the public map is not published from this server"
fi

log "Status"
systemctl --no-pager --lines=0 status tension-bot.service || true
systemctl list-timers 'tension-*' --no-pager || true
if [[ -n "$(get_env .env GATEWAY_TOKEN)" ]]; then
  curl -fsS -m 5 "$(get_env .env GATEWAY_URL)/health" >/dev/null \
    && log "claude-gateway answers at $(get_env .env GATEWAY_URL)" \
    || log "claude-gateway does not answer at $(get_env .env GATEWAY_URL): is it installed and running?"
fi
./scripts/healthcheck.sh || true
