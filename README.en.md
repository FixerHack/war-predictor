# Tension Index

[Українська](README.md) · **English**

An escalation-signal indicator for European countries on a 0–10 scale. The system collects official government travel advisories every day, diffs new versions against previous ones, classifies the changes and shows what exactly changed and how many independent sources confirm it.

> ⚠️ This is an indicator of the state of signals, not a forecast and not advice to leave a country. Decisions are up to each person.

- 📋 Plan: [PLAN.en.md](PLAN.en.md) (generated from [`roadmap/roadmap.yaml`](roadmap/roadmap.yaml))
- 🧮 Scale algorithm: [docs/algorithm.md](docs/algorithm.md) (Ukrainian)
- 🗂 Data sources and war trackers: [docs/sources.md](docs/sources.md) (Ukrainian)
- ✅ What the owner has to do (access, decisions): [docs/owner-steps.md](docs/owner-steps.md) (Ukrainian)
- 📊 Progress: https://fixerhack.github.io/war-predictor/
- 🗺 Public dashboard (map, scores and reasons per country): https://fixerhack.github.io/war-predictor/dashboard/

## Scale

| Score | Level | Meaning |
|---|---|---|
| 0–2 | 🟢 green | baseline |
| 3–4 | 🟡 yellow | isolated changes, single source |
| 5–6 | 🟠 orange | changes across several blocks, or several governments in sync |
| 7–8 | 🔴 red | airspace restrictions, authorised departure of embassy staff, emergency measures |
| 9–10 | 🟥 critical | ordered departure by several governments, airspace closure, mobilisation |

Countries: EU-27, UK, Norway, Switzerland, Iceland, Moldova, Western Balkans (38).

## Bot

1. `/start` → choose a language (Українська / English).
2. Choose one of 38 countries (up to 5 can be followed later).
3. A dashboard, edited in place with inline buttons. It shows:
   - the tension score (or "calibrating" while data is thin) and the main reasons with quotes;
   - a short line for each other followed country;
   - the war status on the country's territory;
   - borders with a country at war or with the aggressor;
   - advisory changes in the last 7 days;
   - the current notification and language settings.

   Buttons: 🔔 alerts · 📰 daily digest · 🌍 countries (up to 5) · 🌐 language · 🔄 refresh · ℹ️ how it works · buttons for the other countries to switch.

