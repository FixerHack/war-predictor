# ruff: noqa: E501
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

from tension_index import storage, war_status
from tension_index.bot import handlers, views
from tension_index.bot.callbacks import CountryCb, LangCb, MenuCb, ViewCb


def texts(kb) -> list[str]:
    return [b.text for row in kb.inline_keyboard for b in row]


def test_language_screen_offers_both():
    text, kb = views.language_screen()
    assert texts(kb) == ["🇺🇦 Українська", "🇬🇧 English"]


def test_country_screen_first_choice_and_follow_list():
    _, kb = views.country_screen("uk")
    labels = texts(kb)
    assert len(labels) == 38 and "🇵🇱 Польща" in labels
    text, kb = views.country_screen("en", ["PL", "EE"])
    assert "✅ 🇵🇱 Poland" in texts(kb) and "🇱🇻 Latvia" in texts(kb)
    assert texts(kb)[-1] == "✔️ Done" and "up to 5" in text


def dash(**kw) -> views.DashboardData:
    base = dict(
        lang="uk",
        country="PL",
        notify=True,
        score=None,
        level=None,
        war=war_status.get("PL"),
        changes_7d=0,
        updated=None,
    )
    return views.DashboardData(**{**base, **kw})


def test_dashboard_indicators():
    text, kb = views.dashboard_screen(dash())
    assert "🇵🇱 <b>Польща</b>" in text
    assert "калібрування" in text
    assert "збройного конфлікту немає" in text
    assert "🇺🇦 Україна (війна)" in text and "🇷🇺 Росія" in text
    assert "Сповіщення: увімкнено" in text and "Мова: українська" in text
    assert "не прогноз" in text
    assert texts(kb)[0] == "🔔 Сповіщення: увімк."

    text, kb = views.dashboard_screen(
        dash(
            lang="en",
            country="MD",
            notify=False,
            score=6.2,
            level="orange",
            war=war_status.get("MD"),
            updated="2026-09-30T10:00:00+00:00",
        )
    )
    assert "🟠 <b>6.2</b> / 10 · elevated" in text
    assert "▰▰▰▰▰▰▱▱▱▱" in text
    assert "frozen conflict" in text and "Transnistria" in text
    assert "Notifications: off" in text
    assert texts(kb)[0] == "🔕 Notifications: off"
    assert "🌐 Українська" in texts(kb)


# --- Handler flow ---------------------------------------------------------------------------


def make_callback(uid: int = 42):
    msg = MagicMock(spec=Message)
    msg.edit_text = AsyncMock()
    return SimpleNamespace(from_user=SimpleNamespace(id=uid), message=msg, answer=AsyncMock())


def last_edit(cb) -> tuple[str, list[str]]:
    args, kwargs = cb.message.edit_text.call_args
    return args[0], texts(kwargs["reply_markup"])


@pytest.fixture
async def db_settings(settings):
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
    return settings


async def test_onboarding_and_toggles(db_settings):
    s = db_settings
    message = MagicMock(spec=Message)
    message.from_user = SimpleNamespace(id=42)
    message.answer = AsyncMock()
    await handlers.cmd_start(message, s)
    assert "Choose your language" in message.answer.call_args.args[0]

    cb = make_callback()
    await handlers.on_lang(cb, LangCb(code="uk"), s)
    text, _ = last_edit(cb)
    assert text.startswith("Оберіть країну")

    cb = make_callback()
    await handlers.on_country(cb, CountryCb(code="EE"), s)
    text, buttons = last_edit(cb)
    assert "🇪🇪 <b>Естонія</b>" in text and "Сповіщення: увімкнено" in text

    cb = make_callback()
    await handlers.on_menu(cb, MenuCb(action="notify"), s)
    assert "Сповіщення: вимкнено" in last_edit(cb)[0]

    cb = make_callback()
    await handlers.on_menu(cb, MenuCb(action="lang"), s)
    assert "🇪🇪 <b>Estonia</b>" in last_edit(cb)[0]

    cb = make_callback()
    await handlers.on_menu(cb, MenuCb(action="country"), s)
    assert last_edit(cb)[1][-1] == "✔️ Done" and "✅ 🇪🇪 Estonia" in last_edit(cb)[1]

    cb = make_callback()
    await handlers.on_country(cb, CountryCb(code="MD"), s)  # follow a second country
    assert "✅ 🇲🇩 Moldova" in last_edit(cb)[1]

    cb = make_callback()
    await handlers.on_menu(cb, MenuCb(action="home"), s)
    text, buttons = last_edit(cb)
    assert "🇪🇪 <b>Estonia</b>" in text and "Also following" in text and "🇲🇩 Moldova · ⏳ 🧊" in text
    assert "🌍 Countries (2/5)" in buttons and "🇲🇩 Moldova" in buttons

    cb = make_callback()
    await handlers.on_view(cb, ViewCb(code="MD"), s)
    assert "🇲🇩 <b>Moldova</b>" in last_edit(cb)[0] and "🇪🇪 Estonia · ⏳" in last_edit(cb)[0]

    cb = make_callback()
    await handlers.on_menu(cb, MenuCb(action="digest"), s)
    assert "Digest: on" in last_edit(cb)[0]

    async with storage.connect(s.database_path) as db:
        user = await storage.get_user(db, 42)
        assert (user.lang, user.country, user.notify, user.digest) == ("en", "MD", False, True)
        assert user.followed == ["EE", "MD"]
        assert await storage.subscribers(db, "MD") == []  # alerts are off
        assert [u.tg_id for u in await storage.digest_users(db)] == [42]

    # Returning user goes straight to the dashboard.
    message.answer.reset_mock()
    await handlers.cmd_start(message, s)
    assert "Moldova" in message.answer.call_args.args[0]


