"""Processing steps after collection: classify -> signals -> scores -> alerts.

Each step is idempotent and works on whatever is pending in the database, so steps can be
run separately (CLI) or together (`tension-index run`).
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import aiosqlite

from tension_index import storage
from tension_index.classifier import Classification, ClaudeClassifier, classify_rules
from tension_index.config import Settings
from tension_index.countries import COUNTRIES, peers
from tension_index.scoring import (
    ScoreResult,
    Signal,
    advisory_strength,
    compute_score,
    load_config,
)

log = logging.getLogger(__name__)

# Publishers whose level is not structured: the classifier reads it from the text.
TEXT_LEVEL_PUBLISHERS = {"fr"}


async def _snapshot(db: aiosqlite.Connection, snapshot_id: int | None) -> aiosqlite.Row | None:
    if snapshot_id is None:
        return None
    async with db.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)) as cur:
        return await cur.fetchone()


def make_classifier(settings: Settings) -> ClaudeClassifier | None:
    return ClaudeClassifier(settings) if settings.anthropic_api_key else None


async def classify_pending(
    db: aiosqlite.Connection, settings: Settings, claude: ClaudeClassifier | None
) -> dict[str, int]:
    """Classify new changes and current snapshots that matter for the score."""
    cfg = load_config()
    stats = {"changes": 0, "snapshots": 0, "claude": 0}

    for row in await storage.unclassified_changes(db, limit=500):
        new = await _snapshot(db, row["new_snapshot"])
        async with db.execute(
            "SELECT prev_snapshot FROM changes WHERE id = ?", (row["id"],)
        ) as cur:
            prev_id = (await cur.fetchone())[0]
        prev = await _snapshot(db, prev_id)
        before = prev["level"] if prev else None
        after = new["level"] if new else None
        change = (
            advisory_strength(cfg, row["source"], before),
            advisory_strength(cfg, row["source"], after),
        )
        result = classify_rules(row["diff"], level_change=change if before != after else None)
        if claude is not None and result.change_type != "editorial":
            result = await claude.classify(
                publisher=row["source"],
                country=row["country"],
                text=row["diff"],
                level_before=before,
                level_after=after,
                fallback=result,
            )
        await storage.save_classification(
            db,
            ref_type="change",
            ref_id=row["id"],
            country=row["country"],
            publisher=row["source"],
            method=result.method,
            payload=result.to_json(),
        )
        stats["changes"] += 1
        stats["claude"] += result.method == "claude"

    # The current version of each advisory: its reason decides how much its level counts.
    for snap in await storage.latest_snapshots(db):
        if await storage.get_classification(db, "snapshot", snap["id"]):
            continue
        strength = advisory_strength(cfg, snap["source"], snap["level"])
        needs_text_level = snap["source"] in TEXT_LEVEL_PUBLISHERS
        result = classify_rules(snap["text"])
        if claude is not None and (strength > 0 or needs_text_level):
            result = await claude.classify(
                publisher=snap["source"],
                country=snap["country"],
                text=snap["text"],
                level_before=None,
                level_after=snap["level"],
                fallback=result,
            )
        await storage.save_classification(
            db,
            ref_type="snapshot",
            ref_id=snap["id"],
            country=snap["country"],
            publisher=snap["source"],
            method=result.method,
            payload=result.to_json(),
        )
        stats["snapshots"] += 1
        stats["claude"] += result.method == "claude"
    log.info("classified: %s", stats)
    return stats


async def classification_of(
    db: aiosqlite.Connection, ref_type: str, ref_id: int
) -> Classification | None:
    row = await storage.get_classification(db, ref_type, ref_id)
    return Classification.from_json(row["payload"]) if row else None


# --- Signals --------------------------------------------------------------------------------

ADVISORY_EVENT_TYPES = (
    "level_raised",
    "staff_posture",
    "consular",
    "borders",
    "airspace",
    "security_update",
)


def parse_when(value: str | None) -> datetime | None:
    """Best effort for publishers' date formats (ISO, RFC 822, epoch ms/s)."""
    if not value:
        return None
    text = str(value).strip()
    try:
        number = float(text)
        return datetime.fromtimestamp(number / 1000 if number > 1e11 else number, UTC)
    except ValueError:
        pass
    for parse in (datetime.fromisoformat, parsedate_to_datetime):
        try:
            dt = parse(text.replace("Z", "+00:00") if parse is datetime.fromisoformat else text)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            continue
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


