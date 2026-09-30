"""United States: State Department travel advisories RSS.

https://travel.state.gov/content/travel/en/rss.html -> /_res/rss/TAsTWs.xml
<item><title>Poland - Level 1: Exercise Normal Precautions</title><link/><pubDate/>
      <description>(html)</description><category domain="Country-Tag">PL</category></item>
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from tension_index.countries import Country
from tension_index.sources.base import Advisory, Source, SourceFormatError, html_to_text

FEED = "https://travel.state.gov/_res/rss/TAsTWs.xml"
ALIASES = {
    "CZ": ["czechia", "czech republic"],
    "MK": ["north macedonia", "macedonia"],
    "NL": ["netherlands", "the netherlands"],
    "GB": ["united kingdom", "the united kingdom"],
    "XK": ["kosovo"],
}
_LEVEL = re.compile(r"Level\s*([1-4])", re.I)


def _names(country: Country) -> list[str]:
    return ALIASES.get(country.code, [country.name.lower()])


class UsSource(Source):
    name = "us"
    label = "🇺🇸 State Department"

    async def prepare(self) -> None:
        response = await self.get(FEED)
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise SourceFormatError("us: feed is not valid XML") from exc
        self.items: list[dict] = []
        for item in root.iter("item"):
            self.items.append(
                {
                    "title": (item.findtext("title") or "").strip(),
                    "link": (item.findtext("link") or "").strip(),
                    "date": (item.findtext("pubDate") or "").strip(),
                    "description": item.findtext("description") or "",
                    "tags": [(c.text or "").strip().upper() for c in item.findall("category")],
                }
            )
        if not self.items:
            raise SourceFormatError("us: no <item> elements in feed")

    def supports(self, country: Country) -> bool:
        return True

    def _find(self, country: Country) -> dict:
        for item in self.items:
            if country.code in item["tags"]:
                return item
        for item in self.items:
            head = item["title"].split(" - ")[0].strip().lower()
            if head in _names(country):
                return item
        raise SourceFormatError(f"us: {country.name} not in feed")

    async def fetch(self, country: Country) -> Advisory:
        item = self._find(country)
        m = _LEVEL.search(item["title"]) or _LEVEL.search(item["description"])
        return Advisory(
            country=country.code,
            url=item["link"] or FEED,
            title=item["title"],
            text=html_to_text(item["description"]),
            level=m.group(1) if m else None,
            source_updated=item["date"],
        )
