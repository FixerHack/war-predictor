"""Daily summary for users with the digest on: their countries (score, 24 h change, war
status) and the largest rises in the same regions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape

import aiosqlite

from tension_index import storage, war_status
from tension_index.bot.views import LEVEL_ICONS
from tension_index.countries import COUNTRIES, get_country
from tension_index.i18n import t

REGION_RISE = 0.5  # show regional movers from half a point up


@dataclass(slots=True)
class Row:
    code: str
    score: float | None
    level: str | None
    delta: float | None


async def snapshot(db: aiosqlite.Connection, now: datetime) -> dict[str, Row]:
    day_ago = (now - timedelta(hours=24)).isoformat()
    rows = {}
    for code in COUNTRIES:
        latest = await storage.latest_score(db, code)
        before = await storage.score_before(db, code, day_ago)
        score = latest["score"] if latest else None
        prev = before["score"] if before else None
        delta = round(score - prev, 1) if score is not None and prev is not None else None
        rows[code] = Row(code, score, latest["level"] if latest else None, delta)
    return rows


def render(user: storage.User, rows: dict[str, Row]) -> str:
    lang = user.lang or "uk"
    lines = [f"<b>{t(lang, 'digest_title')}</b>", ""]
    for code in user.followed:
        c, r = get_country(code), rows[code]
        if r.score is None or r.level is None:
            value = t(lang, "calibrating")
        else:
            change = f" ({r.delta:+.1f})" if r.delta else ""
            value = f"{LEVEL_ICONS[r.level]} <b>{r.score:.1f}</b>{change}"
        war = war_status.get(code).status
        war_note = f" · {war_status.ICONS[war]} {t(lang, 'war_' + war)}" if war != "none" else ""
        lines.append(f"{c.flag} {escape(c.title(lang))}: {value}{war_note}")
    regions = {get_country(code).region for code in user.followed}
    movers = sorted(
        (r for r in rows.values()
         if get_country(r.code).region in regions and r.code not in user.followed
         and r.delta is not None and r.delta >= REGION_RISE),
        key=lambda r: -(r.delta or 0),
    )[:3]  # fmt: skip
    lines.append("")
    if movers:
        items = ", ".join(f"{get_country(r.code).flag} {r.delta:+.1f}" for r in movers)
        lines.append(t(lang, "digest_region", items=items))
    else:
        lines.append(t(lang, "digest_quiet"))
    lines += ["", f"<i>{t(lang, 'disclaimer')}</i>"]
    return "\n".join(lines)


async def send_digests(settings, now: datetime | None = None) -> int:
    from tension_index.notify import TELEGRAM_LIMIT, make_bot

    now = now or datetime.now(UTC)
    async with storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        users = await storage.digest_users(db)
        if not users or not settings.telegram_bot_token:
            return 0
        rows = await snapshot(db, now)
    bot = make_bot(settings)
    sent = 0
    try:
        for user in users:
            try:
                await bot.send_message(user.tg_id, render(user, rows)[:TELEGRAM_LIMIT])
                sent += 1
            except Exception:  # one blocked user must not stop the rest
                continue
    finally:
        await bot.session.close()
    return sent
