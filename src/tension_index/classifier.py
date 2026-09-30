"""Classify advisory changes: why the text changed and what it means for the scale.

Two layers:
- `classify_rules`: deterministic keyword rules. Always available (no API key, tests,
  backtests), and the fallback when Claude is unavailable, refuses or the spend cap is hit.
- `ClaudeClassifier`: Claude with a strict JSON schema. The model and effort come from
  settings (CLASSIFIER_MODEL / CLASSIFIER_EFFORT); only changed fragments are sent.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field

from tension_index.config import Settings

log = logging.getLogger(__name__)

REASONS = (
    "armed_conflict", "military_threat", "hybrid_attack", "civil_unrest", "terrorism",
    "crime", "health", "natural_disaster", "unknown",
)  # fmt: skip
CHANGE_TYPES = (
    "level_raised", "level_lowered", "staff_posture", "consular", "borders", "airspace",
    "security_update", "editorial", "none",
)  # fmt: skip
STAFF = (
    "normal", "limited_consular_services", "authorized_departure", "ordered_departure",
    "embassy_suspended", "unknown",
)  # fmt: skip
AIRSPACE = ("normal", "restricted", "closed", "unknown")


@dataclass(slots=True)
class Classification:
    reason: str = "unknown"
    change_type: str = "none"
    level: str = ""  # publisher level key when the text states it (e.g. FR "orange")
    staff_posture: str = "unknown"
    airspace: str = "unknown"
    borders_closed: bool = False
    quote: str = ""
    summary_uk: str = ""
    summary_en: str = ""
    method: str = "rules"
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> Classification:
        data = json.loads(raw)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# --- Rules ----------------------------------------------------------------------------------

_STAFF_RULES = [  # most severe first
    ("embassy_suspended", r"suspended (its |all )?operations|embassy (is |has )?(closed|suspended)|"
     r"ambassade (est )?fermée|botschaft (ist )?geschlossen"),
    ("ordered_departure", r"ordered (the )?departure|départ ordonné"),
    ("authorized_departure", r"authori[sz]ed (the )?(voluntary )?departure"),
    ("limited_consular_services", r"limited consular (services|assistance)|"
     r"(unable|not able) to provide consular"),
]  # fmt: skip
_REASON_RULES = {  # order = severity for ties
    "armed_conflict": r"armed conflict|military (action|attack|operations?)|invasion|hostilities|"
    r"missile|shelling|\bwar\b|krieg|conflit armé|frappes",
    "military_threat": r"military (build-?up|exercises?|activity|threat)|troops? (near|along|"
    r"massing)|mobili[sz]ation|militärische",
    "hybrid_attack": r"drones?|sabotage|gps (jamming|interference)|cyber.?attack|hybrid",
    "civil_unrest": r"civil unrest|demonstrations?|protests?|riots?|manifestations?",
    "terrorism": r"terror",
    "crime": r"\bcrime|criminal|theft|pickpocket",
    "health": r"health|disease|outbreak|epidemic|pandemic|covid",
    "natural_disaster": r"earthquake|flood|wildfire|hurricane|volcan|storm",
}
_AIRSPACE_RULES = [
    ("closed", r"airspace (is |has been |remains )?closed|closed (its |the )?airspace|"
     r"espace aérien (est )?fermé|luftraum (ist )?gesperrt"),
    ("restricted", r"airspace restrictions?|restricted airspace|flight restrictions|notam"),
]  # fmt: skip
_BORDERS = re.compile(
    r"borders? (crossings? )?(are |is |has been |have been |remain )?closed|"
    r"closed (its |the )?borders?|frontières? fermées?|grenze (ist )?geschlossen",
    re.I,
)
_LEVEL_LINE = re.compile(r"^LEVEL: (.*?) -> (.*)$", re.M)


def _added_lines(diff: str) -> str:
    """For a unified diff keep only added lines; for plain text return it unchanged."""
    lines = diff.splitlines()
    if any(line.startswith(("+", "-", "@@")) for line in lines):
        return "\n".join(line[1:] for line in lines if line.startswith("+"))
    return diff


def classify_rules(text: str, *, level_change: tuple[float, float] | None = None) -> Classification:
    """`text`: a unified diff (only added lines are read) or a full advisory text.
    `level_change`: (old, new) strength when the publisher's level changed."""
    added = _added_lines(text)
    low = added.lower()
    result = Classification()

    for posture, pattern in _STAFF_RULES:
        if re.search(pattern, low):
            result.staff_posture = posture
            break
    for state, pattern in _AIRSPACE_RULES:
        if re.search(pattern, low):
            result.airspace = state
            break
    result.borders_closed = bool(_BORDERS.search(added))

    hits = {r: len(re.findall(p, low)) for r, p in _REASON_RULES.items()}
    best = max(hits.values(), default=0)
    if best:
        result.reason = next(r for r in _REASON_RULES if hits[r] == best)

    if level_change and level_change[1] > level_change[0]:
        result.change_type = "level_raised"
    elif level_change and level_change[1] < level_change[0]:
        result.change_type = "level_lowered"
    elif result.staff_posture not in ("unknown", "normal"):
        result.change_type = "staff_posture"
    elif result.airspace != "unknown":
        result.change_type = "airspace"
    elif result.borders_closed:
        result.change_type = "borders"
    elif added.strip():
        result.change_type = "security_update" if best else "editorial"

    pattern = "|".join(
        [p for _, p in _STAFF_RULES]
        + [p for _, p in _AIRSPACE_RULES]
        + list(_REASON_RULES.values())
    )
    quote_line = next(
        (ln for ln in added.splitlines() if re.search(pattern, ln.lower())),
        next((ln for ln in added.splitlines() if ln.strip()), ""),
    )
    result.quote = quote_line.strip()[:300]
    return result


