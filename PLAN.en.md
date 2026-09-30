# Tension Index: Europe — Project plan

> Generated from `roadmap/roadmap.yaml` by `uv run tension-index roadmap`. Do not edit by hand. [Українська версія](PLAN.md)

Version **0.2.18**, updated 2026-09-30.

**Overall progress: 34%** · left ≈ 28.9 days · ✅ 33 · 🟡 6 · ⬜ 38 · ⛔ 1

## Milestones

- **M1** — MVP: 14 days of unattended collection, backtest scores Ukraine 7+ before 2022-02-24, every alert explained

## S0. Foundation & infrastructure — 79%

_Repository, working environment on the MacBook and server, keys, Telegram bot._

Branch: `dev-bootstrap`

- ✅ **S0.1** Repository, main as default branch, branch naming rules
- ✅ **S0.2** Python 3.12 + uv, package layout, tension-index CLI
- ✅ **S0.3** SQLite storage with migrations, full text versions
- ✅ **S0.4** Healthcheck (CLI, script, systemd timer, Telegram alert, dead-man ping)
- ✅ **S0.5** Run, deploy and server install scripts (systemd)
- ✅ **S0.6** CI: ruff + pytest via uv
- ✅ **S0.7** Plan + progress page on GitHub Pages
- ✅ **S0.8** README in Ukrainian and English
- ✅ **S0.9** MacBook: install uv and Claude Code, clone the repo, ./scripts/bootstrap.sh _(manual)_
- ⬜ **S0.10** Anthropic Console: top-up, API key, monthly spend cap _(manual)_
- ✅ **S0.11** Create bot via @BotFather, test channel, fill in .env _(manual)_
- ⬜ **S0.12** First server deploy: install_server.sh, verify healthcheck _(manual)_
  - Postponed: bot and system first.
- ✅ **S0.13** Enable GitHub Pages: Source → Deploy from a branch → gh-pages / root _(manual)_
  - Live: fixerhack.github.io/war-predictor
- ⬜ **S0.15** Unlock GitHub Actions: Settings → Billing and plans (invoice / card) _(manual)_
  - CI does not start: "account is locked due to a billing issue".
- ✅ **S0.16** Publish the progress page without Actions (make pages → gh-pages branch)
- ⬜ **S0.14** Protect main (PR only, CI green); delete branch claude/funny-planck-leoxip _(manual)_

## S1. Input decisions — 80%

_Fix scope, format and sources._

Branch: `—`

- ✅ **S1.1** Countries: EU-27, UK, Norway, Switzerland, Iceland, Moldova, Western Balkans (38)
  - Ukraine excluded: active war keeps the scale at maximum.
- ✅ **S1.2** Format: public service
- ✅ **S1.3** Advisory sources: US, UK, Israel, Canada, Australia, Germany, France + Russian and Belarusian MFA
- 🟡 **S1.4** Approve the source list (docs/sources.md) _(manual)_
  - Source catalogue with access and verification status is ready, needs approval.
- ✅ **S1.5** Development: project owner + Claude Code; own server
- ✅ **S1.6** Budget: free stack, only Claude API is paid (10–20 $ cap)
- ⬜ **S1.7** Legal disclaimer text (not a forecast, not advice) _(manual)_
- ✅ **S1.8** 0–10 scale algorithm (docs/algorithm.md)
- ✅ **S1.9** Research of sources and war trackers (docs/sources.md)

## S2. Official advisory collection — 52%

_Regular collection of advisories, storing every text version._

Branch: `dev-collector`

- ✅ **S2.1** Source framework, version storage, change detection (diff)
- ✅ **S2.2** UK (GOV.UK Content API)
  - Verified on live data (PL, EE, MD).
- 🟡 **S2.3** Germany (Auswärtiges Amt OpenData API)
  - Implemented; verify live: tension-index probe
- 🟡 **S2.4** US (TAsTWs RSS + country pages + embassy Security Alerts)
  - Implemented; verify live: tension-index probe
- 🟡 **S2.5** Canada (open data JSON)
  - Implemented; verify live: tension-index probe
- 🟡 **S2.6** Australia (Smartraveller destinations-export)
  - Implemented; verify live: tension-index probe
- 🟡 **S2.7** France (diplomatie.gouv.fr, scraping)
  - Page text only, level set by the classifier; verify with probe fr
