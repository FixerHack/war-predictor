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
