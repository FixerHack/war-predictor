# Tension Index: Europe — Project plan

> Generated from `roadmap/roadmap.yaml` by `uv run tension-index roadmap`. Do not edit by hand. [Українська версія](PLAN.md)

Version **0.2.97**, updated 2026-10-03.

**Overall progress: 77%** · left ≈ 11.2 days · ✅ 65 · 🟡 14 · ⬜ 8 · ⛔ 4

## Milestones

- **M1** — MVP: 14 days of unattended collection, backtest scores Ukraine 7+ before 2022-02-24, every alert explained

## S0. Foundation & infrastructure — 93%

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
- ✅ **S0.10** OpenRouter: top-up, API key (OPENROUTER_API_KEY in .env), spend limit _(manual)_
  - Instead of OpenRouter the classifier runs through the local Claude Code CLI on a subscription (CLASSIFIER_PROVIDER=claude_code).
- ✅ **S0.11** Create bot via @BotFather, test channel, fill in .env _(manual)_
- ✅ **S0.12** First server deploy: install_server.sh, verify healthcheck _(manual)_
  - Deployed 2026-10-01 following docs/deploy-agent.md: claude-gateway in ~/claude-gateway and the bot with timers in ~/war-predictor, separate services started on boot; the bot uses its own gateway token.
- ✅ **S0.13** Enable GitHub Pages: Source → Deploy from a branch → gh-pages / root _(manual)_
  - Live: fixerhack.github.io/war-predictor
- ⬜ **S0.15** Unlock GitHub Actions: Settings → Billing and plans (invoice / card) _(manual)_
  - CI does not start: "account is locked due to a billing issue".
- ✅ **S0.16** Publish the progress page without Actions (make pages → gh-pages branch)
- ✅ **S0.17** Gateway installer waits up to 30 s for the service to start instead of a fixed 2 s
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

## S2. Official advisory collection — 71%

_Regular collection of advisories, storing every text version._

Branch: `dev-collector`

- ✅ **S2.1** Source framework, version storage, change detection (diff)
- ✅ **S2.2** UK (GOV.UK Content API)
  - Verified on live data (PL, EE, MD).
- ✅ **S2.3** Germany (Auswärtiges Amt OpenData API)
  - Verified on live data 30 Sep–1 Oct 2026.
- ✅ **S2.4** US (TAsTWs RSS + country pages + embassy Security Alerts)
  - Verified on live data. The feed serves two layouts of the same advice — both reduce to one canonical text.
- ✅ **S2.5** Canada (open data JSON)
  - Verified on live data 30 Sep–1 Oct 2026.
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
- 🟡 **S2.12** US: RSS feed gone (404) — fallback to the cadataapi.state.gov API (RSS/Atom/JSON)
  - API format only assumed; needs a probe us check.

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

## S6. Change classification (Claude API) — 76%

_Claude determines the reason and type of each change and turns it into a signal._

Branch: `dev-classifier`

- ✅ **S6.1** Prompt and JSON schema: reason, change type, staff, borders, quote
- ✅ **S6.2** Call only on changed fragments, prompt caching, spend cap
  - Changed fragments only, cached system prompt, CLASSIFIER_MAX_CALLS cap; rules work without a key.
- ⬜ **S6.3** Manual check on 50 examples _(manual)_
  - Needs an API key and real changes; review 50 classifications by hand.
- ✅ **S6.7** Classifier through the local Claude Code CLI (claude -p, no API key)
  - CLASSIFIER_PROVIDER=claude_code: claude -p with a JSON schema, no tools, no saved sessions; uses the subscription's limits. On a server, claude setup-token is needed.
- ✅ **S6.8** Separate claude-gateway tool: HTTP API (own, OpenAI- and Anthropic-compatible) and MCP on top of Claude Code
  - gateway/: token required, no tools or sessions, parallel call limit, systemd service; tension-index can classify through it (CLASSIFIER_PROVIDER=gateway).
- ✅ **S6.9** False alarms from live data: drills and tests are not mobilisation or an emergency, some closed crossings are not a closed border, no random quotes
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

## S8. Backtesting — 100%

_The scale must fire on known episodes in time and without mass false alarms._

Branch: `dev-backtest`

- ✅ **S8.1** Replay the scale on historical episodes
  - Wayback archive, Claude Haiku 4.5 classification via Claude Code: Ukraine 2022 — 7 from 20 Dec 2021 (66 days ahead); Armenia–Azerbaijan 2020 — reaction 3+ on day 2 (surprise attack); Israel 2024 — 7 from the window start (US staff departure); France 2016 (control) — max 3.0. All PASS.
- ✅ **S8.2** False alarm and miss report
- ✅ **S8.3** Weight tuning
  - Capped surge bonus, narrowed synchrony, separate measure reason, two-source airspace floors, lower weight for regional warnings. Revisit after 30+ days of live history.

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
- ✅ **S11.7** Map: neighbours at war (Ukraine, Russia, Belarus) for context; phone layout for the map and the plan page
  - Neighbours are not scored, only hatched for context; data in the context section of conflicts.yaml (needs human review).
