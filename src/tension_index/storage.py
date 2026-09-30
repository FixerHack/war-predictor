"""SQLite storage with simple forward-only migrations (PRAGMA user_version).

Every fetched advisory text is stored in full so versions can be diffed and the
history replayed later (backtesting, re-scoring with new weights).
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

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
) -> int:
    cur = await db.execute(
        "INSERT INTO snapshots (source, country, fetched_at, source_updated, url, title, level, "
        "content_hash, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source, country, utcnow(), source_updated, url, title, level, content_hash(text), text),
    )
    return cur.lastrowid or 0


async def insert_change(
    db: aiosqlite.Connection,
    *,
    source: str,
    country: str,
    prev_snapshot: int | None,
    new_snapshot: int,
    diff: str,
) -> int:
    cur = await db.execute(
        "INSERT INTO changes (source, country, detected_at, prev_snapshot, new_snapshot, diff) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (source, country, utcnow(), prev_snapshot, new_snapshot, diff),
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


@dataclass(slots=True)
class User:
    tg_id: int
    lang: str | None
    country: str | None
    notify: bool


async def get_user(db: aiosqlite.Connection, tg_id: int) -> User | None:
    async with db.execute(
        "SELECT tg_id, lang, country, notify FROM users WHERE tg_id = ?", (tg_id,)
    ) as cur:
        row = await cur.fetchone()
    return User(row[0], row[1], row[2], bool(row[3])) if row else None


_USER_FIELDS = {"lang", "country", "notify"}


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
    async with db.execute(
        "SELECT tg_id, lang, country, notify FROM users WHERE country = ? AND notify = 1",
        (country,),
    ) as cur:
        return [User(r[0], r[1], r[2], True) for r in await cur.fetchall()]


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
