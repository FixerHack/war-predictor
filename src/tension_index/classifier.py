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
    # Why the staff posture / airspace / border measure was taken, when it differs from the
    # advice as a whole (e.g. COVID-19 border closures in an advisory about a conflict).
    measure_reason: str = ""
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


QUOTE_MIN_WORDS = 4
QUOTE_MIN_CHARS = 20

# Rules result kept while the model was unavailable (cap, credits, outage): retried later.
PENDING = "rules_pending"


# --- Rules ----------------------------------------------------------------------------------

_FAMILY = r" of (eligible )?(family members|dependents|dependants)"
_STAFF_RULES = [  # most severe first
    ("embassy_suspended", r"suspend(ed|ing|s)? (its |all )?(embassy )?operations|"
     r"embassy (is |has )?(closed|suspended)|ambassade (est )?fermée|botschaft (ist )?geschlossen"),
    # Ordering only families out is the step before ordering staff out: counted as authorized.
    ("ordered_departure", rf"ordered (the )?departure(?!{_FAMILY})|départ ordonné|"
     r"relocat(ed|ing) (its |our )?(embassy|embassy staff|diplomatic staff) (operations )?to"),
    ("authorized_departure", rf"authori[sz]ed (the )?(voluntary )?departure|ordered (the )?departure{_FAMILY}|"
     r"(staff|dependants|dependents)[\w ,]{0,40}(are being|have been|being) withdrawn|"
     r"withdraw(ing|n)? (some |non-essential )?(embassy )?staff"),
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
    # Country-level wording only: "NOTAM" or drone rules near an airport are routine.
    ("restricted", r"airspace (is |has been |remains )?(partially )?(restricted|limited)|"
     r"closed (parts|part|sections) of (its |the )?airspace|restrictions on (the use of )?"
     r"(its |the )?airspace"),
]  # fmt: skip
_BORDERS = re.compile(
    r"borders? (crossings? )?(are |is |has been |have been |remain )?closed|"
    r"closed (its |the )?borders?|frontières? fermées?|grenze (ist )?geschlossen",
    re.I,
)
_LEVEL_LINE = re.compile(r"^LEVEL: (.*?) -> (.*)$", re.M)


def _added_lines(diff: str) -> str:
    """For a unified diff keep only added lines; for plain text return it unchanged."""
    # Only our own diffs count as diffs (hunk headers or a LEVEL line): a page with a bullet
    # "- ..." or a phone "+1 ..." is still a full text.
    lines = diff.splitlines()
    if lines and (lines[0].startswith("LEVEL:") or any(line.startswith("@@") for line in lines)):
        return "\n".join(line[1:] for line in lines if line.startswith("+"))
    return diff


_PANDEMIC = re.compile(r"covid|coronavirus|pandemic|quarantine|sanitary|epidemi", re.I)


def _measure_reason(text: str) -> str:
    """The reason stated in the sentence of a measure (posture, airspace, borders): health for
    COVID, else the reason words of that sentence, else unknown ("" when no measure)."""
    patterns = [p for _, p in _STAFF_RULES] + [p for _, p in _AIRSPACE_RULES] + [_BORDERS.pattern]
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        low = sentence.lower()
        if not any(re.search(p, low) for p in patterns):
            continue
        if _PANDEMIC.search(sentence):
            return "health"
        return next((r for r, p in _REASON_RULES.items() if re.search(p, low)), "unknown")
    return ""


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
    result.measure_reason = _measure_reason(added)

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
    result.quote = usable_quote(quote_line)
    return result


def usable_quote(text: str) -> str:
    """A quote worth showing to users: a sentence, not a page fragment like "3 pays"."""
    text = " ".join(text.split())[:300]
    words = re.findall(r"[^\W\d_]{2,}", text)
    return text if len(words) >= QUOTE_MIN_WORDS and len(text) >= QUOTE_MIN_CHARS else ""


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
        "measure_reason": {"type": "string", "enum": list(REASONS)},
        "quote": {"type": "string"},
        "summary_uk": {"type": "string"},
        "summary_en": {"type": "string"},
    },
    "required": [
        "reason", "change_type", "level", "staff_posture", "airspace", "borders_closed",
        "measure_reason", "quote", "summary_uk", "summary_en",
    ],
    "additionalProperties": False,
}  # fmt: skip

