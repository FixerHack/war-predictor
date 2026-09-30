from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

from tension_index import storage, war_status
from tension_index.bot import handlers, views
from tension_index.bot.callbacks import CountryCb, LangCb, MenuCb


def texts(kb) -> list[str]:
    return [b.text for row in kb.inline_keyboard for b in row]


def test_language_screen_offers_both():
    text, kb = views.language_screen()
    assert texts(kb) == ["🇺🇦 Українська", "🇬🇧 English"]


def test_country_screen_lists_all_localised():
    _, kb = views.country_screen("uk", can_go_back=False)
    labels = texts(kb)
    assert len(labels) == 38 and "🇵🇱 Польща" in labels
    _, kb = views.country_screen("en", can_go_back=True)
    assert "🇵🇱 Poland" in texts(kb) and texts(kb)[-1] == "« Back"


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
    assert "🟠 <b>6.2</b> / 10 · orange" in text
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
    assert last_edit(cb)[1][-1] == "« Back"

    cb = make_callback()
    await handlers.on_country(cb, CountryCb(code="MD"), s)
    assert "Moldova" in last_edit(cb)[0]

    async with storage.connect(s.database_path) as db:
        user = await storage.get_user(db, 42)
        assert (user.lang, user.country, user.notify) == ("en", "MD", False)
        assert await storage.subscribers(db, "MD") == []

    # Returning user goes straight to the dashboard.
    message.answer.reset_mock()
    await handlers.cmd_start(message, s)
    assert "Moldova" in message.answer.call_args.args[0]


async def test_unknown_callback_values_are_ignored(db_settings):
    cb = make_callback()
    await handlers.on_country(cb, CountryCb(code="UA"), db_settings)
    cb.message.edit_text.assert_not_called()
    cb.answer.assert_awaited()


async def test_menu_before_setup_restarts_onboarding(db_settings):
    cb = make_callback(uid=7)
    await handlers.on_menu(cb, MenuCb(action="refresh"), db_settings)
    assert "Choose your language" in last_edit(cb)[0]
