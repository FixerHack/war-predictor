"""Stage S5: load past versions of advisory pages from the Wayback Machine.

CDX API lists captures; each capture is fetched raw (`id_` suffix, no Wayback toolbar),
reduced to text and stored as a snapshot in a separate history database with the capture
time. Levels are read from the page wording (archived pages are HTML, not the live APIs).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import aiosqlite
import httpx
import yaml

from tension_index import storage
from tension_index.diff import changed_fragment, normalize
from tension_index.sources.au import overall_level as au_level
from tension_index.sources.base import html_to_text, main_content

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "episodes.yaml"
CDX = "https://web.archive.org/cdx/search/cdx"
RAW = "https://web.archive.org/web/{ts}id_/{url}"
DENSE_DAYS = 45  # daily captures in the weeks before the event, sparser before
SPARSE_STEP = 5
PAUSE_SECONDS = 1.0
# The Wayback Machine is slow and often busy: long timeouts, a few retries with backoff.
WAYBACK_TIMEOUT = httpx.Timeout(120.0, connect=30.0)
RETRIES = 4
RETRY_STATUS = {429, 500, 502, 503, 504}


async def wayback_get(
    client: httpx.AsyncClient, url: str, params: dict | None = None, backoff: float = 5.0
) -> httpx.Response:
    """GET with retries on timeouts, connection errors and 429/5xx."""
    for attempt in range(1, RETRIES + 1):
        try:
            response = await client.get(url, params=params, timeout=WAYBACK_TIMEOUT)
            if response.status_code not in RETRY_STATUS or attempt == RETRIES:
                response.raise_for_status()
                return response
            problem = f"HTTP {response.status_code}"
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == RETRIES:
                raise
            problem = type(exc).__name__
        log.info("wayback: %s, retry %d/%d", problem, attempt, RETRIES - 1)
        await asyncio.sleep(backoff * 2 ** (attempt - 1))
    raise AssertionError("unreachable")


@dataclass(slots=True)
class Episode:
    id: str
    country: str
    start: date
    end: date
    event: date | None
    urls: dict[str, str]
    expect: dict


@lru_cache
def load_episodes(path: Path = CONFIG_PATH) -> dict[str, Episode]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))["episodes"]
    return {
        key: Episode(key, e["country"], e["from"], e["to"], e.get("event"), e["urls"],
                     e.get("expect") or {})
        for key, e in data.items()
    }  # fmt: skip


# --- Levels from archived page wording ------------------------------------------------------


def _earliest(text: str, phrases: list[tuple[str, str]]) -> str | None:
    """The level whose phrase appears first (the overall level leads the page)."""
    low = text.lower()
    # Ties (one phrase is a prefix of another) go to the longer, more specific phrase.
    hits = [(low.find(p), -len(p), level) for level, p in phrases if p in low]
    return min(hits)[2] if hits else None


def level_from_page(publisher: str, text: str) -> str | None:
    if publisher == "us":
        m = re.search(r"Level\s*([1-4])\s*:", text)
        return m.group(1) if m else None
    if publisher == "gov_uk":
        return _earliest(text, [
            ("avoid_all_travel_to_whole_country", "against all travel to the whole"),
            ("avoid_all_but_essential_travel_to_whole_country", "against all but essential travel to the whole"),
            ("avoid_all_travel_to_parts", "against all travel to"),
            ("avoid_all_but_essential_travel_to_parts", "against all but essential travel to"),
        ]) or "none"  # fmt: skip
    if publisher == "ca":
        return _earliest(text, [
            ("avoid_all", "avoid all travel"),
            ("avoid_non_essential", "avoid non-essential travel"),
            ("high_caution", "exercise a high degree of caution"),
            ("normal", "take normal security precautions"),
        ])  # fmt: skip
    if publisher == "au":
        return au_level(text)
    if publisher == "de":
        low = text.lower()
        if "teilreisewarnung" in low:
            return "partial_warning"
        if "reisewarnung" in low and "keine reisewarnung" not in low:
            return "travel_warning"
        return "none"
    return None


# --- Wayback --------------------------------------------------------------------------------


def pick_captures(rows: list[list[str]], episode: Episode) -> list[tuple[str, str]]:
    """[(timestamp, original_url)]: one capture per day close to the event, sparser before."""
    dense_from = (episode.event or episode.end) - timedelta(days=DENSE_DAYS)
    picked: list[tuple[str, str]] = []
    last_day: date | None = None
    for ts, original in rows:
        day = datetime.strptime(ts[:8], "%Y%m%d").date()
        step = 1 if day >= dense_from else SPARSE_STEP
        if last_day is None or (day - last_day).days >= step:
            picked.append((ts, original))
            last_day = day
    return picked


async def list_captures(client: httpx.AsyncClient, url: str, episode: Episode) -> list[list[str]]:
    response = await wayback_get(client, CDX, params={
        "url": url, "from": episode.start.strftime("%Y%m%d"), "to": episode.end.strftime("%Y%m%d"),
        "output": "json", "filter": "statuscode:200", "collapse": "timestamp:8",
        "fl": "timestamp,original",
    })  # fmt: skip
    rows = response.json() if response.text.strip() else []
    return [r for r in rows[1:] if len(r) == 2]  # first row is the header


async def drop_duplicates(db: aiosqlite.Connection) -> int:
    """Remove versions loaded twice (same publisher, country, time and text) with the changes
    and classifications that point at them. Older databases got them from repeated loads."""
    async with db.execute(
        "SELECT id FROM snapshots s WHERE EXISTS (SELECT 1 FROM snapshots o WHERE "
        "o.source = s.source AND o.country = s.country AND o.fetched_at = s.fetched_at "
        "AND o.content_hash = s.content_hash AND o.id < s.id)"
    ) as cur:
        dupes = [r[0] for r in await cur.fetchall()]
    if not dupes:
        return 0
    marks = ",".join("?" * len(dupes))
    async with db.execute(
        f"SELECT id FROM changes WHERE new_snapshot IN ({marks}) OR prev_snapshot IN ({marks})",
        dupes * 2,
    ) as cur:
        changes = [r[0] for r in await cur.fetchall()]
    for ref_type, ids in (("snapshot", dupes), ("change", changes)):
        if ids:
            await db.execute(
                f"DELETE FROM classifications WHERE ref_type = ? AND ref_id IN "
                f"({','.join('?' * len(ids))})",
                [ref_type, *ids],
            )
    if changes:
        await db.execute(
            f"DELETE FROM changes WHERE id IN ({','.join('?' * len(changes))})", changes
        )
    await db.execute(f"DELETE FROM snapshots WHERE id IN ({marks})", dupes)
    await db.commit()
    log.info("removed %d duplicate versions and %d changes", len(dupes), len(changes))
    return len(dupes)


async def _loaded(db: aiosqlite.Connection, publisher: str, episode: Episode) -> int:
    async with db.execute(
        "SELECT COUNT(*) FROM snapshots WHERE source = ? AND country = ? "
        "AND fetched_at >= ? AND fetched_at <= ?",
        (publisher, episode.country, episode.start.isoformat(),
         (episode.end + timedelta(days=1)).isoformat()),
    ) as cur:  # fmt: skip
        return (await cur.fetchone())[0]


async def _forget(db: aiosqlite.Connection, publisher: str, episode: Episode) -> None:
    """Drop a publisher's archived versions for the episode (before a refresh)."""
    window = (publisher, episode.country, episode.start.isoformat(),
              (episode.end + timedelta(days=1)).isoformat())  # fmt: skip
    where = "source = ? AND country = ? AND fetched_at >= ? AND fetched_at <= ?"
    async with db.execute(f"SELECT id FROM snapshots WHERE {where}", window) as cur:
        ids = [r[0] for r in await cur.fetchall()]
    marks = ",".join("?" * len(ids))
    await db.execute(
        f"DELETE FROM classifications WHERE (ref_type = 'snapshot' AND ref_id IN ({marks})) "
        f"OR (ref_type = 'change' AND ref_id IN (SELECT id FROM changes WHERE new_snapshot "
        f"IN ({marks})))",
        ids * 2,
    )
    await db.execute(f"DELETE FROM changes WHERE new_snapshot IN ({marks})", ids)
    await db.execute(f"DELETE FROM snapshots WHERE id IN ({marks})", ids)
    await db.commit()


