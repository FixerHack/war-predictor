"""Stage S8: replay the scale day by day on a historical episode and report how it behaved.

Uses the same rules as the live pipeline (classification -> signals -> compute_score), on
archived advisory versions from `history.py`. Only block A (advisories) exists in the
archive, so coverage is not checked and the result is a lower bound of the live scale.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import aiosqlite

from tension_index import storage
from tension_index.classifier import Classification, ClaudeClassifier, classify_rules
from tension_index.history import Episode
from tension_index.scoring import (
    Signal,
    advisory_strength,
    compute_score,
    load_config,
    relevance,
)

BASELINE_BACKDATE_DAYS = 30


@dataclass(slots=True)
class Day:
    day: date
    score: float
    level: str
    raw: float
    flags: list[str]
    top: list[str]


@dataclass(slots=True)
class Report:
    episode: Episode
    days: list[Day] = field(default_factory=list)

    def first_reaching(self, threshold: float) -> date | None:
        return next((d.day for d in self.days if d.score >= threshold), None)

    @property
    def max_score(self) -> float:
        return max((d.score for d in self.days), default=0.0)

    def verdict(self) -> tuple[bool, str]:
        exp = self.episode.expect
        if "max_score" in exp:
            ok = self.max_score <= exp["max_score"]
            return ok, f"max {self.max_score:.1f} (limit {exp['max_score']})"
        first = self.first_reaching(exp.get("min_score", 7))
        event = self.episode.event
        if first is None or event is None:
            return False, f"never reached {exp.get('min_score', 7)}"
        lead = (event - first).days
        ok = lead >= exp.get("before_event_days", 0)
        return ok, f"reached {exp.get('min_score', 7)} on {first}, {lead} days before the event"

    def csv(self) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["date", "score", "level", "raw", "flags", "top"])
        for d in self.days:
            writer.writerow(
                [d.day, d.score, d.level, round(d.raw, 3), " ".join(d.flags), " | ".join(d.top)]
            )
        return out.getvalue()

    def markdown(self) -> str:
        ok, detail = self.verdict()
        e = self.episode
        lines = [
            f"# Backtest: {e.id}",
            "",
            f"Country {e.country}, {e.start} → {e.end}, event: {e.event or '—'}.",
            f"Result: **{'PASS' if ok else 'FAIL'}** — {detail}.",
            "",
            "| Threshold | First day | Days before event |",
            "|---|---|---|",
        ]
        for threshold in (3, 5, 7, 9):
            first = self.first_reaching(threshold)
            lead = (e.event - first).days if first and e.event else ""
            lines.append(f"| {threshold} | {first or '—'} | {lead} |")
        lines += ["", "Score changes:", ""]
        previous = None
        for d in self.days:
            if d.score != previous:
                lines.append(
                    f"- {d.day}: **{d.score}** ({d.level}) {' '.join(d.flags)} — {'; '.join(d.top)}"
                )
                previous = d.score
        lines += ["", "_Advisories only (block A): a lower bound of the live scale._"]
        return "\n".join(lines) + "\n"


async def _cached(
    db: aiosqlite.Connection, ref_type: str, ref_id: int, claude: ClaudeClassifier | None
) -> bool:
    """Already classified - by Claude, or by rules when Claude is not asked for (so a later
    `backtest --claude` upgrades earlier rule-based results)."""
    row = await storage.get_classification(db, ref_type, ref_id)
    return row is not None and (claude is None or row["method"] == "claude")


async def classify_history(db: aiosqlite.Connection, claude: ClaudeClassifier | None) -> int:
    """Classify every archived version and change (cached in the history DB)."""
    cfg = load_config()
    done = 0
    async with db.execute("SELECT * FROM snapshots ORDER BY id") as cur:
        snapshots = await cur.fetchall()
    for snap in snapshots:
        if await _cached(db, "snapshot", snap["id"], claude):
            continue
        result = classify_rules(snap["text"])
        if claude is not None and advisory_strength(cfg, snap["source"], snap["level"]) > 0:
            result = await claude.classify(publisher=snap["source"], country=snap["country"],
                                           text=snap["text"], level_before=None,
                                           level_after=snap["level"], fallback=result)  # fmt: skip
        await storage.save_classification(db, ref_type="snapshot", ref_id=snap["id"],
                                           country=snap["country"], publisher=snap["source"],
                                           method=result.method, payload=result.to_json())  # fmt: skip
        done += 1
    async with db.execute(
        "SELECT c.*, p.level AS before, n.level AS after FROM changes c "
        "JOIN snapshots n ON n.id = c.new_snapshot "
        "LEFT JOIN snapshots p ON p.id = c.prev_snapshot ORDER BY c.id"
    ) as cur:
        changes = await cur.fetchall()  # fmt: skip
    for ch in changes:
        if await _cached(db, "change", ch["id"], claude):
            continue
        levels = (advisory_strength(cfg, ch["source"], ch["before"]),
                  advisory_strength(cfg, ch["source"], ch["after"]))  # fmt: skip
        result = classify_rules(
            ch["diff"], level_change=levels if ch["before"] != ch["after"] else None
        )
        if claude is not None and result.change_type != "editorial":
            result = await claude.classify(publisher=ch["source"], country=ch["country"],
                                           text=ch["diff"], level_before=ch["before"],
                                           level_after=ch["after"], fallback=result)  # fmt: skip
        await storage.save_classification(db, ref_type="change", ref_id=ch["id"],
                                          country=ch["country"], publisher=ch["source"],
                                          method=result.method, payload=result.to_json())  # fmt: skip
        done += 1
    return done


async def _load(db: aiosqlite.Connection, country: str):
    async with db.execute(
        "SELECT s.*, k.payload FROM snapshots s LEFT JOIN classifications k "
        "ON k.ref_type = 'snapshot' AND k.ref_id = s.id WHERE s.country = ? ORDER BY s.fetched_at",
        (country,),
    ) as cur:
        snapshots = await cur.fetchall()
    async with db.execute(
        "SELECT c.*, k.payload FROM changes c LEFT JOIN classifications k "
        "ON k.ref_type = 'change' AND k.ref_id = c.id WHERE c.country = ? ORDER BY c.detected_at",
        (country,),
    ) as cur:
        changes = await cur.fetchall()
    return snapshots, changes


def signals_at(snapshots, changes, moment: datetime, cfg: dict) -> list[Signal]:
    """The signals the live pipeline would have had at `moment`."""
    latest: dict[str, aiosqlite.Row] = {}
    first_seen: dict[str, datetime] = {}
    for snap in snapshots:
        when = datetime.fromisoformat(snap["fetched_at"])
        first_seen.setdefault(snap["source"], when)
        if when <= moment:
            latest[snap["source"]] = snap
    out = []
    for publisher, snap in latest.items():
        cls = (
            Classification.from_json(snap["payload"])
            if snap["payload"]
            else classify_rules(snap["text"])
        )
        when = datetime.fromisoformat(snap["fetched_at"])
        if when == first_seen[publisher]:
            when -= timedelta(days=BASELINE_BACKDATE_DAYS)  # like live: first sighting is old news
        base = {"country": snap["country"], "publisher": publisher, "observed_at": when,
                "reason": cls.reason, "state": True, "note": cls.quote}  # fmt: skip
        out.append(Signal(block="advisories", kind="advisory_level",
                          strength=advisory_strength(cfg, publisher, snap["level"] or cls.level), **base))  # fmt: skip
        posture = cfg["staff_posture"].get(cls.staff_posture, 0.0)
        if posture > 0:
            out.append(
                Signal(
                    block="advisories",
                    kind=f"staff_posture:{cls.staff_posture}",
                    strength=posture,
                    **base,
                )
            )
        if (
            cls.airspace in ("closed", "restricted")
            and relevance(cfg, cls.reason) >= cfg["airspace_min_relevance"]
        ):
            out.append(Signal(block="aviation", kind=f"aviation:airspace_{cls.airspace}",
                              strength=1.0 if cls.airspace == "closed" else 0.6, **base))  # fmt: skip
    for ch in changes:
        when = datetime.fromisoformat(ch["detected_at"])
        if when > moment or not ch["payload"]:
            continue
        cls = Classification.from_json(ch["payload"])
        if cls.change_type in cfg["advisory_events"]:
            out.append(Signal(country=ch["country"], block="advisories",
                              kind=f"advisory_update:{cls.change_type}",
                              strength=cfg["advisory_events"][cls.change_type], publisher=ch["source"],
                              observed_at=when, reason=cls.reason, note=cls.quote))  # fmt: skip
    return out


async def replay(db: aiosqlite.Connection, episode: Episode) -> Report:
    cfg = load_config()
    snapshots, changes = await _load(db, episode.country)
    report = Report(episode)
    raws: list[float] = []
    day = episode.start
    while day <= episode.end:
        moment = datetime(day.year, day.month, day.day, 23, 59, tzinfo=UTC)
        signals = signals_at(snapshots, changes, moment, cfg)
        window = raws[-cfg["baseline"]["window_days"] :]
        result = compute_score(episode.country, signals, moment, history=window,
                               history_days=len(raws), cfg=cfg)  # fmt: skip
        raws.append(result.raw)
        top = [f"{c.publisher}:{c.kind}" for c in result.top[:3]]
        report.days.append(Day(day, result.score or 0.0, result.level or "green", result.raw,
                               [f for f in result.flags if f != "short_history"], top))  # fmt: skip
        day += timedelta(days=1)
    return report
