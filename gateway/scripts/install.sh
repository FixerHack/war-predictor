#!/usr/bin/env bash
# Standalone claude-gateway setup on a Debian/Ubuntu server with systemd; safe to re-run.
# Works from any copy of the gateway directory, independent of the war-predictor app:
#   git clone --filter=blob:none --sparse https://github.com/FixerHack/war-predictor.git ~/claude-gateway
#   cd ~/claude-gateway && git sparse-checkout set gateway && cd gateway && ./scripts/install.sh
# Needs sudo for the systemd unit. Installs uv and Claude Code if missing.
set -euo pipefail

GW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$GW_DIR"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"
log() { printf '\033[1;34m[%s]\033[0m %s\n' "$(date '+%H:%M:%S')" "$*"; }
die() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }
get_env() { grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- || true; }
set_env() {
  local file="$1" key="$2" value="$3" tmp
  if grep -q "^${key}=" "$file"; then
    tmp="$(mktemp)"
    awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' "$file" >"$tmp"
    cat "$tmp" >"$file" && rm -f "$tmp"
  else
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}

if ! command -v uv >/dev/null 2>&1; then
  log "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
if ! command -v claude >/dev/null 2>&1; then
  log "Installing Claude Code"
  curl -fsSL https://claude.ai/install.sh | bash
fi
CLAUDE_BIN="$(command -v claude || true)"
[[ -n "$CLAUDE_BIN" ]] || die "claude not found after install; see https://code.claude.com/docs/en/setup"

log "Installing dependencies"
uv sync --frozen --no-dev

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
fi
if [[ -z "$(get_env .env GATEWAY_TOKENS)" ]]; then
  set_env .env GATEWAY_TOKENS "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  log "Generated a gateway token in $GW_DIR/.env (GATEWAY_TOKENS)"
fi
set_env .env GATEWAY_CLAUDE_BIN "$CLAUDE_BIN"

log "Installing systemd unit claude-gateway.service"
sed -e "s|@GW_DIR@|$GW_DIR|g" -e "s|@APP_USER@|$(id -un)|g" -e "s|@UV@|$(command -v uv)|g" \
  -e "s|@HOME@|$HOME|g" deploy/claude-gateway.service \
  | sudo tee /etc/systemd/system/claude-gateway.service >/dev/null
sudo systemctl daemon-reload

if [[ -z "$(get_env .env CLAUDE_CODE_OAUTH_TOKEN)" ]] && ! "$CLAUDE_BIN" auth status >/dev/null 2>&1; then
  log "Claude Code is not signed in. On your own computer run:  claude setup-token"
  log "then put the token into $GW_DIR/.env as CLAUDE_CODE_OAUTH_TOKEN=... and re-run this script."
  exit 0
fi

sudo systemctl enable --now claude-gateway.service
sudo systemctl restart claude-gateway.service
# Startup takes a few seconds; poll /health for up to 30 s.
HEALTH_URL="http://127.0.0.1:$(get_env .env GATEWAY_PORT | grep . || echo 8787)/health"
for _ in $(seq 30); do
  if curl -fsS -m 2 "$HEALTH_URL" >/dev/null 2>&1; then
    log "claude-gateway is up. Clients use the URL http://127.0.0.1:8787 and a token from GATEWAY_TOKENS."
    exit 0
  fi
  sleep 1
done
die "claude-gateway did not answer: journalctl -u claude-gateway -n 50"