# --- Claude ---------------------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string", "enum": list(REASONS)},
        "change_type": {"type": "string", "enum": list(CHANGE_TYPES)},
        "level": {"type": "string"},
        "staff_posture": {"type": "string", "enum": list(STAFF)},
        "airspace": {"type": "string", "enum": list(AIRSPACE)},
        "borders_closed": {"type": "boolean"},
        "quote": {"type": "string"},
        "summary_uk": {"type": "string"},
        "summary_en": {"type": "string"},
    },
    "required": [
        "reason", "change_type", "level", "staff_posture", "airspace", "borders_closed",
        "quote", "summary_uk", "summary_en",
    ],
    "additionalProperties": False,
}  # fmt: skip

SYSTEM_PROMPT = """You classify changes in official government travel advisories for European \
countries. The output feeds an indicator of escalation signals (not a forecast of war).

You receive: the publishing government, the country the advice is about, the advice level \
before and after (if the publisher has structured levels), and either a unified diff of the \
advice text (lines starting with "+" were added, "-" removed) or the full current text.

Fill every field of the JSON schema:

- reason: the main stated reason for the advice or for the change.
  armed_conflict = fighting, military attacks, missiles, invasion, war on or near the territory.
  military_threat = troop build-ups, military exercises near the border, mobilisation, \
threat of attack.
  hybrid_attack = drones over infrastructure, sabotage, GPS jamming, cyber attacks by a state.
  civil_unrest = protests, riots, political instability. terrorism = terrorist threat or attacks.
  crime, health, natural_disaster as named. unknown = no reason stated or only editorial text.
  Judge the reason by substance, not by keywords: "no known terrorist threat" is not terrorism.
- change_type: what changed. level_raised / level_lowered when the overall level changed; \
staff_posture for embassy staff departures or embassy closure; consular for changes to consular \
services; borders for border closures or crossing restrictions; airspace for flight or airspace \
restrictions; security_update for other substantive security wording; editorial for formatting, \
contact details, dates or non-security topics (visas, customs, driving); none if nothing changed.
- level: only for publishers without structured levels (France: vert, jaune, orange, rouge as \
stated for the whole country); otherwise an empty string.
- staff_posture: the embassy staff situation stated in the text. authorized_departure = \
voluntary departure of staff/families allowed; ordered_departure = departure ordered; \
embassy_suspended = embassy closed or operations suspended; limited_consular_services; \
normal if explicitly normal; unknown if not mentioned.
- airspace: closed / restricted if the text says so for the country, normal if it explicitly \
says flights operate normally, unknown otherwise.
- borders_closed: true only if land borders of the country are stated to be closed.
- quote: one sentence copied verbatim from the added or current text that best supports the \
classification (max 300 characters). Empty if nothing substantive.
- summary_uk / summary_en: one short neutral sentence each (Ukrainian / English) saying what \
changed, for a notification to the public. Do not speculate or predict."""


# Models that accept server-side refusal fallbacks (`fallbacks: "default"`).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


