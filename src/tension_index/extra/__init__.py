"""Non-advisory collectors (aviation, news, markets).

Each collector is `async def collect(db, client, settings) -> RunResult`: it records its own
run in `collect_runs` (health + coverage) and writes signals. `BLOCKS` maps collector name ->
scoring block, used for coverage.
"""

from tension_index.extra import aviation

COLLECTORS = {
    "easa": aviation.collect_czib,
    "opensky": aviation.collect_traffic,
}
BLOCKS = {
    "easa": "aviation",
    "opensky": "aviation",
}

# What `tension-index probe <name>` fetches for these collectors.
PROBE_URLS = {
    "easa": aviation.CZIB_PAGE,
    "opensky": aviation.OPENSKY + "?lamin=49&lomin=14&lamax=55&lomax=24",
}
