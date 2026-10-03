from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

from tension_index import refresh, runner, storage, war_status
from tension_index.bot import handlers, views
from tension_index.bot.callbacks import CountryCb, LangCb, MenuCb
from tension_index.countries import COUNTRIES

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("score", "hours"),
    [(None, 12), (0.0, 12), (0.9, 12), (1.0, 8), (3.7, 8), (4.0, 4), (6.9, 4), (7.0, 1), (10, 1)],
)
def test_interval_by_score(score, hours):
    assert refresh.interval_hours(score) == hours


async def test_due_countries_follow_their_score(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        assert await refresh.due_countries(db, NOW) == list(COUNTRIES)  # never checked

        await storage.mark_checked(db, list(COUNTRIES), NOW.isoformat())
        for code in COUNTRIES:
            await storage.insert_score(db, code, 0.0, "green", "{}")
        await storage.insert_score(db, "PL", 5.4, "orange", "{}")
        await storage.insert_score(db, "EE", 7.2, "red", "{}")
        await storage.insert_score(db, "MD", 3.0, "yellow", "{}")

        assert await refresh.due_countries(db, NOW + timedelta(minutes=30)) == []
        assert await refresh.due_countries(db, NOW + timedelta(minutes=50)) == ["EE"]
        assert set(await refresh.due_countries(db, NOW + timedelta(hours=4))) == {"EE", "PL"}
        assert set(await refresh.due_countries(db, NOW + timedelta(hours=8))) == {
            "EE", "PL", "MD",
        }  # fmt: skip
        assert len(await refresh.due_countries(db, NOW + timedelta(hours=12))) == len(COUNTRIES)


async def test_adaptive_cycle_fetches_only_due_countries(monkeypatch, settings):
    calls = []

    async def fake_collect_all(settings_, sources=None, countries=None, db_path=None):
        calls.append(countries)
        return []

    monkeypatch.setattr(runner, "collect_all", fake_collect_all)
    monkeypatch.setattr(runner, "EXTRA_COLLECTORS", {})
    monkeypatch.setattr(runner, "make_classifier", lambda s: None)

    first = await runner.run_cycle(settings, adaptive=True)
    assert calls == [None] and len(first.due) == len(COUNTRIES)  # first run: everything

    second = await runner.run_cycle(settings, adaptive=True)  # all just checked, all calm
    assert second.due == [] and len(calls) == 1

    async with storage.connect(settings.database_path) as db:
        await storage.insert_score(db, "PL", 7.5, "red", '{"raw": 0.7}')
        stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        await storage.mark_checked(db, ["PL"], stale)
    third = await runner.run_cycle(settings, adaptive=True)
    assert third.due == ["PL"] and calls[-1] == ["PL"]


def test_dashboard_shows_how_often_the_country_is_checked():
    data = views.DashboardData(
        lang="uk", country="PL", notify=True, score=0.0, level="green", war=war_status.get("PL"),
        changes_7d=0, updated="2026-10-03T06:11:00+00:00", refresh_hours=12,
    )  # fmt: skip
    text, _ = views.dashboard_screen(data)
    assert "Оновлено: 2026-10-03 06:11 UTC · перевірка кожні 12 год" in text
    data.lang, data.refresh_hours = "en", 1
    assert "checked hourly" in views.dashboard_screen(data)[0]


async def test_many_users_asking_about_one_country_fetch_nothing(monkeypatch, settings):
    """The bot reads stored results: two people refreshing Poland cost no requests."""

    async def no_fetch(*args, **kwargs):
        raise AssertionError("the bot must not fetch sources")

    monkeypatch.setattr(handlers, "collect_all", no_fetch)
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        await storage.insert_score(db, "PL", 5.4, "orange", "{}")

    screens = []
    for uid in (1, 2):
        for handler, data in ((handlers.on_lang, LangCb(code="uk")),
                              (handlers.on_country, CountryCb(code="PL")),
                              (handlers.on_menu, MenuCb(action="refresh"))):  # fmt: skip
            msg = MagicMock(spec=Message)
            msg.edit_text = AsyncMock()
            cb = SimpleNamespace(from_user=SimpleNamespace(id=uid), message=msg, answer=AsyncMock())
            await handler(cb, data, settings)
        screens.append(msg.edit_text.call_args.args[0])
    assert screens[0] == screens[1] and "5.4" in screens[0] and "кожні 4 год" in screens[0]
