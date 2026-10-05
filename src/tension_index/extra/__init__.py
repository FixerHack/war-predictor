"""Non-advisory collectors (aviation, news, media, markets).

Each collector is `async def collect(db, client, settings) -> RunResult`: it records its own
run in `collect_runs` (health + coverage) and writes signals. `BLOCKS` maps collector name ->
scoring block, used for coverage.
"""

from tension_index.extra import aviation, gdelt, markets, news

COLLECTORS = {
    "easa": aviation.collect_czib,
    "opensky": aviation.collect_traffic,
    "news": news.collect_news,
    "gdelt": gdelt.collect_gdelt,
    "ecb": markets.collect_markets,
}
BLOCKS = {
    "easa": "aviation",
    "opensky": "aviation",
    "news": "media",
    "gdelt": "media",
    "ecb": "markets",
}

# Collectors that run once a day: allowed staleness for health checks.
MAX_AGE_HOURS = {"gdelt": 30, "ecb": 30}

# What `tension-index probe <name>` fetches for these collectors.
PROBE_URLS = {
    "easa": aviation.CZIB_PAGE,
    "opensky": aviation.OPENSKY + "?lamin=49&lomin=14&lamax=55&lomax=24",
    "gdelt": gdelt.EVENTS_INDEX,
    "ecb": markets.FX + "?format=csvdata&lastNObservations=2",
}