SYSTEM_PROMPT = """You classify changes in official government travel advisories for European \
countries. The output feeds an indicator of escalation signals (not a forecast of war).

You receive: the publishing government, the country the advice is about, the advice level \
before and after (if the publisher has structured levels), and either a unified diff of the \
advice text (lines starting with "+" were added, "-" removed) or the full current text.

Fill every field of the JSON schema:

- reason: the main stated reason for the overall advice level for the country as a whole (or \
for the change). A reason given only for some regions (e.g. areas occupied for years) counts \
only when it sets the overall level; e.g. "Level 4 due to COVID-19, some areas have increased \
risk due to armed conflict" is health.
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
- airspace: closed / restricted if the text says the country's airspace is closed or \
restricted as a whole or over a large part of it because of a security threat, normal if it \
explicitly says flights operate normally, unknown otherwise. Routine NOTAMs, drone rules near \
airports, strikes, weather, and restrictions limited to occupied or separatist areas that have \
been in place for years are unknown.
- borders_closed: true only if land borders of the country are stated to be closed.
- measure_reason: the reason for the staff posture, airspace or border measure you reported \
(same values as reason; health for COVID-19 measures such as flight bans or reduced consular \
services). Use unknown when no such measure is reported.
- quote: one sentence copied verbatim from the added or current text that best supports the \
classification (max 300 characters). Empty if nothing substantive.
- summary_uk / summary_en: one short neutral sentence each (Ukrainian / English) saying what \
changed, for a notification to the public. Do not speculate or predict."""


