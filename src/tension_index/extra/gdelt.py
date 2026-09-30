"""GDELT DOC 2.0 API (free, no key): block E media volume and block D aggressor advice.

- Volume: daily article counts about each country with military keywords over 3 months;
  a surge (last 2 days vs the median of the prior 60) is a tier-3 media signal that counts
  only when tier 1-2 news confirm activity in the same country.
- Russian/Belarusian MFA advice: Russian-language articles about the MFA telling citizens to
  avoid travel; countries matched by Russian stems; 2+ outlets = confirmed signal.
Runs at most once a day (GDELT asks for one request every 5 seconds).
"""

from __future__ import annotations

import asyncio
import statistics
from datetime import UTC, datetime, timedelta

import aiosqlite
import httpx

from tension_index import storage
from tension_index.collector import RunResult
from tension_index.config import Settings
from tension_index.countries import COUNTRIES
from tension_index.extra.lexicon import countries_in_ru
from tension_index.scoring import Signal

API = "https://api.gdeltproject.org/api/v2/doc/doc"
KEYWORDS = "(military OR troops OR attack OR invasion OR mobilization OR sabotage OR missile)"
MFA_QUERY = '("МИД России" OR "МИД РФ" OR "МИД Белоруссии" OR "МИД Беларуси") поездок'
PAUSE_SECONDS = 5.5
MIN_INTERVAL_HOURS = 20
SURGE_RATIO = 2.0


def daily_counts(payload: dict) -> list[tuple[str, float]]:
    """[(YYYYMMDD, count)] from a timelinevolraw response."""
    timeline = payload.get("timeline") or []
    if not timeline:
        return []
    return [(str(p["date"])[:8], float(p["value"])) for p in timeline[0].get("data", [])]


def surge_ratio(counts: list[tuple[str, float]]) -> float | None:
    values = [v for _, v in counts]
    if len(values) < 30:
        return None
    recent = statistics.mean(values[-2:])
    base = statistics.median(values[-62:-2])
    return recent / base if base >= 3 else None


def surge_strength(ratio: float) -> float:
    return min(1.0, 0.3 + (ratio - SURGE_RATIO) * 0.2)


async def _recently_ran(db: aiosqlite.Connection, now: datetime) -> bool:
    last = await storage.last_success(db, "gdelt")
    return bool(last) and now - datetime.fromisoformat(last) < timedelta(hours=MIN_INTERVAL_HOURS)


async def _news_confirmed(db: aiosqlite.Connection, country: str, now: datetime) -> bool:
    since = (now - timedelta(hours=72)).isoformat()
    async with db.execute(
        "SELECT 1 FROM signals WHERE country = ? AND publisher = 'news' AND tier <= 2 "
        "AND observed_at >= ? LIMIT 1",
        (country, since),
    ) as cur:
        return await cur.fetchone() is not None


async def collect_gdelt(
    db: aiosqlite.Connection,
    client: httpx.AsyncClient,
    settings: Settings,
    pause: float = PAUSE_SECONDS,
) -> RunResult:
    now = datetime.now(UTC)
    result = RunResult(source="gdelt")
    if await _recently_ran(db, now):
        result.fetched = 1  # nothing to do today; not a failure
        return result
    run_id = await storage.start_run(db, "gdelt")
    for code, country in COUNTRIES.items():
        try:
            response = await client.get(API, params={
                "query": f'"{country.name}" {KEYWORDS}', "mode": "timelinevolraw",
                "timespan": "3months", "format": "json",
            })  # fmt: skip
            response.raise_for_status()
            counts = daily_counts(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            result.failed += 1
            result.errors.append(f"{code}: {type(exc).__name__}: {exc}")
            if result.fetched == 0 and result.failed >= 3:
                result.errors.append("GDELT unreachable: stopped after 3 failures")
                break
            await asyncio.sleep(pause)
            continue
        result.fetched += 1
        for day, value in counts[-3:]:
            await db.execute(
                "INSERT OR REPLACE INTO series (source, country, key, period, value) "
                "VALUES ('gdelt', ?, 'volume', ?, ?)",
                (code, day, value),
            )
        ratio = surge_ratio(counts)
        if ratio is not None and ratio >= SURGE_RATIO:
            confirmed = await _news_confirmed(db, code, now)
            signal = Signal(
                country=code, block="media", kind="media:gdelt_surge", strength=surge_strength(ratio),
                publisher="gdelt", observed_at=now, tier=3, confirmed=confirmed,
                reason="military_threat", note=f"military-related coverage x{ratio:.1f} vs usual",
            )  # fmt: skip
            await storage.upsert_signal(db, signal, f"gdelt:{now:%Y-%m-%d}")
            result.changed += 1
        await asyncio.sleep(pause)

    try:
        response = await client.get(API, params={
            "query": f"{MFA_QUERY} sourcelang:russian", "mode": "artlist",
            "maxrecords": "75", "timespan": "7days", "format": "json",
        })  # fmt: skip
        response.raise_for_status()
        articles = response.json().get("articles") or []
        result.changed += await mfa_signals(db, articles, now)
    except (httpx.HTTPError, ValueError) as exc:
        result.errors.append(f"mfa: {type(exc).__name__}: {exc}")
    await db.commit()
    await storage.finish(db, result, run_id)
    return result


async def mfa_signals(db: aiosqlite.Connection, articles: list[dict], now: datetime) -> int:
    """Aggressor advice to its citizens about a country: 2+ outlets = confirmed."""
    by_country: dict[str, list[dict]] = {}
    for article in articles:
        for code in countries_in_ru(article.get("title", "")):
            by_country.setdefault(code, []).append(article)
    count = 0
    for code, items in by_country.items():
        domains = {a.get("domain") for a in items}
        confirmed = len(domains) >= 2
        signal = Signal(
            country=code, block="aggressor", kind="aggressor:mfa_advisory", strength=0.8,
            publisher="gdelt", observed_at=now, tier=2 if confirmed else 3, confirmed=confirmed,
            reason="military_threat", note=items[0].get("title", "")[:200],
        )  # fmt: skip
        await storage.upsert_signal(db, signal, f"gdelt-mfa:{now:%Y-%m-%d}")
        count += 1
    return count
