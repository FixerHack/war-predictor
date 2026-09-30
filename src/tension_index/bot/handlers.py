"""aiogram 3 handlers. Public commands are read-only; admin commands are gated by
TELEGRAM_ADMIN_IDS."""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from tension_index import __version__, storage
from tension_index.collector import collect_all
from tension_index.config import Settings
from tension_index.health import run_checks

router = Router(name="main")

HELP = (
    "<b>Tension Index</b> v{version}\n"
    "Індикатор стану сигналів ескалації для країн Європи (шкала 0–10).\n"
    "<i>Це не прогноз і не порада щодо виїзду.</i>\n\n"
    "/status — стан системи\n"
    "/changes — останні зміни в рекомендаціях\n"
    "/help — ця довідка"
)


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP.format(version=__version__))


@router.message(Command("status"))
async def cmd_status(message: Message, settings: Settings) -> None:
    report = await run_checks(settings)
    await message.answer(f"<pre>{escape(report.as_text())}</pre>")


@router.message(Command("changes"))
async def cmd_changes(message: Message, settings: Settings) -> None:
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        rows = await storage.recent_changes(db, limit=10)
    if not rows:
        await message.answer("Змін поки не зафіксовано.")
        return
    lines = [f"{r['detected_at']} · {r['country']} · {r['source']} (#{r['id']})" for r in rows]
    await message.answer("<b>Останні зміни</b>\n" + escape("\n".join(lines)))


def admin_filter(settings: Settings):
    return F.from_user.id.in_(set(settings.telegram_admin_ids))


def register_admin(router_: Router, settings: Settings) -> None:
    @router_.message(Command("collect"), admin_filter(settings))
    async def cmd_collect(message: Message) -> None:
        await message.answer("Запускаю збір…")
        results = await collect_all(settings)
        text = "\n".join(
            f"{r.source}: fetched={r.fetched} changed={r.changed} failed={r.failed}"
            for r in results
        )
        await message.answer(f"<pre>{escape(text) or 'no sources'}</pre>")
