# Contributing / Як вносити зміни

## Гілки / Branches

| Тип / Type | Шаблон / Pattern | Приклад / Example |
|---|---|---|
| Нова функція / feature | `dev-<area>` | `dev-tg-bot`, `dev-collector`, `dev-scoring` |
| Виправлення / fix | `fix-<what>` | `fix-gov-uk-parser` |
| Документація / docs | `docs-<what>` | `docs-server-setup` |

- `main` — за замовчуванням, захищена, тільки через PR / default, protected, PR-only.
- Назви: латиниця, нижній регістр, дефіси, 2–3 слова / lowercase latin, hyphens, 2–3 words.
- Назва гілки етапу — у `roadmap/roadmap.yaml` (`branch`) / each stage lists its branch in the roadmap.

## Цикл задачі / Task loop

1. `git checkout main && git pull && git checkout -b dev-<area>`
2. Код + тести / code + tests.
3. Статус задачі в `roadmap/roadmap.yaml` → `make plan`.
4. `make check` (ruff, pytest, plan) — має бути зелено / must pass.
5. Push, PR у `main`, CI зелений → merge. Pages оновиться автоматично / Pages redeploys automatically.

## Правила коду / Code rules

- Залежності тільки через uv: `uv add <pkg>` / `uv add --dev <pkg>`; `uv.lock` комітиться.
- Секрети тільки в `.env` (не комітиться) / secrets only in `.env`.
- Нове джерело = клас у `src/tension_index/sources/` + реєстрація в `REGISTRY` + тест з `httpx.MockTransport` (без мережі) / new source = class + registry entry + offline test.
