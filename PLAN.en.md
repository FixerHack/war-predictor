# Tension Index: Europe — Project plan

> Generated from `roadmap/roadmap.yaml` by `uv run tension-index roadmap`. Do not edit by hand. [Українська версія](PLAN.md)

Version **0.2.63**, updated 2026-09-30.

**Overall progress: 68%** · left ≈ 14.4 days · ✅ 51 · 🟡 19 · ⬜ 10 · ⛔ 4

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
- ⬜ **S0.10** OpenRouter: top-up, API key (OPENROUTER_API_KEY in .env), spend limit _(manual)_
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

## S2. Official advisory collection — 56%

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
- ⛔ **S2.6** Australia (Smartraveller destinations-export)
  - Smartraveller does not answer automated requests (export and pages, tested 2026-09-30); disabled via DISABLED_SOURCES=au.
- 🟡 **S2.7** France (diplomatie.gouv.fr, scraping)
  - Page text only, level set by the classifier; verify with probe fr
- ⛔ **S2.8** Israel (NSC travel warnings)
  - NSC page is a JS app with no known API; needs a sample response. Low weight for Europe.
- 🟡 **S2.9** Russian and Belarusian MFA advisories to own citizens
  - Via GDELT: Russian-language reports of RU/BY MFA advice, 2+ outlets = confirmed.
- ✅ **S2.10** Telegram alert when a source breaks
- ✅ **S2.11** Strip update dates and boilerplate before diffing

## S3. Aviation & airspace — 33%

_Official airspace warnings and actual traffic drops._

Branch: `dev-aviation`

- 🟡 **S3.1** EASA Conflict Zone Information Bulletins
  - Implemented (page parsing); verify: tension-index probe easa
- ⛔ **S3.2** NOTAM: airspace restrictions and closures
  - No free European NOTAM API (EUROCONTROL EAD is paid). Airspace limits come from advisory texts and CZIBs.
- 🟡 **S3.3** OpenSky: drop in flights per airport
  - Implemented via OpenSky (traffic drop); baseline needs ~3 weeks of samples.
- ✅ **S3.6** Air traffic drop: norm only from 3+ weeks, 20-aircraft and 3σ thresholds, signal cleared on recovery
  - The false LU signal ("3 aircraft vs usual 10") can no longer happen.

## S4. News, analysis, domestic measures — 50%

_Independent confirmation from media, analysis, markets and the country's own measures._

Branch: `dev-news`

- 🟡 **S4.1** Tier 1–2 RSS, headlines and links only
  - Implemented: 13 feeds in config/feeds.yaml, an event counts only from 2+ feeds; check URLs: tension-index probe news
- 🟡 **S4.2** GDELT: volume and tone per country
  - Implemented: surge of military coverage vs 60 days (daily); counts only when news confirm.
- 🟡 **S4.3** CrisisWatch: deterioration and Conflict Risk Alerts
  - Via the Crisis Group RSS in the news feeds.
- 🟡 **S4.4** Domestic measures: mobilisation, emergency decrees, border closures
  - From news: emergency, borders, mobilisation (2+ feeds only).
- 🟡 **S4.5** Markets: bonds and FX via ECB Data Portal
  - ECB: 10y spread over Germany and FX (daily).

## S5. Historical archive — 76%

_Past advisory versions to test the scale on known episodes._

Branch: `dev-history`

- ✅ **S5.1** Download past versions from the Wayback Machine (CDX API)
  - tension-index history: Wayback captures (daily 45 days before the event, every 5 days earlier) into data/history.sqlite3.
- 🟡 **S5.2** Episodes: Ukraine 2021–22, Armenia/Azerbaijan 2020, Israel/Iran 2024–25
  - Episodes in config/episodes.yaml (Ukraine 2022, Azerbaijan 2020, Israel 2024, control France 2016); loading needs network, run locally.
- ✅ **S5.5** Wayback archive: long timeouts, retries on 429/5xx, progress in logs

## S6. Change classification (Claude API) — 62%

_Claude determines the reason and type of each change and turns it into a signal._

Branch: `dev-classifier`

- ✅ **S6.1** Prompt and JSON schema: reason, change type, staff, borders, quote
- ✅ **S6.2** Call only on changed fragments, prompt caching, spend cap
  - Changed fragments only, cached system prompt, CLASSIFIER_MAX_CALLS cap; rules work without a key.