Alerts (in the user's language): a changed advisory for a followed country (editorial edits skipped) and score moves of 1 or more with who says what and why. Digest: every morning, each followed country's score, its 24 h change and the largest rises in the region.
Admin commands (`TELEGRAM_ADMIN_IDS`): `/status`, `/collect`, `/warcheck`.

**War status** comes from the curated, RULAC-based [`config/conflicts.yaml`](config/conflicts.yaml). Every day `tension-index war-check` compares it with Wikipedia's list of ongoing conflicts and sends any mismatches to admins. The file is never changed automatically.

## Stack

Python 3.12 · [uv](https://docs.astral.sh/uv/) · aiogram 3 · httpx · SQLite (aiosqlite) · Claude Haiku 4.5 via OpenRouter, the Anthropic API or the local Claude Code CLI (`CLASSIFIER_PROVIDER=claude_code`, on a Claude subscription) to classify changes · systemd on our own server · GitHub Pages (published by the server) · GitHub Actions (CI, optional).

## Layout

```
src/tension_index/
  cli.py           commands: init-db, collect, health, bot, war-check, roadmap
  config.py        settings from .env
  countries.py     the 38 monitored countries
  storage.py       SQLite + migrations
  diff.py          change detection between versions
  collector.py     collection across all sources
  sources/         advisory sources (gov_uk.py — United Kingdom)
  health.py        health checks
  notify.py        Telegram delivery
  bot/             Telegram bot (aiogram): handlers, views, callbacks
  i18n.py          bot texts uk/en
  scoring.py       0-10 scale (config/weights.yaml)
  war_status.py    war status (config/conflicts.yaml + Wikipedia)
  roadmap.py       renders PLAN.md and the progress page
scripts/           bootstrap, run, healthcheck, deploy, backup, install_server
deploy/systemd/    units: bot, collect/health/backup timers
config/           weights.yaml (scale), conflicts.yaml (war status)
docs/             algorithm and sources
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
./scripts/run.sh run       # full cycle: collect → classify → score (~1 min)
./scripts/run.sh gdelt     # daily GDELT collection on its own (up to 10 minutes)
./scripts/run.sh why LU       # what a country's score is made of (blocks, signals)
./scripts/run.sh collect --countries PL,EE   # collection only, a few countries
./scripts/run.sh probe us --country PL      # what a source really returns
./scripts/run.sh health    # system health
./scripts/run.sh bot       # bot (Ctrl+C to stop)
make plan                  # regenerate PLAN.md after editing roadmap.yaml
make site                  # preview the progress page at http://localhost:8000
make pages                 # publish the progress page and dashboard (data from data/tension.sqlite3) to gh-pages
```

**Public map and progress page.** The server publishes them to the `gh-pages` branch every 30 minutes (`tension-pages.timer` → `scripts/publish_pages.sh`), only when the data changed. The branch keeps a single commit, the current site. This needs a deploy key with write access on the server and `PAGES_REMOTE` in `.env` (see [docs/owner-steps.md](docs/owner-steps.md)). By hand: `make pages` (data from the local database; the server replaces it with its own within half an hour).

Pages is set to serve the `gh-pages` branch (Settings → Pages → Deploy from a branch → `gh-pages` / `root`).

## Server

Requirements: Debian/Ubuntu with systemd, a user with `sudo`.

```bash
git clone https://github.com/FixerHack/war-predictor.git ~/war-predictor
cd ~/war-predictor
./scripts/install_server.sh   # first run creates .env and stops
nano .env                     # fill in TELEGRAM_*
./scripts/install_server.sh   # installs and starts the systemd units
```

On the server, classification goes through the Claude Code gateway. It is a separate service from its own repository, [FixerHack/claude-gateway](https://github.com/FixerHack/claude-gateway), in its own directory (`~/claude-gateway`), installed on its own (that repository's `scripts/install.sh`, see [`docs/deploy-agent.md`](docs/deploy-agent.md)). The bot connects to it like any client: `.env` sets `GATEWAY_URL` (default `http://127.0.0.1:8787`) and `GATEWAY_TOKEN` (one of the gateway's `GATEWAY_TOKENS`). Without a token the bot classifies with rules only.

What runs:

| Unit | Purpose |
|---|---|
| `tension-bot.service` | the bot, restarted on failure |
| `tension-collect.timer` | hourly: collect for countries due a refresh (score 0 every 12 h, 1–3 every 8 h, 4–6 every 4 h, 7–10 hourly), classify, score, alerts |
| `tension-health.timer` | health check every 15 minutes, Telegram alert on FAIL |
| `tension-backup.timer` | daily SQLite backup, last 14 kept |
| `tension-warcheck.timer` | daily war status check against Wikipedia |
| `tension-digest.timer` | daily digest to subscribers (06:37 UTC) |
| `tension-gdelt.timer` | daily GDELT collection (07:43 UTC, up to 10 minutes) |
| `tension-pages.timer` | every 30 minutes: the public map and progress page to `gh-pages` when the data changed (needs `PAGES_REMOTE`) |

Update: `./scripts/deploy.sh` (branch `main`) or `./scripts/deploy.sh dev-tg-bot` to test a branch.
Status: `./scripts/healthcheck.sh` (exit codes: 0 OK, 1 WARN, 2 FAIL); logs: `journalctl -u tension-bot -f`.

For external monitoring set `HEALTH_PING_URL` (e.g. free [healthchecks.io](https://healthchecks.io)): if the server stops pinging, you get an email.

## Claude Code gateway

[claude-gateway](https://github.com/FixerHack/claude-gateway) is a separate tool in its own repository: an HTTP API (its own, OpenAI- and Anthropic-compatible) and an MCP server on top of Claude Code. Any program on the server can call Claude through it with ready-made requests, and `tension-index` can classify changes through it (`CLASSIFIER_PROVIDER=gateway`).

## Branches and workflow

- `main` is the default branch and always works. Changes land only via Pull Request with green CI.
- New branches: `dev-<area>`, short and clear: `dev-tg-bot`, `dev-collector`, `dev-scoring`. Fixes: `fix-<what>`, docs: `docs-<what>`. Each stage in the plan names its branch.
- After each finished task, update its status in `roadmap/roadmap.yaml` and run `make plan`.

More: [CONTRIBUTING.md](CONTRIBUTING.md).