# Models that accept server-side refusal fallbacks (`fallbacks: "default"`).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
    "openrouter": "anthropic/claude-haiku-4.5",
    "claude_code": "haiku",  # an alias the Claude Code CLI resolves
}
CLAUDE_CODE_TIMEOUT = 90  # seconds per call (the CLI starts a short session each time)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class ClaudeClassifier:
    """Claude with strict JSON output, directly (Anthropic API) or through OpenRouter.
    Falls back to rules on refusal, API errors or when the per-run call cap is reached
    (keeps spend bounded)."""

    def __init__(self, settings: Settings, client: object | None = None) -> None:
        self.settings = settings
        self.provider = settings.classifier_provider
        self.model = settings.classifier_model or DEFAULT_MODELS[self.provider]
        self.calls = 0
        self.stopped = ""  # set on an account error (no credits, bad key): no more calls this run
        if client is None and self.provider != "claude_code":
            if self.provider == "openrouter":
                import httpx

                client = httpx.AsyncClient(timeout=120)
            else:
                import anthropic

                client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.client = client

    @property
    def available(self) -> bool:
        return not self.stopped and self.calls < self.settings.classifier_max_calls

    def _account_error(self, status: int, detail: str) -> bool:
        """401/402/403: the key or the credits are the problem - retrying is pointless."""
        if status not in (401, 402, 403):
            return False
        self.stopped = f"HTTP {status}"
        log.error(
            "classifier stopped for this run (%s %s): %s - rules used, the model will "
            "re-classify these texts on a later run", self.provider, status, detail[:200],
        )  # fmt: skip
        return True

    async def _call(
        self, system: str, user: str, schema: dict, max_tokens: int
    ) -> tuple[str | None, str]:
        """JSON text from the model, or (None, reason) so the caller can fall back."""
        self.calls += 1
        if self.provider == "openrouter":
            return await self._call_openrouter(system, user, schema, max_tokens)
        if self.provider == "claude_code":
            return await self._call_claude_code(system, user, schema)
        return await self._call_anthropic(system, user, schema, max_tokens)

    async def _call_claude_code(
        self, system: str, user: str, schema: dict
    ) -> tuple[str | None, str]:
        """One non-interactive `claude -p` call: no tools, no saved session, JSON validated
        against the schema. Runs in a temporary directory so no CLAUDE.md is picked up."""
        import asyncio
        import tempfile
        import time

        started = time.monotonic()
        args = [
            self.settings.claude_code_bin, "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(schema),
            "--system-prompt", system,
            "--model", self.model,
            "--tools", "",
            "--disallowedTools", "mcp__*",
            "--no-session-persistence",
        ]  # fmt: skip
        try:
            with tempfile.TemporaryDirectory() as cwd:
                proc = await asyncio.create_subprocess_exec(
                    *args, cwd=cwd, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )  # fmt: skip
                out, err = await asyncio.wait_for(
                    proc.communicate(user.encode()), CLAUDE_CODE_TIMEOUT
                )
        except TimeoutError:
            proc.kill()
            self.stopped = f"claude CLI did not answer in {CLAUDE_CODE_TIMEOUT} s"
            log.error("classifier stopped for this run: %s - rules used", self.stopped)
            return None, "timeout"
        except OSError as exc:
            log.warning("claude CLI unavailable (%s); using rules", type(exc).__name__)
            return None, type(exc).__name__
        result = self._claude_code_result(proc.returncode, out, err)
        log.info("claude CLI call %d/%d: %s in %.0f s", self.calls,
                 self.settings.classifier_max_calls, "ok" if result[0] else result[1],
                 time.monotonic() - started)  # fmt: skip
        return result

    def _claude_code_result(
        self, code: int | None, out: bytes, err: bytes
    ) -> tuple[str | None, str]:
        try:
            data = json.loads(out.decode("utf-8", "replace") or "{}")
        except ValueError:
            data = {}
        text = str(data.get("result") or err.decode("utf-8", "replace") or "")
        if code != 0 or data.get("is_error"):
            low = text.lower()
            if any(
                w in low
                for w in (
                    "not logged in",
                    "log in",
                    "login",
                    "usage limit",
                    "limit reached",
                    "credit",
                )
            ):
                self.stopped = "claude CLI: " + text[:80]
                log.error(
                    "classifier stopped for this run (claude CLI): %s - rules used", text[:200]
                )
            else:
                log.warning("claude CLI error (exit %s): %s", code, text[:200])
            return None, f"claude CLI exit {code}"
        structured = data.get("structured_output")
        if isinstance(structured, dict):
            return json.dumps(structured), ""
        start, end = text.find("{"), text.rfind("}")
        return (text[start : end + 1] if start != -1 and end > start else text), ""

    async def _call_anthropic(
        self, system: str, user: str, schema: dict, max_tokens: int
    ) -> tuple[str | None, str]:
        import anthropic

        output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
        if self.settings.classifier_effort:  # not accepted by every model (e.g. Haiku 4.5)
            output_config["effort"] = self.settings.classifier_effort
        extra = (
            {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
            if self.model in FALLBACK_MODELS
            else {}
        )
        try:
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config=output_config,
                **extra,
            )
        except (anthropic.APIConnectionError, anthropic.RateLimitError) as exc:
            log.warning("Claude unavailable (%s); using rules", exc)
            return None, f"{type(exc).__name__}"
        except anthropic.APIStatusError as exc:
            if not self._account_error(exc.status_code, str(exc)):
                log.warning("Claude API error %s; using rules", exc.status_code)
            return None, f"HTTP {exc.status_code}"
        if response.stop_reason == "refusal":
            return None, "refusal"
        return next((b.text for b in response.content if b.type == "text"), ""), ""

    async def _call_openrouter(
        self, system: str, user: str, schema: dict, max_tokens: int
    ) -> tuple[str | None, str]:
        import httpx

        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                # cache_control is passed through to Anthropic models by OpenRouter
                {"role": "system", "content": [
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                ]},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": schema},
            },
        }  # fmt: skip
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "X-Title": "Tension Index",
            "HTTP-Referer": "https://github.com/FixerHack/war-predictor",
        }
        try:
            response = await self.client.post(OPENROUTER_URL, json=body, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("OpenRouter unavailable (%s); using rules", exc)
            return None, type(exc).__name__
        if response.status_code != 200:
            if not self._account_error(response.status_code, response.text):
                log.warning("OpenRouter error %s: %s", response.status_code, response.text[:300])
            return None, f"HTTP {response.status_code}"
        try:
            choice = response.json()["choices"][0]
        except (ValueError, KeyError, IndexError):
            return None, "unexpected response"
        if choice.get("finish_reason") in ("content_filter", "refusal"):
            return None, "refusal"
        content = (choice.get("message") or {}).get("content") or ""
        # Tolerate a fenced or prefixed answer: take the outermost JSON object.
        start, end = content.find("{"), content.rfind("}")
        return (content[start : end + 1] if start != -1 and end > start else content), ""

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
            fallback.notes.append(f"claude: {self.stopped or 'per-run cap reached'}, rules used")
            fallback.method = PENDING  # the model gets it on a later run
            return fallback
        user = (
            f"Publisher: {publisher}\nCountry: {country}\n"
            f"Level before: {level_before or 'n/a'}\nLevel after: {level_after or 'n/a'}\n\n"
            f"<advisory>\n{text[:12000]}\n</advisory>"
        )
        text_out, problem = await self._call(SYSTEM_PROMPT, user, SCHEMA, 2048)
        if text_out is None:
            fallback.notes.append(f"claude: {problem}, rules used")
            if problem != "refusal":
                fallback.method = PENDING
            return fallback
        try:
            data = json.loads(text_out)
            optional = {"measure_reason"}  # added later; older outputs lack it
            result = Classification(**{
                k: data[k] for k in SCHEMA["required"] if k in data or k not in optional
            })  # fmt: skip
        except (ValueError, KeyError, TypeError):
            fallback.notes.append("claude: unparseable output, rules used")
            return fallback
        result.method = "claude"
        result.quote = usable_quote(result.quote) or fallback.quote
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
    numbered = "\n".join(f"{i}. {h}" for i, h in enumerate(headlines))
    text, _ = await claude._call(HEADLINE_PROMPT, numbered, HEADLINE_SCHEMA, 8192)
    if text is None:
        return None
    try:
        items = json.loads(text)["items"]
    except (ValueError, KeyError, TypeError):
        return None
    return {
        int(x["i"]): (x["category"], max(0.0, min(1.0, float(x["severity"]))))
        for x in items
        if 0 <= int(x["i"]) < len(headlines) and x["category"] in HEADLINE_CATEGORIES
    }
