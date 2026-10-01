#!/usr/bin/env bash
# One-time server setup (Debian/Ubuntu with systemd); safe to re-run. Run as the user that will
# own the app, from inside the cloned repo:
#   git clone https://github.com/FixerHack/war-predictor.git ~/war-predictor
#   cd ~/war-predictor && ./scripts/install_server.sh
# Needs sudo for installing systemd units. Installs: uv, the bot and its timers, Claude Code and
# claude-gateway (the bot classifies through the gateway, see gateway/README.md).
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

# --- Claude Code and claude-gateway ---------------------------------------------------------
if ! command -v claude >/dev/null 2>&1; then
  log "Installing Claude Code"
  curl -fsSL https://claude.ai/install.sh | bash
fi
CLAUDE_BIN="$(command -v claude || true)"
[[ -n "$CLAUDE_BIN" ]] || die "claude not found after install; see https://code.claude.com/docs/en/setup"

log "Installing claude-gateway"
(cd gateway && uv sync --frozen --no-dev)
if [[ ! -f gateway/.env ]]; then
  cp gateway/.env.example gateway/.env
  chmod 600 gateway/.env
fi
if [[ -z "$(get_env gateway/.env GATEWAY_TOKENS)" ]]; then
  set_env gateway/.env GATEWAY_TOKENS "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi
set_env gateway/.env GATEWAY_CLAUDE_BIN "$CLAUDE_BIN"
GATEWAY_SECRET="$(get_env gateway/.env GATEWAY_TOKENS | cut -d, -f1)"
# The bot talks to the gateway with the same token.
[[ -n "$(get_env .env GATEWAY_URL)" ]] || set_env .env GATEWAY_URL http://127.0.0.1:8787
set_env .env GATEWAY_TOKEN "$GATEWAY_SECRET"

CLAUDE_READY=0
if [[ -n "$(get_env gateway/.env CLAUDE_CODE_OAUTH_TOKEN)" ]]; then
  CLAUDE_READY=1
elif "$CLAUDE_BIN" auth status >/dev/null 2>&1; then
  CLAUDE_READY=1
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
for unit in deploy/systemd/*.service deploy/systemd/*.timer gateway/deploy/claude-gateway.service; do
  render "$unit"
done
sudo systemctl daemon-reload

if [[ "$CLAUDE_READY" == 1 ]]; then
  sudo systemctl enable --now claude-gateway.service
  sudo systemctl restart claude-gateway.service
else
  log "Claude Code is not signed in yet. On your own computer run:  claude setup-token"
  log "then put the printed token into $ROOT_DIR/gateway/.env as CLAUDE_CODE_OAUTH_TOKEN=... and re-run."
  log "Until then the bot classifies with keyword rules only."
fi
sudo systemctl enable --now tension-bot.service
sudo systemctl restart tension-bot.service
sudo systemctl enable --now tension-collect.timer tension-health.timer tension-backup.timer \
  tension-warcheck.timer tension-digest.timer tension-gdelt.timer

log "Status"
systemctl --no-pager --lines=0 status tension-bot.service claude-gateway.service || true
systemctl list-timers 'tension-*' --no-pager || true
if [[ "$CLAUDE_READY" == 1 ]]; then
  sleep 2
  if curl -fsS -m 5 http://127.0.0.1:8787/health >/dev/null; then
    log "claude-gateway is up on 127.0.0.1:8787"
  else
    log "claude-gateway did not answer: journalctl -u claude-gateway -n 50"
  fi
fi
./scripts/healthcheck.sh || true
