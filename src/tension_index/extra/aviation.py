"""Block B, aviation.

- EASA Conflict Zone Information Bulletins: the EU aviation regulator's warnings about
  airspace affected by conflict. Parsed from the public list page (no API).
- OpenSky Network: airborne aircraft per country from one Europe-wide anonymous query
  (4 of 400 free daily credits), compared with the country's own count at the same hour of
  the week. A sharp drop means airlines avoid the airspace.
"""

from __future__ import annotations

import re
import statistics
from datetime import UTC, datetime, timedelta

import aiosqlite
import httpx

from tension_index import storage
from tension_index.collector import RunResult
from tension_index.config import Settings
from tension_index.countries import COUNTRIES
from tension_index.scoring import Signal
from tension_index.sources.base import html_to_text, main_content

CZIB_PAGE = "https://www.easa.europa.eu/en/domains/air-operations/czibs"
OPENSKY = "https://opensky-network.org/api/states/all"
EUROPE = {"lamin": 34.0, "lomin": -25.0, "lamax": 72.0, "lomax": 35.0}

# Approximate bounding boxes (lat_min, lat_max, lon_min, lon_max). Overlaps with neighbours
# are fine: the signal is a drop relative to the same box's own history.
BOXES: dict[str, tuple[float, float, float, float]] = {
    "AT": (46.4, 49.0, 9.5, 17.2), "BE": (49.5, 51.5, 2.5, 6.4), "BG": (41.2, 44.2, 22.4, 28.6),
    "HR": (42.4, 46.6, 13.5, 19.5), "CY": (34.6, 35.7, 32.3, 34.6), "CZ": (48.5, 51.1, 12.1, 18.9),
    "DK": (54.5, 57.8, 8.0, 12.7), "EE": (57.5, 59.7, 21.8, 28.2), "FI": (59.8, 70.1, 20.5, 31.6),
    "FR": (42.3, 51.1, -4.8, 8.2), "DE": (47.3, 55.1, 5.9, 15.0), "GR": (34.8, 41.8, 19.4, 28.3),
    "HU": (45.7, 48.6, 16.1, 22.9), "IE": (51.4, 55.4, -10.5, -6.0), "IT": (36.6, 47.1, 6.6, 18.5),
    "LV": (55.7, 58.1, 21.0, 28.2), "LT": (53.9, 56.5, 21.0, 26.8), "LU": (49.4, 50.2, 5.7, 6.5),
    "MT": (35.8, 36.1, 14.2, 14.6), "NL": (50.7, 53.6, 3.3, 7.2), "PL": (49.0, 54.8, 14.1, 24.2),
    "PT": (36.9, 42.2, -9.5, -6.2), "RO": (43.6, 48.3, 20.2, 29.7), "SK": (47.7, 49.6, 16.8, 22.6),
    "SI": (45.4, 46.9, 13.4, 16.6), "ES": (36.0, 43.8, -9.3, 3.3), "SE": (55.3, 69.1, 11.1, 24.2),
    "GB": (49.9, 58.7, -8.2, 1.8), "NO": (58.0, 71.2, 4.6, 31.1), "CH": (45.8, 47.8, 5.9, 10.5),
    "IS": (63.3, 66.6, -24.5, -13.5), "MD": (45.5, 48.5, 26.6, 30.2), "RS": (42.2, 46.2, 18.8, 23.0),
    "ME": (41.8, 43.6, 18.4, 20.4), "MK": (40.8, 42.4, 20.4, 23.0), "AL": (39.6, 42.7, 19.3, 21.1),
    "BA": (42.5, 45.3, 15.7, 19.6), "XK": (41.8, 43.3, 20.0, 21.8),
}  # fmt: skip
TOTAL = "EU"  # pseudo-country for the whole query, to detect data outages
MIN_BASELINE = 5  # aircraft; smaller boxes are too noisy to judge
DROP_RATIO = 0.5  # signal when traffic falls below half of the usual level
BASELINE_DAYS = 28


# --- EASA CZIB ------------------------------------------------------------------------------

_CZIB_ID = re.compile(r"CZIB[\s-]*(\d{4}-\d{2}(?:\s*R\s*\d+)?)", re.I)
_ALIASES = {"MD": ["Moldova", "Republic of Moldova"], "MK": ["North Macedonia"],
            "BA": ["Bosnia"], "CZ": ["Czech", "Czechia"], "GB": ["United Kingdom"]}  # fmt: skip


_SECTION = re.compile(r"^(withdrawn|archived|expired|past|active|current|valid)\b", re.I)


