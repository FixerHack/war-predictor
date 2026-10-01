# claude-gateway

[English](README.en.md)

Окремий інструмент, який робить із Claude Code на сервері (або на ноутбуці) сервіс для будь-яких програм:

- **власний HTTP API:** `POST /v1/complete`;
- **OpenAI-сумісний API:** `POST /v1/chat/completions`, тож підходять готові клієнти й SDK OpenAI;
- **Anthropic-сумісний API:** `POST /v1/messages`, тож підходить SDK Anthropic;
- **MCP-сервер:** інструмент `ask_claude` через HTTP (`/mcp`) або stdio (`claude-gateway mcp`).

Кожен запит виконується як окремий виклик `claude -p`:
- без інструментів (жодних команд, файлів чи MCP);
- без збереження сесії;
- у порожній тимчасовій теці.

Тобто Claude Code працює лише як модель. Відповідь можна отримати у форматі JSON за схемою (`json_schema`).

Зі шлюзом працює й `tension-index`: `CLASSIFIER_PROVIDER=gateway`, `GATEWAY_URL`, `GATEWAY_TOKEN`.

## Запуск

```bash
cd gateway
uv sync
cp .env.example .env      # заповніть GATEWAY_TOKENS
set -a; . ./.env; set +a
uv run claude-gateway check            # один тестовий запит через CLI
uv run claude-gateway serve            # http://127.0.0.1:8787
```

Потрібен встановлений і залогінений Claude Code (`claude auth status`). На сервері без браузера:
1. на машині, де ви вже увійшли, запустіть `claude setup-token`;
2. отриманий токен покладіть у `CLAUDE_CODE_OAUTH_TOKEN` у `.env`.

Сервіс systemd: [`deploy/claude-gateway.service`](deploy/claude-gateway.service).

## Запити

Кожен запит, крім `/health`, потребує токен: `Authorization: Bearer <токен>` або `x-api-key: <токен>`.

```bash
curl -s http://127.0.0.1:8787/v1/complete \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt": "Столиця Польщі?", "system": "Відповідай одним словом.", "model": "haiku"}'
# {"text": "Варшава", "structured": null, "model": "claude-haiku-4-5-...", "duration_ms": 5300, ...}
```

JSON за схемою:

```bash
curl -s http://127.0.0.1:8787/v1/complete -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{
    "prompt": "Оціни тон тексту: «Посольство наказало персоналу виїхати».",
    "json_schema": {"type": "object", "properties": {"tone": {"type": "string",
      "enum": ["calm", "tense", "alarming"]}}, "required": ["tone"]}}'
# {"text": "...", "structured": {"tone": "alarming"}, ...}
```

OpenAI SDK (Python):

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8787/v1", api_key=TOKEN)
r = client.chat.completions.create(model="haiku", messages=[{"role": "user", "content": "Привіт"}])
print(r.choices[0].message.content)
```

Anthropic SDK (Python):

```python
import anthropic

client = anthropic.Anthropic(base_url="http://127.0.0.1:8787", api_key=TOKEN)
r = client.messages.create(
    model="haiku", max_tokens=500, messages=[{"role": "user", "content": "Привіт"}]
)
print(r.content[0].text)
```

MCP:
- Claude Code: `claude mcp add --transport http claude-gateway http://127.0.0.1:8787/mcp --header "Authorization: Bearer $TOKEN"`.
- Будь-який MCP-клієнт через stdio: `uv run --directory /шлях/до/gateway claude-gateway mcp`.

Моделі задаються псевдонімами Claude Code: `haiku`, `sonnet`, `opus` або повною назвою. `GATEWAY_ALLOWED_MODELS` обмежує список.

Чого немає: потокової відповіді (`stream: true` повертає 400), зображень і викликів інструментів. Розмова з кількох реплік передається одним текстом.

## Помилки

| Код | `error.type` | Що сталося |
|---|---|---|
| 401 | `unauthorized` | немає або неправильний токен |
| 400 / 413 | `invalid_request` | порожній чи завеликий запит, модель поза списком, `stream` |
| 429 | `usage_limit` | вичерпано ліміт підписки Claude |
| 503 | `not_logged_in` / `unavailable` | CLI не залогінений або не встановлений |
| 504 | `timeout` | немає відповіді за `GATEWAY_TIMEOUT` |
| 502 | `claude_error` | інша помилка CLI |

## Безпека й умови

- **Токен обов'язковий.** Без `GATEWAY_TOKENS` шлюз не запуститься, бо інакше будь-хто витрачав би вашу підписку. Виняток — `GATEWAY_ALLOW_NO_AUTH=1`, і лише при прослуховуванні `127.0.0.1`.
- **Доступ ззовні — лише через HTTPS.** Слухайте `127.0.0.1` і ставте перед шлюзом reverse proxy з HTTPS (Caddy, nginx). Не відкривайте порт напряму.
- **Ліміти підписки.** Шлюз використовує ліміти й умови того облікового запису, під яким залогінений Claude Code. Особиста підписка Claude призначена для вас, тож використовуйте шлюз для власних програм. Для чужих програм чи сервісу для інших людей потрібен ключ Anthropic API: `claude auth login --console` або `ANTHROPIC_API_KEY` у `.env`. CLI тоді працює з оплатою за API.
