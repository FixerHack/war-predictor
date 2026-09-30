"""One full cycle: collect everything, classify, derive signals, score, notify.

Run by the systemd timer (`tension-index run --notify`) or by hand.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html import escape

import httpx

from tension_index import extra, storage
from tension_index.collector import RunResult, collect_all, make_client
from tension_index.config import Settings
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
# Seconds per collector; GDELT asks for one request per 5 s (38 countries once a day).
EXTRA_DEADLINES = {"gdelt": 420.0, "news": 180.0}


@dataclass(slots=True)
class CycleReport:
    results: list[RunResult] = field(default_factory=list)
    classified: dict[str, int] = field(default_factory=dict)
    updates: list[ScoreUpdate] = field(default_factory=list)

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


async def run_cycle(settings: Settings, notify: bool = False) -> CycleReport:
    from tension_index.notify import broadcast, broadcast_change, render_score, send
    from tension_index.sources import REGISTRY

    report = CycleReport()
    report.results = await collect_all(settings)
    async with make_client(settings) as client, storage.connect(settings.database_path) as db:
        await storage.migrate(db)
        for name, collect in EXTRA_COLLECTORS.items():
            log.info("collecting %s", name)
            try:
                result = await asyncio.wait_for(
                    collect(db, client, settings), EXTRA_DEADLINES.get(name, 120.0)
                )
                log.info("%s: fetched=%d changed=%d failed=%d ok=%s", name, result.fetched,
                         result.changed, result.failed, result.ok)  # fmt: skip
                report.results.append(result)
            except (httpx.HTTPError, ValueError, KeyError, TimeoutError) as exc:
                log.warning("collector %s failed: %s", name, exc)
                bad = RunResult(source=name, failed=1, errors=[f"{type(exc).__name__}: {exc}"])
                run_id = await storage.start_run(db, name)
                await storage.finish_run(db, run_id, ok=False, fetched=0, changed=0, failed=1,
                                         error=bad.errors[0])  # fmt: skip
                report.results.append(bad)
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
