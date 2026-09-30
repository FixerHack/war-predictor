# Tension Index

**Українська** · [English](README.en.md)

Індикатор стану сигналів ескалації для країн Європи за шкалою 0–10. Система щодня збирає офіційні рекомендації урядів своїм громадянам (travel advisories), порівнює нові версії з попередніми, класифікує зміни і показує, що саме змінилося й скільки незалежних джерел це підтверджують.

> ⚠️ Це індикатор стану сигналів, а не прогноз і не порада щодо виїзду. Рішення людина ухвалює самостійно.

- 📋 План робіт: [PLAN.md](PLAN.md) (генерується з [`roadmap/roadmap.yaml`](roadmap/roadmap.yaml))
- 📊 Прогрес: GitHub Pages проєкту (`https://fixerhack.github.io/war-predictor/` після увімкнення Pages)

## Шкала

| Бал | Рівень | Що означає |
|---|---|---|
| 0–2 | 🟢 зелений | базовий фон |
| 3–4 | 🟡 жовтий | поодинокі зміни, одне джерело |
| 5–6 | 🟠 помаранчевий | зміни в кількох блоках або синхронно в кількох держав |
| 7–8 | 🔴 червоний | обмеження повітряного простору, добровільний виїзд персоналу посольств, надзвичайні заходи |
| 9–10 | 🟥 критичний | примусовий виїзд персоналу кількома державами, закриття неба, мобілізація |

Країни: ЄС-27, Велика Британія, Норвегія, Швейцарія, Ісландія, Молдова, Західні Балкани (38).

## Стек

Python 3.12 · [uv](https://docs.astral.sh/uv/) · aiogram 3 · httpx · SQLite (aiosqlite) · Claude API (з етапу S6) · systemd на власному сервері · GitHub Actions (CI і Pages).

## Структура

```
src/tension_index/
  cli.py           команди: init-db, collect, health, bot, roadmap
  config.py        налаштування з .env
  countries.py     38 країн моніторингу
  storage.py       SQLite + міграції
  diff.py          виявлення змін між версіями
  collector.py     збір з усіх джерел
  sources/         джерела рекомендацій (gov_uk.py — Велика Британія)
  health.py        перевірки стану
  notify.py        надсилання в Telegram
  bot/             Telegram-бот (aiogram)
  roadmap.py       генерація PLAN.md і сторінки прогресу
scripts/           bootstrap, run, healthcheck, deploy, backup, install_server
deploy/systemd/    юніти: бот, таймери збору, healthcheck і бекапу
roadmap/           roadmap.yaml — єдине джерело плану
site/              шаблон сторінки прогресу
tests/
```

## Локальний запуск (MacBook)

```bash
brew install uv            # або: curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/FixerHack/war-predictor.git
cd war-predictor
./scripts/bootstrap.sh     # Python 3.12, залежності, .env, база, тести
```

Далі заповніть `.env` (токен бота, ID каналу, свій Telegram ID в `TELEGRAM_ADMIN_IDS`) і запускайте:

```bash
make test                  # тести
make lint                  # ruff
./scripts/run.sh collect --countries PL,EE   # збір для кількох країн
./scripts/run.sh health    # стан системи
./scripts/run.sh bot       # бот (Ctrl+C для зупинки)
make plan                  # перегенерувати PLAN.md після зміни roadmap.yaml
make site                  # переглянути сторінку прогресу на http://localhost:8000
```

## Сервер

Вимоги: Debian/Ubuntu із systemd, користувач із `sudo`.

```bash
git clone https://github.com/FixerHack/war-predictor.git ~/war-predictor
cd ~/war-predictor
./scripts/install_server.sh   # 1-й запуск створить .env і зупиниться
nano .env                     # заповнити
./scripts/install_server.sh   # встановить і запустить systemd-юніти
```

Що запускається:

| Юніт | Що робить |
|---|---|
| `tension-bot.service` | бот, перезапуск при падінні |
| `tension-collect.timer` | збір кожні 3 години, сповіщення про зміни й збої |
| `tension-health.timer` | healthcheck кожні 15 хвилин, алерт у Telegram при FAIL |
| `tension-backup.timer` | щоденний бекап SQLite, зберігаються останні 14 |

Оновлення: `./scripts/deploy.sh` (гілка `main`) або `./scripts/deploy.sh dev-tg-bot` для тесту гілки.
Стан: `./scripts/healthcheck.sh` (коди виходу: 0 OK, 1 WARN, 2 FAIL), логи: `journalctl -u tension-bot -f`.

Для зовнішнього моніторингу вкажіть `HEALTH_PING_URL` (наприклад, безкоштовний [healthchecks.io](https://healthchecks.io)): якщо сервер перестане надсилати пінги, прийде лист.

## Гілки і процес

- `main` — гілка за замовчуванням, завжди робоча. Зміни тільки через Pull Request із зеленим CI.
- Нові гілки: `dev-<область>`, коротко й зрозуміло: `dev-tg-bot`, `dev-collector`, `dev-scoring`. Виправлення: `fix-<що>`, документація: `docs-<що>`. Назва гілки для кожного етапу вказана в плані.
- Після кожної завершеної задачі оновлюється статус у `roadmap/roadmap.yaml` і виконується `make plan`.

Детальніше: [CONTRIBUTING.md](CONTRIBUTING.md).
