import copy

import httpx

from tension_index import storage
from tension_index.collector import collect_source
from tension_index.health import Status, run_checks
from tension_index.sources.gov_uk import GovUkSource
from tests.test_gov_uk import PAYLOAD


def make_source(payload: dict, fail: set[str] = frozenset()) -> GovUkSource:
    def handler(request: httpx.Request) -> httpx.Response:
        slug = request.url.path.rsplit("/", 1)[-1]
        if slug in fail:
            return httpx.Response(503)
        return httpx.Response(200, json=payload)

    return GovUkSource(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_baseline_then_change(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)

        first = await collect_source(db, make_source(PAYLOAD), ["PL", "EE"])
        assert (first.fetched, first.changed, first.ok) == (2, 0, True)

        same = await collect_source(db, make_source(PAYLOAD), ["PL", "EE"])
        assert same.changed == 0

        changed = copy.deepcopy(PAYLOAD)
        changed["details"]["alert_status"] = ["avoid_all_travel_to_whole_country"]
        changed["details"]["parts"][0]["body"] = "<p>FCDO advises against all travel.</p>"
        result = await collect_source(db, make_source(changed), ["PL"])
        assert result.changed == 1
        country, diff, _ = result.changes[0]
        assert country == "PL"
        assert diff.startswith("LEVEL: none -> avoid_all_travel_to_whole_country")
        assert "+FCDO advises against all travel." in diff
        assert len(await storage.recent_changes(db)) == 1


async def test_source_failing_everywhere_is_not_ok(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        result = await collect_source(
            db, make_source(PAYLOAD, fail={"poland", "estonia"}), ["PL", "EE"]
        )
        assert not result.ok
        assert result.failed == 2
        runs = await storage.last_runs(db)
        assert runs[0]["ok"] == 0


async def test_health_warns_before_first_run_then_ok(settings):
    report = await run_checks(settings)
    assert report.status == Status.WARN  # telegram not configured + no runs yet
    names = {c.name: c.status for c in report.checks}
    assert names["database"] == Status.OK
    assert names["collector.gov_uk"] == Status.WARN

    async with storage.connect(settings.database_path) as db:
        await collect_source(db, make_source(PAYLOAD), ["PL"])
    report = await run_checks(settings)
    assert {c.name: c.status for c in report.checks}["collector.gov_uk"] == Status.OK


async def test_health_fails_on_stale_collector(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        await db.execute(
            "INSERT INTO collect_runs (source, started_at, finished_at, ok) VALUES (?, ?, ?, 1)",
            ("gov_uk", "2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00"),
        )
        await db.commit()
    report = await run_checks(settings)
    assert report.status == Status.FAIL


async def test_prepare_failure_fails_the_run(settings):
    from tension_index.sources.ca import CaSource

    transport = httpx.MockTransport(lambda r: httpx.Response(503))
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        result = await collect_source(db, CaSource(httpx.AsyncClient(transport=transport)), ["PL"])
    assert not result.ok and result.failed == 1 and result.errors[0].startswith("prepare:")


async def test_daily_collectors_may_be_a_day_old(settings):
    from datetime import UTC, datetime, timedelta

    old = (datetime.now(UTC) - timedelta(hours=20)).isoformat(timespec="seconds")
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        for source in ("gdelt", "gov_uk"):
            await db.execute(
                "INSERT INTO collect_runs (source, started_at, finished_at, ok) VALUES (?, ?, ?, 1)",
                (source, old, old),
            )
        await db.commit()
    checks = {c.name: c.status for c in (await run_checks(settings)).checks}
    assert checks["collector.gdelt"] == Status.OK
    assert checks["collector.gov_uk"] == Status.FAIL  # 3-hourly collector, 20 h is stale


async def test_source_deadline_stops_a_hanging_site(settings):
    import asyncio

    from tension_index.countries import get_country
    from tension_index.sources.base import Advisory, Source

    class Hanging(Source):
        name = "hang"

        def supports(self, country):
            return True

        async def fetch(self, country):
            if country.code == "PL":
                return Advisory(country="PL", url="u", text="ok")
            await asyncio.sleep(30)

    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        result = await collect_source(db, Hanging(None), ["PL", "EE", "LV"], deadline_seconds=0.2)
    assert result.fetched == 1 and result.failed == 2
    assert get_country("EE")  # sanity


def test_disabled_sources_setting(monkeypatch):
    from tension_index.config import Settings

    assert Settings(_env_file=None).disabled_sources == ["au"]
    monkeypatch.setenv("DISABLED_SOURCES", "au, fr")
    assert Settings(_env_file=None).disabled_sources == ["au", "fr"]
    monkeypatch.setenv("DISABLED_SOURCES", "")
    assert Settings(_env_file=None).disabled_sources == []


async def test_flapping_source_records_one_change(settings):
    """A -> B -> A -> B within days: the first swing is recorded, the flapping is not."""
    other = copy.deepcopy(PAYLOAD)
    other["details"]["parts"][0]["body"] = "<p>Another version of the text.</p>"
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        await collect_source(db, make_source(PAYLOAD), ["PL"])
        swings = [
            (await collect_source(db, make_source(p), ["PL"])).changed
            for p in (other, PAYLOAD, other, PAYLOAD)
        ]
        assert swings == [1, 0, 0, 0]
        # Known versions are not stored again (so they are not re-classified every run).
        async with db.execute("SELECT COUNT(*) FROM snapshots") as cur:
            assert (await cur.fetchone())[0] == 2