- ⬜ **S6.3** Manual check on 50 examples _(manual)_
  - Needs an API key and real changes; review 50 classifications by hand.
- ✅ **S6.6** Quote filter: page fragments ("3 pays") are not shown

## S7. Scoring 0–10 — 100%

_Weighted score with modifiers, numbers in config/weights.yaml._

Branch: `dev-scoring`

- ✅ **S7.1** Scoring engine: blocks A–F, caps, reasons, decay, verification, floors
- ✅ **S7.2** Country baseline and deviation, cross-government synchrony, regional divergence
- ✅ **S7.3** Signals table and daily score computation for all countries
  - tension-index run: collect → classify → signals → score; no score without enough coverage (except threshold events).
- ✅ **S7.4** Score explanation in alerts and on the dashboard
- ✅ **S7.5** Guard against flapping sources (A → B → A) and the why command
  - Returning to a version seen within 7 days is not a change; such changes produce no score events. tension-index why LU lists blocks and active signals.

## S8. Backtesting — 50%

_The scale must fire on known episodes in time and without mass false alarms._

Branch: `dev-backtest`

- 🟡 **S8.1** Replay the scale on historical episodes
  - tension-index backtest: day-by-day replay, reports in reports/backtest; tested on synthetic data, awaiting the real archive.
- 🟡 **S8.2** False alarm and miss report
  - Report: PASS/FAIL against the episode expectation, first days at 3/5/7/9, control episode for false alarms.
- 🟡 **S8.3** Weight tuning
  - First step done on reconstructed timelines: surge bonus capped at 0.10, synchrony counts only real tightening (no terrorism or rewording). France 2015: 7.3 → 4.5; one government ordering departure: 7.6 → 7.0; Ukraine 2022 unchanged (8.3 / 9.0). Next: run on the real archive.

## S9. Telegram bot & alerts — 100%

_Bot with language and country choice, a dashboard and explained alerts._

Branch: `dev-tg-bot`

- ✅ **S9.1** Base aiogram 3 bot and admin commands /status, /collect, /warcheck
- ✅ **S9.2** Onboarding: language (uk/en) → country → dashboard
- ✅ **S9.3** Inline dashboard: score, war status, neighbours, 7-day changes; toggles for alerts, country, language
- ✅ **S9.4** Change alerts to a country's subscribers in their language
- ✅ **S9.5** Alerts on score change of 1+ with explanation and quote
  - Score moves by 1+ → subscribers get an explanation with sources and quotes.
- ✅ **S9.6** Daily regional digest
  - Daily digest (toggle on the dashboard, 06:37 UTC timer): score, 24 h change, regional rises.
- ✅ **S9.7** Several countries per user
  - Up to 5 countries: ticked list, switch the detailed card by buttons.

## S10. War status — 57%

_Show whether a war is already under way on the country's territory, separately from the escalation scale._

Branch: `dev-war-status`

- ✅ **S10.1** Curated config/conflicts.yaml based on RULAC (Moldova, Cyprus — occupation; borders with war and aggressor)
- ✅ **S10.2** Daily check against Wikipedia, mismatches to admins (war-check)
- ⬜ **S10.3** Obtain a UCDP API token _(manual)_
- ⛔ **S10.4** UCDP Candidate Events as a second automatic source
  - Waiting for the UCDP token (S10.3).
- ✅ **S10.5** Verify the Wikipedia parser against the live page
  - Verified on the live page: sections, Location column; France (French Guiana) excluded by review.

## S11. Public dashboard — 96%

_Country map and score history on free hosting._

Branch: `dev-dashboard`

- ✅ **S11.1** Export scores.json (read-only public API)
  - tension-index export → dashboard/scores.json (score, level, reasons, war status, 90-day history).
- ✅ **S11.2** Map of Europe coloured by level
  - Tile map of 38 countries, single-hue scale validated for colour blindness, light and dark.
- ✅ **S11.3** Country page: score history and change explanations
  - Country card: score, reasons with quotes, flags, war status, 90-day chart; table of all countries; #PL links.
- 🟡 **S11.4** Disclaimer and methodology on the site _(manual)_
  - Working disclaimer and methodology on the page; final wording approved by the owner (S1.7).
- ✅ **S11.6** Ukrainian explanations: the classifier's summary instead of the English quote (map, bot, alerts)
  - English quotes remain for ENG and where no Ukrainian summary exists yet (news, rule-based classification).
- ✅ **S11.5** Detailed explanation on the map (uk/en): summary, blocks, what governments say, what was observed, full method

