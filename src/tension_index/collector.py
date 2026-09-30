"""Fetch advisories from all sources, store new versions and record changes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from tension_index import storage
from tension_index.config import Settings
from tension_index.countries import COUNTRIES
from tension_index.diff import changed_fragment, normalize
from tension_index.sources import REGISTRY, Source

log = logging.getLogger(__name__)

# Be polite to government sites: few parallel requests per source.
CONCURRENCY = 4


@dataclass(slots=True)
class RunResult:
    source: str
    fetched: int = 0
    changed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    changes: list[tuple[str, str]] = field(default_factory=list)  # (country, diff)

    @property
    def ok(self) -> bool:
        # One flaky country page shouldn't mark the whole source as broken,
        # but a source that fails everywhere (e.g. layout change, IP block) must.
        return self.fetched > 0 and self.failed <= max(1, self.fetched // 10)


async def collect_source(db, source: Source, countries: list[str] | None = None) -> RunResult:
    result = RunResult(source=source.name)
    run_id = await storage.start_run(db, source.name)
    targets = [
        c
        for code, c in COUNTRIES.items()
        if (not countries or code in countries) and source.supports(c)
    ]
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def one(country):
        async with semaphore:
            return country, await source.fetch(country)

    outcomes = await asyncio.gather(*(one(c) for c in targets), return_exceptions=True)
    for country, outcome in zip(targets, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            result.failed += 1
            result.errors.append(f"{country.code}: {type(outcome).__name__}: {outcome}")
            log.warning("%s %s failed: %s", source.name, country.code, outcome)
            continue
        _, advisory = outcome
        result.fetched += 1
        text = normalize(advisory.text)
        previous = await storage.latest_snapshot(db, source.name, country.code)
        if previous and previous.content_hash == storage.content_hash(text):
            continue
        snapshot_id = await storage.insert_snapshot(
            db,
            source=source.name,
            country=country.code,
            url=advisory.url,
            text=text,
            title=advisory.title,
            level=advisory.level,
            source_updated=advisory.source_updated,
        )
        if previous is None:
            continue  # first sighting is the baseline, not a change
        diff = changed_fragment(previous.text, text)
        if previous.level != advisory.level:
            diff = f"LEVEL: {previous.level} -> {advisory.level}\n{diff}"
        await storage.insert_change(
            db,
            source=source.name,
            country=country.code,
            prev_snapshot=previous.id,
            new_snapshot=snapshot_id,
            diff=diff,
        )
        result.changed += 1
        result.changes.append((country.code, diff))
    await db.commit()
    await storage.finish_run(
        db,
        run_id,
        ok=result.ok,
        fetched=result.fetched,
        changed=result.changed,
        failed=result.failed,
        error="\n".join(result.errors[:20]) or None,
    )
    return result


def make_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.http_timeout_seconds,
        headers={"User-Agent": settings.http_user_agent},
        follow_redirects=True,
    )


async def collect_all(
    settings: Settings,
    sources: list[str] | None = None,
    countries: list[str] | None = None,
    db_path: Path | None = None,
) -> list[RunResult]:
    results: list[RunResult] = []
    async with (
        make_client(settings) as client,
        storage.connect(db_path or settings.database_path) as db,
    ):
        await storage.migrate(db)
        for name, cls in REGISTRY.items():
            if sources and name not in sources:
                continue
            result = await collect_source(db, cls(client), countries)
            log.info(
                "%s: fetched=%d changed=%d failed=%d ok=%s",
                name,
                result.fetched,
                result.changed,
                result.failed,
                result.ok,
            )
            results.append(result)
    return results
