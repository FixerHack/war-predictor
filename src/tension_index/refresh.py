"""How often each country is re-checked: the higher its latest score, the more often.

The collect timer fires every hour; a cycle fetches advisories only for countries whose
interval (config/weights.yaml, `refresh`) has passed. Users never trigger fetches: the bot
and the map read the stored result, so any number of people asking about one country cost
no extra requests.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import aiosqlite

from tension_index import storage
from tension_index.countries import COUNTRIES
from tension_index.scoring import load_config


def interval_hours(score: float | None, cfg: dict | None = None) -> float:
    """Re-check interval for a country with this published score (None = calmest step)."""
    cfg = cfg or load_config()
    steps = cfg["refresh"]["steps"]
    value = score if score is not None else 0.0
    return next((s["hours"] for s in steps if value < s["below"]), steps[-1]["hours"])


def longest_interval_hours(cfg: dict | None = None) -> float:
    cfg = cfg or load_config()
    return max(s["hours"] for s in cfg["refresh"]["steps"])


async def due_countries(
    db: aiosqlite.Connection, now: datetime, cfg: dict | None = None
) -> list[str]:
    """Countries whose interval has passed since their last check (never checked = due)."""
    cfg = cfg or load_config()
    slack = timedelta(minutes=cfg["refresh"]["slack_minutes"])  # timer jitter
    checked = await storage.country_checks(db)
    due = []
    for code in COUNTRIES:
        last = checked.get(code)
        if last is None:
            due.append(code)
            continue
        row = await storage.latest_score(db, code)
        hours = interval_hours(row["score"] if row else None, cfg)
        if now - datetime.fromisoformat(last) >= timedelta(hours=hours) - slack:
            due.append(code)
    return due