## S12. Operations — 45%

_The system runs unattended and reports failures._

Branch: `dev-ops`

- ✅ **S12.1** Daily SQLite backup with rotation
- ⬜ **S12.2** Dead-man switch on healthchecks.io (free) _(manual)_
- 🟡 **S12.3** Auto-deploy from main (GitHub Actions → SSH)
  - .github/workflows/deploy.yml is ready (SSH → scripts/deploy.sh); runs once Actions are unlocked and DEPLOY_* secrets are set.

## S13. MVP criteria — 23%

_The MVP is done when all three conditions hold._

Branch: `—`

- ⬜ **S13.1** 14 consecutive days of collection without manual intervention
- ⬜ **S13.2** On the Ukraine episode the score reaches 7+ before 2022-02-24
- ✅ **S13.3** Every alert contains the source, a description of the change and a quote
  - Advisory alerts: source, description (classifier) and quote; score alerts: who, what and quotes.

## Decisions

- 2026-09-30: Surge bonus at most 0.10 to R; synchrony counts only level raises, staff posture, consular/border/airspace measures with reason relevance ≥ 0.5.
- 2026-09-30: Change classification: Claude Haiku 4.5 via OpenRouter
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

- A genuine revert of an advisory within 7 days is not reported as a change (the state still updates).
- Some government sites block automated requests (Australia); a source can be lost without notice
- GitHub Actions locked by an account billing issue: no CI until unlocked, checks run locally only (make check)
- Collection blocking: government sites may block requests from the server
- Terms of use: no open Reuters/AP RSS; ACLED licence for a public service
- Public responsibility: the score will be read as a forecast; disclaimer and methodology needed
- Untested weights: an expert hypothesis until stage S8
- Automatic war trackers list countries hit only by spillover; manual review needed

## Changelog

- **0.2.63** (2026-09-30)
  - W
  - a
  - y
  - b
  - a
  - c
  - k
  -  
  - a
  - r
  - c
  - h
  - i
  - v
  - e
  -  
  - l
  - o
  - a
  - d
  - i
  - n
  - g
  -  
  - n
  - o
  -  
  - l
  - o
  - n
  - g
  - e
  - r
  -  
  - f
  - a
  - i
  - l
  - s
  -  
  - o
  - n
  -  
  - s
  - l
  - o
  - w
  -  
  - a
  - n
  - s
  - w
  - e
  - r
  - s
  - :
  -  
  - 1
  - 2
  - 0
  -  
  - s
  -  
  - t
  - i
  - m
  - e
  - o
  - u
  - t
  -  
  - a
  - n
  - d
  -  
  - u
  - p
  -  
  - t
  - o
  -  
  - 3
  -  
  - r
  - e
  - t
  - r
  - i
  - e
  - s
  - .
- **0.2.62** (2026-09-30)
  - I
  - n
  -  
  - U
  - k
  - r
  - a
  - i
  - n
  - i
  - a
  - n
  - ,
  -  
  - e
  - x
  - p
  - l
  - a
  - n
  - a
  - t
  - i
  - o
  - n
  - s
  -  
  - n
  - o
  - w
  -  
  - s
  - h
  - o
  - w
  -  
  - a
  -  
  - U
  - k
  - r
  - a
  - i
  - n
  - i
  - a
  - n
  -  
  - s
  - u
  - m
  - m
  - a
  - r
  - y
  -  
  - i
  - n
  - s
  - t
  - e
  - a
  - d
  -  
  - o
  - f
  -  
  - t
  - h
  - e
  -  
  - E
  - n
  - g
  - l
  - i
  - s
  - h
  -  
  - q
  - u
  - o
  - t
  - e
  - ;
  -  
  - t
  - e
  - m
  - p
  - l
  - a
  - t
  - e
  - d
  -  
  - n
  - o
  - t
  - e
  - s
  -  
  - (
  - a
  - i
  - r
  -  
  - t
  - r
  - a
  - f
  - f
  - i
  - c
  - ,
  -  
  - m
  - e
  - d
  - i
  - a
  - ,
  -  
  - m
  - a
  - r
  - k
  - e
  - t
  - s
  - )
  -  
  - a
  - r
  - e
  -  
  - t
  - r
  - a
  - n
  - s
  - l
  - a
  - t
  - e
  - d
  - .