async def test_follow_limits(db_settings):
    s = db_settings
    message = MagicMock(spec=Message)
    message.from_user = SimpleNamespace(id=5)
    message.answer = AsyncMock()
    await handlers.cmd_start(message, s)
    await handlers.on_lang(make_callback(5), LangCb(code="uk"), s)
    await handlers.on_country(make_callback(5), CountryCb(code="PL"), s)

    cb = make_callback(5)
    await handlers.on_country(cb, CountryCb(code="PL"), s)  # can't drop the last one
    assert cb.answer.call_args.kwargs["show_alert"] and "хоча б одну" in cb.answer.call_args.args[0]
    for code in ("EE", "LV", "LT", "FI"):
        await handlers.on_country(make_callback(5), CountryCb(code=code), s)
    cb = make_callback(5)
    await handlers.on_country(cb, CountryCb(code="SE"), s)
    assert "до 5" in cb.answer.call_args.args[0]
    await handlers.on_country(make_callback(5), CountryCb(code="PL"), s)  # unfollow the shown one
    async with storage.connect(s.database_path) as db:
        user = await storage.get_user(db, 5)
    assert user.followed == ["EE", "LV", "LT", "FI"] and user.country == "EE"
    async with storage.connect(s.database_path) as db:
        assert [u.tg_id for u in await storage.subscribers(db, "LV")] == [5]


async def test_unknown_callback_values_are_ignored(db_settings):
    cb = make_callback()
    await handlers.on_country(cb, CountryCb(code="UA"), db_settings)
    cb.message.edit_text.assert_not_called()
    cb.answer.assert_awaited()


async def test_menu_before_setup_restarts_onboarding(db_settings):
    cb = make_callback(uid=7)
    await handlers.on_menu(cb, MenuCb(action="refresh"), db_settings)
    assert "Choose your language" in last_edit(cb)[0]


async def test_digest_render(db_settings):
    from datetime import UTC, datetime, timedelta

    from tension_index.digest import render, snapshot

    s = db_settings
    now = datetime.now(UTC)
    async with storage.connect(s.database_path) as db:
        for code, old, new in (("EE", 2.0, 3.5), ("LV", 1.0, 2.0), ("FI", 1.0, 1.1)):
            await db.execute(
                "INSERT INTO scores (country, computed_at, score, level, payload) VALUES (?, ?, ?, 'green', '{}')",
                (code, (now - timedelta(hours=30)).isoformat(), old),
            )
            await db.execute(
                "INSERT INTO scores (country, computed_at, score, level, payload) VALUES (?, ?, ?, 'yellow', '{}')",
                (code, now.isoformat(), new),
            )
        await db.commit()
        await storage.upsert_user(db, 9, lang="uk", digest=True)
        user = await storage.set_followed(db, 9, "EE", True)
        user = await storage.set_followed(db, 9, "MD", True)
        rows = await snapshot(db, now)
    text = render(user, rows)
    assert "🇪🇪 Естонія: 🟡 <b>3.5</b> (+1.5)" in text
    assert "🇲🇩 Молдова: ⏳ калібрування" in text and "заморожений конфлікт" in text
    assert "найбільше зросла напруга: 🇱🇻 +1.0" in text  # same region, not followed
    assert "🇫🇮" not in text  # +0.1 is below the threshold
