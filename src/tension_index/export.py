"""Export the public data file for the dashboard (read-only public API: scores.json)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite

from tension_index import __version__, explain, war_status
from tension_index.countries import COUNTRIES
from tension_index.pipeline import active_signals

HISTORY_DAYS = 90
MAX_SIGNALS = 15


def _labels(publisher: str, kind: str) -> dict:
    # uk/en inline; the codes let the page use its translated labels for other languages.
    return {
        "publisher": {lang: explain.publisher_label(publisher, lang) for lang in ("uk", "en")},
        "kind": {lang: explain.kind_label(kind, lang) for lang in ("uk", "en")},
        "pcode": publisher,
        "kcode": kind,
    }


async def build(db: aiosqlite.Connection, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=HISTORY_DAYS)).isoformat()
    by_country: dict[str, list] = {}
    for sig in await active_signals(db, now):
        by_country.setdefault(sig.country, []).append(sig)
    countries = {}
    for code, c in COUNTRIES.items():
        async with db.execute(
            "SELECT computed_at, score, level, payload FROM scores WHERE country = ? "
            "AND computed_at >= ? ORDER BY id",
            (code, since),
        ) as cur:
            rows = await cur.fetchall()
        daily: dict[str, float | None] = {}
        for r in rows:  # last score of each day
            daily[r["computed_at"][:10]] = r["score"]
        latest = rows[-1] if rows else None
        payload = json.loads(latest["payload"]) if latest else {}
        war = war_status.get(code)
        published = latest is not None and latest["score"] is not None
        countries[code] = {
            "name": {"uk": c.name_uk, "en": c.name},
            "flag": c.flag,
            "region": c.region,
            "score": latest["score"] if latest else None,
            "level": latest["level"] if latest else None,
            "updated": latest["computed_at"] if latest else None,
            "reasons": {lang: explain.reasons(payload, lang) for lang in ("uk", "en")}
            if published
            else {"uk": [], "en": []},
            "flags": {
                lang: explain.flag_lines(payload.get("flags", []), lang) for lang in ("uk", "en")
            },
            "war": {"status": war.status, "note": {"uk": war.note_uk, "en": war.note_en}},
            # Full breakdown for the dashboard's detailed explanation.
            "raw": payload.get("raw"),
            "blocks": payload.get("blocks", {}),
            "floors": payload.get("floors", []),
            "flag_keys": payload.get("flags", []),
            "contributors": [
                {
                    "block": c["block"],
                    "value": round(c["value"], 3),
                    "note": c.get("note") or "",
                    "note_uk": c.get("note_uk") or "",
                }
                | _labels(c["publisher"], c["kind"])
                for c in payload.get("top", [])
            ],
            "signals": [
                {
                    "block": sig.block,
                    "strength": round(sig.strength, 3),
                    "state": sig.state,
                    "observed_at": sig.observed_at.isoformat(timespec="minutes"),
                    "reason": sig.reason,
                    "note": sig.note,
                    "note_uk": sig.note_uk,
                }
                | _labels(sig.publisher, sig.kind)
                for sig in sorted(by_country.get(code, []), key=lambda s: -s.strength)[:MAX_SIGNALS]
            ],
            "history": sorted(daily.items()),
            "stability": await _stability(db, code, now),
        }
    names = {"UA": ("Україна", "Ukraine"), "RU": ("Росія", "Russia"), "BY": ("Білорусь", "Belarus")}
    context = {
        code: {
            "name": {"uk": names.get(code, (code, code))[0], "en": names.get(code, (code, code))[1]},
            "flag": "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code),
            "status": e["status"], "role": e["role"],
            "note": {"uk": e.get("note_uk", ""), "en": e.get("note_en", "")},
        }
        for code, e in war_status.context().items()
    }  # fmt: skip
    # When the data was computed (the latest score), not when it was exported: the map says
    # "updated" and an unchanged export is not published again.
    computed = [c["updated"] for c in countries.values() if c["updated"]]
    generated = max(computed) if computed else now.isoformat(timespec="seconds")
    return {"generated_at": generated, "version": __version__,
            "countries": countries, "context": context}  # fmt: skip


STABILITY_EVENTS = 6


async def _stability(db: aiosqlite.Connection, code: str, now: datetime) -> dict:
    """The institutional stability scale for the panel: score and the strongest events."""
    from tension_index.extra.stability import stability_score

    result = await stability_score(db, code, now)
    top = sorted(result["events"], key=lambda e: -e["value"])[:STABILITY_EVENTS]
    return {"score": result["score"], "events": [_local_title(code, e) for e in top]}


def _local_title(code: str, event: dict) -> dict:
    """National headlines: shown as published in the country's own language."""
    from tension_index.languages import local_languages

    text = dict(event["text"])
    local = local_languages(code)
    if local:
        text[local[0]] = text["orig"]
    return {**event, "text": text}


