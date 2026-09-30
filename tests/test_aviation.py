from datetime import UTC, datetime, timedelta

import httpx

from tension_index import storage
from tension_index.extra import aviation

CZIB_HTML = """<html><nav>menu</nav><main>
<h2>Active CZIBs</h2>
<div><a href="/czib-2022-01r13">CZIB-2022-01R13</a> Airspace of Ukraine. Issued 24/02/2022</div>
<div><a>CZIB-2022-02R4</a> Airspace of the Republic of Moldova. Issued 03/03/2022</div>
<h2>Withdrawn</h2>
<div>CZIB-2019-05 Airspace of Poland (withdrawn 2020)</div>
</main></html>"""


def test_parse_czibs_active_only():
    found = aviation.parse_czibs(aviation.html_to_text(aviation.main_content(CZIB_HTML)))
    assert [(c, code) for c, code, _ in found] == [("2022-02", "MD")]


def mock(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_collect_czib_and_deactivation(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        async with mock(lambda r: httpx.Response(200, text=CZIB_HTML)) as c:
            result = await aviation.collect_czib(db, c, settings)
        assert result.ok and result.changed == 1
        async with mock(
            lambda r: httpx.Response(200, text="<main>CZIB-2017-03 Airspace of Syria</main>")
        ) as c:
            await aviation.collect_czib(db, c, settings)
        async with db.execute("SELECT active FROM signals WHERE kind = 'aviation:czib'") as cur:
            assert [r[0] for r in await cur.fetchall()] == [0]
        async with mock(lambda r: httpx.Response(200, text="<main>nothing here</main>")) as c:
            assert not (await aviation.collect_czib(db, c, settings)).ok


def state(lat, lon, on_ground=False):
    return ["abc", "CALL", "X", 0, 0, lon, lat, 10000, on_ground] + [None] * 8


def test_count_by_country():
    counts = aviation.count_by_country(
        [state(52, 21), state(52, 21, on_ground=True), state(47, 28.8), state(None, None)]
    )
    assert counts["PL"] == 1 and counts["MD"] == 1 and counts[aviation.TOTAL] == 2


async def _seed_history(db, when, pl=40, total=2000, weeks=4):
    for w in range(1, weeks + 1):
        t = when - timedelta(weeks=w)
        for code, value in (("PL", pl), (aviation.TOTAL, total)):
            await db.execute(
                "INSERT INTO traffic (country, observed_at, hour_of_week, aircraft) VALUES (?, ?, ?, ?)",
                (code, t.isoformat(), aviation.hour_of_week(t), value),
            )
    await db.commit()


def opensky_response(when, pl_count, other=1990):
    states = [state(52, 21)] * pl_count + [state(40, -3)] * other  # PL + Spain
    return httpx.Response(200, json={"time": int(when.timestamp()), "states": states})


async def test_traffic_drop_signal(settings):
    when = datetime(2026, 9, 30, 12, tzinfo=UTC)
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        await _seed_history(db, when)
        async with mock(lambda r: opensky_response(when, pl_count=4)) as c:
            result = await aviation.collect_traffic(db, c, settings)
        assert result.ok and result.changed == 1
        async with db.execute(
            "SELECT country, strength, note FROM signals WHERE kind = 'aviation:traffic_drop'"
        ) as cur:
            row = await cur.fetchone()
    assert row["country"] == "PL" and 0.9 < row["strength"] <= 1.0 and "usual 40" in row["note"]


async def test_europe_wide_collapse_is_treated_as_outage(settings):
    when = datetime(2026, 9, 30, 12, tzinfo=UTC)
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        await _seed_history(db, when)
        async with mock(lambda r: opensky_response(when, pl_count=5, other=100)) as c:
            result = await aviation.collect_traffic(db, c, settings)
        assert not result.ok and "outage" in result.errors[0]
        async with db.execute("SELECT COUNT(*) FROM signals") as cur:
            assert (await cur.fetchone())[0] == 0


def test_drop_strength_range():
    assert aviation.drop_strength(0.5) == 0.3
    assert aviation.drop_strength(0.1) == 1.0


async def test_traffic_drop_clears_when_traffic_recovers(settings):
    when = datetime(2026, 9, 30, 12, tzinfo=UTC)
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        await _seed_history(db, when)
        async with mock(lambda r: opensky_response(when, pl_count=4)) as c:
            await aviation.collect_traffic(db, c, settings)
        later = when + timedelta(minutes=10)
        async with mock(lambda r: opensky_response(later, pl_count=38)) as c:
            await aviation.collect_traffic(db, c, settings)
        async with db.execute("SELECT COUNT(*) FROM signals WHERE active = 1") as cur:
            assert (await cur.fetchone())[0] == 0


async def test_no_traffic_signal_without_a_real_norm(settings):
    """Runs from one afternoon are not a norm; tiny boxes are noise either way."""
    when = datetime(2026, 9, 30, 12, tzinfo=UTC)
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        for minutes in (30, 60, 90):  # three runs earlier the same day
            t = when - timedelta(minutes=minutes)
            await db.execute(
                "INSERT INTO traffic (country, observed_at, hour_of_week, aircraft) VALUES (?, ?, ?, ?)",
                ("PL", t.isoformat(), aviation.hour_of_week(t), 40),
            )
        await db.commit()
        assert await aviation.baseline(db, "PL", when) is None
    assert not aviation.is_drop(3, 10)  # "3 vs usual 10": too few aircraft to judge
    assert aviation.is_drop(4, 40) and not aviation.is_drop(25, 40)
