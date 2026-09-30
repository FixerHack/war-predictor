"""Block F, markets, from the ECB Data Portal (free SDMX API, CSV).

- Long-term (10y) government bond yields (IRS, monthly): spread over Germany jumping by
  1+ percentage point vs its own 12-month median.
- Exchange rates vs EUR (EXR, daily): the national currency losing 5%+ vs its 60-day median.
Countries without data (euro area FX, non-EU bonds) simply get no market signal.
Runs at most once a day.
"""

from __future__ import annotations

import csv
import io
import statistics
from datetime import UTC, datetime, timedelta

import aiosqlite
import httpx

from tension_index import storage
from tension_index.collector import RunResult
from tension_index.config import Settings
from tension_index.countries import COUNTRIES
from tension_index.scoring import Signal

API = "https://data-api.ecb.europa.eu/service/data"
BONDS = f"{API}/IRS/M..L.L40.CI.0000..N.Z"
FX = f"{API}/EXR/D..EUR.SP00.A"
CURRENCY = {
    "PL": "PLN", "CZ": "CZK", "HU": "HUF", "RO": "RON", "SE": "SEK", "DK": "DKK",
    "GB": "GBP", "NO": "NOK", "CH": "CHF", "IS": "ISK", "RS": "RSD", "MD": "MDL",
    "MK": "MKD", "AL": "ALL", "BA": "BAM",
}  # fmt: skip
SPREAD_JUMP = 1.0  # percentage points
FX_DROP = 0.05
MIN_INTERVAL_HOURS = 20


def parse_csv(text: str, area_field: str) -> dict[str, list[tuple[str, float]]]:
    """{area: [(period, value)]} sorted by period, from ECB csvdata."""
    out: dict[str, list[tuple[str, float]]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            value = float(row["OBS_VALUE"])
        except (KeyError, ValueError):
            continue
        out.setdefault(row[area_field], []).append((row["TIME_PERIOD"], value))
    return {k: sorted(v) for k, v in out.items()}


def spread_jumps(bonds: dict[str, list[tuple[str, float]]]) -> dict[str, float]:
    """{country: jump in pp} where the latest spread over DE exceeds its median by SPREAD_JUMP."""
    de = dict(bonds.get("DE", []))
    out = {}
    for area, series in bonds.items():
        if area == "DE" or area not in COUNTRIES:
            continue
        spreads = [v - de[p] for p, v in series if p in de]
        if len(spreads) < 6:
            continue
        jump = spreads[-1] - statistics.median(spreads[:-1])
        if jump >= SPREAD_JUMP:
            out[area] = jump
    return out


def fx_drops(rates: dict[str, list[tuple[str, float]]]) -> dict[str, float]:
    """{country: depreciation share}. Rates are units of currency per EUR (up = weaker)."""
    out = {}
    for country, cur in CURRENCY.items():
        series = rates.get(cur, [])
        if len(series) < 30:
            continue
        values = [v for _, v in series]
        drop = values[-1] / statistics.median(values[-61:-1]) - 1
        if drop >= FX_DROP:
            out[country] = drop
    return out


async def collect_markets(
    db: aiosqlite.Connection, client: httpx.AsyncClient, settings: Settings
) -> RunResult:
    now = datetime.now(UTC)
    result = RunResult(source="ecb")
    last = await storage.last_success(db, "ecb")
    if last and now - datetime.fromisoformat(last) < timedelta(hours=MIN_INTERVAL_HOURS):
        result.fetched = 1
        return result
    run_id = await storage.start_run(db, "ecb")
    signals: list[Signal] = []
    try:
        bonds = await client.get(BONDS, params={"format": "csvdata", "lastNObservations": "13"})
        bonds.raise_for_status()
        for code, jump in spread_jumps(parse_csv(bonds.text, "REF_AREA")).items():
            signals.append(Signal(
                country=code, block="markets", kind="markets:spread_jump",
                strength=min(1.0, jump / 3), publisher="ecb", observed_at=now,
                note=f"10y spread over Germany up {jump:.1f} pp vs its 12-month median",
            ))  # fmt: skip
        result.fetched += 1
    except (httpx.HTTPError, KeyError) as exc:
        result.failed += 1
        result.errors.append(f"bonds: {type(exc).__name__}: {exc}")
    try:
        fx = await client.get(FX, params={"format": "csvdata", "lastNObservations": "90"})
        fx.raise_for_status()
        for code, drop in fx_drops(parse_csv(fx.text, "CURRENCY")).items():
            signals.append(Signal(
                country=code, block="markets", kind="markets:fx_drop",
                strength=min(1.0, drop / 0.15), publisher="ecb", observed_at=now,
                note=f"{CURRENCY[code]} down {drop:.0%} vs EUR against its 60-day median",
            ))  # fmt: skip
        result.fetched += 1
    except (httpx.HTTPError, KeyError) as exc:
        result.failed += 1
        result.errors.append(f"fx: {type(exc).__name__}: {exc}")
    for s in signals:
        await storage.upsert_signal(db, s, f"ecb:{now:%Y-%m-%d}")
        result.changed += 1
    await db.commit()
    await storage.finish(db, result, run_id)
    return result
