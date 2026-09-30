"""Health checks used by `tension-index health`, the bot's /status and scripts/healthcheck.sh.

Exit codes follow the Nagios convention: 0 = OK, 1 = WARN, 2 = FAIL.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path

from tension_index import storage
from tension_index.config import Settings
from tension_index.pipeline import source_blocks


class Status(IntEnum):
    OK = 0
    WARN = 1
    FAIL = 2


@dataclass(slots=True)
class Check:
    name: str
    status: Status
    detail: str

    def as_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.name
        return data


@dataclass(slots=True)
class Report:
    checks: list[Check]

    @property
    def status(self) -> Status:
        return max((c.status for c in self.checks), default=Status.OK)

    def as_dict(self) -> dict:
        return {
            "status": self.status.name,
            "checked_at": storage.utcnow(),
            "checks": [c.as_dict() for c in self.checks],
        }

    def as_text(self) -> str:
        icon = {Status.OK: "✅", Status.WARN: "⚠️", Status.FAIL: "❌"}
        lines = [f"{icon[self.status]} overall: {self.status.name}"]
        lines += [f"{icon[c.status]} {c.name}: {c.detail}" for c in self.checks]
        return "\n".join(lines)


def _age_hours(iso: str) -> float:
    return (datetime.now(UTC) - datetime.fromisoformat(iso)).total_seconds() / 3600


def check_config(settings: Settings) -> list[Check]:
    checks = []
    tg_ok = bool(settings.telegram_bot_token and settings.telegram_chat_id)
    checks.append(
        Check(
            "config.telegram",
            Status.OK if tg_ok else Status.WARN,
            "token and chat id set" if tg_ok else "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing",
        )
    )
    return checks


def check_disk(path: Path, min_free_mb: int) -> Check:
    path.mkdir(parents=True, exist_ok=True)
    free_mb = shutil.disk_usage(path).free // (1024 * 1024)
    status = Status.OK if free_mb >= min_free_mb else Status.FAIL
    return Check("disk", status, f"{free_mb} MB free (min {min_free_mb})")


async def run_checks(settings: Settings, db_path: Path | None = None) -> Report:
    db_path = db_path or settings.database_path
    checks = check_config(settings)
    checks.append(check_disk(db_path.parent, settings.health_min_free_disk_mb))
    try:
        async with storage.connect(db_path) as db:
            version = await storage.migrate(db)
            checks.append(Check("database", Status.OK, f"schema v{version} at {db_path}"))
            for name in source_blocks():
                last = await storage.last_success(db, name)
                if last is None:
                    checks.append(Check(f"collector.{name}", Status.WARN, "no successful run yet"))
                    continue
                age = _age_hours(last)
                status = Status.OK if age <= settings.health_max_collect_age_hours else Status.FAIL
                checks.append(
                    Check(f"collector.{name}", status, f"last success {age:.1f} h ago ({last})")
                )
    except Exception as exc:  # health must report, never crash
        checks.append(Check("database", Status.FAIL, f"{type(exc).__name__}: {exc}"))
    return Report(checks)
