"""GDELT (free, no key): block E media volume and block D aggressor advice.

- Volume: GDELT 1.0 daily event exports (one static zip per day, no rate limit) give the
  number of articles about military events (CAMEO roots 15/18/19/20) located in each
  country; a surge (last 2 days vs the median of the prior 60) is a tier-3 media signal that
  counts only when tier 1-2 news confirm activity in the same country. The DOC 2.0 API used
  before throttles hard (429 even at one request per 5 s, `{}` for busy queries), so 38
  timeline queries could not finish in time.
- Russian/Belarusian MFA advice: one DOC 2.0 query for Russian-language articles about the
  MFA telling citizens to avoid travel; countries matched by Russian stems; 2+ outlets =
  confirmed signal. Requests stay >= 5 s apart, as GDELT asks.
Runs at most once a day.
"""

from __future__ import annotations

import asyncio
import io
import statistics
import zipfile
from datetime import UTC, date, datetime, timedelta

import aiosqlite
import httpx

from tension_index import storage
from tension_index.collector import RunResult
from tension_index.config import Settings
from tension_index.countries import COUNTRIES
from tension_index.extra.lexicon import countries_in_ru
from tension_index.scoring import Signal
from tension_index.sources.us import FIPS

API = "https://api.gdeltproject.org/api/v2/doc/doc"
EVENTS = "https://data.gdeltproject.org/events/{day}.export.CSV.zip"
EVENTS_INDEX = "https://data.gdeltproject.org/events/index.html"
MFA_QUERY = '("МИД России" OR "МИД РФ" OR "МИД Белоруссии" OR "МИД Беларуси") поездок'
# CAMEO event roots: 15 force posture, 18 assault, 19 fight, 20 mass violence.
MILITARY_ROOTS = frozenset({"15", "18", "19", "20"})
# Columns of the 58-column daily export (tab-separated, no header).
COL_ROOT, COL_ARTICLES, COL_GEO_COUNTRY = 28, 33, 51
SERIES_KEY = "conflict"
HISTORY_DAYS = 62  # 2 recent days + 60 for the baseline
BACKFILL_PER_RUN = 20  # older days fetched per run until the history is complete
MAX_FAILURES = 3  # consecutive failed/empty responses before giving up
PAUSE_SECONDS = 5.5  # between DOC API requests
FILE_PAUSE_SECONDS = 1.0  # between static event files
MIN_INTERVAL_HOURS = 20
SURGE_RATIO = 2.0
_ISO_BY_FIPS = {fips: iso for iso, fips in FIPS.items() if iso in COUNTRIES}


class EmptyResponse(ValueError):
    """GDELT answered 200 with no data (it does so under load, e.g. `{}`)."""


def parse_events(data: bytes) -> dict[str, float]:
    """{ISO: articles about military events} from a zipped daily export."""
    totals = dict.fromkeys(COUNTRIES, 0.0)
    rows = 0
    archive = zipfile.ZipFile(io.BytesIO(data))
    with archive, archive.open(archive.namelist()[0]) as raw:
        for line in io.TextIOWrapper(raw, encoding="utf-8", errors="replace"):
            fields = line.split("\t")
            if len(fields) <= COL_GEO_COUNTRY:
                continue
            rows += 1
            iso = _ISO_BY_FIPS.get(fields[COL_GEO_COUNTRY])
            if iso and fields[COL_ROOT] in MILITARY_ROOTS:
                totals[iso] += float(fields[COL_ARTICLES] or 0)
    if not rows:
        raise EmptyResponse("event file has no rows")
    return totals


def surge_ratio(counts: list[tuple[str, float]]) -> float | None:
    values = [v for _, v in counts]
    if len(values) < 30:
        return None
    recent = statistics.mean(values[-2:])
    base = statistics.median(values[-62:-2])
    return recent / base if base >= 3 else None


def surge_strength(ratio: float) -> float:
    return min(1.0, 0.3 + (ratio - SURGE_RATIO) * 0.2)


def days_to_fetch(have: set[str], today: date) -> list[str]:
    """Missing days (YYYYMMDD), newest first: yesterday, then a capped backfill."""
    wanted = [f"{today - timedelta(days=i):%Y%m%d}" for i in range(1, HISTORY_DAYS + 1)]
    missing = [d for d in wanted if d not in have]
    return missing[:BACKFILL_PER_RUN]


