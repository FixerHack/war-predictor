from datetime import UTC, datetime, timedelta

import httpx

from tension_index import storage
from tension_index.extra import gdelt, markets, news
from tension_index.extra.lexicon import countries_in, countries_in_ru

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Poland closes border crossings with Belarus after drone incursion</title>
<link>https://a.example/1</link><pubDate>Tue, 29 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>Football: Spain beat Italy</title><link>https://a.example/2</link></item>
</channel></rss>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Warsaw orders closure of the border with Belarus</title>
<link href="https://b.example/1"/><updated>2026-09-29T12:00:00Z</updated></entry></feed>"""
RDF = b"""<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<item><title>Estonia reports GPS jamming near Narva</title><link>https://c.example/1</link>
<dc:date>2026-09-29T08:00:00Z</dc:date></item></rdf:RDF>"""


def test_parse_feed_formats():
    assert news.parse_feed(RSS)[0][1] == "https://a.example/1"
    assert news.parse_feed(ATOM) == [
        (
            "Warsaw orders closure of the border with Belarus",
            "https://b.example/1",
            "2026-09-29T12:00:00Z",
        )
    ]
    assert news.parse_feed(RDF)[0][2] == "2026-09-29T08:00:00Z"


def test_lexicon():
    assert countries_in("Warsaw orders closure of the border") == ["PL"]
    assert set(countries_in("Serbian and Kosovar officials meet in Brussels")) == {"BE", "RS", "XK"}
    assert countries_in("Polish sausage festival") == ["PL"]  # tagging only; category decides
    assert countries_in_ru("МИД России рекомендовал воздержаться от поездок в Польшу") == ["PL"]


def test_categorize():
    assert news.categorize("Poland closes border crossings with Belarus") == "domestic_emergency"
    assert (
        news.categorize("Warsaw orders closure of the border with Belarus") == "domestic_emergency"
    )
    assert news.categorize("Estonia reports GPS jamming near Narva") == "hybrid_attack"
    assert news.categorize("Moldova declares partial mobilisation") == "mobilisation"
    assert news.categorize("Moldova parliament debates budget") == "none"


async def test_news_needs_two_feeds(settings):
    feeds = {
        "feeds": [
            {"name": "one", "tier": 1, "url": "https://a.example/rss"},
            {"name": "two", "tier": 1, "url": "https://b.example/atom"},
        ],
        "confirmation": {"min_feeds": 2, "window_hours": 72000},
        "categories": news.load_config()["categories"],
    }
    news.load_config.cache_clear()
    original = news.load_config
    news.load_config = lambda: feeds  # type: ignore[assignment]
    routes = {"https://a.example/rss": RSS, "https://b.example/atom": ATOM}
    try:
        async with storage.connect(settings.database_path) as db:
            await storage.migrate(db)
            transport = httpx.MockTransport(
                lambda r: httpx.Response(200, content=routes[str(r.url)])
            )
            async with httpx.AsyncClient(transport=transport) as c:
                result = await news.collect_news(db, c, settings)
            assert result.ok and result.changed == 3  # the football item names Spain and Italy
            async with db.execute(
                "SELECT country, kind, tier, confirmed, note FROM signals"
            ) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
    finally:
        news.load_config = original
    pl = [r for r in rows if r["country"] == "PL"]
    assert (
        pl
        == [
            {
                "country": "PL",
                "kind": "domestic:emergency",
                "tier": 1,
                "confirmed": 1,
                "note": pl[0]["note"],
            }
        ]
        and "(2 feeds)" in pl[0]["note"]
    )


def test_gdelt_surge():
    series = [(f"202607{d:02d}", 10.0) for d in range(1, 31)] + [
        ("20260731", 40.0),
        ("20260801", 50.0),
    ]
    ratio = gdelt.surge_ratio(series)
    assert ratio == 4.5 and gdelt.surge_strength(ratio) == 0.8
    assert gdelt.surge_ratio(series[:10]) is None


async def test_gdelt_mfa_confirmation(settings):
    articles = [
        {"title": "МИД России рекомендовал воздержаться от поездок в Латвию", "domain": "ria.ru"},
        {"title": "МИД РФ советует не ездить в Латвию", "domain": "tass.ru"},
        {"title": "МИД Белоруссии: поездки в Литву опасны", "domain": "belta.by"},
    ]
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        assert await gdelt.mfa_signals(db, articles, NOW) == 2
        async with db.execute("SELECT country, confirmed FROM signals ORDER BY country") as cur:
            assert [tuple(r) for r in await cur.fetchall()] == [("LT", 0), ("LV", 1)]


BONDS_CSV = "KEY,REF_AREA,TIME_PERIOD,OBS_VALUE\n" + "".join(
    f"x,{area},2026-{m:02d},{value}\n"
    for m in range(1, 10)
    for area, value in (("DE", 2.5), ("PL", 5.5 if m < 9 else 7.0), ("FR", 3.0))
)


def test_spread_jumps():
    assert markets.spread_jumps(markets.parse_csv(BONDS_CSV, "REF_AREA")) == {"PL": 1.5}


def test_fx_drops():
    rates = {"PLN": [(f"d{i:03d}", 4.3) for i in range(60)] + [("d999", 4.6)]}
    drops = markets.fx_drops(rates)
    assert set(drops) == {"PL"} and round(drops["PL"], 3) == 0.07


async def test_daily_collectors_skip_when_recent(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        for name in ("gdelt", "ecb"):
            run = await storage.start_run(db, name)
            await storage.finish_run(db, run, ok=True, fetched=1, changed=0, failed=0)
        boom = httpx.MockTransport(
            lambda r: (_ for _ in ()).throw(AssertionError("no request expected"))
        )
        async with httpx.AsyncClient(transport=boom) as c:
            assert (await gdelt.collect_gdelt(db, c, settings)).ok
            assert (await markets.collect_markets(db, c, settings)).ok


async def test_markets_collect(settings):
    fx = (
        "KEY,CURRENCY,TIME_PERIOD,OBS_VALUE\n"
        + "".join(f"x,PLN,2026-07-{i:02d},4.3\n" for i in range(1, 31))
        + "x,PLN,2026-08-01,4.8\n"
    )

    def handler(r):
        return httpx.Response(200, text=BONDS_CSV if "/IRS/" in str(r.url) else fx)

    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            result = await markets.collect_markets(db, c, settings)
        async with db.execute("SELECT kind FROM signals ORDER BY kind") as cur:
            kinds = [r[0] for r in await cur.fetchall()]
    assert result.ok and kinds == ["markets:fx_drop", "markets:spread_jump"]


def test_gdelt_window_constant():
    assert gdelt.MIN_INTERVAL_HOURS < 24 and timedelta(hours=gdelt.MIN_INTERVAL_HOURS)


async def test_gdelt_gives_up_when_unreachable(settings):
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("proxy says no")

    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            result = await gdelt.collect_gdelt(db, c, settings, pause=0)
    assert not result.ok and len(calls) <= 4  # 3 countries + the MFA query


async def test_run_cycle_skips_gdelt_unless_asked(monkeypatch, settings):
    from tension_index import runner

    called = []

    async def fake(db, client, s):
        called.append(1)
        return runner.RunResult(source="gdelt", fetched=1)

    async def no_collect(*a, **k):
        return []

    monkeypatch.setitem(runner.EXTRA_COLLECTORS, "gdelt", fake)
    for name in [n for n in runner.EXTRA_COLLECTORS if n != "gdelt"]:
        monkeypatch.delitem(runner.EXTRA_COLLECTORS, name)
    monkeypatch.setattr(runner, "collect_all", no_collect)
    await runner.run_cycle(settings)
    assert called == []
    await runner.run_cycle(settings, slow=True)
    assert called == [1]


def test_preparedness_is_not_the_measure():
    # LRT headlines from October 2026: drills and plans, not a declared mobilisation.
    for title in (
        "Lithuania launches largest annual mobilisation drills, tests wartime supply system",
        "Lithuania plans first activation of state reserve during mobilisation exercise",
        "PM urges Lithuanian banks to prepare for payments during national mobilisation",
        "Lithuania to test air raid sirens on Tuesday",
    ):
        assert news.categorize(title) == "none", title
        assert news.effective_category(title, "mobilisation") == "none", title
    assert news.categorize("Moldova declares partial mobilisation") == "mobilisation"
    assert news.effective_category("Estonia exercise near Narva", "military_threat") == (
        "military_threat"
    )


async def test_relabelled_headlines_lose_their_signal(settings):
    now = datetime.now(UTC)
    title = "Lithuania launches largest annual mobilisation drills"
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        for feed, url in (("lrt_en", "https://a.example/1"), ("err", "https://b.example/1")):
            await db.execute(
                "INSERT INTO news_items (url, feed, tier, title, published, countries, seen_at, "
                "category, severity, classified) VALUES (?, ?, 1, ?, ?, 'LT', ?, 'mobilisation', "
                "0.6, 1)",
                (url, feed, title, now.isoformat(), now.isoformat()),
            )
        # Written by an earlier version that took the drill for a mobilisation.
        from tension_index.scoring import Signal

        old = Signal(country="LT", block="domestic", kind="domestic:mobilisation", strength=0.6,
                     publisher="news", observed_at=now, tier=1, confirmed=True,
                     reason="military_threat", note=title)  # fmt: skip
        await storage.upsert_signal(db, old, f"news:mobilisation:{now.date().isoformat()}")
        await news.derive_news_signals(db, now)
        async with db.execute("SELECT COUNT(*) FROM signals WHERE active = 1") as cur:
            assert (await cur.fetchone())[0] == 0