CHRONICLE_EVENTS = 80
SCORE_MOVE = 0.5  # a day-to-day score change worth a line in the chronicle
QUIET_CHANGES = ("editorial", "none")


async def chronicle(db: aiosqlite.Connection, code: str, now: datetime | None = None) -> list[dict]:
    """What happened in a country over HISTORY_DAYS, newest first: government advice changes
    (with their summary), news/aviation/aggressor signals, and notable score moves. Each item
    says whether it counts in the score, so the page can explain quiet events too."""
    from tension_index.classifier import Classification

    now = now or datetime.now(UTC)
    since = (now - timedelta(days=HISTORY_DAYS)).isoformat()
    events: list[dict] = []

    async with db.execute(
        "SELECT c.id, c.source, c.detected_at, k.payload, s.active, s.strength FROM changes c "
        "JOIN classifications k ON k.ref_type = 'change' AND k.ref_id = c.id "
        "LEFT JOIN signals s ON s.ref = 'change:' || c.id "
        "WHERE c.country = ? AND c.detected_at >= ?",
        (code, since),
    ) as cur:
        for row in await cur.fetchall():
            cls = Classification.from_json(row["payload"])
            if cls.change_type in QUIET_CHANGES:
                continue
            events.append({
                "at": row["detected_at"][:16], "type": "advice", "change": cls.change_type,
                "reason": cls.reason, "counted": bool(row["active"]),
                "text": {"uk": cls.summary_uk or cls.summary_en, "en": cls.summary_en} | cls.summaries,
                "quote": cls.quote,
            } | _labels(row["source"], f"advisory_update:{cls.change_type}"))  # fmt: skip

    async with db.execute(
        "SELECT publisher, kind, observed_at, confirmed, active, note, note_uk FROM signals "
        "WHERE country = ? AND observed_at >= ? AND ref NOT LIKE 'change:%' "
        "AND ref NOT LIKE 'snapshot:%' AND ref NOT LIKE 'national:%'",  # those: type stability
        (code, since),
    ) as cur:
        for row in await cur.fetchall():
            events.append({
                "at": row["observed_at"][:16], "type": "signal",
                "counted": bool(row["active"] and row["confirmed"]),
                "confirmed": bool(row["confirmed"]),
                "text": {"uk": row["note_uk"] or row["note"], "en": row["note"]},
            } | _labels(row["publisher"], row["kind"]))  # fmt: skip

    from tension_index.extra.stability import confirmed
    from tension_index.extra.stability import events as stability_events

    rows = await stability_events(db, code, since)
    for row in rows:
        events.append(_local_title(code, {
            "at": row["published"][:16], "type": "stability", "category": row["category"],
            "counted": confirmed(row, rows), "feed": row["feed"],
            "text": {"orig": row["title"], "uk": row["title_uk"] or row["title_en"], "en": row["title_en"]},
        }))  # fmt: skip

    async with db.execute(
        "SELECT computed_at, score FROM scores WHERE country = ? AND computed_at >= ? "
        "AND score IS NOT NULL ORDER BY id",
        (code, since),
    ) as cur:
        daily: dict[str, tuple[str, float]] = {}
        for row in await cur.fetchall():
            daily[row["computed_at"][:10]] = (row["computed_at"][:16], row["score"])
    previous = None
    for at, score in daily.values():
        if previous is not None and abs(score - previous) >= SCORE_MOVE:
            events.append({"at": at, "type": "score", "from": previous, "to": score})
        previous = score

    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:CHRONICLE_EVENTS]


async def chronicles(db: aiosqlite.Connection, now: datetime | None = None) -> dict[str, list]:
    return {code: await chronicle(db, code, now) for code in COUNTRIES}


def write_chronicles(all_events: dict[str, list], out_dir: Path) -> int:
    """chronicle/<CODE>.json for every country, loaded by the page when a country is opened."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for code, events in all_events.items():
        (out_dir / f"{code}.json").write_text(
            json.dumps({"country": code, "events": events}, ensure_ascii=False), encoding="utf-8"
        )
    return len(all_events)


def write(data: dict, out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data