async def load_episode(
    db: aiosqlite.Connection,
    client: httpx.AsyncClient,
    episode: Episode,
    pause: float = PAUSE_SECONDS,
    refresh: bool = False,
) -> dict[str, int]:
    """Store archived versions (only when the text changed) and the changes between them.
    A publisher already loaded for this episode is skipped unless `refresh`."""
    await storage.migrate(db)
    await drop_duplicates(db)
    stats: dict[str, int] = {}
    for publisher, url in episode.urls.items():
        existing = await _loaded(db, publisher, episode)
        if existing and not refresh:
            log.info("%s: already loaded (%d versions), skipped", publisher, existing)
            stats[publisher] = existing
            continue
        if existing:
            await _forget(db, publisher, episode)
        try:
            captures = pick_captures(await list_captures(client, url, episode), episode)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("%s: CDX failed: %s %s", publisher, type(exc).__name__, exc)
            stats[publisher] = -1
            continue
        log.info("%s: %d captures to fetch", publisher, len(captures))
        stored = 0
        previous: aiosqlite.Row | None = None
        for ts, original in captures:
            try:
                response = await wayback_get(client, RAW.format(ts=ts, url=original))
            except httpx.HTTPError as exc:
                log.warning("%s %s: %s %s", publisher, ts, type(exc).__name__, exc)
                continue
            text = normalize(html_to_text(main_content(response.text)))
            when = datetime.strptime(ts, "%Y%m%d%H%M%S").isoformat() + "+00:00"
            level = level_from_page(publisher, text)
            if previous is not None and previous["text"] == text and previous["level"] == level:
                await asyncio.sleep(pause)
                continue
            sid = await storage.insert_snapshot(
                db, source=publisher, country=episode.country, url=original, text=text,
                level=level, fetched_at=when, source_updated=when,
            )  # fmt: skip
            if previous is not None:
                diff = changed_fragment(previous["text"], text)
                if previous["level"] != level:
                    diff = f"LEVEL: {previous['level']} -> {level}\n{diff}"
                await storage.insert_change(
                    db, source=publisher, country=episode.country, prev_snapshot=previous["id"],
                    new_snapshot=sid, diff=diff, detected_at=when,
                )  # fmt: skip
            await db.commit()
            async with db.execute("SELECT * FROM snapshots WHERE id = ?", (sid,)) as cur:
                previous = await cur.fetchone()
            stored += 1
            await asyncio.sleep(pause)
        stats[publisher] = stored
        log.info("%s: %d versions stored", publisher, stored)
    return stats