- ✅ **S11.5** Detailed explanation on the map (uk/en): summary, blocks, what governments say, what was observed, full method

## S12. Operations — 35%

_The system runs unattended and reports failures._

Branch: `dev-ops`

- ✅ **S12.1** Daily SQLite backup with rotation
- ⬜ **S12.2** Dead-man switch on healthchecks.io (free) _(manual)_
- 🟡 **S12.3** Auto-deploy from main (GitHub Actions → SSH)
  - .github/workflows/deploy.yml is ready (SSH → scripts/deploy.sh); runs once Actions are unlocked and DEPLOY_* secrets are set.
- ⬜ **S12.5** Server: install Claude Code, claude setup-token, run claude-gateway (systemd) behind an HTTPS proxy _(manual)_
  - The gateway is deployed separately from the bot: ~/claude-gateway, gateway/scripts/install.sh; the bot connects with a token. Step by step: docs/deploy-agent.md.

## S13. MVP criteria — 62%

_The MVP is done when all three conditions hold._

Branch: `—`

- ⬜ **S13.1** 14 consecutive days of collection without manual intervention
- ✅ **S13.2** On the Ukraine episode the score reaches 7+ before 2022-02-24
  - Wayback archive backtest: 7 from 20 Dec 2021, 66 days before 24 Feb 2022.
- ✅ **S13.3** Every alert contains the source, a description of the change and a quote
  - Advisory alerts: source, description (classifier) and quote; score alerts: who, what and quotes.

## Decisions

- 2026-10-01: claude-gateway is a separate service with its own directory, .env, unit and updates; programs (including war-predictor) connect to it, each with its own token.
- 2026-10-01: Neighbours at war are shown on the map as context only (hatched, no score); the list is the context section of config/conflicts.yaml.
- 2026-09-30: Surprise attacks (Armenia–Azerbaijan 2020) are tested for a reaction within 3 days: government advice did not change before the fighting began.
- 2026-09-30: Advisory measures and floors count only for a security reason for the measure (relevance ≥ 0.7 for measures, ≥ 0.5 for floors).
- 2026-09-30: Regional warnings: UK "avoid all travel to parts" 0.45, "all but essential to parts" 0.3, German partial warning 0.35 — they mostly cover long-occupied or border areas.
- 2026-09-30: Airspace floors (8 / 6) only with two independent sources, like the ordered-departure floor.
- 2026-09-30: Ordered departure of family members only = authorized staff departure (floor 7), not ordered staff departure (floor 9 with two governments).
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

- The gateway uses the signed-in person's Claude subscription: it must not be opened to other people; other people's programs need an API key.
- Without OpenRouter credits classification falls back to rules only: reasons and embassy posture are cruder, the score less precise.
- A genuine revert of an advisory within 7 days is not reported as a change (the state still updates).
- Some government sites block automated requests (Australia); a source can be lost without notice
- GitHub Actions locked by an account billing issue: no CI until unlocked, checks run locally only (make check)
- Collection blocking: government sites may block requests from the server
- Terms of use: no open Reuters/AP RSS; ACLED licence for a public service
- Public responsibility: the score will be read as a forecast; disclaimer and methodology needed
- Untested weights: an expert hypothesis until stage S8
- Automatic war trackers list countries hit only by spillover; manual review needed

## Changelog

- **0.2.97** (2026-10-03)
  - Fixed false alarms: news about mobilisation drills and siren tests no longer trigger the floor of 9, and long-standing closure of some crossings (Poland - Belarus) no longer counts as a closed border; normal-level advisories read without Claude show no random quotes.
- **0.2.96** (2026-10-01)
  - gateway/scripts/install.sh no longer reports a false failure on re-install: the /health check waits up to 30 s for the gateway to start.
- **0.2.95** (2026-10-01)
  - First server deploy: claude-gateway and war-predictor run as separate systemd services started on boot; the first run classified changes through the gateway and published 38/38 scores.
- **0.2.94** (2026-10-01)
  - The gateway and war-predictor are deployed separately: the gateway has its own installer (gateway/scripts/install.sh), directory, .env and service; install_server.sh installs only the bot and timers, which connect to the gateway with a token.
  - The deployment agent instructions now describe two separate installations.
- **0.2.93** (2026-10-01)
  - docs/deploy-agent.md — step-by-step instructions for an agent (Claude Code) deploying the server over SSH.
- **0.2.92** (2026-10-01)
  - install_server.sh also installs Claude Code and claude-gateway, generates the gateway token and sets the bot to classify through it.
