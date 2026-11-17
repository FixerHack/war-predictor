"""Institutional stability: what national media report about a country's own government,
president, army, police and security services.

Headlines of 1-3 national outlets per country (config/national_feeds.yaml) are read in their
own language and labelled by Claude, one call per country: decisions favouring the aggressor,
removal or arrest of security chiefs, armed men without insignia or attacks by people in
uniform, power grabs, the leader's disappearance or unexplained moves, violent unrest against
the authorities, polls of falling trust. They make an own 0-10 scale shown in the country panel,
and the strongest kinds also add a domestic signal to the tension score. Like everything here
it describes signals, not a forecast. Without a Claude provider nothing is labelled (keyword
rules cannot read 30 languages reliably), and the scale stays empty.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import aiosqlite
import httpx
import yaml

from tension_index import storage
from tension_index.collector import RunResult
from tension_index.config import Settings
from tension_index.countries import COUNTRIES
from tension_index.extra.news import parse_feed
from tension_index.scoring import Signal, load_config

log = logging.getLogger(__name__)

FEEDS_PATH = Path(__file__).resolve().parents[3] / "config" / "national_feeds.yaml"
CATEGORIES = (
    "pro_aggressor_policy", "security_purge", "armed_unmarked", "power_grab",
    "leader_absence", "violent_unrest", "trust_drop", "none",
)  # fmt: skip
MAX_PER_CALL = 60
SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "severity": {"type": "number"},
                    "title_uk": {"type": "string"},
                    "title_en": {"type": "string"},
                },
                "required": ["i", "category", "severity", "title_uk", "title_en"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}
PROMPT = """You read news headlines from national media of {country} (in their own language) \
for an indicator of institutional stability. Label each numbered headline.

Categories - only about {country}'s OWN government, head of state, parliament, army, police or \
security services; news about other countries, sport, culture, economy or crime is none:
- pro_aggressor_policy: {country}'s authorities take or announce decisions that favour Russia \
or Belarus against Ukraine or the EU/NATO line: veto or block sanctions, stop aid to Ukraine, \
deals with or visits to the aggressor's leadership, leaving a common position. Strengthening \
defence, NATO or allied (e.g. US) presence is the opposite: none. Decisions of other \
governments about {country} are none.
- security_purge: sudden dismissal, resignation or arrest of the commanders of the army, \
police, intelligence or border guard, or of the defence or interior minister. Managers of \
companies, power plants or agencies and staff of other ministries are none.
- armed_unmarked: armed people in uniform without insignia, attacks by people in uniform, \
paramilitary groups appearing, security forces used against civilians or institutions.
- power_grab: coup attempt, irregular emergency rule, parliament dissolved or elections \
cancelled outside the constitution.
- leader_absence: the head of state or government disappears from public view without \
explanation, makes unexplained or secret trips, flees the country.
- violent_unrest: violent mass protests, riots or clashes with police against the authorities \
(peaceful protests and strikes are none).
- trust_drop: a poll showing low or falling trust in the police, army or government.
- none: everything else.

