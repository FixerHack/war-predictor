"""Fetch advisories from all sources, store new versions and record changes."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from tension_index import storage
from tension_index.config import Settings
from tension_index.countries import COUNTRIES
from tension_index.diff import changed_fragment, normalize
from tension_index.scoring import load_config
from tension_index.sources import REGISTRY, Source

log = logging.getLogger(__name__)

# Be polite to government sites: few parallel requests per source.
CONCURRENCY = 4
# A source that stops answering must not stall the whole cycle.
SOURCE_DEADLINE_SECONDS = 120.0


@dataclass(slots=True)
class RunResult:
    source: str
    fetched: int = 0
    changed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    # (country, diff, change id)
    changes: list[tuple[str, str, int]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # One flaky country page shouldn't mark the whole source as broken,
        # but a source that fails everywhere (e.g. layout change, IP block) must.
        return self.fetched > 0 and self.failed <= max(1, self.fetched // 10)


async def collect_source(
    db,
    source: Source,
    countries: list[str] | None = None,
    deadline_seconds: float = SOURCE_DEADLINE_SECONDS,
) -> RunResult:
    result = RunResult(source=source.name)
    run_id = await storage.start_run(db, source.name)
    targets = [
        c
        for code, c in COUNTRIES.items()
        if (not countries or code in countries) and source.supports(c)
    ]
    semaphore = asyncio.Semaphore(CONCURRENCY)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds
    log.info("collecting %s (%d countries)", source.name, len(targets))
    try:
        await asyncio.wait_for(source.prepare(), deadline_seconds)
    except Exception as exc:  # index unavailable: every country fails, report once
        result.failed = len(targets)
        result.errors.append(f"prepare: {type(exc).__name__}: {exc}")
        log.warning("%s prepare failed: %s", source.name, exc)
        await storage.finish_run(
            db,
            run_id,
            ok=False,
            fetched=0,
            changed=0,
            failed=result.failed,
            error=result.errors[0],
        )
        return result

    async def one(country):
        async with semaphore:
            left = deadline - loop.time()
            if left <= 0:
                raise TimeoutError(f"{source.name}: {deadline_seconds:.0f} s limit reached")
            return country, await asyncio.wait_for(source.fetch(country), left)

    flap_days = load_config()["flap_window_days"]
    flap_since = (datetime.now(UTC) - timedelta(days=flap_days)).isoformat(timespec="seconds")
    flapping: list[str] = []
    outcomes = await asyncio.gather(*(one(c) for c in targets), return_exceptions=True)
    for country, outcome in zip(targets, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            result.failed += 1
            result.errors.append(f"{country.code}: {type(outcome).__name__}: {outcome}")
            log.warning("%s %s failed: %s", source.name, country.code, outcome)
            continue
        _, advisory = outcome
        result.fetched += 1
        text = source.canonical(normalize(advisory.text))
        previous = await storage.latest_snapshot(db, source.name, country.code)
        # Compare against the previous text re-normalised with today's rules, so a new
        # boilerplate filter doesn't register as a change everywhere.
        previous_text = source.canonical(normalize(previous.text)) if previous else ""
        if previous and previous_text == text and previous.level == advisory.level:
            continue
        if previous is not None and (storage.content_hash(text), advisory.level) in (
            await storage.seen_versions(db, source.name, country.code, flap_since)
        ):
            # A version seen a few days ago (A -> B -> A, e.g. CDN nodes serving different
            # copies): not news, and not stored again, so it is not re-classified each run.
            flapping.append(country.code)
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
        diff = changed_fragment(previous_text, text)
        if previous.level != advisory.level:
            diff = f"LEVEL: {previous.level} -> {advisory.level}\n{diff}"
        change_id = await storage.insert_change(
            db,
            source=source.name,
            country=country.code,
            prev_snapshot=previous.id,
            new_snapshot=snapshot_id,
            diff=diff,
        )
        result.changed += 1
        result.changes.append((country.code, diff, change_id))
    if flapping:
        log.info("%s: %d countries alternate between known versions, ignored: %s",
                 source.name, len(flapping), ",".join(flapping))  # fmt: skip
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
            if not sources and name in settings.disabled_sources:
                continue  # switched off in settings (DISABLED_SOURCES)
            source = cls(client)
            if countries and not any(
                source.supports(c) for code, c in COUNTRIES.items() if code in countries
            ):
                # e.g. only France is due and France does not advise on itself: no run at all,
                # otherwise an empty run reads as a failure.
                log.info("%s: none of the due countries is covered, skipped", name)
                continue
            result = await collect_source(db, source, countries)
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
