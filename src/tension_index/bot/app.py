"""Long-running bot process (long polling)."""

from __future__ import annotations

import logging

from aiogram import Dispatcher, Router
from aiogram.types import BotCommand

from tension_index.bot.handlers import register_admin, router
from tension_index.config import Settings
from tension_index.notify import make_bot

log = logging.getLogger(__name__)


def build_dispatcher(settings: Settings) -> Dispatcher:
    dp = Dispatcher(settings=settings)  # `settings` is injected into handlers
    admin = Router(name="admin")
    register_admin(admin, settings)
    dp.include_routers(admin, router)
    return dp


async def run_bot(settings: Settings) -> None:
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set (see .env.example)")
    bot = make_bot(settings)
    dp = build_dispatcher(settings)
    await bot.set_my_commands(
        [
            BotCommand(command="status", description="Стан системи"),
            BotCommand(command="changes", description="Останні зміни"),
            BotCommand(command="help", description="Довідка"),
        ]
    )
    log.info("Bot started (polling)")
    await dp.start_polling(bot)
