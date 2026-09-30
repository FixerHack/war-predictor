# Tension Index — Project plan

> Generated from `roadmap/roadmap.yaml` by `uv run tension-index roadmap`. Do not edit by hand. [Українська версія](PLAN.md)

**Overall progress: 15%** · left ≈ 30.3 days · ✅ 17 · 🟡 2 · ⬜ 40 · ⛔ 0

## Milestones

- **M1** — MVP: 14 days of unattended collection, backtest scores Ukraine 7+ before 2022-02-24, every alert explained

## S0. Foundation & infrastructure — 75%

Branch: `dev-bootstrap`

- ✅ **S0.1** Repository, main as default branch, branch naming rules
- ✅ **S0.2** Python 3.12 + uv, package layout, tension-index CLI
- ✅ **S0.3** SQLite storage with migrations, full text versions
- ✅ **S0.4** Healthcheck (CLI, script, systemd timer, Telegram alert, dead-man ping)
- ✅ **S0.5** Run, deploy and server install scripts (systemd)
- ✅ **S0.6** CI: ruff + pytest via uv
- ✅ **S0.7** Plan + progress page on GitHub Pages
- ✅ **S0.8** README in Ukrainian and English
- ⬜ **S0.9** Enable GitHub Pages (Settings → Pages → Source: GitHub Actions) _(owner: Dmytro)_
- ⬜ **S0.10** Create bot via @BotFather, test channel, fill in .env _(owner: Dmytro)_
- ⬜ **S0.11** First server deploy: install_server.sh, verify healthcheck _(owner: Dmytro)_
- ⬜ **S0.12** Protect main (Settings → Branches: PR only, CI green) _(owner: Dmytro)_

## S1. Input decisions — 60%

Branch: `—`

- ✅ **S1.1** Countries: EU-27, UK, Norway, Switzerland, Iceland, Moldova, Western Balkans (38)
- ✅ **S1.2** Format: public service
- ✅ **S1.3** Advisory sources: US, UK, Israel, Canada, Australia, Germany, France + Russian and Belarusian MFA
- 🟡 **S1.4** Approve tier 1–2 news source list
- ✅ **S1.5** Development: Dmytro + Claude Code; own server
- ✅ **S1.6** Budget: free stack, only Claude API is paid (10–20 $ cap)
- ⬜ **S1.7** Legal disclaimer text (not a forecast, not advice) _(owner: Dmytro)_

## S2. Official advisory collection — 17%

Branch: `dev-collector`

- ✅ **S2.1** Source framework, version storage, change detection (diff)
- 🟡 **S2.2** UK (GOV.UK Content API): implemented, needs live verification
- ⬜ **S2.3** Germany (Auswärtiges Amt OpenData API)
- ⬜ **S2.4** US (travel.state.gov levels + embassy Security Alerts)
- ⬜ **S2.5** Canada (travel.gc.ca)
- ⬜ **S2.6** Australia (Smartraveller)
- ⬜ **S2.7** France (diplomatie.gouv.fr, Conseils aux voyageurs)
- ⬜ **S2.8** Israel (NSC travel warnings)
- ⬜ **S2.9** Russian and Belarusian MFA advisories to own citizens (aggressor signals)
- ✅ **S2.10** Telegram alert when a source breaks

## S3. Aviation & airspace — 0%

Branch: `dev-aviation`

- ⬜ **S3.1** EASA Conflict Zone Information Bulletins
- ⬜ **S3.2** NOTAM: airspace restrictions and closures
- ⬜ **S3.3** Airline flight cancellations (source TBD)

## S4. News, analysis, domestic measures — 0%

Branch: `dev-news`

- ⬜ **S4.1** Tier 1–2 RSS (BBC, NATO, EEAS, ERR, LSM, LRT, Yle, ISW, CrisisWatch, ECFR, RUSI), headlines and links only
- ⬜ **S4.2** GDELT: volume and tone per country
- ⬜ **S4.3** Source trust tiers; unconfirmed tier 3–4 items don't affect the score
- ⬜ **S4.4** Domestic measures: mobilisation, emergency decrees, border closures
- ⬜ **S4.5** Market indicators: CDS, spreads, FX (free source)

## S5. Historical archive — 0%

Branch: `dev-history`

- ⬜ **S5.1** Download past advisory versions from the Wayback Machine (CDX API)
- ⬜ **S5.2** Episodes: Ukraine 2021–22, Armenia/Azerbaijan 2020, Israel/Iran 2024–25

## S6. Change classification (Claude API) — 0%

Branch: `dev-classifier`

- ⬜ **S6.1** Prompt and JSON schema: reason, change type, staff, borders, quote
- ⬜ **S6.2** Call only on changed fragments, prompt caching, spend cap
- ⬜ **S6.3** Gold set of 30–50 changes to evaluate quality

## S7. Scoring 0–10 — 0%

Branch: `dev-scoring`

- ⬜ **S7.1** Blocks A–F with weights in config/weights.yaml
- ⬜ **S7.2** Per-country 6–12 month baseline and deviation
- ⬜ **S7.3** Modifiers: cross-government synchrony, regional divergence, decay, verification
- ⬜ **S7.4** Score explanation: which signals, how many independent sources

## S8. Backtesting — 0%

Branch: `dev-backtest`

- ⬜ **S8.1** Replay the scale on historical episodes
- ⬜ **S8.2** Weight tuning, false alarm and miss report

## S9. Telegram bot & alerts — 17%

Branch: `dev-tg-bot`

- ✅ **S9.1** Base aiogram 3 bot: /status, /changes, /help, admin /collect
- ⬜ **S9.2** Alerts on score change of 1+ with explanation and quote
- ⬜ **S9.3** /country XX: current score, history, reasons
- ⬜ **S9.4** User country subscriptions, weekly digest

## S10. Public dashboard — 0%

Branch: `dev-dashboard`

- ⬜ **S10.1** Export scores.json (read-only public API)
- ⬜ **S10.2** Map of Europe with levels and per-country score history
- ⬜ **S10.3** Disclaimer and methodology on the page

## S11. Operations — 13%

Branch: `dev-ops`

- ✅ **S11.1** Daily SQLite backup with rotation
- ⬜ **S11.2** Dead-man switch on healthchecks.io (free) _(owner: Dmytro)_
- ⬜ **S11.3** Auto-deploy from main (GitHub Actions → SSH)
- ⬜ **S11.4** 14 days of continuous collection without manual intervention

## Ideas

- Bilingual bot (uk/en) — the public product serves foreigners too
- "Silence" signal: country drops out of the media while advisories are active
- Cross-government wording match: same reason within a week = stronger signal
- Message Batches API for the historical archive — half the price
- Move to PostgreSQL if dashboard traffic grows
