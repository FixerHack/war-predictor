"""Australia: Smartraveller country pages.

The bulk export (/destinations-export) did not answer within 120 s from a normal client, so
each country page is fetched instead (38 small requests):
https://www.smartraveller.gov.au/destinations/europe/<slug>
The level is the phrase that follows "Overall advice level" on the page.
"""

from __future__ import annotations

from tension_index.countries import Country
from tension_index.sources.base import (
    Advisory,
    Source,
    SourceFormatError,
    html_to_text,
    main_content,
)

PAGE = "https://www.smartraveller.gov.au/destinations/europe/{slug}"
PHRASES = [  # most severe first
    ("4", "do not travel"),
    ("3", "reconsider your need to travel"),
    ("2", "exercise a high degree of caution"),
    ("1", "exercise normal safety precautions"),
]
SLUGS = {"GB": "united-kingdom"}
# The site throttles unknown clients; identify as a regular browser plus our project URL.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TensionIndexBot/0.2; +https://github.com/FixerHack/war-predictor)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-AU,en;q=0.8",
}


def level_from_text(text: str) -> str | None:
    """The most severe standard phrase anywhere in `text` (for short texts)."""
    low = text.lower()
    for level, phrase in PHRASES:
        if phrase in low:
            return level
    return None


def overall_level(text: str) -> str | None:
    """The phrase right after "Overall advice level"; else the first phrase on the page
    (regional "do not travel" warnings further down must not win)."""
    low = text.lower()
    anchor = low.find("overall advice level")
    window = low[anchor : anchor + 200] if anchor != -1 else low
    hits = [(window.find(p), level) for level, p in PHRASES if p in window]
    return min(hits)[1] if hits else None


class AuSource(Source):
    name = "au"
    label = "🇦🇺 Smartraveller"
    timeout = 45.0

    def supports(self, country: Country) -> bool:
        return bool(SLUGS.get(country.code) or country.gov_uk_slug)

    async def fetch(self, country: Country) -> Advisory:
        url = PAGE.format(slug=SLUGS.get(country.code) or country.gov_uk_slug)
        response = await self.client.get(url, headers=HEADERS, timeout=self.timeout)
        self.raw[str(response.url)] = response.text
        response.raise_for_status()
        text = html_to_text(main_content(response.text))
        level = overall_level(text)
        if level is None:
            raise SourceFormatError(f"au: no advice level on {url}")
        return Advisory(country=country.code, url=str(response.url), title=f"Smartraveller: {country.name}",
                        text=text, level=level)  # fmt: skip