- **0.2.91** (2026-10-01)
  - claude-gateway is a standalone project with its own uv.lock (not part of the bot's dependencies).
- **0.2.90** (2026-10-01)
  - New separate tool claude-gateway: any program can call Claude Code on the server over HTTP (own format, OpenAI- or Anthropic-compatible) or MCP.
  - The tension-index classifier can run through the gateway (CLASSIFIER_PROVIDER=gateway).
- **0.2.88** (2026-10-01)
  - The map shows Ukraine (war), Russia (aggressor) and Belarus (territory used for the attack) for context, without a score.
  - Phone layout: no horizontal scroll on the map, the country panel scrolls into view, the table is clickable; the plan page can hide finished tasks and folds the changelog after 15 entries.
  - Fixed: changelog entries written as one string broke PLAN.md and the plan page.
- **0.2.87** (2026-09-30)
  - Bot dashboard: the level meaning in one sentence, flags and threshold events, three reasons, a "Details on the map" button; levels have neutral names, as on the map (low…critical).
- **0.2.86** (2026-09-30)
  - State Department: two layouts of one advisory (line breaks, the "If you decide to travel" block, update notes) reduce to one text — the flapping stops without a wave of changes on upgrade.
- **0.2.80** (2026-09-30)
  - Backtest stage finished: all four historical episodes pass with model classification.
- **0.2.77** (2026-09-30)
  - The Claude Code log shows each call's own number, not the counter at completion.
- **0.2.76** (2026-09-30)
  - The classifier makes up to 4 model calls in parallel (CLASSIFIER_CONCURRENCY), and via Claude Code without extended thinking; classification should be several times faster.
- **0.2.75** (2026-09-30)
  - The Claude Code classifier logs every call; if the CLI does not answer in 90 s, calls stop for the rest of the run.
- **0.2.74** (2026-09-30)
  - New classifier provider — the local Claude Code CLI on a subscription; the Armenia–Azerbaijan 2020 episode tests the reaction (score 3+ within 3 days of the attack), not an early warning.
- **0.2.73** (2026-09-30)
  - The classifier stops after the first key or credit refusal (401/402/403) instead of sending hundreds of requests; texts classified by rules while the model was unavailable are re-classified by the model later. Rules take a measure's reason from the sentence that states it.
- **0.2.72** (2026-09-30)
  - Measures with an unspecified security reason ("unpredictable situation") count again; only clearly non-military reasons are excluded (COVID, ash, weather, crime, terrorism).
- **0.2.71** (2026-09-30)
  - A separate reason for measures (embassy posture, airspace, borders): COVID-19 measures in a conflict advisory no longer raise the score or trigger floors; one government's "airspace closed" gives the aviation block 0.7, not 1.0.
- **0.2.70** (2026-09-30)
  - Loading the archive again skips what is already loaded (--refresh reloads), and duplicates in older databases are removed automatically.
- **0.2.69** (2026-09-30)
  - Advisory-derived signals (airspace, embassy posture, borders) switch off when a new classification of the same text no longer supports them.
- **0.2.68** (2026-09-30)
  - Alternating versions are no longer stored or re-classified (saves model calls); regional warnings (UK "to parts", German partial warning) weigh less; airspace closures count only for a security reason.
- **0.2.67** (2026-09-30)
  - State Department: fallback source after the RSS feed disappeared; airspace closures for volcanic ash or weather no longer count as security signals; the model takes the reason for the country's overall level, not for single regions.
- **0.2.66** (2026-09-30)
  - Rule-based classifications are redone once more after narrowing the airspace rules.
- **0.2.65** (2026-09-30)
  - Airspace closed/restricted floors now need two independent sources; rules and the model no longer treat routine NOTAMs, drone rules or long-standing regional bans as airspace restrictions.
- **0.2.64** (2026-09-30)
  - Fixed rule classification: full pages with bullets or phone numbers are no longer read as diffs; new embassy posture wordings (withdrawal, relocation, suspension); "Still valid" and bare-date noise removed. Rule-based classifications are redone.
- **0.2.63** (2026-09-30)
  - Wayback archive loading no longer fails on slow answers: 120 s timeout and up to 3 retries.
- **0.2.62** (2026-09-30)
  - In Ukrainian, explanations now show a Ukrainian summary instead of the English quote; templated notes (air traffic, media, markets) are translated.
- **0.2.61** (2026-09-30)
  - Scale tuning: capped the surge bonus and narrowed government synchrony to real tightening; the France 2015 false alarm is gone.
- **0.2.60** (2026-09-30)
  - Quotes shorter than 4 words (navigation fragments) are no longer shown in explanations.
- **0.2.59** (2026-09-30)
  - The map explains every country's score: a short summary, the six blocks, government advice levels and all observed signals with quotes, plus the full method. False air-traffic-drop signals for small countries removed.
- **0.2.57** (2026-09-30)
  - Sources that swing between two text versions (like the US feed) no longer create changes or lift the score; new why command explains a country's score.
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
