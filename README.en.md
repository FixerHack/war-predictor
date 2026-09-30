# Tension Index

[Українська](README.md) · **English**

An escalation-signal indicator for European countries on a 0–10 scale. The system collects official government travel advisories every day, diffs new versions against previous ones, classifies the changes and shows what exactly changed and how many independent sources confirm it.

> ⚠️ This is an indicator of the state of signals, not a forecast and not advice to leave a country. Decisions are up to each person.

- 📋 Plan: [PLAN.en.md](PLAN.en.md) (generated from [`roadmap/roadmap.yaml`](roadmap/roadmap.yaml))
- 📊 Progress: the project's GitHub Pages (`https://fixerhack.github.io/war-predictor/` once Pages is enabled)

## Scale

| Score | Level | Meaning |
|---|---|---|
| 0–2 | 🟢 green | baseline |
| 3–4 | 🟡 yellow | isolated changes, single source |
| 5–6 | 🟠 orange | changes across several blocks, or several governments in sync |
| 7–8 | 🔴 red | airspace restrictions, authorised departure of embassy staff, emergency measures |
| 9–10 | 🟥 critical | ordered departure by several governments, airspace closure, mobilisation |

Countries: EU-27, UK, Norway, Switzerland, Iceland, Moldova, Western Balkans (38).

## Stack

Python 3.12 · [uv](https://docs.astral.sh/uv/) · aiogram 3 · httpx · SQLite (aiosqlite) · Claude API (from stage S6) · systemd on our own server · GitHub Actions (CI and Pages).

## Layout

```
src/tension_index/
  cli.py           commands: init-db, collect, health, bot, roadmap
  config.py        settings from .env
  countries.py     the 38 monitored countries
  storage.py       SQLite + migrations
  diff.py          change detection between versions
  collector.py     collection across all sources
  sources/         advisory sources (gov_uk.py — United Kingdom)
  health.py        health checks
  notify.py        Telegram delivery
  bot/             Telegram bot (aiogram)
  roadmap.py       renders PLAN.md and the progress page
scripts/           bootstrap, run, healthcheck, deploy, backup, install_server
deploy/systemd/    units: bot, collect/health/backup timers
roadmap/           roadmap.yaml — single source of the plan
site/              progress page template
tests/
```

## Local development (MacBook)

```bash
brew install uv            # or: curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/FixerHack/war-predictor.git
cd war-predictor
./scripts/bootstrap.sh     # Python 3.12, deps, .env, database, tests
```

Then fill in `.env` (bot token, channel ID, your Telegram ID in `TELEGRAM_ADMIN_IDS`) and run:

```bash
make test                  # tests
make lint                  # ruff
./scripts/run.sh collect --countries PL,EE   # collect a few countries
./scripts/run.sh health    # system health
./scripts/run.sh bot       # bot (Ctrl+C to stop)
make plan                  # regenerate PLAN.md after editing roadmap.yaml
make site                  # preview the progress page at http://localhost:8000
```

## Server

Requirements: Debian/Ubuntu with systemd, a user with `sudo`.

```bash
git clone https://github.com/FixerHack/war-predictor.git ~/war-predictor
cd ~/war-predictor
./scripts/install_server.sh   # first run creates .env and stops
nano .env                     # fill it in
./scripts/install_server.sh   # installs and starts the systemd units
```

What runs:

| Unit | Purpose |
|---|---|
| `tension-bot.service` | the bot, restarted on failure |
| `tension-collect.timer` | collection every 3 hours, alerts on changes and failures |
| `tension-health.timer` | health check every 15 minutes, Telegram alert on FAIL |
| `tension-backup.timer` | daily SQLite backup, last 14 kept |

Update: `./scripts/deploy.sh` (branch `main`) or `./scripts/deploy.sh dev-tg-bot` to test a branch.
Status: `./scripts/healthcheck.sh` (exit codes: 0 OK, 1 WARN, 2 FAIL); logs: `journalctl -u tension-bot -f`.

For external monitoring set `HEALTH_PING_URL` (e.g. free [healthchecks.io](https://healthchecks.io)): if the server stops pinging, you get an email.

## Branches and workflow

- `main` is the default branch and always works. Changes land only via Pull Request with green CI.
- New branches: `dev-<area>`, short and clear: `dev-tg-bot`, `dev-collector`, `dev-scoring`. Fixes: `fix-<what>`, docs: `docs-<what>`. Each stage in the plan names its branch.
- After each finished task, update its status in `roadmap/roadmap.yaml` and run `make plan`.

More: [CONTRIBUTING.md](CONTRIBUTING.md).
