"""Processing steps after collection: classify -> signals -> scores -> alerts.

Each step is idempotent and works on whatever is pending in the database, so steps can be
run separately (CLI) or together (`tension-index run`).
"""

from __future__ import annotations

import logging

import aiosqlite

from tension_index import storage
from tension_index.classifier import Classification, ClaudeClassifier, classify_rules
from tension_index.config import Settings
from tension_index.scoring import advisory_strength, load_config

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
                publisher=row["source"], country=row["country"], text=row["diff"],
                level_before=before, level_after=after, fallback=result,
            )  # fmt: skip
        await storage.save_classification(
            db, ref_type="change", ref_id=row["id"], country=row["country"],
            publisher=row["source"], method=result.method, payload=result.to_json(),
        )  # fmt: skip
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
                publisher=snap["source"], country=snap["country"], text=snap["text"],
                level_before=None, level_after=snap["level"], fallback=result,
            )  # fmt: skip
        await storage.save_classification(
            db, ref_type="snapshot", ref_id=snap["id"], country=snap["country"],
            publisher=snap["source"], method=result.method, payload=result.to_json(),
        )  # fmt: skip
        stats["snapshots"] += 1
        stats["claude"] += result.method == "claude"
    log.info("classified: %s", stats)
    return stats


async def classification_of(
    db: aiosqlite.Connection, ref_type: str, ref_id: int
) -> Classification | None:
    row = await storage.get_classification(db, ref_type, ref_id)
    return Classification.from_json(row["payload"]) if row else None