- **0.2.61** (2026-09-30)
  - S
  - c
  - a
  - l
  - e
  -  
  - t
  - u
  - n
  - i
  - n
  - g
  - :
  -  
  - c
  - a
  - p
  - p
  - e
  - d
  -  
  - t
  - h
  - e
  -  
  - s
  - u
  - r
  - g
  - e
  -  
  - b
  - o
  - n
  - u
  - s
  -  
  - a
  - n
  - d
  -  
  - n
  - a
  - r
  - r
  - o
  - w
  - e
  - d
  -  
  - g
  - o
  - v
  - e
  - r
  - n
  - m
  - e
  - n
  - t
  -  
  - s
  - y
  - n
  - c
  - h
  - r
  - o
  - n
  - y
  -  
  - t
  - o
  -  
  - r
  - e
  - a
  - l
  -  
  - t
  - i
  - g
  - h
  - t
  - e
  - n
  - i
  - n
  - g
  - ;
  -  
  - t
  - h
  - e
  -  
  - F
  - r
  - a
  - n
  - c
  - e
  -  
  - 2
  - 0
  - 1
  - 5
  -  
  - f
  - a
  - l
  - s
  - e
  -  
  - a
  - l
  - a
  - r
  - m
  -  
  - i
  - s
  -  
  - g
  - o
  - n
  - e
  - .
- **0.2.60** (2026-09-30)
  - Q
  - u
  - o
  - t
  - e
  - s
  -  
  - s
  - h
  - o
  - r
  - t
  - e
  - r
  -  
  - t
  - h
  - a
  - n
  -  
  - 4
  -  
  - w
  - o
  - r
  - d
  - s
  -  
  - (
  - n
  - a
  - v
  - i
  - g
  - a
  - t
  - i
  - o
  - n
  -  
  - f
  - r
  - a
  - g
  - m
  - e
  - n
  - t
  - s
  - )
  -  
  - a
  - r
  - e
  -  
  - n
  - o
  -  
  - l
  - o
  - n
  - g
  - e
  - r
  -  
  - s
  - h
  - o
  - w
  - n
  -  
  - i
  - n
  -  
  - e
  - x
  - p
  - l
  - a
  - n
  - a
  - t
  - i
  - o
  - n
  - s
  - .
- **0.2.59** (2026-09-30)
  - T
  - h
  - e
  -  
  - m
  - a
  - p
  -  
  - e
  - x
  - p
  - l
  - a
  - i
  - n
  - s
  -  
  - e
  - v
  - e
  - r
  - y
  -  
  - c
  - o
  - u
  - n
  - t
  - r
  - y
  - '
  - s
  -  
  - s
  - c
  - o
  - r
  - e
  - :
  -  
  - a
  -  
  - s
  - h
  - o
  - r
  - t
  -  
  - s
  - u
  - m
  - m
  - a
  - r
  - y
  - ,
  -  
  - t
  - h
  - e
  -  
  - s
  - i
  - x
  -  
  - b
  - l
  - o
  - c
  - k
  - s
  - ,
  -  
  - g
  - o
  - v
  - e
  - r
  - n
  - m
  - e
  - n
  - t
  -  
  - a
  - d
  - v
  - i
  - c
  - e
  -  
  - l
  - e
  - v
  - e
  - l
  - s
  -  
  - a
  - n
  - d
  -  
  - a
  - l
  - l
  -  
  - o
  - b
  - s
  - e
  - r
  - v
  - e
  - d
  -  
  - s
  - i
  - g
  - n
  - a
  - l
  - s
  -  
  - w
  - i
  - t
  - h
  -  
  - q
  - u
  - o
  - t
  - e
  - s
  - ,
  -  
  - p
  - l
  - u
  - s
  -  
  - t
  - h
  - e
  -  
  - f
  - u
  - l
  - l
  -  
  - m
  - e
  - t
  - h
  - o
  - d
  - .
  -  
  - F
  - a
  - l
  - s
  - e
  -  
  - a
  - i
  - r
  - -
  - t
  - r
  - a
  - f
  - f
  - i
  - c
  - -
  - d
  - r
  - o
  - p
  -  
  - s
  - i
  - g
  - n
  - a
  - l
  - s
  -  
  - f
  - o
  - r
  -  
  - s
  - m
  - a
  - l
  - l
  -  
  - c
  - o
  - u
  - n
  - t
  - r
  - i
  - e
  - s
  -  
  - r
  - e
  - m
  - o
  - v
  - e
  - d
  - .
