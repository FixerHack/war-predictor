"""UK FCDO foreign travel advice via the GOV.UK Content API.

Docs: https://content-api.publishing.service.gov.uk/
Endpoint: https://www.gov.uk/api/content/foreign-travel-advice/<slug>
"""

from __future__ import annotations

from tension_index.countries import Country
from tension_index.sources.base import Advisory, Source, SourceFormatError, html_to_text

API = "https://www.gov.uk/api/content/foreign-travel-advice/{slug}"
PUBLIC = "https://www.gov.uk/foreign-travel-advice/{slug}"


class GovUkSource(Source):
    name = "gov_uk"
    label = "🇬🇧 UK FCDO"

    def supports(self, country: Country) -> bool:
        return bool(country.gov_uk_slug)

    async def fetch(self, country: Country) -> Advisory:
        data = await self.get_json(API.format(slug=country.gov_uk_slug))
        if not isinstance(data, dict):
            raise SourceFormatError("gov_uk: expected a JSON object")
        return parse(country.code, country.gov_uk_slug, data)


def parse(country_code: str, slug: str, data: dict) -> Advisory:
    details = data.get("details") or {}
    sections: list[str] = []
    for part in details.get("parts") or []:
        body = html_to_text(part.get("body") or "")
        sections.append(f"## {part.get('title', '').strip()}\n{body}".strip())
    alert_status = details.get("alert_status") or []
    return Advisory(
        country=country_code,
        url=PUBLIC.format(slug=slug),
        title=data.get("title"),
        text="\n\n".join(sections),
        level=",".join(sorted(alert_status)) or "none",
        source_updated=data.get("public_updated_at"),
    )
