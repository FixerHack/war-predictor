"""Canada: travel advice open data (Open Government Licence - Canada).

https://open.canada.ca/data/en/dataset/bef2ebb3-ca9a-485f-aaff-5dc36eb89426
GET https://data.international.gc.ca/travel-voyage/index-updated.json
-> {"data": {"PL": {"advisory-state": 0..3, "eng": {"name", "url-slug", "advisory-text",
    "recent-updates"}, "date-published": {"date": ...}, ...}}}
"""

from __future__ import annotations

from tension_index.countries import Country
from tension_index.sources.base import Advisory, Source, SourceFormatError, html_to_text

INDEX = "https://data.international.gc.ca/travel-voyage/index-updated.json"
PUBLIC = "https://travel.gc.ca/destinations/{slug}"
LEVELS = {0: "normal", 1: "high_caution", 2: "avoid_non_essential", 3: "avoid_all"}


class CaSource(Source):
    name = "ca"
    label = "🇨🇦 Travel.gc.ca"

    async def prepare(self) -> None:
        payload = await self.get_json(INDEX)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not data:
            raise SourceFormatError("ca: expected {'data': {ISO: {...}}}")
        self.index: dict[str, dict] = {}
        for key, entry in data.items():
            if not isinstance(entry, dict):
                continue
            self.index[str(entry.get("country-iso") or key).upper()] = entry
            name = (entry.get("eng") or {}).get("name")
            if name:
                self.index[name.lower()] = entry

    def supports(self, country: Country) -> bool:
        return True

    async def fetch(self, country: Country) -> Advisory:
        entry = self.index.get(country.code) or self.index.get(country.name.lower())
        if entry is None:
            raise SourceFormatError(f"ca: {country.code} not in index")
        eng = entry.get("eng") or {}
        try:
            level = LEVELS[int(entry.get("advisory-state", 0))]
        except (KeyError, ValueError) as exc:
            raise SourceFormatError(f"ca: bad advisory-state for {country.code}") from exc
        parts = [eng.get("advisory-text") or "", html_to_text(eng.get("recent-updates") or "")]
        if int(entry.get("has-regional-advisory") or 0):
            parts.append("Regional advisories in effect.")
        published = entry.get("date-published") or {}
        return Advisory(
            country=country.code,
            url=PUBLIC.format(slug=eng.get("url-slug") or country.name.lower()),
            title=eng.get("name"),
            text="\n".join(p for p in parts if p),
            level=level,
            source_updated=str(published.get("date") or ""),
        )