- **0.2.57** (2026-09-30)
  - S
  - o
  - u
  - r
  - c
  - e
  - s
  -  
  - t
  - h
  - a
  - t
  -  
  - s
  - w
  - i
  - n
  - g
  -  
  - b
  - e
  - t
  - w
  - e
  - e
  - n
  -  
  - t
  - w
  - o
  -  
  - t
  - e
  - x
  - t
  -  
  - v
  - e
  - r
  - s
  - i
  - o
  - n
  - s
  -  
  - (
  - l
  - i
  - k
  - e
  -  
  - t
  - h
  - e
  -  
  - U
  - S
  -  
  - f
  - e
  - e
  - d
  - )
  -  
  - n
  - o
  -  
  - l
  - o
  - n
  - g
  - e
  - r
  -  
  - c
  - r
  - e
  - a
  - t
  - e
  -  
  - c
  - h
  - a
  - n
  - g
  - e
  - s
  -  
  - o
  - r
  -  
  - l
  - i
  - f
  - t
  -  
  - t
  - h
  - e
  -  
  - s
  - c
  - o
  - r
  - e
  - ;
  -  
  - n
  - e
  - w
  -  
  - w
  - h
  - y
  -  
  - c
  - o
  - m
  - m
  - a
  - n
  - d
  -  
  - e
  - x
  - p
  - l
  - a
  - i
  - n
  - s
  -  
  - a
  -  
  - c
  - o
  - u
  - n
  - t
  - r
  - y
  - '
  - s
  -  
  - s
  - c
  - o
  - r
  - e
  - .
- **0.2.56** (2026-09-30)
  - GDELT is its own daily command and timer; run no longer waits for it
  - US: duplicate items with different text no longer cause false changes
- **0.2.55** (2026-09-30)
  - US: reissue notes are not counted as changes
- **0.2.54** (2026-09-30)
  - run: progress and time limits for aviation, news, GDELT, ECB
  - US: deterministic item choice per country (fewer false changes)
  - changes command: recent changes with diff
- **0.2.53** (2026-09-30)
  - 2-minute limit per source: a hanging site no longer stalls the cycle
  - Australia disabled by default (DISABLED_SOURCES)
  - "collecting …" log line before each source
- **0.2.52** (2026-09-30)
  - Australia: country pages instead of the slow export (level after "Overall advice level")
  - News: dropped Kyiv Independent (404)
- **0.2.51** (2026-09-30)
  - Readable error for a bad .env; a model id in CLASSIFIER_PROVIDER is read as OpenRouter
- **0.2.50** (2026-09-30)
  - Classifier via OpenRouter (Claude Haiku 4.5) as the main option; direct Anthropic API remains
- **0.2.49** (2026-09-30)
  - US: country matched by name (feed tags are FIPS, not ISO)
  - Australia: longer timeout; France: new page URL and menu stripping
  - News: dropped NATO/ISW/ECFR (unreachable), added Politico Europe and Kyiv Independent
  - GDELT: retry after 429; probe easa shows parsed bulletins
- **0.2.48** (2026-09-30)
  - GDELT: stop after 3 consecutive failures when the service is unreachable
- **0.2.47** (2026-09-30)
  - Auto-deploy from main over SSH (once Actions are unlocked)
  - Source implementation status in docs/sources.md
- **0.2.44** (2026-09-30)
  - Public dashboard: map of Europe, country card with chart, table, methodology (/dashboard/)
  - scores.json export
- **0.2.40** (2026-09-30)
  - Bot: up to 5 countries per user, switching between them, daily digest
- **0.2.38** (2026-09-30)
  - Wayback archive for historical episodes (tension-index history)
  - Scale backtest with PASS/FAIL reports (tension-index backtest)
- **0.2.33** (2026-09-30)
  - News: 13 feeds, headline categories (rules + Claude), two-feed confirmation
  - GDELT: media surges and RU/BY MFA advice
  - ECB markets: bond spreads and FX
  - probe news / gdelt / ecb
- **0.2.27** (2026-09-30)
  - Aviation: EASA conflict zone bulletins, air traffic drops (OpenSky) with data-outage guard
- **0.2.24** (2026-09-30)
  - Signals from advisories, daily score, explanations
  - run command (full cycle) and score-change alerts
  - Bot shows the score and reasons
- **0.2.21** (2026-09-30)
  - Change classifier: rules + Claude (strict JSON schema, caching, call cap)
  - classify command
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
