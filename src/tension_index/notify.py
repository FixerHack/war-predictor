"""Outgoing Telegram messages (alerts, change notifications) for short-lived processes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from html import escape

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


async def admin_lang(settings: Settings) -> str:
    """Language of TELEGRAM_CHAT_ID: the one its owner chose in the bot, Ukrainian otherwise."""
    from tension_index import storage
    from tension_index.i18n import DEFAULT_LANG

    try:
        chat_id = int(settings.telegram_chat_id)
    except ValueError:
        return DEFAULT_LANG
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        user = await storage.get_user(db, chat_id)
    return (user.lang if user else None) or DEFAULT_LANG


async def send_admin(settings: Settings, render: Callable[[str], str]) -> bool:
    """Send `render(lang)` to TELEGRAM_CHAT_ID in the language its owner uses in the bot."""
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return await send(settings, render("en"))  # only logged
    return await send(settings, render(await admin_lang(settings)))


async def broadcast(settings: Settings, country: str, render: Callable[[str], str]) -> int:
    """Send `render(lang)` to every user following `country` with alerts on, each in their
    own language. Returns the number of messages delivered."""
    import asyncio

    from aiogram.exceptions import TelegramForbiddenError

    from tension_index import storage

    if not settings.telegram_bot_token:
        return 0
    async with storage.connect(settings.database_path) as db:
        users = await storage.subscribers(db, country)
        if not users:
            return 0
        bot = make_bot(settings)
        sent = 0
        try:
            for user in users:
                try:
                    await bot.send_message(user.tg_id, render(user.lang or "uk")[:TELEGRAM_LIMIT])
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


def render_change(
    country: str, source_label: str, diff: str, summary: dict[str, str] | None, quote: str
) -> Callable[[str], str]:
    from tension_index.countries import get_country
    from tension_index.i18n import t

    c = get_country(country)

    def render(lang: str) -> str:
        head = t(lang, "alert_change", flag=c.flag, country=escape(c.title(lang)),
                 source=escape(source_label))  # fmt: skip
        text = (summary or {}).get(lang, "")
        body = escape(text) if text else f"<pre>{escape(diff[:1500])}</pre>"
        if quote:
            body += f"\n<i>«{escape(quote[:300])}»</i>"
        return f"{head}\n{body}\n\n<i>{t(lang, 'disclaimer')}</i>"

    return render


def render_admin_change(
    country: str,
    source_label: str,
    diff: str,
    summary: dict[str, str] | None = None,
    quote: str = "",
) -> Callable[[str], str]:
    """Change notice for the operator: the summary in their language, the original text diff
    folded under it (the source text itself stays in the source's language)."""
    from tension_index.countries import get_country
    from tension_index.i18n import t

    c = get_country(country)

    def render(lang: str) -> str:
        head = t(lang, "alert_change", flag=c.flag, country=escape(c.title(lang)),
                 source=escape(source_label))  # fmt: skip
        text = (summary or {}).get(lang, "")
        body = escape(text) if text else t(lang, "admin_no_summary")
        if quote:
            body += f"\n<i>«{escape(quote[:300])}»</i>"
        return (f"{head}\n{body}\n\n{t(lang, 'admin_diff')}\n"
                f"<blockquote expandable>{escape(diff[:2500])}</blockquote>")  # fmt: skip

    return render


def render_collector_failed(source: str, failed: int, fetched: int, errors: list[str]):
    from tension_index.i18n import t

    def render(lang: str) -> str:
        text = t(lang, "admin_collector_failed", source=escape(source), failed=failed)
        if not errors and not fetched:
            text += "\n" + t(lang, "admin_nothing_fetched")
        if errors:
            text += f"\n<pre>{escape(chr(10).join(e[:300] for e in errors[:5]))}</pre>"
        return text

    return render


async def broadcast_change(
    settings: Settings,
    country: str,
    source_label: str,
    diff: str,
    summary: dict[str, str] | None = None,
    quote: str = "",
) -> int:
    return await broadcast(
        settings, country, render_change(country, source_label, diff, summary, quote)
    )


def render_score(country: str, previous: float, payload: dict) -> Callable[[str], str]:
    from tension_index.countries import get_country
    from tension_index.explain import explain
    from tension_index.i18n import t

    c = get_country(country)
    score, level = payload["score"], payload["level"]
    arrow = "⬆️" if score > previous else "⬇️"

    def render(lang: str) -> str:
        return (
            t(lang, "alert_score", arrow=arrow, flag=c.flag, country=escape(c.title(lang)),
              old=f"{previous:.1f}", new=f"{score:.1f}", level=t(lang, "level_" + level))
            + f"\n\n<b>{t(lang, 'why')}:</b>\n{escape(explain(payload, lang))}"
            + f"\n\n<i>{t(lang, 'disclaimer')}</i>"
        )  # fmt: skip

    return render
