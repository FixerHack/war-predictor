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
    "BA": ["bosnia and herzegovina", "bosnia-herzegovina"],
    "CZ": ["czechia", "czech republic"],
    "MK": ["north macedonia", "macedonia"],
    "NL": ["netherlands", "the netherlands"],
    "GB": ["united kingdom", "the united kingdom"],
    "XK": ["kosovo"],
}
# ISO 3166 -> FIPS 10-4 codes used in the feed's Country-Tag.
FIPS = {
    "AT": "AU", "BE": "BE", "BG": "BU", "HR": "HR", "CY": "CY", "CZ": "EZ", "DK": "DA",
    "EE": "EN", "FI": "FI", "FR": "FR", "DE": "GM", "GR": "GR", "HU": "HU", "IE": "EI",
    "IT": "IT", "LV": "LG", "LT": "LH", "LU": "LU", "MT": "MT", "NL": "NL", "PL": "PL",
    "PT": "PO", "RO": "RO", "SK": "LO", "SI": "SI", "ES": "SP", "SE": "SW", "GB": "UK",
    "NO": "NO", "CH": "SZ", "IS": "IC", "MD": "MD", "RS": "RI", "ME": "MJ", "MK": "MK",
    "AL": "AL", "BA": "BK", "XK": "KV",
}  # fmt: skip
_LEVEL = re.compile(r"Level\s*([1-4])", re.I)


def _names(country: Country) -> list[str]:
    return ALIASES.get(country.code, [country.name.lower()])


def _rank(item: dict) -> tuple:
    from email.utils import parsedate_to_datetime

    try:
        when = parsedate_to_datetime(item["date"]).timestamp() if item["date"] else 0.0
    except (TypeError, ValueError):
        when = 0.0
    # The feed can repeat an item with the same title, date and link but a different text;
    # comparing the text last keeps the choice independent of the feed order.
    return (bool(_LEVEL.search(item["title"])), when, item["link"], item["description"])


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
        # The title names the country; the Country-Tag is a FIPS code, not ISO (Sweden is
        # "SW", while "SE" is Seychelles), so it is only a fallback via the FIPS table.
        matches = [
            i for i in self.items if i["title"].split(" - ")[0].strip().lower() in _names(country)
        ]
        if not matches:
            fips = FIPS.get(country.code)
            matches = [i for i in self.items if fips and fips in i["tags"]]
        if not matches:
            raise SourceFormatError(f"us: {country.name} not in feed")
        # Several items for one country (feed order varies between downloads): pick the same
        # one every time - an advisory with a level first, then the newest, then by link.
        return max(matches, key=_rank)

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
