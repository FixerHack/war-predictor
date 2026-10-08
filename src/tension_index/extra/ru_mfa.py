"""Block D: Russian/Belarusian MFA advice to their own citizens, from Russian news RSS.

The GDELT DOC query for the same thing (gdelt.py) answers 429 most days, so the headlines
of major Russian outlets are checked every cycle instead: an MFA (or embassy / Rosturizm)
headline about travel or citizens that names a monitored country. One outlet = tier 3,
two or more outlets = confirmed (mfa_signals). BelTA and the ministries' own sites refuse
requests from the server, so Belarusian advice comes only through Russian outlets.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import aiosqlite
import httpx

from tension_index import storage
from tension_index.collector import RunResult
from tension_index.config import Settings
from tension_index.extra.gdelt import mfa_signals
from tension_index.extra.lexicon import countries_in_ru
from tension_index.extra.news import parse_feed

FEEDS = (
    "https://tass.ru/rss/v2.xml",
    "https://ria.ru/export/rss2/archive/index.xml",
    "https://www.interfax.ru/rss.asp",
    "https://lenta.ru/rss/news",
    "https://rg.ru/xml/index.xml",
)
_WHO = re.compile(r"\bМИД\b|посольств|Ростуризм", re.I)
_WHAT = re.compile(r"поездк|турист|россиян|белорус\w* граждан|граждан\w* (России|РФ)|"
                   r"воздерж|покинуть|выезд|не рекоменд", re.I)  # fmt: skip
_NOT_OURS = re.compile(r"МИД (Украины|Латвии|Литвы|Эстонии|Польши|Молдавии|Финляндии)", re.I)


def advice_headlines(items: list[tuple[str, str, str | None]], domain: str) -> list[dict]:
    """Headlines that look like Russian/Belarusian MFA travel advice, as article dicts."""
    return [
        {"title": title, "domain": domain, "url": link}
        for title, link, _ in items
        if _WHO.search(title) and _WHAT.search(title) and not _NOT_OURS.search(title)
        and countries_in_ru(title)
    ]  # fmt: skip


async def collect_ru_mfa(
    db: aiosqlite.Connection, client: httpx.AsyncClient, settings: Settings
) -> RunResult:
    now = datetime.now(UTC)
    result = RunResult(source="ru_mfa")
    run_id = await storage.start_run(db, "ru_mfa")
    articles: list[dict] = []
    for url in FEEDS:
        try:
            response = await client.get(url)
            response.raise_for_status()
            items = parse_feed(response.content)
        except (httpx.HTTPError, ValueError, SyntaxError) as exc:  # ParseError is a SyntaxError
            result.failed += 1
            result.errors.append(f"{urlsplit(url).netloc}: {type(exc).__name__}: {exc}")
            continue
        if not items:
            result.failed += 1
            result.errors.append(f"{urlsplit(url).netloc}: empty feed")
            continue
        result.fetched += 1
        articles += advice_headlines(items, urlsplit(url).netloc.removeprefix("www."))
    result.changed = await mfa_signals(db, articles, now, publisher="ru_media")
    await db.commit()
    await storage.finish(db, result, run_id)
    return result