async def _is_baseline(db: aiosqlite.Connection, snap: aiosqlite.Row) -> bool:
    async with db.execute(
        "SELECT 1 FROM changes WHERE new_snapshot = ? LIMIT 1", (snap["id"],)
    ) as cur:
        return await cur.fetchone() is None


async def upsert_signal(db: aiosqlite.Connection, s: Signal, ref: str) -> None:
    await db.execute(
        "INSERT INTO signals (country, block, kind, strength, publisher, observed_at, tier, "
        "confirmed, reason, state, active, note, ref) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?) "
        "ON CONFLICT (ref, kind, country) WHERE ref != '' DO UPDATE SET "
        "strength = excluded.strength, reason = excluded.reason, note = excluded.note, active = 1",
        (
            s.country,
            s.block,
            s.kind,
            s.strength,
            s.publisher,
            s.observed_at.isoformat(),
            s.tier,
            int(s.confirmed),
            s.reason,
            int(s.state),
            s.note,
            ref,
        ),
    )


async def derive_advisory_signals(db: aiosqlite.Connection) -> int:
    """Turn current advisories (+ their classification) into state signals and classified
    changes into event signals. Superseded advisory versions are deactivated."""
    cfg = load_config()
    count = 0
    current_refs: dict[tuple[str, str], str] = {}
    for snap in await storage.latest_snapshots(db):
        cls = await classification_of(db, "snapshot", snap["id"]) or classify_rules(snap["text"])
        ref = f"snapshot:{snap['id']}"
        current_refs[(snap["country"], snap["source"])] = ref
        fetched = datetime.fromisoformat(snap["fetched_at"])
        when = fetched
        if await _is_baseline(db, snap):
            # First sighting: the level was set some time ago, not "now" (avoid fake synchrony).
            when = parse_when(snap["source_updated"]) or fetched - timedelta(days=30)
            when = min(when, fetched)
        level = snap["level"] or cls.level
        base = {
            "country": snap["country"],
            "publisher": snap["source"],
            "observed_at": when,
            "reason": cls.reason,
            "state": True,
            "note": cls.quote,
        }
        strength = advisory_strength(cfg, snap["source"], level)
        await upsert_signal(
            db, Signal(block="advisories", kind="advisory_level", strength=strength, **base), ref
        )
        count += 1
        posture = cfg["staff_posture"].get(cls.staff_posture, 0.0)
        if posture > 0:
            await upsert_signal(
                db,
                Signal(
                    block="advisories",
                    kind=f"staff_posture:{cls.staff_posture}",
                    strength=posture,
                    **base,
                ),
                ref,
            )
            count += 1
        if cls.airspace in ("closed", "restricted"):
            await upsert_signal(
                db,
                Signal(
                    block="aviation",
                    kind=f"aviation:airspace_{cls.airspace}",
                    strength=1.0 if cls.airspace == "closed" else 0.6,
                    **base,
                ),
                ref,
            )
            count += 1
        if cls.borders_closed:
            await upsert_signal(
                db,
                Signal(
                    block="domestic",
                    kind="domestic:borders_closed",
                    strength=cfg["borders_closed_strength"],
                    **base,
                ),
                ref,
            )
            count += 1
    # Deactivate signals of superseded advisory versions.
    async with db.execute(
        "SELECT id, country, publisher, ref FROM signals WHERE active = 1 AND ref LIKE 'snapshot:%'"
    ) as cur:
        rows = await cur.fetchall()
    stale = [r["id"] for r in rows if current_refs.get((r["country"], r["publisher"])) != r["ref"]]
    for sid in stale:
        await db.execute("UPDATE signals SET active = 0 WHERE id = ?", (sid,))

    # One-off events from classified changes.
    async with db.execute(
        "SELECT c.id, c.country, c.source, c.detected_at, k.payload FROM changes c "
        "JOIN classifications k ON k.ref_type = 'change' AND k.ref_id = c.id"
    ) as cur:
        for row in await cur.fetchall():
            cls = Classification.from_json(row["payload"])
            if cls.change_type not in ADVISORY_EVENT_TYPES:
                continue
            event = Signal(
                country=row["country"],
                block="advisories",
                kind=f"advisory_update:{cls.change_type}",
                strength=cfg["advisory_events"][cls.change_type],
                publisher=row["source"],
                observed_at=datetime.fromisoformat(row["detected_at"]),
                reason=cls.reason,
                state=False,
                note=cls.summary_en or cls.quote,
            )
            await upsert_signal(db, event, f"change:{row['id']}")
            count += 1
    await db.commit()
    return count