def parse_czibs(text: str) -> list[tuple[str, str, str]]:
    """[(czib_id, country, snippet)] for active bulletins naming a monitored country.
    Line-based: each bulletin is its own line (plus the next line when it holds no id);
    everything under a "Withdrawn"/"Archived" heading is skipped."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    found: dict[tuple[str, str], str] = {}
    withdrawn_section = False
    for i, line in enumerate(lines):
        m = _CZIB_ID.search(line)
        if not m:
            heading = _SECTION.match(line)
            if heading:
                withdrawn_section = heading.group(1).lower() not in ("active", "current", "valid")
            continue
        window = line
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if nxt and not _CZIB_ID.search(nxt) and not _SECTION.match(nxt):
            window += " " + nxt
        if withdrawn_section or re.search(r"withdrawn|superseded|revoked", window, re.I):
            continue
        base_id = re.sub(r"\s+", "", m.group(1)).upper().split("R")[0]
        for code, country in COUNTRIES.items():
            names = _ALIASES.get(code, [country.name])
            if any(re.search(rf"\b{re.escape(n)}\b", window) for n in names):
                found[(base_id, code)] = window[:200]  # revisions of one CZIB collapse
    return [(czib, code, snippet) for (czib, code), snippet in found.items()]


async def collect_czib(
    db: aiosqlite.Connection, client: httpx.AsyncClient, settings: Settings
) -> RunResult:
    result = RunResult(source="easa")
    run_id = await storage.start_run(db, "easa")
    try:
        response = await client.get(CZIB_PAGE)
        response.raise_for_status()
        text = html_to_text(main_content(response.text))
        if not _CZIB_ID.search(text):
            raise ValueError("no CZIB identifiers on the page; layout changed?")
        result.fetched = 1
        now = datetime.now(UTC)
        refs = set()
        for czib, code, snippet in parse_czibs(text):
            ref = f"czib:{czib}"
            refs.add(ref)
            signal = Signal(country=code, block="aviation", kind="aviation:czib", strength=0.8,
                            publisher="easa", observed_at=now, state=True, note=snippet)  # fmt: skip
            await storage.upsert_signal(db, signal, ref)
            result.changed += 1
        await storage.deactivate_signals(db, "easa", refs)
        await db.commit()
    except (httpx.HTTPError, ValueError) as exc:
        result.fetched = 0
        result.failed = 1
        result.errors.append(f"{type(exc).__name__}: {exc}")
    await storage.finish(db, result, run_id)
    return result


# --- OpenSky --------------------------------------------------------------------------------


def count_by_country(states: list[list]) -> dict[str, int]:
    """Airborne aircraft per country box (+ TOTAL for the whole response)."""
    counts = dict.fromkeys(BOXES, 0)
    counts[TOTAL] = 0
    for state in states:
        lon, lat, on_ground = state[5], state[6], state[8]
        if lon is None or lat is None or on_ground:
            continue
        counts[TOTAL] += 1
        for code, (la0, la1, lo0, lo1) in BOXES.items():
            if la0 <= lat <= la1 and lo0 <= lon <= lo1:
                counts[code] += 1
    return counts


def hour_of_week(when: datetime) -> int:
    return when.weekday() * 24 + when.hour


async def baseline(db: aiosqlite.Connection, country: str, when: datetime) -> float | None:
    """Median count at the same hour of the week (±1 h) over the last 4 weeks."""
    how = hour_of_week(when)
    hours = [(how + d) % 168 for d in (-1, 0, 1)]
    since = (when - timedelta(days=BASELINE_DAYS)).isoformat()
    async with db.execute(
        f"SELECT aircraft FROM traffic WHERE country = ? AND observed_at >= ? AND observed_at < ? "
        f"AND hour_of_week IN ({','.join('?' * len(hours))})",
        (country, since, when.isoformat(), *hours),
    ) as cur:
        values = [r[0] for r in await cur.fetchall()]
    return statistics.median(values) if len(values) >= 3 else None


def drop_strength(ratio: float) -> float:
    """0.3 at half the usual traffic, 1.0 at about a tenth."""
    return min(1.0, 0.3 + (DROP_RATIO - ratio) * 1.75)


async def collect_traffic(
    db: aiosqlite.Connection, client: httpx.AsyncClient, settings: Settings
) -> RunResult:
    result = RunResult(source="opensky")
    run_id = await storage.start_run(db, "opensky")
    try:
        response = await client.get(OPENSKY, params={k: str(v) for k, v in EUROPE.items()})
        response.raise_for_status()
        data = response.json()
        states = data.get("states") or []
        now = datetime.fromtimestamp(data.get("time") or datetime.now(UTC).timestamp(), UTC)
        counts = count_by_country(states)
        result.fetched = len(counts)

        total_base = await baseline(db, TOTAL, now)
        outage = total_base is not None and counts[TOTAL] < total_base * DROP_RATIO
        for code, value in counts.items():
            await db.execute(
                "INSERT INTO traffic (country, observed_at, hour_of_week, aircraft) VALUES (?, ?, ?, ?)",
                (code, now.isoformat(), hour_of_week(now), value),
            )
        if outage:
            # Europe-wide collapse = receiver/data outage, not 38 simultaneous closures.
            raise ValueError(
                f"total traffic {counts[TOTAL]} vs usual {total_base:.0f}: data outage?"
            )
        for code in BOXES:
            base = await baseline(db, code, now)
            if base is None or base < MIN_BASELINE:
                continue
            ratio = counts[code] / base
            if ratio < DROP_RATIO:
                signal = Signal(
                    country=code, block="aviation", kind="aviation:traffic_drop",
                    strength=drop_strength(ratio), publisher="opensky", observed_at=now,
                    note=f"{counts[code]} aircraft vs usual {base:.0f} at this hour",
                )  # fmt: skip
                await storage.upsert_signal(db, signal, f"opensky:{code}:{now:%Y-%m-%dT%H}")
                result.changed += 1
        await db.commit()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        await db.commit()  # keep the traffic sample for the baseline
        result.fetched = 0
        result.failed = 1
        result.errors.append(f"{type(exc).__name__}: {exc}")
    await storage.finish(db, result, run_id)
    return result
