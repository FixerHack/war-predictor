"""One full cycle: collect everything, classify, derive signals, score, notify.

Run by the systemd timer (`tension-index run --notify`) or by hand.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape

import httpx

from tension_index import extra, storage
from tension_index.collector import RunResult, collect_all, make_client
from tension_index.config import Settings
from tension_index.countries import COUNTRIES
from tension_index.pipeline import (
    ScoreUpdate,
    classification_of,
    classify_pending,
    derive_advisory_signals,
    make_classifier,
    score_all,
)

log = logging.getLogger(__name__)

# Non-advisory collectors (aviation, news, markets): async def collect(db, client, settings)
Collector = Callable[..., Awaitable[RunResult]]
EXTRA_COLLECTORS: dict[str, Collector] = dict(extra.COLLECTORS)
# Seconds per collector. GDELT (daily event files + one throttled DOC query) must stay well
# below TimeoutStartSec=15min of tension-gdelt.service, so the run row is always closed.
EXTRA_DEADLINES = {"gdelt": 600.0, "news": 180.0}
# Slow daily collectors run from their own timer (`tension-index gdelt`), not every cycle.
SLOW_COLLECTORS = {"gdelt"}


@dataclass(slots=True)
class CycleReport:
    results: list[RunResult] = field(default_factory=list)
    classified: dict[str, int] = field(default_factory=dict)
    updates: list[ScoreUpdate] = field(default_factory=list)
    due: list[str] = field(default_factory=list)  # countries whose advisories were fetched

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)


def score_alerts(updates: list[ScoreUpdate], threshold: float = 1.0) -> list[ScoreUpdate]:
    """Countries whose published score moved by `threshold` or more since the last run."""
    return [
        u
        for u in updates
        if u.previous is not None
        and u.result.score is not None
        and abs(u.result.score - u.previous) >= threshold
    ]


async def run_extra(db, client, settings: Settings, name: str) -> RunResult:
    """One non-advisory collector under its deadline. On a deadline, error or cancellation the
    collect_runs row is still closed (ok=0) so health never sees a run stuck in progress."""
    deadline = EXTRA_DEADLINES.get(name, 120.0)
    try:
        result = await asyncio.wait_for(EXTRA_COLLECTORS[name](db, client, settings), deadline)
    except (httpx.HTTPError, ValueError, KeyError, TimeoutError, asyncio.CancelledError) as exc:
        if isinstance(exc, TimeoutError):
            error = f"deadline of {deadline:.0f} s exceeded"
        elif isinstance(exc, asyncio.CancelledError):
            error = "cancelled (stopped by systemd or Ctrl-C)"
        else:
            error = f"{type(exc).__name__}: {exc}"
        log.warning("collector %s failed: %s", name, error)
        if not await storage.abort_open_runs(db, name, error):
            run_id = await storage.start_run(db, name)
            await storage.finish_run(db, run_id, ok=False, fetched=0, changed=0, failed=1,
                                     error=error)  # fmt: skip
        if isinstance(exc, asyncio.CancelledError):
            raise
        return RunResult(source=name, failed=1, errors=[error])
    log.info("%s: fetched=%d changed=%d failed=%d ok=%s", name, result.fetched,
             result.changed, result.failed, result.ok)  # fmt: skip
    for error in result.errors[:10]:
        log.info("%s: %s", name, error)
    return result


async def run_slow(settings: Settings) -> list[RunResult]:
    """The daily slow collectors (GDELT) on their own. SIGTERM (systemd stop or timeout)
    cancels the run cleanly: the collect_runs row is closed as failed before exiting."""
    results = []
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    if task is not None:
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        async with make_client(settings) as client, storage.connect(settings.database_path) as db:
            await storage.migrate(db)
            for name in SLOW_COLLECTORS:
                log.info("collecting %s (daily, deadline %.0f s)", name, EXTRA_DEADLINES[name])
                try:
                    results.append(await run_extra(db, client, settings, name))
                except asyncio.CancelledError:
                    if task is not None:
                        task.uncancel()  # handled: exit with a failed result, not a traceback
                    results.append(RunResult(source=name, failed=1, errors=["cancelled"]))
                    break
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
    return results


async def run_cycle(
    settings: Settings, notify: bool = False, slow: bool = False, adaptive: bool = False
) -> CycleReport:
    """`adaptive`: fetch only countries whose refresh interval has passed (refresh.py); with
    none due, nothing runs. Otherwise every country is fetched."""
    from tension_index.notify import broadcast, broadcast_change, render_score, send
    from tension_index.refresh import due_countries
    from tension_index.sources import REGISTRY

    report = CycleReport()
    now = datetime.now(UTC)
    report.due = list(COUNTRIES)
    if adaptive:
        async with storage.connect(settings.database_path) as db:
            await storage.migrate(db)
            report.due = await due_countries(db, now)
        if not report.due:
            log.info("no country is due for a refresh")
            return report
        log.info("due for a refresh: %s", ",".join(report.due))
    report.results = await collect_all(
        settings, countries=None if len(report.due) == len(COUNTRIES) else report.due
    )
    async with make_client(settings) as client, storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        await storage.mark_checked(db, report.due, now.isoformat(timespec="seconds"))
        for name in EXTRA_COLLECTORS:
            if name in SLOW_COLLECTORS and not slow:
                continue
            log.info("collecting %s", name)
            report.results.append(await run_extra(db, client, settings, name))
        report.classified = await classify_pending(db, settings, make_classifier(settings))
        await derive_advisory_signals(db)
        report.updates = await score_all(db)

        if notify:
            for r in report.results:
                label = REGISTRY[r.source].label if r.source in REGISTRY else r.source
                for country, diff, change_id in r.changes:
                    cls = await classification_of(db, "change", change_id)
                    if cls and cls.change_type == "editorial":
                        continue  # formatting/contact edits are not worth a push
                    summary = {"uk": cls.summary_uk, "en": cls.summary_en} if cls else None
                    await send(settings, f"🔔 <b>{country}</b> · {escape(label)}\n"
                               f"<pre>{escape(diff[:3000])}</pre>")  # fmt: skip
                    await broadcast_change(settings, country, label, diff, summary,
                                           cls.quote if cls else "")  # fmt: skip
                if not r.ok:
                    await send(
                        settings,
                        f"❌ Collector <b>{escape(r.source)}</b> failed ({r.failed} errors)\n"
                        f"<pre>{escape(chr(10).join(r.errors[:5]))}</pre>",
                    )
            for u in score_alerts(report.updates):
                payload = u.result.as_dict()
                await broadcast(settings, u.country, render_score(u.country, u.previous, payload))
    return report