async def _doc_json(client: httpx.AsyncClient, params: dict, pause: float) -> dict:
    """DOC 2.0 API request; retries 429 and empty answers, at most MAX_FAILURES attempts."""
    problems: list[str] = []
    for attempt in range(MAX_FAILURES):
        if attempt:
            await asyncio.sleep(pause * 2)
        try:
            response = await client.get(API, params=params)
            if response.status_code == 429:
                problems.append("429 Too Many Requests")
                continue
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            problems.append(f"{type(exc).__name__}")
            continue
        except ValueError:
            problems.append("not JSON")
            continue
        if not payload:
            problems.append("empty {}")
            continue
        return payload
    raise EmptyResponse(f"no data after {MAX_FAILURES} attempts: {', '.join(problems)}")


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


async def _stored_days(db: aiosqlite.Connection) -> set[str]:
    async with db.execute(
        "SELECT DISTINCT period FROM series WHERE source = 'gdelt' AND key = ?", (SERIES_KEY,)
    ) as cur:
        return {r[0] for r in await cur.fetchall()}


async def _series(db: aiosqlite.Connection, country: str) -> list[tuple[str, float]]:
    async with db.execute(
        "SELECT period, value FROM series WHERE source = 'gdelt' AND country = ? AND key = ? "
        "ORDER BY period DESC LIMIT ?",
        (country, SERIES_KEY, HISTORY_DAYS),
    ) as cur:
        return [(r[0], r[1]) for r in reversed(await cur.fetchall())]


async def collect_events(
    db: aiosqlite.Connection, client: httpx.AsyncClient, result: RunResult, today: date,
    pause: float = FILE_PAUSE_SECONDS,
) -> None:  # fmt: skip
    """Fetch missing daily event files into `series`; stop after MAX_FAILURES in a row."""
    days = days_to_fetch(await _stored_days(db), today)
    streak = 0
    for i, day in enumerate(days):
        if i:
            await asyncio.sleep(pause)
        try:
            response = await client.get(EVENTS.format(day=day))
            if response.status_code == 404 and i == 0:
                # Yesterday's file is published around 07:00 UTC; not a broken source.
                result.errors.append(f"events {day}: not published yet")
                continue
            response.raise_for_status()
            totals = parse_events(response.content)
        except (httpx.HTTPError, ValueError, zipfile.BadZipFile) as exc:
            result.failed += 1
            result.errors.append(f"events {day}: {type(exc).__name__}: {exc}")
            streak += 1
            if streak >= MAX_FAILURES:
                result.errors.append(f"events: stopped after {MAX_FAILURES} failures in a row")
                return
            continue
        streak = 0
        result.fetched += 1
        await db.executemany(
            "INSERT OR REPLACE INTO series (source, country, key, period, value) "
            "VALUES ('gdelt', ?, ?, ?, ?)",
            [(code, SERIES_KEY, day, value) for code, value in totals.items()],
        )
        await db.commit()


async def surge_signals(db: aiosqlite.Connection, now: datetime) -> int:
    count = 0
    fresh = f"{now.date() - timedelta(days=3):%Y%m%d}"
    for code in COUNTRIES:
        counts = await _series(db, code)
        if not counts or counts[-1][0] < fresh:
            continue  # no recent day: a ratio would describe the past
        ratio = surge_ratio(counts)
        if ratio is None or ratio < SURGE_RATIO:
            continue
        signal = Signal(
            country=code, block="media", kind="media:gdelt_surge", strength=surge_strength(ratio),
            publisher="gdelt", observed_at=now, tier=3,
            confirmed=await _news_confirmed(db, code, now), reason="military_threat",
            note=f"military-related coverage x{ratio:.1f} vs usual",
            note_uk=f"публікацій на військову тему в {ratio:.1f} раза більше за звичне",
        )  # fmt: skip
        await storage.upsert_signal(db, signal, f"gdelt:{now:%Y-%m-%d}")
        count += 1
    return count


async def collect_gdelt(
    db: aiosqlite.Connection,
    client: httpx.AsyncClient,
    settings: Settings,
    pause: float = PAUSE_SECONDS,
    file_pause: float = FILE_PAUSE_SECONDS,
) -> RunResult:
    now = datetime.now(UTC)
    result = RunResult(source="gdelt")
    if await _recently_ran(db, now):
        result.fetched = 1  # nothing to do today; not a failure
        return result
    run_id = await storage.start_run(db, "gdelt")
    await collect_events(db, client, result, now.date(), file_pause)
    result.changed += await surge_signals(db, now)
    try:
        payload = await _doc_json(client, {
            "query": f"{MFA_QUERY} sourcelang:russian", "mode": "artlist",
            "maxrecords": "75", "timespan": "7days", "format": "json",
        }, pause)  # fmt: skip
        result.changed += await mfa_signals(db, payload.get("articles") or [], now)
    except (httpx.HTTPError, ValueError) as exc:
        result.failed += 1
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
