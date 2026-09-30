"""aiogram 3 handlers.

Flow: /start -> language -> country -> dashboard. The dashboard is one message edited in
place by inline buttons (notifications on/off, change country, change language, refresh, about).
Admin commands (/status, /collect, /warcheck) are gated by TELEGRAM_ADMIN_IDS.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape

import aiosqlite
import httpx
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from tension_index import storage, war_status
from tension_index.bot import views
from tension_index.bot.callbacks import CountryCb, LangCb, MenuCb
from tension_index.collector import collect_all, make_client
from tension_index.config import Settings
from tension_index.countries import COUNTRIES
from tension_index.health import run_checks
from tension_index.i18n import LANGS, t

router = Router(name="main")


async def build_dashboard(db: aiosqlite.Connection, user: storage.User) -> views.Screen:
    assert user.lang and user.country
    score_row = await storage.latest_score(db, user.country)
    since = (datetime.now(UTC) - timedelta(days=7)).isoformat(timespec="seconds")
    data = views.DashboardData(
        lang=user.lang,
        country=user.country,
        notify=user.notify,
        score=score_row["score"] if score_row else None,
        level=score_row["level"] if score_row else None,
        war=war_status.get(user.country),
        changes_7d=await storage.changes_since(db, user.country, since),
        updated=score_row["computed_at"] if score_row else None,
    )
    return views.dashboard_screen(data)


async def next_screen(db: aiosqlite.Connection, user: storage.User | None) -> views.Screen:
    """Whatever the user still has to set up, else the dashboard."""
    if user is None or user.lang not in LANGS:
        return views.language_screen()
    if user.country not in COUNTRIES:
        return views.country_screen(user.lang, can_go_back=False)
    return await build_dashboard(db, user)


async def show(callback: CallbackQuery, screen: views.Screen) -> None:
    text, kb = screen
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest as exc:  # "message is not modified" on refresh
            if "not modified" not in str(exc):
                raise
    await callback.answer()


async def reply(message: Message, screen: tuple[str, InlineKeyboardMarkup]) -> None:
    text, kb = screen
    await message.answer(text, reply_markup=kb)


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, settings: Settings) -> None:
    assert message.from_user
    async with storage.connect(settings.database_path) as db:
        user = await storage.get_user(db, message.from_user.id)
        await reply(message, await next_screen(db, user))


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings) -> None:
    assert message.from_user
    async with storage.connect(settings.database_path) as db:
        user = await storage.get_user(db, message.from_user.id)
    lang = user.lang if user else None
    await message.answer(t(lang, "help") + "\n\n<i>" + t(lang, "disclaimer") + "</i>")


@router.callback_query(LangCb.filter())
async def on_lang(callback: CallbackQuery, callback_data: LangCb, settings: Settings) -> None:
    if callback_data.code not in LANGS:
        await callback.answer()
        return
    async with storage.connect(settings.database_path) as db:
        user = await storage.upsert_user(db, callback.from_user.id, lang=callback_data.code)
        await show(callback, await next_screen(db, user))


@router.callback_query(CountryCb.filter())
async def on_country(callback: CallbackQuery, callback_data: CountryCb, settings: Settings) -> None:
    if callback_data.code not in COUNTRIES:
        await callback.answer()
        return
    async with storage.connect(settings.database_path) as db:
        user = await storage.upsert_user(db, callback.from_user.id, country=callback_data.code)
        await show(callback, await next_screen(db, user))


@router.callback_query(MenuCb.filter())
async def on_menu(callback: CallbackQuery, callback_data: MenuCb, settings: Settings) -> None:
    uid = callback.from_user.id
    async with storage.connect(settings.database_path) as db:
        user = await storage.get_user(db, uid)
        if user is None or user.lang not in LANGS or user.country not in COUNTRIES:
            await show(callback, await next_screen(db, user))
            return
        match callback_data.action:
            case "notify":
                user = await storage.upsert_user(db, uid, notify=not user.notify)
            case "lang":
                user = await storage.upsert_user(db, uid, lang="en" if user.lang == "uk" else "uk")
            case "country":
                await show(callback, views.country_screen(user.lang, can_go_back=True))
                return
            case "about":
                await show(callback, views.about_screen(user.lang))
                return
        # refresh / home / after toggles
        await show(callback, await build_dashboard(db, user))


# --- Admin ----------------------------------------------------------------------------------


def register_admin(router_: Router, settings: Settings) -> None:
    is_admin = F.from_user.id.in_(set(settings.telegram_admin_ids))

    @router_.message(Command("status"), is_admin)
    async def cmd_status(message: Message) -> None:
        report = await run_checks(settings)
        await message.answer(f"<pre>{escape(report.as_text())}</pre>")

    @router_.message(Command("collect"), is_admin)
    async def cmd_collect(message: Message) -> None:
        await message.answer("Запускаю збір…")
        results = await collect_all(settings)
        text = "\n".join(
            f"{r.source}: fetched={r.fetched} changed={r.changed} failed={r.failed}"
            for r in results
        )
        await message.answer(f"<pre>{escape(text) or 'no sources'}</pre>")

    @router_.message(Command("warcheck"), is_admin)
    async def cmd_warcheck(message: Message) -> None:
        try:
            async with make_client(settings) as client:
                detected = war_status.parse_wikipedia(await war_status.fetch_wikipedia(client))
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            await message.answer(f"❌ war-check failed: {escape(str(exc))}")
            return
        diff = war_status.mismatches(war_status.load(), detected)
        await message.answer(
            "Розбіжностей з Wikipedia немає ✅"
            if not diff
            else "<pre>" + escape("\n".join(diff)) + "</pre>"
        )