severity 0..1: 1 = official and confirmed; 0.5 = reported, alleged or partial; 0.2 = talk, \
plans or opposition claims. Label by what the headline states, not by alarming words.
For every headline that is not none, give title_uk and title_en: the headline translated \
into Ukrainian and English, neutral and short. For none, leave both empty."""


@lru_cache
def load_feeds(path: Path = FEEDS_PATH) -> dict[str, list[dict]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["feeds"]


async def fetch_headlines(
    db: aiosqlite.Connection, client: httpx.AsyncClient, countries: list[str], result: RunResult
) -> None:
    from tension_index.pipeline import parse_when

    now = datetime.now(UTC)
    feeds = load_feeds()
    for code in countries:
        for feed in feeds.get(code, []):
            try:
                response = await client.get(feed["url"])
                response.raise_for_status()
                items = parse_feed(response.content)
            except (httpx.HTTPError, ET.ParseError) as exc:
                result.failed += 1
                result.errors.append(f"{code}/{feed['name']}: {type(exc).__name__}: {exc}")
                continue
            result.fetched += 1
            for title, link, date in items:
                published = parse_when(date) or now
                cur = await db.execute(
                    "INSERT OR IGNORE INTO national_items (url, country, feed, tier, title, "
                    "published, seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (link, code, feed["name"], feed["tier"], title, published.isoformat(),
                     now.isoformat()),
                )  # fmt: skip
                result.changed += cur.rowcount
    await db.commit()


async def label_headlines(db: aiosqlite.Connection, claude, countries: list[str]) -> int:
    """Label new headlines with Claude, one call per country (up to MAX_PER_CALL each)."""
    labelled = 0
    for code in countries:
        if claude is None or not claude.available:
            break
        async with db.execute(
            "SELECT url, title FROM national_items WHERE country = ? AND classified = 0 "
            "ORDER BY published DESC, rowid LIMIT ?",
            (code, MAX_PER_CALL),
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            continue
        numbered = "\n".join(f"{i}. {r['title']}" for i, r in enumerate(rows))
        system = PROMPT.format(country=COUNTRIES[code].name)
        text, problem = await claude._call(system, numbered, SCHEMA, 8192)
        if text is None:
            log.warning("stability %s: not labelled (%s)", code, problem)
            continue
        try:
            items = {int(x["i"]): x for x in json.loads(text)["items"]}
        except (ValueError, KeyError, TypeError):
            log.warning("stability %s: unparseable labels", code)
            continue
        for i, row in enumerate(rows):
            x = items.get(i, {})
            category = x.get("category") if x.get("category") in CATEGORIES else "none"
            severity = max(0.0, min(1.0, float(x.get("severity") or 0)))
            await db.execute(
                "UPDATE national_items SET classified = 1, category = ?, severity = ?, "
                "title_uk = ?, title_en = ? WHERE url = ?",
                (category, severity if category != "none" else 0.0,
                 x.get("title_uk", "") if category != "none" else "",
                 x.get("title_en", "") if category != "none" else "", row["url"]),
            )  # fmt: skip
            labelled += 1
        await db.commit()
    # Older unlabelled headlines are not worth a call any more: they would only add history.
    stale = (
        datetime.now(UTC) - timedelta(days=load_config()["stability"]["window_days"])
    ).isoformat()
    await db.execute(
        "UPDATE national_items SET classified = 1 WHERE classified = 0 AND published < ?", (stale,)
    )
    await db.commit()
    return labelled


async def events(db: aiosqlite.Connection, code: str, since: str) -> list[aiosqlite.Row]:
    async with db.execute(
        "SELECT url, feed, tier, title, published, category, severity, title_uk, title_en "
        "FROM national_items WHERE country = ? AND category != 'none' AND published >= ? "
        "ORDER BY published DESC",
        (code, since),
    ) as cur:
        return list(await cur.fetchall())


def confirmed(row, rows) -> bool:
    """A public broadcaster or agency counts on its own; a private outlet needs a second outlet
    reporting the same kind within two days."""
    if row["tier"] <= 2:
        return True
    when = datetime.fromisoformat(row["published"])
    return any(
        r["feed"] != row["feed"] and r["category"] == row["category"]
        and abs(datetime.fromisoformat(r["published"]) - when) <= timedelta(days=2)
        for r in rows
    )  # fmt: skip


async def stability_score(db: aiosqlite.Connection, code: str, now: datetime | None = None) -> dict:
    """{"score": 0-10, "events": [...]}: the institutional stability scale of one country.
    Higher = more signals of instability (not a forecast)."""
    cfg = load_config()["stability"]
    now = now or datetime.now(UTC)
    rows = await events(db, code, (now - timedelta(days=cfg["window_days"])).isoformat())
    # One event reported in several headlines counts once: the strongest per kind and day;
    # days of one kind add up as confirmations but never beyond that kind's weight.
    strongest: dict[tuple[str, str], float] = {}
    out = []
    for row in rows:
        weight = cfg["categories"][row["category"]]["weight"]
        age = max(0.0, (now - datetime.fromisoformat(row["published"])).total_seconds() / 86400)
        sure = confirmed(row, rows)
        value = weight * row["severity"] * 0.5 ** (age / cfg["half_life_days"])
        value *= 1.0 if sure else cfg["unconfirmed_factor"]
        key = (row["category"], row["published"][:10])
        strongest[key] = max(strongest.get(key, 0.0), value)
        out.append({
            "at": row["published"][:16], "category": row["category"], "feed": row["feed"],
            "severity": round(row["severity"], 2), "confirmed": sure, "value": round(value, 3),
            "text": {"orig": row["title"], "uk": row["title_uk"] or row["title_en"], "en": row["title_en"]},
        })  # fmt: skip
    per_kind: dict[str, float] = {}
    for (category, _), value in strongest.items():
        per_kind[category] = 1.0 - (1.0 - per_kind.get(category, 0.0)) * (1.0 - value)
    keep = 1.0
    for category, value in per_kind.items():
        keep *= 1.0 - min(value, cfg["categories"][category]["weight"])
    raw = 1.0 - keep
    score = round(10.0 * raw ** cfg["curve_gamma"], 1) if raw > 0 else 0.0
    return {"score": score, "events": out}


async def derive_signals(db: aiosqlite.Connection, countries: list[str], now: datetime) -> int:
    """The strongest kinds as domestic signals of the tension score (one per country, kind and
    day; strength = the category's `tension` x severity)."""
    cfg = load_config()["stability"]
    since = (now - timedelta(days=cfg["window_days"])).isoformat()
    count = 0
    for code in countries:
        rows = await events(db, code, since)
        best: dict[tuple[str, str], aiosqlite.Row] = {}
        for row in rows:
            if cfg["categories"][row["category"]]["tension"] <= 0:
                continue
            key = (row["category"], row["published"][:10])
            if key not in best or row["severity"] > best[key]["severity"]:
                best[key] = row
        for (category, day), row in best.items():
            sure = confirmed(row, rows)
            signal = Signal(
                country=code, block="domestic", kind=f"domestic:{category}",
                strength=cfg["categories"][category]["tension"] * row["severity"],
                publisher="national", observed_at=datetime.fromisoformat(row["published"]),
                tier=min(2, row["tier"]) if sure else 3, confirmed=sure,
                reason="civil_unrest" if category == "violent_unrest" else "military_threat",
                note=row["title_en"] or row["title"], note_uk=row["title_uk"],
            )  # fmt: skip
            await storage.upsert_signal(db, signal, f"national:{category}:{day}")
            count += 1
    await db.commit()
    return count


async def collect_stability(
    db: aiosqlite.Connection, client: httpx.AsyncClient, settings: Settings,
    countries: list[str] | None = None,
) -> RunResult:  # fmt: skip
    from tension_index.pipeline import make_classifier

    result = RunResult(source="national")
    run_id = await storage.start_run(db, "national")
    targets = [c for c in (countries or list(COUNTRIES)) if c in load_feeds()]
    await fetch_headlines(db, client, targets, result)
    await label_headlines(db, make_classifier(settings), targets)
    await derive_signals(db, targets, datetime.now(UTC))
    await storage.finish(db, result, run_id)
    return result
