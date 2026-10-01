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
    return {
        "publisher": {lang: explain.publisher_label(publisher, lang) for lang in ("uk", "en")},
        "kind": {lang: explain.kind_label(kind, lang) for lang in ("uk", "en")},
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
    return {"generated_at": now.isoformat(timespec="seconds"), "version": __version__,
            "countries": countries, "context": context}  # fmt: skip


def write(data: dict, out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data
