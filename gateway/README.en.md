# claude-gateway

[Українська](README.md)

A separate tool that turns Claude Code on a server (or a laptop) into a service for any program:

- **its own HTTP API:** `POST /v1/complete`;
- **OpenAI-compatible API:** `POST /v1/chat/completions`, so existing OpenAI clients and SDKs work;
- **Anthropic-compatible API:** `POST /v1/messages`, so the Anthropic SDK works;
- **MCP server:** the `ask_claude` tool over HTTP (`/mcp`) or stdio (`claude-gateway mcp`).

Every request is a separate `claude -p` call:
- with no tools (no commands, files or MCP);
- with no saved session;
- in an empty temporary directory.

So Claude Code acts only as a model. Answers can be JSON matching a schema (`json_schema`).

`tension-index` can use it too: `CLASSIFIER_PROVIDER=gateway`, `GATEWAY_URL`, `GATEWAY_TOKEN`.

## Running

```bash
cd gateway
uv sync
cp .env.example .env      # fill in GATEWAY_TOKENS
set -a; . ./.env; set +a
uv run claude-gateway check            # one test request through the CLI
uv run claude-gateway serve            # http://127.0.0.1:8787
```

Claude Code must be installed and signed in (`claude auth status`). On a server without a browser:
1. run `claude setup-token` on a machine where you are signed in;
2. put the printed token into `CLAUDE_CODE_OAUTH_TOKEN` in `.env`.

systemd service: [`deploy/claude-gateway.service`](deploy/claude-gateway.service).

## Requests

Every request except `/health` needs a token: `Authorization: Bearer <token>` or `x-api-key: <token>`.

```bash
curl -s http://127.0.0.1:8787/v1/complete \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt": "Capital of Poland?", "system": "Answer in one word.", "model": "haiku"}'
# {"text": "Warsaw", "structured": null, "model": "claude-haiku-4-5-...", "duration_ms": 5300, ...}
```

JSON matching a schema:

```bash
curl -s http://127.0.0.1:8787/v1/complete -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{
    "prompt": "Rate the tone: \"The embassy ordered staff to leave.\"",
    "json_schema": {"type": "object", "properties": {"tone": {"type": "string",
      "enum": ["calm", "tense", "alarming"]}}, "required": ["tone"]}}'
# {"text": "...", "structured": {"tone": "alarming"}, ...}
```

OpenAI SDK (Python):

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key=TOKEN)
r = client.chat.completions.create(model="haiku", messages=[{"role": "user", "content": "Hello"}])
print(r.choices[0].message.content)
```

Anthropic SDK (Python):

```python
import anthropic

client = anthropic.Anthropic(base_url="http://127.0.0.1:8787", api_key=TOKEN)
r = client.messages.create(
    model="haiku", max_tokens=500, messages=[{"role": "user", "content": "Hello"}]
)
print(r.content[0].text)
```

MCP:
- Claude Code: `claude mcp add --transport http claude-gateway http://127.0.0.1:8787/mcp --header "Authorization: Bearer $TOKEN"`.
- Any MCP client over stdio: `uv run --directory /path/to/gateway claude-gateway mcp`.

Models are Claude Code aliases: `haiku`, `sonnet`, `opus`, or a full model name. `GATEWAY_ALLOWED_MODELS` restricts the list.

Not supported: streaming (`stream: true` returns 400), images and tool calls. A multi-turn conversation is passed as one text.

## Errors

| Code | `error.type` | What happened |
|---|---|---|
| 401 | `unauthorized` | missing or wrong token |
| 400 / 413 | `invalid_request` | empty or too long prompt, model not allowed, `stream` |
| 429 | `usage_limit` | the Claude subscription's usage limit is reached |
| 503 | `not_logged_in` / `unavailable` | the CLI is not signed in or not installed |
| 504 | `timeout` | no answer within `GATEWAY_TIMEOUT` |
| 502 | `claude_error` | another CLI error |

## Security and terms

- **A token is required.** The gateway does not start without `GATEWAY_TOKENS`, because otherwise anyone could spend your subscription. The exception is `GATEWAY_ALLOW_NO_AUTH=1`, and only while listening on `127.0.0.1`.
- **Remote access only over HTTPS.** Listen on `127.0.0.1` and put a reverse proxy with HTTPS (Caddy, nginx) in front. Do not expose the port directly.
- **Subscription limits.** The gateway uses the limits and terms of the account Claude Code is signed in with. A personal Claude subscription is for you, so use the gateway for your own programs. For other people's programs or a service for others you need an Anthropic API key: `claude auth login --console` or `ANTHROPIC_API_KEY` in `.env`. The CLI then runs on API billing.
