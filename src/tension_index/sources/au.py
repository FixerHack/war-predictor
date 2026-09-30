"""Australia: Smartraveller destinations export (free public API).

https://www.smartraveller.gov.au/consular-services/resources -> /destinations-export
The export schema is not documented, so parsing is tolerant: the destination name, the
overall advice level and the text are located by field names, and the level falls back to
the standard phrases. Run `tension-index probe au --country PL` if parsing fails.
"""

from __future__ import annotations

import json
import re

from tension_index.countries import Country
from tension_index.sources.base import Advisory, Source, SourceFormatError, html_to_text

EXPORT = "https://www.smartraveller.gov.au/destinations-export"
PHRASES = [  # most severe first
    ("4", "do not travel"),
    ("3", "reconsider your need to travel"),
    ("2", "exercise a high degree of caution"),
    ("1", "exercise normal safety precautions"),
]
_NAME_KEYS = ("title", "name", "destination", "country")
_LEVEL_KEYS = ("overall_advice_level", "advice_level", "level", "advice")
_TEXT_KEYS = ("summary", "body", "overview", "latest_update", "advice_summary")


def _flatten(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def level_from_text(text: str) -> str | None:
    low = text.lower()
    for level, phrase in PHRASES:
        if phrase in low:
            return level
    return None


def _field(entry: dict, keys: tuple[str, ...]) -> object | None:
    lowered = {k.lower(): v for k, v in entry.items()}
    for key in keys:
        if lowered.get(key) not in (None, "", []):
            return lowered[key]
    return None


def _items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("items", "data", "destinations", "results"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
    raise SourceFormatError("au: expected a list of destinations")


class AuSource(Source):
    name = "au"
    label = "🇦🇺 Smartraveller"

    async def prepare(self) -> None:
        self.index: dict[str, dict] = {}
        for entry in _items(await self.get_json(EXPORT)):
            name = _field(entry, _NAME_KEYS)
            if isinstance(name, str):
                self.index[re.sub(r"\s+", " ", html_to_text(name)).strip().lower()] = entry
        if not self.index:
            raise SourceFormatError("au: no destination names found")

    def supports(self, country: Country) -> bool:
        return True

    async def fetch(self, country: Country) -> Advisory:
        aliases = {country.name.lower(), country.name.lower().replace(" and ", " & ")}
        if country.code == "CZ":
            aliases.add("czech republic")
        entry = next((self.index[a] for a in aliases if a in self.index), None)
        if entry is None:
            raise SourceFormatError(f"au: {country.name} not in export")
        level_field = _field(entry, _LEVEL_KEYS)
        text_field = _field(entry, _TEXT_KEYS)
        text = html_to_text(_flatten(text_field)) if text_field is not None else ""
        level = level_from_text(_flatten(level_field)) if level_field is not None else None
        level = level or level_from_text(text) or level_from_text(_flatten(entry))
        url = _field(entry, ("url", "path", "link"))
        if isinstance(url, str) and url.startswith("/"):
            url = "https://www.smartraveller.gov.au" + url
        return Advisory(
            country=country.code,
            url=url if isinstance(url, str) else EXPORT,
            title=str(_field(entry, _NAME_KEYS)),
            text=text or _flatten(level_field or ""),
            level=level,
            source_updated=str(_field(entry, ("updated", "changed", "date", "last_updated")) or ""),
        )
