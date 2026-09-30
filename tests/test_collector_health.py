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
        country, diff = result.changes[0]
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
