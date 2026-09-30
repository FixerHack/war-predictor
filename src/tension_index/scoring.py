"""Tension scale 0-10: turns classified signals into a per-country score.

Pure functions only (no I/O) so the same code runs live and in backtests.
The maths is documented in docs/algorithm.md; numbers live in config/weights.yaml.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

from tension_index.countries import get_country

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "weights.yaml"
REASON_BLOCKS = {"advisories", "aggressor"}


@dataclass(slots=True)
class Signal:
    country: str
    block: str  # advisories | aviation | domestic | aggressor | media | markets
    kind: (
        str  # e.g. "advisory_level", "staff_posture:ordered_departure", "aviation:airspace_closed"
    )
    strength: float  # 0..1 before reason relevance and decay
    publisher: str  # who says it: "us", "gov_uk", "easa", "gdelt", ...
    observed_at: datetime
    tier: int = 1  # source trust tier 1..4
    confirmed: bool = False  # tier 3-4 item corroborated by tier 1-2
    reason: str = "unknown"  # classifier reason (advisories/aggressor only)
    state: bool = False  # True: holds while active (no decay); False: one-off event (decays)
    note: str = ""  # quote / human explanation shown to users
    note_uk: str = ""  # the same in Ukrainian when available (Claude summary, templates)


@dataclass(slots=True)
class Contribution:
    block: str
    publisher: str
    kind: str
    value: float
    note: str
    note_uk: str = ""


@dataclass(slots=True)
class ScoreResult:
    country: str
    score: float | None  # None when coverage is too low to publish
    level: str | None
    raw: float  # composite R before surge/synchrony, 0..1
    blocks: dict[str, float]
    flags: list[str] = field(default_factory=list)
    floors: list[str] = field(default_factory=list)
    top: list[Contribution] = field(default_factory=list)
    dropped_unverified: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@lru_cache
def load_config(path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def advisory_strength(cfg: dict, publisher: str, level: str | None) -> float:
    """Map a publisher-specific advisory level (e.g. US "3") to 0..1. Several statuses
    joined by commas (GOV.UK alert_status) take the strongest."""
    table = cfg["advisory_levels"].get(publisher, {})
    parts = [p.strip() for p in str(level or "").split(",") if p.strip()]
    return max((float(table.get(p, 0.0)) for p in parts), default=0.0)


def level_for(cfg: dict, score: float) -> str:
    for band in cfg["levels"]:
        if score <= band["max"]:
            return band["key"]
    return cfg["levels"][-1]["key"]


def _effective(cfg: dict, s: Signal, now: datetime) -> float:
    value = max(0.0, min(1.0, s.strength))
    if s.block in REASON_BLOCKS:
        value *= cfg["reason_relevance"].get(s.reason, cfg["reason_relevance"]["unknown"])
    if not s.state:
        age_days = max(0.0, (now - s.observed_at).total_seconds() / 86400)
        value *= 0.5 ** (age_days / cfg["blocks"][s.block]["half_life_days"])
    return value


def block_scores(
    cfg: dict, signals: list[Signal], now: datetime
) -> tuple[dict[str, float], list[Contribution]]:
    """Per block: strongest signal per publisher, then noisy-OR across independent publishers,
    so one source repeating itself does not stack but independent confirmation does."""
    per_pub: dict[tuple[str, str], Contribution] = {}
    for s in signals:
        value = _effective(cfg, s, now)
        key = (s.block, s.publisher)
        if key not in per_pub or value > per_pub[key].value:
            per_pub[key] = Contribution(s.block, s.publisher, s.kind, value, s.note, s.note_uk)
    blocks = dict.fromkeys(cfg["blocks"], 0.0)
    for block in blocks:
        remaining = 1.0
        for (b, _), c in per_pub.items():
            if b == block:
                remaining *= 1.0 - c.value
        blocks[block] = 1.0 - remaining
    top = sorted(per_pub.values(), key=lambda c: c.value, reverse=True)
    return blocks, [c for c in top if c.value > 0.01][:5]


def block_caps(cfg: dict, country: str) -> dict[str, float]:
    caps = {k: v["cap"] for k, v in cfg["blocks"].items()}
    if get_country(country).nato_eu:
        for block, mult in cfg["group_block_multipliers"].get("nato_eu", {}).items():
            caps[block] *= mult
    return caps


def combine(blocks: dict[str, float], caps: dict[str, float]) -> float:
    """Independent-confirmation composite R in 0..1."""
    remaining = 1.0
    for block, value in blocks.items():
        remaining *= 1.0 - caps[block] * value
    return 1.0 - remaining


def compute_score(
    country: str,
    signals: list[Signal],
    now: datetime,
    *,
    history: list[float] | None = None,
    history_days: int = 0,
    peers_surging: list[bool] | None = None,
    covered_blocks: set[str] | None = None,
    cfg: dict | None = None,
) -> ScoreResult:
    """Score one country.

    history: this country's past raw composites (R) inside the baseline window.
    peers_surging: for each peer in the same region, whether it is surging now.
    covered_blocks: blocks whose collectors produced fresh data (None = don't check).
    """
    cfg = cfg or load_config()
    max_tier = cfg["verification"]["max_unconfirmed_tier"]
    own = [s for s in signals if s.country == country]
    usable = [s for s in own if s.tier <= max_tier or s.confirmed]
    dropped = len(own) - len(usable)

    blocks, top = block_scores(cfg, usable, now)
    caps = block_caps(cfg, country)
    raw = combine(blocks, caps)
    flags: list[str] = []

    # Surge above the country's own norm.
    base_cfg = cfg["baseline"]
    deviation = 0.0
    adjusted = raw
    if history and history_days >= base_cfg["min_history_days"]:
        deviation = raw - statistics.median(history)
        # Capped: a surge sharpens the picture but must not replace decisive events (floors).
        bonus = base_cfg["surge_weight"] * max(0.0, deviation)
        adjusted += min(bonus, base_cfg["surge_cap"])
    else:
        flags.append("short_history")

    # Several governments tightening within a week.
    syn = cfg["synchrony"]
    recent = now - timedelta(days=syn["window_days"])
    # Only real tightening counts: a raised level, staff posture, consular/border/airspace
    # measures - for a relevant reason. Routine rewording and terrorism notes do not.
    relevance = cfg["reason_relevance"]
    tightening = {
        s.publisher
        for s in usable
        if s.block == "advisories"
        and s.kind not in syn["ignore_kinds"]
        and s.observed_at >= recent
        and relevance.get(s.reason, relevance["unknown"]) >= syn["min_relevance"]
        and _effective(cfg, s, now) > 0
    }
    if len(tightening) >= syn["min_governments"]:
        adjusted *= syn["multiplier"]
        flags.append(f"synchrony:{len(tightening)}")

    # Regional comparison: alone vs together with peers.
    reg = cfg["regional"]
    if peers_surging and deviation >= reg["surge_threshold"]:
        share = sum(peers_surging) / len(peers_surging)
        if share >= reg["regional_share"]:
            flags.append("regional_escalation")
        elif share == 0:
            flags.append("isolated")
            adjusted *= reg["isolated_factor"]

    adjusted = min(1.0, adjusted)
    score = 10.0 * adjusted ** cfg.get("curve_gamma", 1.0)

    # Hard floors for decisive events.
    hit_floors: list[str] = []
    for rule in cfg["floors"]:
        kinds = {rule["when"]} if isinstance(rule["when"], str) else set(rule["when"])
        publishers = {s.publisher for s in usable if s.kind in kinds}
        needed = max(1, rule["min_governments"])
        if len(publishers) >= needed and score < rule["score"]:
            score = rule["score"]
            hit_floors.append(sorted(kinds)[0] if len(kinds) == 1 else "|".join(sorted(kinds)))

    if covered_blocks is not None:
        coverage = sum(caps[b] for b in covered_blocks if b in caps) / sum(caps.values())
        if coverage < cfg["min_coverage"]:
            flags.append("low_coverage")
            # Decisive events are published even when other blocks lack data.
            if not hit_floors:
                return ScoreResult(
                    country, None, None, raw, blocks, flags, hit_floors, top, dropped
                )

    score = round(min(10.0, score), 1)
    return ScoreResult(
        country, score, level_for(cfg, score), raw, blocks, flags, hit_floors, top, dropped
    )
