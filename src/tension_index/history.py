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
from tension_index.sources.au import level_from_text as au_level
from tension_index.sources.base import html_to_text, main_content

log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "episodes.yaml"
CDX = "https://web.archive.org/cdx/search/cdx"
RAW = "https://web.archive.org/web/{ts}id_/{url}"
DENSE_DAYS = 45  # daily captures in the weeks before the event, sparser before
SPARSE_STEP = 5
PAUSE_SECONDS = 1.0


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
    response = await client.get(CDX, params={
        "url": url, "from": episode.start.strftime("%Y%m%d"), "to": episode.end.strftime("%Y%m%d"),
        "output": "json", "filter": "statuscode:200", "collapse": "timestamp:8",
        "fl": "timestamp,original",
    })  # fmt: skip
    response.raise_for_status()
    rows = response.json() if response.text.strip() else []
    return [r for r in rows[1:] if len(r) == 2]  # first row is the header


async def load_episode(
    db: aiosqlite.Connection,
    client: httpx.AsyncClient,
    episode: Episode,
    pause: float = PAUSE_SECONDS,
) -> dict[str, int]:
    """Store archived versions (only when the text changed) and the changes between them."""
    await storage.migrate(db)
    stats: dict[str, int] = {}
    for publisher, url in episode.urls.items():
        try:
            captures = pick_captures(await list_captures(client, url, episode), episode)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("%s: CDX failed: %s", publisher, exc)
            stats[publisher] = -1
            continue
        stored = 0
        previous: aiosqlite.Row | None = None
        for ts, original in captures:
            try:
                response = await client.get(RAW.format(ts=ts, url=original))
                response.raise_for_status()
            except httpx.HTTPError as exc:
                log.warning("%s %s: %s", publisher, ts, exc)
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
    return stats
