"""Germany: Auswärtiges Amt OpenData API.

Docs: https://www.auswaertiges-amt.de/de/service/opendata/2412916-2412916
Index:  GET /opendata/travelwarning        -> {"response": {"<id>": {countryCode, warning, ...}}}
Detail: GET /opendata/travelwarning/<id>   -> {"response": {"<id>": {..., "content": "<html>"}}}
"""

from __future__ import annotations

from tension_index.countries import Country
from tension_index.sources.base import Advisory, Source, SourceFormatError, html_to_text

INDEX = "https://www.auswaertiges-amt.de/opendata/travelwarning"


def level_of(entry: dict) -> str:
    if entry.get("warning"):
        return "travel_warning"  # Reisewarnung for the whole country
    if entry.get("partialWarning"):
        return "partial_warning"
    if entry.get("situationWarning") or entry.get("situationPartWarning"):
        return "security_notice"
    return "none"


def _entries(payload: object) -> dict[str, dict]:
    """{id: entry} from the index/detail payload (ids are object keys next to metadata)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), dict):
        raise SourceFormatError("de: expected {'response': {...}}")
    return {k: v for k, v in payload["response"].items() if isinstance(v, dict)}


class DeSource(Source):
    name = "de"
    label = "🇩🇪 Auswärtiges Amt"

    async def prepare(self) -> None:
        entries = _entries(await self.get_json(INDEX))
        self.index: dict[str, tuple[str, dict]] = {}
        for entry_id, entry in entries.items():
            code = str(entry.get("countryCode") or "").upper()
            if code:
                self.index[code] = (entry_id, entry)
        if not self.index:
            raise SourceFormatError("de: no entries with countryCode in index")

    def supports(self, country: Country) -> bool:
        return country.code != "DE"  # no advice about Germany itself

    async def fetch(self, country: Country) -> Advisory:
        try:
            entry_id, summary = self.index[country.code]
        except KeyError as exc:
            raise SourceFormatError(f"de: {country.code} not in index") from exc
        detail = _entries(await self.get_json(f"{INDEX}/{entry_id}")).get(entry_id, summary)
        return Advisory(
            country=country.code,
            url=f"{INDEX}/{entry_id}",
            title=detail.get("title") or summary.get("title"),
            text=html_to_text(detail.get("content") or ""),
            level=level_of(detail if "warning" in detail else summary),
            source_updated=str(detail.get("lastModified") or summary.get("lastModified") or ""),
        )