async def active_signals(
    db: aiosqlite.Connection, now: datetime, max_event_age_days: int = 90
) -> list[Signal]:
    since = (now - timedelta(days=max_event_age_days)).isoformat()
    async with db.execute(
        "SELECT * FROM signals WHERE active = 1 AND (state = 1 OR observed_at >= ?)", (since,)
    ) as cur:
        rows = await cur.fetchall()
    return [
        Signal(
            country=r["country"],
            block=r["block"],
            kind=r["kind"],
            strength=r["strength"],
            publisher=r["publisher"],
            observed_at=datetime.fromisoformat(r["observed_at"]),
            tier=r["tier"],
            confirmed=bool(r["confirmed"]),
            reason=r["reason"],
            state=bool(r["state"]),
            note=r["note"],
        )
        for r in rows
    ]


# --- Scores ---------------------------------------------------------------------------------

# Which scoring block each collector feeds (for coverage). Advisory sources are added below.
SOURCE_BLOCKS: dict[str, str] = {}
COVERAGE_MAX_AGE_HOURS = 48


def source_blocks() -> dict[str, str]:
    from tension_index.sources import REGISTRY

    return {**dict.fromkeys(REGISTRY, "advisories"), **SOURCE_BLOCKS}


async def covered_blocks(db: aiosqlite.Connection, now: datetime) -> set[str]:
    covered = set()
    for source, block in source_blocks().items():
        last = await storage.last_success(db, source)
        if last and now - datetime.fromisoformat(last) <= timedelta(hours=COVERAGE_MAX_AGE_HOURS):
            covered.add(block)
    return covered


async def _history(
    db: aiosqlite.Connection, country: str, now: datetime, window_days: int
) -> tuple[list[float], int]:
    since = (now - timedelta(days=window_days)).isoformat()
    async with db.execute(
        "SELECT computed_at, payload FROM scores WHERE country = ? AND computed_at >= ? "
        "ORDER BY id",
        (country, since),
    ) as cur:
        rows = await cur.fetchall()
    values = [json.loads(r["payload"])["raw"] for r in rows]
    async with db.execute(
        "SELECT MIN(computed_at) FROM scores WHERE country = ?", (country,)
    ) as cur:
        first = (await cur.fetchone())[0]
    days = (now - datetime.fromisoformat(first)).days if first else 0
    return values, days


@dataclass(slots=True)
class ScoreUpdate:
    country: str
    previous: float | None
    result: ScoreResult


async def score_all(db: aiosqlite.Connection, now: datetime | None = None) -> list[ScoreUpdate]:
    """Compute and store today's score for every monitored country."""
    cfg = load_config()
    now = now or datetime.now(UTC)
    signals = await active_signals(db, now)
    covered = await covered_blocks(db, now)
    base = cfg["baseline"]

    histories = {c: await _history(db, c, now, base["window_days"]) for c in COUNTRIES}
    first_pass = {c: compute_score(c, signals, now, cfg=cfg) for c in COUNTRIES}
    surging = {}
    for code, (values, days) in histories.items():
        enough = values and days >= base["min_history_days"]
        deviation = first_pass[code].raw - statistics.median(values) if enough else 0.0
        surging[code] = deviation >= cfg["regional"]["surge_threshold"]

    updates = []
    for code in COUNTRIES:
        values, days = histories[code]
        result = compute_score(
            code, signals, now, history=values, history_days=days,
            peers_surging=[surging[p.code] for p in peers(code)],
            covered_blocks=covered, cfg=cfg,
        )  # fmt: skip
        previous = await storage.latest_score(db, code)
        payload = result.as_dict() | {"covered": sorted(covered)}
        await storage.insert_score(db, code, result.score, result.level, json.dumps(payload))
        updates.append(ScoreUpdate(code, previous["score"] if previous else None, result))
    return updates
