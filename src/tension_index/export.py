"""Export the public data file for the dashboard (read-only public API: scores.json)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite

from tension_index import __version__, explain, war_status
from tension_index.countries import COUNTRIES

HISTORY_DAYS = 90


async def build(db: aiosqlite.Connection, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=HISTORY_DAYS)).isoformat()
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
            "history": sorted(daily.items()),
        }
    return {"generated_at": now.isoformat(timespec="seconds"), "version": __version__,
            "countries": countries}  # fmt: skip


def write(data: dict, out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data
