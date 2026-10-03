"""Blocks C/D/E from news headlines (tier 1-2 feeds in config/feeds.yaml).

Only headlines and links are stored. Each headline gets one category (keyword rules, refined
by Claude when a key is set) and the countries it names. A category becomes a signal only
when at least `min_feeds` different feeds report it for the country within the window.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import aiosqlite
import httpx
import yaml

from tension_index import storage
from tension_index.classifier import ClaudeClassifier, classify_headlines
from tension_index.collector import RunResult
from tension_index.config import Settings
from tension_index.extra.lexicon import countries_in
from tension_index.scoring import Signal

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "feeds.yaml"

RULES: list[tuple[str, re.Pattern]] = [
    (cat, re.compile(p, re.I))
    for cat, p in (
        ("armed_attack", r"\b(missile|drone|rocket) (strike|attack)s? (on|hits?|kill)|"
         r"(russian|belarusian) (troops|forces) (cross|enter|invade)|shelling of|invasion of|attacked by russia"),
        ("mobilisation", r"(declares?|orders?|announces?) (a |general |partial )?mobili[sz]ation|"
         r"mobili[sz]ation (declared|ordered|announced)"),
        ("domestic_emergency", r"state of emergency|martial law|air.raid|bomb shelters?|"
         r"evacuation (order|plan)|clos(es|ed|ing) (its |the )?borders?|(border )?closure of (its |the )?borders?|"
         r"border closure|emergency (decree|powers)"),
        ("aggressor_advisory", r"(russia|belarus)\w*\W+(foreign ministry|mfa|embassy)\b.*"
         r"(advis|urg|warn|recommend)\w*.*(citizens|nationals)"),
        ("hybrid_attack", r"sabotage|gps (jamming|interference)|airspace violation|violat\w+ (its |the )?airspace|"
         r"drones? (over|spotted|sighted|incursion)|cyber.?attack|undersea cable"),
        ("military_threat", r"troops? (mass|build|near|along|gather)|military build.?up|snap (drills?|exercises?)|"
         r"threatens? (to )?(attack|invade|strike)|nuclear (threat|drills?)"),
        ("escalation_news", r"escalat|tensions? (rise|mount|soar|spike)|war fears|brink of war"),
    )
]  # fmt: skip

# Preparedness news is not the measure itself: a "mobilisation exercise", a "siren test" or a
# plan to close a border must not count as mobilisation or an emergency (the mobilisation
# floor is 9). Applied to rule and Claude labels alike, also to headlines already stored.
PREPAREDNESS = re.compile(
    r"\b(drills?|exercises?|training|tests?|testing|rehears\w*|simulat\w*|plans?|planning|"
    r"prepar\w*|readiness)\b",
    re.I,
)
PREPAREDNESS_CATEGORIES = {"mobilisation", "domestic_emergency"}


def effective_category(title: str, category: str) -> str:
    if category in PREPAREDNESS_CATEGORIES and PREPAREDNESS.search(title):
        return "none"
    return category


@lru_cache
def load_config(path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def categorize(title: str) -> str:
    category = next((cat for cat, pattern in RULES if pattern.search(title)), "none")
    return effective_category(title, category)


def parse_feed(content: bytes) -> list[tuple[str, str, str | None]]:
    """[(title, link, published)] from RSS 2.0, RSS 1.0 (RDF) or Atom."""
    root = ET.fromstring(content)
    out = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        fields = {c.tag.rsplit("}", 1)[-1]: c for c in el}
        title = (fields["title"].text or "").strip() if "title" in fields else ""
        link_el = fields.get("link")
        link = ""
        if link_el is not None:
            link = (link_el.text or link_el.get("href") or "").strip()
        # (Element truthiness is "has children", so no `or` chains here.)
        date_el = next((fields[k] for k in ("pubDate", "updated", "date") if k in fields), None)
        date = date_el.text.strip() if date_el is not None and date_el.text else None
        if title and link:
            out.append((" ".join(title.split()), link, date))
    return out


async def collect_news(
    db: aiosqlite.Connection, client: httpx.AsyncClient, settings: Settings
) -> RunResult:
    from tension_index.pipeline import parse_when

    cfg = load_config()
    result = RunResult(source="news")
    run_id = await storage.start_run(db, "news")
    now = datetime.now(UTC)
    for feed in cfg["feeds"]:
        try:
            response = await client.get(feed["url"])
            response.raise_for_status()
            items = parse_feed(response.content)
        except (httpx.HTTPError, ET.ParseError) as exc:
            result.failed += 1
            result.errors.append(f"{feed['name']}: {type(exc).__name__}: {exc}")
            continue
        result.fetched += 1
        for title, link, date in items:
            codes = countries_in(title)
            if not codes:
                continue
            published = parse_when(date) or now
            cur = await db.execute(
                "INSERT OR IGNORE INTO news_items (url, feed, tier, title, published, countries, "
                "seen_at, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (link, feed["name"], feed["tier"], title, published.isoformat(), ",".join(codes),
                 now.isoformat(), categorize(title)),
            )  # fmt: skip
            result.changed += cur.rowcount
    await db.commit()

    from tension_index.pipeline import make_classifier

    claude = make_classifier(settings)
    if claude is not None:
        await refine_with_claude(db, claude)
    await db.execute("UPDATE news_items SET classified = 1 WHERE classified = 0")
    await derive_news_signals(db, now)
    await storage.finish(db, result, run_id)
    return result


async def refine_with_claude(db: aiosqlite.Connection, claude: ClaudeClassifier) -> None:
    async with db.execute(
        "SELECT url, title FROM news_items WHERE classified = 0 ORDER BY seen_at LIMIT 150"
    ) as cur:
        rows = await cur.fetchall()
    labels = await classify_headlines(claude, [r["title"] for r in rows])
    if labels is None:
        return
    for i, row in enumerate(rows):
        category, severity = labels.get(i, ("none", 0.0))
        category = effective_category(row["title"], category)
        await db.execute(
            "UPDATE news_items SET category = ?, severity = ? WHERE url = ?",
            (category, severity, row["url"]),
        )
    await db.commit()


async def derive_news_signals(db: aiosqlite.Connection, now: datetime) -> int:
    cfg = load_config()
    window = timedelta(hours=cfg["confirmation"]["window_hours"])
    since = (now - window).isoformat()
    async with db.execute(
        "SELECT feed, tier, title, published, countries, category, severity FROM news_items "
        "WHERE category != 'none' AND published >= ? ORDER BY published",
        (since,),
    ) as cur:
        rows = await cur.fetchall()
    groups: dict[tuple[str, str], list] = {}
    for row in rows:
        category = effective_category(row["title"], row["category"])
        if category == "none":
            continue
        for code in row["countries"].split(","):
            groups.setdefault((code, category), []).append(row)
    count = 0
    current: set[tuple[str, str, str]] = set()  # (ref, kind, country) derived in this window
    for (code, category), items in groups.items():
        spec = cfg["categories"][category]
        feeds = {r["feed"] for r in items}
        confirmed = len(feeds) >= cfg["confirmation"]["min_feeds"]
        latest = max(items, key=lambda r: r["published"])
        strength = spec["strength"] * max(r["severity"] for r in items)
        signal = Signal(
            country=code, block=spec["block"], kind=spec["kind"], strength=strength,
            publisher="news", observed_at=datetime.fromisoformat(latest["published"]),
            # Unconfirmed = tier 3: ignored by the score until a second feed reports it.
            tier=min(r["tier"] for r in items) if confirmed else 3, confirmed=confirmed,
            reason="armed_conflict" if category == "armed_attack" else "military_threat",
            note=f"{latest['title']} ({len(feeds)} feeds)",
        )  # fmt: skip
        day = latest["published"][:10]
        await storage.upsert_signal(db, signal, f"news:{category}:{day}")
        current.add((f"news:{category}:{day}", signal.kind, code))
        count += 1
    # Within the window the groups above are the whole truth: switch off signals of headlines
    # that no longer qualify (e.g. relabelled as a drill). Older days keep decaying as events.
    async with db.execute(
        "SELECT id, ref, kind, country FROM signals WHERE publisher = 'news' AND active = 1 "
        "AND substr(ref, -10) >= ?",
        (since[:10],),
    ) as cur:
        for row in await cur.fetchall():
            if (row["ref"], row["kind"], row["country"]) not in current:
                await db.execute("UPDATE signals SET active = 0 WHERE id = ?", (row["id"],))
    await db.commit()
    return count
