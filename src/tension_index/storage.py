"""SQLite storage with simple forward-only migrations (PRAGMA user_version).

Every fetched advisory text is stored in full so versions can be diffed and the
history replayed later (backtesting, re-scoring with new weights).
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from tension_index.scoring import Signal

MIGRATIONS: list[str] = [
    # 1: snapshots, detected changes, collection runs
    """
    CREATE TABLE snapshots (
        id              INTEGER PRIMARY KEY,
        source          TEXT NOT NULL,
        country         TEXT NOT NULL,
        fetched_at      TEXT NOT NULL,
        source_updated  TEXT,
        url             TEXT NOT NULL,
        title           TEXT,
        level           TEXT,
        content_hash    TEXT NOT NULL,
        text            TEXT NOT NULL
    );
    CREATE INDEX ix_snapshots_source_country ON snapshots (source, country, id);

    CREATE TABLE changes (
        id              INTEGER PRIMARY KEY,
        source          TEXT NOT NULL,
        country         TEXT NOT NULL,
        detected_at     TEXT NOT NULL,
        prev_snapshot   INTEGER REFERENCES snapshots (id),
        new_snapshot    INTEGER NOT NULL REFERENCES snapshots (id),
        diff            TEXT NOT NULL,
        classified      INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE collect_runs (
        id              INTEGER PRIMARY KEY,
        source          TEXT NOT NULL,
        started_at      TEXT NOT NULL,
        finished_at     TEXT,
        ok              INTEGER,
        fetched         INTEGER NOT NULL DEFAULT 0,
        changed         INTEGER NOT NULL DEFAULT 0,
        failed          INTEGER NOT NULL DEFAULT 0,
        error           TEXT
    );
    CREATE INDEX ix_collect_runs_source ON collect_runs (source, id);
    """,
    # 2: bot users and computed scores
    """
    CREATE TABLE users (
        tg_id           INTEGER PRIMARY KEY,
        lang            TEXT,
        country         TEXT,
        notify          INTEGER NOT NULL DEFAULT 1,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    );
    CREATE INDEX ix_users_country ON users (country, notify);

    CREATE TABLE scores (
        id              INTEGER PRIMARY KEY,
        country         TEXT NOT NULL,
        computed_at     TEXT NOT NULL,
        score           REAL,
        level           TEXT,
        payload         TEXT NOT NULL
    );
    CREATE INDEX ix_scores_country ON scores (country, id);
    """,
    # 3: classifier output and scoring signals
    """
    CREATE TABLE classifications (
        id              INTEGER PRIMARY KEY,
        ref_type        TEXT NOT NULL,           -- change | snapshot | news
        ref_id          INTEGER NOT NULL,
        country         TEXT NOT NULL,
        publisher       TEXT NOT NULL,
        method          TEXT NOT NULL,           -- rules | claude
        payload         TEXT NOT NULL,           -- JSON (see classifier.Classification)
        created_at      TEXT NOT NULL,
        UNIQUE (ref_type, ref_id)
    );

    CREATE TABLE signals (
        id              INTEGER PRIMARY KEY,
        country         TEXT NOT NULL,
        block           TEXT NOT NULL,
        kind            TEXT NOT NULL,
        strength        REAL NOT NULL,
        publisher       TEXT NOT NULL,
        observed_at     TEXT NOT NULL,
        tier            INTEGER NOT NULL DEFAULT 1,
        confirmed       INTEGER NOT NULL DEFAULT 0,
        reason          TEXT NOT NULL DEFAULT 'unknown',
        state           INTEGER NOT NULL DEFAULT 0,
        active          INTEGER NOT NULL DEFAULT 1, -- states: 0 once superseded
        note            TEXT NOT NULL DEFAULT '',
        ref             TEXT NOT NULL DEFAULT ''    -- e.g. "snapshot:12", "news:<url>"
    );
    CREATE INDEX ix_signals_country ON signals (country, active, observed_at);
    CREATE UNIQUE INDEX ux_signals_ref ON signals (ref, kind, country) WHERE ref != '';
    """,
    # 4: measurements of non-advisory collectors
    """
    CREATE TABLE traffic (
        id              INTEGER PRIMARY KEY,
        country         TEXT NOT NULL,
        observed_at     TEXT NOT NULL,
        hour_of_week    INTEGER NOT NULL,
        aircraft        INTEGER NOT NULL
    );
    CREATE INDEX ix_traffic_country ON traffic (country, hour_of_week, observed_at);

    CREATE TABLE news_items (
        url             TEXT PRIMARY KEY,
        feed            TEXT NOT NULL,
        tier            INTEGER NOT NULL,
        title           TEXT NOT NULL,
        published       TEXT,
        countries       TEXT NOT NULL,           -- comma-separated ISO codes
        seen_at         TEXT NOT NULL,
        classified      INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE series (
        source          TEXT NOT NULL,
        country         TEXT NOT NULL,
        key             TEXT NOT NULL,           -- e.g. bond_10y, fx, gdelt_vol, gdelt_tone
        period          TEXT NOT NULL,
        value           REAL NOT NULL,
        PRIMARY KEY (source, country, key, period)
    );
    """,
    # 5: headline category (rules or Claude) and its severity
    """
    ALTER TABLE news_items ADD COLUMN category TEXT NOT NULL DEFAULT 'none';
    ALTER TABLE news_items ADD COLUMN severity REAL NOT NULL DEFAULT 1.0;
    """,
    # 6: several countries per user (users.country = the one shown in detail) and digest
    """
    CREATE TABLE user_countries (
        tg_id           INTEGER NOT NULL REFERENCES users (tg_id),
        country         TEXT NOT NULL,
        PRIMARY KEY (tg_id, country)
    );
    INSERT INTO user_countries (tg_id, country)
        SELECT tg_id, country FROM users WHERE country IS NOT NULL;
    ALTER TABLE users ADD COLUMN digest INTEGER NOT NULL DEFAULT 0;
    """,
    # 7: Ukrainian explanation next to the (usually English) quote
    """
    ALTER TABLE signals ADD COLUMN note_uk TEXT NOT NULL DEFAULT '';
    """,
    # 8: rule classifications of full texts missed everything when a page had a line starting
    # with "-" or "+" (read as a diff); redo them
    """
    DELETE FROM classifications WHERE method = 'rules';
    """,
    # 9: airspace rules narrowed (bare "NOTAM" no longer means restricted); redo rule results
    """
    DELETE FROM classifications WHERE method = 'rules';
    """,
]


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class Snapshot:
    id: int
    source: str
    country: str
    fetched_at: str
    content_hash: str
    text: str
    level: str | None = None


@asynccontextmanager
async def connect(path: Path) -> AsyncIterator[aiosqlite.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(path)
    try:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        yield db
    finally:
        await db.close()


async def migrate(db: aiosqlite.Connection) -> int:
    """Apply pending migrations; return the resulting schema version."""
    async with db.execute("PRAGMA user_version") as cur:
        row = await cur.fetchone()
    version = row[0] if row else 0
    for index, script in enumerate(MIGRATIONS[version:], start=version + 1):
        await db.executescript(script)
        await db.execute(f"PRAGMA user_version = {index}")
        await db.commit()
        version = index
    return version


async def latest_snapshot(db: aiosqlite.Connection, source: str, country: str) -> Snapshot | None:
    async with db.execute(
        "SELECT id, source, country, fetched_at, content_hash, text, level FROM snapshots "
        "WHERE source = ? AND country = ? ORDER BY id DESC LIMIT 1",
        (source, country),
    ) as cur:
        row = await cur.fetchone()
    return Snapshot(*row) if row else None


async def seen_versions(
    db: aiosqlite.Connection, source: str, country: str, since_iso: str
) -> set[tuple[str, str | None]]:
    """(content_hash, level) of the versions fetched since `since_iso`."""
    async with db.execute(
        "SELECT content_hash, level FROM snapshots WHERE source = ? AND country = ? "
        "AND fetched_at >= ?",
        (source, country, since_iso),
    ) as cur:
        return {(r[0], r[1]) for r in await cur.fetchall()}


async def insert_snapshot(
    db: aiosqlite.Connection,
    *,
    source: str,
    country: str,
    url: str,
    text: str,
    title: str | None = None,
    level: str | None = None,
    source_updated: str | None = None,
    fetched_at: str | None = None,  # set by the history loader (archive timestamp)
) -> int:
    cur = await db.execute(
        "INSERT INTO snapshots (source, country, fetched_at, source_updated, url, title, level, "
        "content_hash, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source, country, fetched_at or utcnow(), source_updated, url, title, level,
         content_hash(text), text),
    )  # fmt: skip
    return cur.lastrowid or 0


async def insert_change(
    db: aiosqlite.Connection,
    *,
    source: str,
    country: str,
    prev_snapshot: int | None,
    new_snapshot: int,
    diff: str,
    detected_at: str | None = None,
) -> int:
    cur = await db.execute(
        "INSERT INTO changes (source, country, detected_at, prev_snapshot, new_snapshot, diff) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (source, country, detected_at or utcnow(), prev_snapshot, new_snapshot, diff),
    )
    return cur.lastrowid or 0


async def start_run(db: aiosqlite.Connection, source: str) -> int:
    cur = await db.execute(
        "INSERT INTO collect_runs (source, started_at) VALUES (?, ?)", (source, utcnow())
    )
    await db.commit()
    return cur.lastrowid or 0


async def finish_run(
    db: aiosqlite.Connection,
    run_id: int,
    *,
    ok: bool,
    fetched: int,
    changed: int,
    failed: int,
    error: str | None = None,
) -> None:
    await db.execute(
        "UPDATE collect_runs SET finished_at = ?, ok = ?, fetched = ?, changed = ?, failed = ?, "
        "error = ? WHERE id = ?",
        (utcnow(), int(ok), fetched, changed, failed, error, run_id),
    )
    await db.commit()


async def last_runs(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    """Latest run per source (successful or not)."""
    async with db.execute(
        "SELECT r.* FROM collect_runs r JOIN ("
        "  SELECT source, MAX(id) AS id FROM collect_runs GROUP BY source"
        ") last ON last.id = r.id ORDER BY r.source"
    ) as cur:
        return list(await cur.fetchall())


async def last_success(db: aiosqlite.Connection, source: str) -> str | None:
    async with db.execute(
        "SELECT finished_at FROM collect_runs WHERE source = ? AND ok = 1 ORDER BY id DESC LIMIT 1",
        (source,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def recent_changes(db: aiosqlite.Connection, limit: int = 10) -> list[aiosqlite.Row]:
    async with db.execute(
        "SELECT id, source, country, detected_at FROM changes ORDER BY id DESC LIMIT ?", (limit,)
    ) as cur:
        return list(await cur.fetchall())


# --- Bot users ------------------------------------------------------------------------------


MAX_FOLLOWED = 5


@dataclass(slots=True)
class User:
    tg_id: int
    lang: str | None
    country: str | None  # the country shown in detail on the dashboard
    notify: bool
    digest: bool = False
    followed: list[str] = field(default_factory=list)


async def get_user(db: aiosqlite.Connection, tg_id: int) -> User | None:
    async with db.execute(
        "SELECT tg_id, lang, country, notify, digest FROM users WHERE tg_id = ?", (tg_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    async with db.execute(
        "SELECT country FROM user_countries WHERE tg_id = ? ORDER BY rowid", (tg_id,)
    ) as cur:
        followed = [r[0] for r in await cur.fetchall()]
    return User(row[0], row[1], row[2], bool(row[3]), bool(row[4]), followed)


async def set_followed(db: aiosqlite.Connection, tg_id: int, country: str, on: bool) -> User:
    """Follow/unfollow a country (max MAX_FOLLOWED); keeps users.country pointing at a
    followed country (or NULL when none is left)."""
    if on:
        await db.execute(
            "INSERT OR IGNORE INTO user_countries (tg_id, country) VALUES (?, ?)", (tg_id, country)
        )
    else:
        await db.execute(
            "DELETE FROM user_countries WHERE tg_id = ? AND country = ?", (tg_id, country)
        )
    await db.commit()
    user = await get_user(db, tg_id)
    assert user is not None
    if user.country not in user.followed:
        user = await upsert_user(db, tg_id, country=user.followed[0] if user.followed else None)
    elif on and len(user.followed) == 1:
        user = await upsert_user(db, tg_id, country=country)
    return user


_USER_FIELDS = {"lang", "country", "notify", "digest"}


async def upsert_user(db: aiosqlite.Connection, tg_id: int, **fields: object) -> User:
    unknown = set(fields) - _USER_FIELDS
    if unknown:
        raise ValueError(f"unknown user fields: {unknown}")
    now = utcnow()
    await db.execute(
        "INSERT INTO users (tg_id, created_at, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(tg_id) DO NOTHING",
        (tg_id, now, now),
    )
    if fields:
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = [int(v) if isinstance(v, bool) else v for v in fields.values()]
        await db.execute(
            f"UPDATE users SET {assignments}, updated_at = ? WHERE tg_id = ?",
            (*values, now, tg_id),
        )
    await db.commit()
    user = await get_user(db, tg_id)
    assert user is not None
    return user


async def subscribers(db: aiosqlite.Connection, country: str) -> list[User]:
    """Users following `country` with alerts on."""
    async with db.execute(
        "SELECT u.tg_id, u.lang, u.country, u.digest FROM users u JOIN user_countries f "
        "ON f.tg_id = u.tg_id WHERE f.country = ? AND u.notify = 1",
        (country,),
    ) as cur:
        return [User(r[0], r[1], r[2], True, bool(r[3])) for r in await cur.fetchall()]


async def digest_users(db: aiosqlite.Connection) -> list[User]:
    async with db.execute("SELECT tg_id FROM users WHERE digest = 1") as cur:
        ids = [r[0] for r in await cur.fetchall()]
    users = [await get_user(db, i) for i in ids]
    return [u for u in users if u and u.followed]


async def score_before(
    db: aiosqlite.Connection, country: str, before_iso: str
) -> aiosqlite.Row | None:
    """The latest score computed before a moment (for 24 h changes in the digest)."""
    async with db.execute(
        "SELECT score, level FROM scores WHERE country = ? AND computed_at < ? "
        "ORDER BY id DESC LIMIT 1",
        (country, before_iso),
    ) as cur:
        return await cur.fetchone()


# --- Scores and change stats ----------------------------------------------------------------


async def insert_score(
    db: aiosqlite.Connection, country: str, score: float | None, level: str | None, payload: str
) -> None:
    await db.execute(
        "INSERT INTO scores (country, computed_at, score, level, payload) VALUES (?, ?, ?, ?, ?)",
        (country, utcnow(), score, level, payload),
    )
    await db.commit()


async def latest_score(db: aiosqlite.Connection, country: str) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT country, computed_at, score, level, payload FROM scores "
        "WHERE country = ? ORDER BY id DESC LIMIT 1",
        (country,),
    ) as cur:
        return await cur.fetchone()


async def changes_since(db: aiosqlite.Connection, country: str, since_iso: str) -> int:
    async with db.execute(
        "SELECT COUNT(*) FROM changes WHERE country = ? AND detected_at >= ?", (country, since_iso)
    ) as cur:
        row = await cur.fetchone()
    return int(row[0]) if row else 0


# --- Classifications ------------------------------------------------------------------------


async def save_classification(
    db: aiosqlite.Connection,
    *,
    ref_type: str,
    ref_id: int,
    country: str,
    publisher: str,
    method: str,
    payload: str,
) -> None:
    await db.execute(
        "INSERT INTO classifications (ref_type, ref_id, country, publisher, method, payload, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(ref_type, ref_id) DO UPDATE SET "
        "method = excluded.method, payload = excluded.payload, created_at = excluded.created_at",
        (ref_type, ref_id, country, publisher, method, payload, utcnow()),
    )
    await db.commit()


async def get_classification(
    db: aiosqlite.Connection, ref_type: str, ref_id: int
) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT * FROM classifications WHERE ref_type = ? AND ref_id = ?", (ref_type, ref_id)
    ) as cur:
        return await cur.fetchone()


async def unclassified_changes(db: aiosqlite.Connection, limit: int = 100) -> list[aiosqlite.Row]:
    async with db.execute(
        "SELECT c.id, c.source, c.country, c.diff, c.new_snapshot, k.method FROM changes c "
        "LEFT JOIN classifications k ON k.ref_type = 'change' AND k.ref_id = c.id "
        "WHERE k.id IS NULL OR k.method = 'rules_pending' ORDER BY c.id LIMIT ?",
        (limit,),
    ) as cur:
        return list(await cur.fetchall())


async def latest_snapshots(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    """Current version of every (source, country) advisory."""
    async with db.execute(
        "SELECT s.* FROM snapshots s JOIN (SELECT source, country, MAX(id) AS id FROM snapshots "
        "GROUP BY source, country) last ON last.id = s.id ORDER BY s.country, s.source"
    ) as cur:
        return list(await cur.fetchall())


# --- Signals --------------------------------------------------------------------------------


async def upsert_signal(db: aiosqlite.Connection, s: Signal, ref: str) -> None:
    """Insert a signal or refresh it (same ref/kind/country) and mark it active."""
    await db.execute(
        "INSERT INTO signals (country, block, kind, strength, publisher, observed_at, tier, "
        "confirmed, reason, state, active, note, note_uk, ref) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?) "
        "ON CONFLICT (ref, kind, country) WHERE ref != '' DO UPDATE SET "
        "strength = excluded.strength, reason = excluded.reason, note = excluded.note, note_uk = excluded.note_uk, "
        "confirmed = excluded.confirmed, tier = excluded.tier, "
        "observed_at = excluded.observed_at, active = 1",
        (s.country, s.block, s.kind, s.strength, s.publisher, s.observed_at.isoformat(), s.tier,
         int(s.confirmed), s.reason, int(s.state), s.note, s.note_uk, ref),
    )  # fmt: skip


async def deactivate_signals(db: aiosqlite.Connection, publisher: str, keep_refs: set[str]) -> None:
    """Deactivate a publisher's state signals whose ref is no longer current."""
    async with db.execute(
        "SELECT id, ref FROM signals WHERE publisher = ? AND active = 1 AND state = 1", (publisher,)
    ) as cur:
        rows = await cur.fetchall()
    for row in rows:
        if row["ref"] not in keep_refs:
            await db.execute("UPDATE signals SET active = 0 WHERE id = ?", (row["id"],))


async def finish(db: aiosqlite.Connection, result: object, run_id: int) -> None:
    """Close a collect_runs row from a collector.RunResult-like object."""
    await finish_run(
        db, run_id, ok=result.ok, fetched=result.fetched, changed=result.changed,  # type: ignore[attr-defined]
        failed=result.failed, error="\n".join(result.errors[:20]) or None,  # type: ignore[attr-defined]
    )  # fmt: skip