- ⛔ **S2.8** Israel (NSC travel warnings)
  - NSC page is a JS app with no known API; needs a sample response. Low weight for Europe.
- ⬜ **S2.9** Russian and Belarusian MFA advisories to own citizens
  - Moved to S4: collected via news/GDELT (mid.ru blocks foreign requests).
- ✅ **S2.10** Telegram alert when a source breaks
- ✅ **S2.11** Strip update dates and boilerplate before diffing

## S3. Aviation & airspace — 0%

_Official airspace warnings and actual traffic drops._

Branch: `dev-aviation`

- ⬜ **S3.1** EASA Conflict Zone Information Bulletins
- ⬜ **S3.2** NOTAM: airspace restrictions and closures
- ⬜ **S3.3** OpenSky: drop in flights per airport

## S4. News, analysis, domestic measures — 0%

_Independent confirmation from media, analysis, markets and the country's own measures._

Branch: `dev-news`

- ⬜ **S4.1** Tier 1–2 RSS, headlines and links only
- ⬜ **S4.2** GDELT: volume and tone per country
- ⬜ **S4.3** CrisisWatch: deterioration and Conflict Risk Alerts
- ⬜ **S4.4** Domestic measures: mobilisation, emergency decrees, border closures
- ⬜ **S4.5** Markets: bonds and FX via ECB Data Portal

## S5. Historical archive — 0%

_Past advisory versions to test the scale on known episodes._

Branch: `dev-history`

- ⬜ **S5.1** Download past versions from the Wayback Machine (CDX API)
- ⬜ **S5.2** Episodes: Ukraine 2021–22, Armenia/Azerbaijan 2020, Israel/Iran 2024–25

## S6. Change classification (Claude API) — 0%

_Claude determines the reason and type of each change and turns it into a signal._

Branch: `dev-classifier`

- ⬜ **S6.1** Prompt and JSON schema: reason, change type, staff, borders, quote
- ⬜ **S6.2** Call only on changed fragments, prompt caching, spend cap
- ⬜ **S6.3** Manual check on 50 examples

## S7. Scoring 0–10 — 50%

_Weighted score with modifiers, numbers in config/weights.yaml._

Branch: `dev-scoring`

- ✅ **S7.1** Scoring engine: blocks A–F, caps, reasons, decay, verification, floors
- ✅ **S7.2** Country baseline and deviation, cross-government synchrony, regional divergence
- ⬜ **S7.3** Signals table and daily score computation for all countries
- ⬜ **S7.4** Score explanation in alerts and on the dashboard

## S8. Backtesting — 0%

_The scale must fire on known episodes in time and without mass false alarms._

Branch: `dev-backtest`

- ⬜ **S8.1** Replay the scale on historical episodes
- ⬜ **S8.2** False alarm and miss report
- ⬜ **S8.3** Weight tuning

## S9. Telegram bot & alerts — 60%

_Bot with language and country choice, a dashboard and explained alerts._

Branch: `dev-tg-bot`

- ✅ **S9.1** Base aiogram 3 bot and admin commands /status, /collect, /warcheck
- ✅ **S9.2** Onboarding: language (uk/en) → country → dashboard
- ✅ **S9.3** Inline dashboard: score, war status, neighbours, 7-day changes; toggles for alerts, country, language
- ✅ **S9.4** Change alerts to a country's subscribers in their language
- ⬜ **S9.5** Alerts on score change of 1+ with explanation and quote
- ⬜ **S9.6** Daily regional digest
- ⬜ **S9.7** Several countries per user

## S10. War status — 57%

_Show whether a war is already under way on the country's territory, separately from the escalation scale._

Branch: `dev-war-status`

- ✅ **S10.1** Curated config/conflicts.yaml based on RULAC (Moldova, Cyprus — occupation; borders with war and aggressor)
- ✅ **S10.2** Daily check against Wikipedia, mismatches to admins (war-check)
- ⬜ **S10.3** Obtain a UCDP API token _(manual)_
- ⬜ **S10.4** UCDP Candidate Events as a second automatic source
- ✅ **S10.5** Verify the Wikipedia parser against the live page
  - Verified on the live page: sections, Location column; France (French Guiana) excluded by review.

## S11. Public dashboard — 0%

