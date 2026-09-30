"""United States: State Department travel advisories RSS.

https://travel.state.gov/content/travel/en/rss.html -> /_res/rss/TAsTWs.xml
<item><title>Poland - Level 1: Exercise Normal Precautions</title><link/><pubDate/>
      <description>(html)</description><category domain="Country-Tag">PL</category></item>
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from tension_index.countries import Country
from tension_index.sources.base import Advisory, Source, SourceFormatError, html_to_text

# The RSS feed answered 404 in September 2026; the State Department's data API publishes the
# same advisories. Tried in order, the first one that yields items wins.
FEEDS = [
    "https://travel.state.gov/_res/rss/TAsTWs.xml",
    "https://cadataapi.state.gov/api/TravelAdvisories",
]
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


def _field(obj: dict, *names: str) -> str:
    """First non-empty field by case-insensitive name (the API's casing is not documented)."""
    lower = {k.lower(): v for k, v in obj.items()}
    for name in names:
        value = lower.get(name.lower())
        if isinstance(value, list):
            value = " ".join(str(v.get("value", v) if isinstance(v, dict) else v) for v in value)
        if value:
            return str(value).strip()
    return ""


def _tags(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    out = []
    for v in value or []:
        text = (v.get("value") or v.get("text") or "") if isinstance(v, dict) else v
        out.append(str(text).strip().upper())
    return out


def parse_feed(content: bytes) -> list[dict]:
    """Items from the RSS feed, an Atom feed or the JSON API, as title/link/date/description/tags."""
    text = content.decode("utf-8", "replace").lstrip("\ufeff \r\n\t")
    items: list[dict] = []
    if text.startswith(("[", "{")):
        data = json.loads(text)
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [])
        for obj in data:
            if not isinstance(obj, dict):
                continue
            lower = {k.lower(): v for k, v in obj.items()}
            items.append(
                {
                    "title": _field(obj, "title", "name"),
                    "link": _field(obj, "link", "url", "id"),
                    "date": _field(obj, "pubDate", "published", "updated", "date"),
                    "description": _field(obj, "description", "summary", "content"),
                    "tags": _tags(lower.get("category") or lower.get("categories")),
                }
            )
    else:
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise SourceFormatError("us: feed is neither XML nor JSON") from exc
        for item in root.iter():
            tag = item.tag.rsplit("}", 1)[-1]
            if tag not in ("item", "entry"):
                continue
            fields = {c.tag.rsplit("}", 1)[-1]: c for c in item}
            link = fields.get("link")
            items.append(
                {
                    "title": (fields["title"].text or "").strip() if "title" in fields else "",
                    "link": ((link.text or link.get("href") or "").strip() if link is not None else ""),
                    "date": next((
                        (fields[k].text or "").strip() for k in ("pubDate", "published", "updated")
                        if k in fields), ""),
                    "description": next((
                        fields[k].text or "" for k in ("description", "summary", "content")
                        if k in fields), ""),
                    "tags": [(c.text or c.get("term") or "").strip().upper()
                             for c in item if c.tag.rsplit("}", 1)[-1] == "category"],
                }
            )  # fmt: skip
    items = [i for i in items if i["title"]]
    if not items:
        raise SourceFormatError("us: no advisories in feed")
    return items


class UsSource(Source):
    name = "us"
    label = "🇺🇸 State Department"

    async def prepare(self) -> None:
        problems = []
        for url in FEEDS:
            try:
                response = await self.get(url)
                self.items = parse_feed(response.content)
                self.feed = url
                return
            except Exception as exc:  # try the next feed, report all if none works
                problems.append(f"{url}: {type(exc).__name__}: {exc}"[:200])
        raise SourceFormatError("us: no usable feed; " + " | ".join(problems))

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
            url=item["link"] or self.feed,
            title=item["title"],
            text=html_to_text(item["description"]),
            level=m.group(1) if m else None,
            source_updated=item["date"],
        )
