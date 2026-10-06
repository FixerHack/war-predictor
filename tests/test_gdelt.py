import asyncio
import io
import os
import re
import signal
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from tension_index import runner, storage
from tension_index.collector import RunResult
from tension_index.extra import gdelt

YESTERDAY = datetime.now(UTC).date() - timedelta(days=1)


def _row(fips: str, root: str, url: str) -> str:
    fields = [""] * 58
    fields[gdelt.COL_ROOT], fields[gdelt.COL_GEO_COUNTRY], fields[gdelt.COL_URL] = root, fips, url
    return "\t".join(fields) + "\n"


def events_zip(poland_articles: int) -> bytes:
    rows = "".join(
        _row("PL", "19", f"https://pl.example/{i}") * 3  # several events per article
        for i in range(poland_articles)
    )
    rows += (
        _row("PL", "04", "https://pl.example/talks")  # consult: not military
        + _row("AU", "18", "https://at.example/1")  # FIPS AU is Austria
        + _row("AS", "18", "https://au.example/1")  # FIPS AS is Australia: not monitored
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.export.CSV", rows)
    return buf.getvalue()


def _day(request: httpx.Request) -> str:
    return re.search(r"/(\d{8})\.export", str(request.url))[1]


MFA = {"articles": [
    {"title": "МИД России рекомендовал воздержаться от поездок в Латвию", "domain": "ria.ru"},
    {"title": "МИД РФ советует не ездить в Латвию", "domain": "tass.ru"},
]}  # fmt: skip


async def _collect(db, settings, handler, force=False) -> RunResult:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        return await gdelt.collect_gdelt(db, c, settings, pause=0, file_pause=0, force=force)


async def _last_run(db):
    return (await storage.last_runs(db))[0]


def test_parse_events_counts_distinct_articles():
    totals = gdelt.parse_events(events_zip(7))
    assert totals["PL"] == 7 and totals["AT"] == 1 and totals["FR"] == 0
    assert len(totals) == len(gdelt.COUNTRIES)


def test_one_day_spike_or_tiny_numbers_are_not_a_surge():
    quiet = [(f"d{i:02d}", 10.0) for i in range(60)]
    assert gdelt.surge_ratio(quiet + [("a", 300.0), ("b", 12.0)]) is None  # 12 < MIN_RECENT
    assert gdelt.surge_ratio(quiet + [("a", 300.0), ("b", 25.0)]) == 2.5  # min of both days
    tiny = [(f"d{i:02d}", 2.0) for i in range(60)]
    assert gdelt.surge_ratio(tiny + [("a", 20.0), ("b", 20.0)]) is None  # base below MIN_BASE


def test_days_to_fetch_backfills_newest_first():
    days = gdelt.days_to_fetch({f"{YESTERDAY:%Y%m%d}"}, YESTERDAY + timedelta(days=1))
    assert len(days) == gdelt.BACKFILL_PER_RUN
    assert days[0] == f"{YESTERDAY - timedelta(days=1):%Y%m%d}"


async def test_collect_events_and_surge(settings):
    """60 quiet days already stored, then two loud ones: a surge signal, MFA advice stored."""
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        for i in range(3, gdelt.HISTORY_DAYS + 1):
            day = f"{YESTERDAY + timedelta(days=1) - timedelta(days=i):%Y%m%d}"
            await db.execute(
                "INSERT INTO series (source, country, key, period, value) "
                "VALUES ('gdelt', 'PL', ?, ?, 10)",
                (gdelt.SERIES_KEY, day),
            )
        await db.commit()
        requested = []

        def handler(request):
            if "api.gdeltproject.org" in str(request.url):
                return httpx.Response(200, json=MFA)
            requested.append(_day(request))
            return httpx.Response(200, content=events_zip(40))

        result = await _collect(db, settings, handler)
        assert result.ok and result.fetched == 2 and result.failed == 0, result.errors
        assert len(requested) == 2  # only the missing days
        async with db.execute("SELECT country, kind FROM signals ORDER BY country") as cur:
            assert [tuple(r) for r in await cur.fetchall()] == [
                ("LV", "aggressor:mfa_advisory"),
                ("PL", "media:gdelt_surge"),
            ]
        assert (await _last_run(db))["ok"] == 1
        # A forced re-run the same day recomputes the surges instead of stacking them.
        assert (await _collect(db, settings, handler, force=True)).ok
        async with db.execute("SELECT COUNT(*) FROM signals WHERE active = 1") as cur:
            assert (await cur.fetchone())[0] == 2


async def test_empty_mfa_answer_is_recorded_not_silent(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        calls = {"doc": 0}

        def handler(request):
            if "api.gdeltproject.org" in str(request.url):
                calls["doc"] += 1
                if calls["doc"] == 1:
                    return httpx.Response(429, text="Please limit requests")
                return httpx.Response(200, json={})
            if _day(request) == f"{YESTERDAY:%Y%m%d}":
                return httpx.Response(404)  # not published yet
            return httpx.Response(200, content=events_zip(1))

        result = await _collect(db, settings, handler)
        assert calls["doc"] == gdelt.MAX_FAILURES
        assert result.failed == 1 and result.ok  # the events part worked
        assert any("not published yet" in e for e in result.errors)
        mfa = next(e for e in result.errors if e.startswith("mfa:"))
        assert "429" in mfa and "empty {}" in mfa
        assert "empty {}" in (await _last_run(db))["error"]


async def test_stops_after_consecutive_failures(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        requested = []

        def handler(request):
            if "api.gdeltproject.org" in str(request.url):
                return httpx.Response(200, json={})
            requested.append(request.url)
            return httpx.Response(200, content=b"not a zip")

        result = await _collect(db, settings, handler)
        assert len(requested) == gdelt.MAX_FAILURES
        assert not result.ok and result.fetched == 0
        assert any("stopped after" in e for e in result.errors)
        row = await _last_run(db)
        assert row["ok"] == 0 and row["finished_at"] and "stopped after" in row["error"]


async def _hanging_collector(db, client, settings):
    await storage.start_run(db, "gdelt")
    await asyncio.sleep(3600)
    return RunResult(source="gdelt")


async def test_run_slow_closes_the_run_on_deadline(settings, monkeypatch):
    monkeypatch.setitem(runner.EXTRA_COLLECTORS, "gdelt", _hanging_collector)
    monkeypatch.setitem(runner.EXTRA_DEADLINES, "gdelt", 0.05)
    [result] = await runner.run_slow(settings)
    assert not result.ok and "deadline" in result.errors[0]
    async with storage.connect(settings.database_path) as db:
        row = await _last_run(db)
        assert row["ok"] == 0 and row["finished_at"] and "deadline" in row["error"]


async def test_run_slow_closes_the_run_on_sigterm(settings, monkeypatch):
    async def killed(db, client, settings):
        await storage.start_run(db, "gdelt")
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(3600)

    monkeypatch.setitem(runner.EXTRA_COLLECTORS, "gdelt", killed)
    [result] = await runner.run_slow(settings)
    assert not result.ok
    async with storage.connect(settings.database_path) as db:
        row = await _last_run(db)
        assert row["ok"] == 0 and row["finished_at"] and "cancelled" in row["error"]


def test_gdelt_deadline_is_below_the_unit_timeout():
    unit = Path(__file__).parents[1] / "deploy/systemd/tension-gdelt.service"
    minutes = int(re.search(r"TimeoutStartSec=(\d+)min", unit.read_text())[1])
    assert runner.EXTRA_DEADLINES["gdelt"] + 60 <= minutes * 60
