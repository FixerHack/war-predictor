# Tension Index

**Українська** · [English](README.en.md)

Індикатор стану сигналів ескалації для країн Європи за шкалою 0–10. Система щодня збирає офіційні рекомендації урядів своїм громадянам (travel advisories), порівнює нові версії з попередніми, класифікує зміни і показує, що саме змінилося й скільки незалежних джерел це підтверджують.

> ⚠️ Це індикатор стану сигналів, а не прогноз і не порада щодо виїзду. Рішення людина ухвалює самостійно.

- 📋 План робіт: [PLAN.md](PLAN.md) (генерується з [`roadmap/roadmap.yaml`](roadmap/roadmap.yaml))
- 🧮 Алгоритм шкали: [docs/algorithm.md](docs/algorithm.md)
- 🗂 Джерела даних і трекери війн: [docs/sources.md](docs/sources.md)
- 📊 Прогрес: https://fixerhack.github.io/war-predictor/
- 🗺 Публічна панель (карта, бал і причини по країнах): https://fixerhack.github.io/war-predictor/dashboard/

## Шкала

| Бал | Рівень | Що означає |
|---|---|---|
| 0–2 | 🟢 зелений | базовий фон |
| 3–4 | 🟡 жовтий | поодинокі зміни, одне джерело |
| 5–6 | 🟠 помаранчевий | зміни в кількох блоках або синхронно в кількох держав |
| 7–8 | 🔴 червоний | обмеження повітряного простору, добровільний виїзд персоналу посольств, надзвичайні заходи |
| 9–10 | 🟥 критичний | примусовий виїзд персоналу кількома державами, закриття неба, мобілізація |

Країни: ЄС-27, Велика Британія, Норвегія, Швейцарія, Ісландія, Молдова, Західні Балкани (38).

## Бот

1. `/start` → вибір мови (українська / English).
2. Вибір країни з 38 (пізніше можна відстежувати до 5 країн).
3. Панель, яка редагується на місці інлайн-кнопками. Вона показує:
   - бал напруги (або «калібрування», поки даних мало) і головні причини з цитатами;
   - короткий рядок по інших відстежуваних країнах;
   - статус війни на території країни;
   - сусідство з країною у стані війни чи з агресором;
   - зміни рекомендацій за 7 днів;
   - поточні налаштування сповіщень і мови.

   Кнопки: 🔔 сповіщення · 📰 щоденний дайджест · 🌍 країни (до 5) · 🌐 мова · 🔄 оновити · ℹ️ як рахується · кнопки інших країн для перемикання.

Сповіщення (своєю мовою): зміна рекомендації щодо країни (без редакційних правок) і зміна балу на 1 і більше з поясненням, хто це каже і чому. Дайджест: щоранку бал кожної відстежуваної країни, зміна за добу і найбільші зростання в регіоні.
Адмінські команди (`TELEGRAM_ADMIN_IDS`): `/status`, `/collect`, `/warcheck`.

**Статус війни** береться з вручну перевіреного довідника [`config/conflicts.yaml`](config/conflicts.yaml), складеного на основі RULAC. Щодня `tension-index war-check` звіряє його зі списком конфліктів Wikipedia і надсилає розбіжності адміну. Автоматично довідник не змінюється.

## Стек

Python 3.12 · [uv](https://docs.astral.sh/uv/) · aiogram 3 · httpx · SQLite (aiosqlite) · Claude Haiku 4.5 через OpenRouter, Anthropic API або локальний Claude Code (`CLASSIFIER_PROVIDER=claude_code`, за підпискою Claude) для класифікації змін · systemd на власному сервері · GitHub Actions (CI і Pages).

## Структура

```
src/tension_index/
  cli.py           команди: init-db, collect, health, bot, war-check, roadmap
  config.py        налаштування з .env
  countries.py     38 країн моніторингу
  storage.py       SQLite + міграції
  diff.py          виявлення змін між версіями
  collector.py     збір з усіх джерел
  sources/         джерела рекомендацій (gov_uk.py — Велика Британія)
  health.py        перевірки стану
  notify.py        надсилання в Telegram
  bot/             Telegram-бот (aiogram): handlers, views, callbacks
  i18n.py          тексти бота укр/англ
  scoring.py       шкала 0–10 (config/weights.yaml)
  war_status.py    статус війни (config/conflicts.yaml + Wikipedia)
  roadmap.py       генерація PLAN.md і сторінки прогресу
scripts/           bootstrap, run, healthcheck, deploy, backup, install_server
deploy/systemd/    юніти: бот, таймери збору, healthcheck і бекапу
config/           weights.yaml (шкала), conflicts.yaml (статус війни)
docs/             алгоритм і джерела
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
./scripts/run.sh run       # повний цикл: збір → класифікація → бал (~1 хв)
./scripts/run.sh gdelt     # щоденний збір GDELT окремо (кілька хвилин)
./scripts/run.sh why LU       # з чого складається бал країни (блоки, сигнали)
./scripts/run.sh collect --countries PL,EE   # лише збір для кількох країн
./scripts/run.sh probe us --country PL      # що насправді віддає джерело
./scripts/run.sh health    # стан системи
./scripts/run.sh bot       # бот (Ctrl+C для зупинки)
make plan                  # перегенерувати PLAN.md після зміни roadmap.yaml
make site                  # переглянути сторінку прогресу на http://localhost:8000
make pages                 # опублікувати сторінку прогресу і панель (дані з data/tension.sqlite3) у gh-pages
```

**Сторінка прогресу.** Є два способи публікації:
- автоматично через GitHub Actions (`.github/workflows/pages.yml` оновлює гілку `gh-pages` після кожного push у `main`);
- без Actions: `make pages` збирає сайт і пушить його в гілку `gh-pages` (Settings → Pages → Source: Deploy from a branch → `gh-pages` / `root`).

Pages налаштовано на гілку `gh-pages` (Settings → Pages → Deploy from a branch).

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
| `tension-collect.timer` | повний цикл кожні 3 години: збір, класифікація, бал, сповіщення |
| `tension-health.timer` | healthcheck кожні 15 хвилин, алерт у Telegram при FAIL |
| `tension-backup.timer` | щоденний бекап SQLite, зберігаються останні 14 |
| `tension-warcheck.timer` | щоденна звірка статусу війни з Wikipedia |
| `tension-digest.timer` | щоденний дайджест підписникам (06:37 UTC) |
| `tension-gdelt.timer` | щоденний збір GDELT (04:43 UTC, кілька хвилин) |

Оновлення: `./scripts/deploy.sh` (гілка `main`) або `./scripts/deploy.sh dev-tg-bot` для тесту гілки.
Стан: `./scripts/healthcheck.sh` (коди виходу: 0 OK, 1 WARN, 2 FAIL), логи: `journalctl -u tension-bot -f`.

Для зовнішнього моніторингу вкажіть `HEALTH_PING_URL` (наприклад, безкоштовний [healthchecks.io](https://healthchecks.io)): якщо сервер перестане надсилати пінги, прийде лист.

## Гілки і процес

- `main` — гілка за замовчуванням, завжди робоча. Зміни тільки через Pull Request із зеленим CI.
- Нові гілки: `dev-<область>`, коротко й зрозуміло: `dev-tg-bot`, `dev-collector`, `dev-scoring`. Виправлення: `fix-<що>`, документація: `docs-<що>`. Назва гілки для кожного етапу вказана в плані.
- Після кожної завершеної задачі оновлюється статус у `roadmap/roadmap.yaml` і виконується `make plan`.

Детальніше: [CONTRIBUTING.md](CONTRIBUTING.md).