class ClaudeClassifier:
    """Claude with strict JSON output. Falls back to rules on refusal, API errors or when
    the per-run call cap is reached (keeps spend bounded)."""

    def __init__(self, settings: Settings, client: object | None = None) -> None:
        self.settings = settings
        self.calls = 0
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.client = client

    @property
    def available(self) -> bool:
        return self.calls < self.settings.classifier_max_calls

    def _request(self, user: str) -> dict:
        return {
            "model": self.settings.classifier_model,
            "max_tokens": 2048,
            "system": [
                {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "format": {"type": "json_schema", "schema": SCHEMA},
                # effort is not accepted by every model (e.g. Haiku 4.5): empty = omit
                **(
                    {"effort": self.settings.classifier_effort}
                    if self.settings.classifier_effort
                    else {}
                ),
            },
        }

    async def classify(
        self,
        *,
        publisher: str,
        country: str,
        text: str,
        level_before: str | None,
        level_after: str | None,
        fallback: Classification,
    ) -> Classification:
        if not self.available:
            fallback.notes.append("claude: per-run cap reached, rules used")
            return fallback
        import anthropic

        user = (
            f"Publisher: {publisher}\nCountry: {country}\n"
            f"Level before: {level_before or 'n/a'}\nLevel after: {level_after or 'n/a'}\n\n"
            f"<advisory>\n{text[:12000]}\n</advisory>"
        )
        self.calls += 1
        try:
            extra = (
                {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
                if self.settings.classifier_model in FALLBACK_MODELS
                else {}
            )
            response = await self.client.beta.messages.create(**self._request(user), **extra)
        except (anthropic.APIConnectionError, anthropic.RateLimitError) as exc:
            log.warning("Claude unavailable (%s); using rules", exc)
            fallback.notes.append(f"claude: {type(exc).__name__}, rules used")
            return fallback
        except anthropic.APIStatusError as exc:
            log.warning("Claude API error %s; using rules", exc.status_code)
            fallback.notes.append(f"claude: HTTP {exc.status_code}, rules used")
            return fallback

        if response.stop_reason == "refusal":
            fallback.notes.append("claude: refusal, rules used")
            return fallback
        text_out = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text_out)
            result = Classification(**{k: data[k] for k in SCHEMA["required"]})
        except (ValueError, KeyError, TypeError):
            fallback.notes.append("claude: unparseable output, rules used")
            return fallback
        result.method = "claude"
        result.quote = result.quote[:300]
        # Keep the deterministic level-change direction: it comes from structured data.
        if fallback.change_type in ("level_raised", "level_lowered"):
            result.change_type = fallback.change_type
        return result


# --- Headlines ------------------------------------------------------------------------------

HEADLINE_CATEGORIES = (
    "armed_attack", "mobilisation", "domestic_emergency", "aggressor_advisory",
    "hybrid_attack", "military_threat", "escalation_news", "none",
)  # fmt: skip
HEADLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "category": {"type": "string", "enum": list(HEADLINE_CATEGORIES)},
                    "severity": {"type": "number"},
                },
                "required": ["i", "category", "severity"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}
HEADLINE_PROMPT = """You label news headlines about European countries for an indicator of \
escalation signals. For each numbered headline return its category and a severity 0..1.

Categories (about the country named in the headline):
- armed_attack: a military attack actually happened on its territory (missile/drone strike, \
troops crossing the border, shelling).
- mobilisation: the country actually declared or ordered mobilisation (not debates or drills).
- domestic_emergency: state of emergency, martial law, border closure, evacuation orders, \
shelters prepared because of a threat, air-raid alerts.
- aggressor_advisory: Russia's or Belarus's government advises its citizens to avoid or \
leave the country, or reduces its embassy there.
- hybrid_attack: sabotage, GPS jamming, airspace violations by drones/aircraft, attacks on \
infrastructure or undersea cables attributed to a state.
- military_threat: troop build-ups or exercises near its border, explicit threats of attack.
- escalation_news: other reporting on rising military tension involving the country.
- none: anything else (politics, economy, sport, routine defence procurement, history).

Severity: 1 = confirmed, large-scale, official; 0.5 = partial or unconfirmed; 0.2 = minor.
Label by what the headline states happened, not by alarming words."""


async def classify_headlines(
    claude: ClaudeClassifier, headlines: list[str]
) -> dict[int, tuple[str, float]] | None:
    """{index: (category, severity)} from Claude, or None (then rules are used)."""
    if not headlines or not claude.available:
        return None
    import anthropic

    numbered = "\n".join(f"{i}. {h}" for i, h in enumerate(headlines))
    request = claude._request(numbered)
    request["system"] = [
        {"type": "text", "text": HEADLINE_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]
    request["output_config"]["format"] = {"type": "json_schema", "schema": HEADLINE_SCHEMA}
    request["max_tokens"] = 8192
    extra = (
        {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        if claude.settings.classifier_model in FALLBACK_MODELS
        else {}
    )
    claude.calls += 1
    try:
        response = await claude.client.beta.messages.create(**request, **extra)
    except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
        log.warning("Claude headline classification failed: %s", exc)
        return None
    if response.stop_reason == "refusal":
        return None
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        items = json.loads(text)["items"]
    except (ValueError, KeyError, TypeError):
        return None
    return {
        int(x["i"]): (x["category"], max(0.0, min(1.0, float(x["severity"]))))
        for x in items
        if 0 <= int(x["i"]) < len(headlines) and x["category"] in HEADLINE_CATEGORIES
    }
