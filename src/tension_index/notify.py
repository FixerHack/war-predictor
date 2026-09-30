"""Outgoing Telegram messages (alerts, change notifications) for short-lived processes."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from tension_index.config import Settings

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4000  # hard limit is 4096; keep headroom


def make_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


async def send(settings: Settings, text: str) -> bool:
    """Send `text` to TELEGRAM_CHAT_ID. Returns False (and logs) instead of raising."""
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        log.info("Telegram not configured, message not sent:\n%s", text)
        return False
    bot = make_bot(settings)
    try:
        await bot.send_message(settings.telegram_chat_id, text[:TELEGRAM_LIMIT])
        return True
    except Exception:
        log.exception("Failed to send Telegram message")
        return False
    finally:
        await bot.session.close()


async def broadcast_change(settings: Settings, country: str, source_label: str, diff: str) -> int:
    """Send an advisory-change alert to every user following `country` with alerts on,
    each in their own language. Returns the number of messages delivered."""
    import asyncio
    from html import escape

    from aiogram.exceptions import TelegramForbiddenError

    from tension_index import storage
    from tension_index.countries import get_country
    from tension_index.i18n import t

    if not settings.telegram_bot_token:
        return 0
    c = get_country(country)
    async with storage.connect(settings.database_path) as db:
        users = await storage.subscribers(db, country)
        if not users:
            return 0
        bot = make_bot(settings)
        sent = 0
        try:
            for user in users:
                text = (
                    t(
                        user.lang,
                        "alert_change",
                        flag=c.flag,
                        country=escape(c.title(user.lang or "uk")),
                        source=escape(source_label),
                    )
                    + f"\n<pre>{escape(diff[:2500])}</pre>\n<i>{t(user.lang, 'disclaimer')}</i>"
                )
                try:
                    await bot.send_message(user.tg_id, text[:TELEGRAM_LIMIT])
                    sent += 1
                except TelegramForbiddenError:
                    # User blocked the bot: stop sending until they come back.
                    await storage.upsert_user(db, user.tg_id, notify=False)
                except Exception:
                    log.exception("Failed to notify %s", user.tg_id)
                await asyncio.sleep(0.05)  # stay well under Telegram's 30 msg/s
        finally:
            await bot.session.close()
    return sent