_Country map and score history on free hosting._

Branch: `dev-dashboard`

- ⬜ **S11.1** Export scores.json (read-only public API)
- ⬜ **S11.2** Map of Europe coloured by level
- ⬜ **S11.3** Country page: score history and change explanations
- ⬜ **S11.4** Disclaimer and methodology on the site

## S12. Operations — 20%

_The system runs unattended and reports failures._

Branch: `dev-ops`

- ✅ **S12.1** Daily SQLite backup with rotation
- ⬜ **S12.2** Dead-man switch on healthchecks.io (free) _(manual)_
- ⬜ **S12.3** Auto-deploy from main (GitHub Actions → SSH)

## S13. MVP criteria — 0%

_The MVP is done when all three conditions hold._

Branch: `—`

- ⬜ **S13.1** 14 consecutive days of collection without manual intervention
- ⬜ **S13.2** On the Ukraine episode the score reaches 7+ before 2022-02-24
- ⬜ **S13.3** Every alert contains the source, a description of the change and a quote

## Decisions

- 2026-09-30: Overseas territories of European countries do not affect war status; exclusions are recorded by hand in wikipedia_ignore
- 2026-09-30: Server deploy postponed; priority is the bot and system on the MacBook
- 2026-09-27: 0–10 scale instead of a probability: describes signals, does not forecast war
- 2026-09-27: Advisories weigh less for EU/NATO members: allies rarely raise levels in advance
- 2026-09-27: Compare against the country's own baseline, not absolute levels
- 2026-09-30: Own server (systemd) instead of scheduled GitHub Actions; Python 3.12 + uv, aiogram 3
- 2026-09-30: Branches: main by default, work in dev-<area>, fix-<what>, docs-<what>
- 2026-09-30: Blocks combine as independent confirmations, each with a contribution cap
- 2026-09-30: War status is separate from the scale; curated by hand, automation only proposes changes

## Risks

- GitHub Actions locked by an account billing issue: no CI until unlocked, checks run locally only (make check)
- Collection blocking: government sites may block requests from the server
- Terms of use: no open Reuters/AP RSS; ACLED licence for a public service
- Public responsibility: the score will be read as a forecast; disclaimer and methodology needed
- Untested weights: an expert hypothesis until stage S8
- Automatic war trackers list countries hit only by spillover; manual review needed

## Changelog

- **0.2.18** (2026-09-30)
  - Sources: Germany, US, Canada, Australia, France
  - Boilerplate (update dates) stripped before diffing
  - probe command to inspect sources
- **0.2.10** (2026-09-30)
  - War status: reviewed exclusions via wikipedia_ignore; France — Brazilian drug war (French Guiana)
  - Wikipedia check verified on the live page
- **0.2.9** (2026-09-30)
  - war-check --explain: correct conflict name and Location cell text
- **0.2.8** (2026-09-30)
  - Wikipedia war status: Location column only (parties to conflicts abroad no longer count)
  - war-check --explain: where a country mention comes from
- **0.2.7** (2026-09-30)
  - Wikipedia parser works on rendered HTML and headings of any level
  - war-check --headings: page structure diagnostics
- **0.2.6** (2026-09-30)
  - Verified on the MacBook: bootstrap, bot (onboarding and dashboard), GOV.UK collection, healthcheck
  - war-check: fails if the Wikipedia layout changes; prints recognised countries
- **0.2.2** (2026-09-30)
  - Progress page live from the gh-pages branch
  - pages.yml now refreshes gh-pages instead of deploying directly
- **0.2.1** (2026-09-30)
  - Publish the progress page without GitHub Actions: make pages → gh-pages branch
- **0.2.0** (2026-09-30)
  - Bot: language → country → inline dashboard with toggles
  - War status: RULAC-based list + Wikipedia check
  - Scale algorithm and scoring engine with tests
  - Source catalogue
  - Plan merged with the earlier dashboard
- **0.1.1** (2026-09-30)
  - Project skeleton: uv, SQLite, GOV.UK collector, bot, healthcheck, scripts, CI, Pages
- **0.1.0** (2026-09-27)
  - Project dashboard created
  - Input decisions recorded

## Ideas

- "Silence" signal: country drops out of the media while advisories are active
- Message Batches API for the historical archive — half the price
- Move to PostgreSQL if user numbers grow
