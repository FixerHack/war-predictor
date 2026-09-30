"""France: Conseils aux voyageurs (diplomatie.gouv.fr). No API: the country page text is
stored and the colour level (vert/jaune/orange/rouge) is left to the classifier."""

from __future__ import annotations

from tension_index.countries import Country
from tension_index.sources.base import Advisory, Source, html_to_text, main_content

PAGE = (
    "https://www.diplomatie.gouv.fr/fr/conseils-aux-voyageurs/conseils-par-pays-destination/{slug}/"
)
SLUGS = {
    "AT": "autriche", "BE": "belgique", "BG": "bulgarie", "HR": "croatie", "CY": "chypre",
    "CZ": "republique-tcheque", "DK": "danemark", "EE": "estonie", "FI": "finlande",
    "DE": "allemagne", "GR": "grece", "HU": "hongrie", "IE": "irlande", "IT": "italie",
    "LV": "lettonie", "LT": "lituanie", "LU": "luxembourg", "MT": "malte", "NL": "pays-bas",
    "PL": "pologne", "PT": "portugal", "RO": "roumanie", "SK": "slovaquie", "SI": "slovenie",
    "ES": "espagne", "SE": "suede", "GB": "royaume-uni", "NO": "norvege", "CH": "suisse",
    "IS": "islande", "MD": "moldavie", "RS": "serbie", "ME": "montenegro",
    "MK": "macedoine-du-nord", "AL": "albanie", "BA": "bosnie-herzegovine", "XK": "kosovo",
}  # fmt: skip


class FrSource(Source):
    name = "fr"
    label = "🇫🇷 France Diplomatie"

    def supports(self, country: Country) -> bool:
        return country.code in SLUGS  # no advice about France itself

    async def fetch(self, country: Country) -> Advisory:
        url = PAGE.format(slug=SLUGS[country.code])
        response = await self.get(url)
        return Advisory(
            country=country.code,
            url=url,
            title=f"Conseils aux voyageurs: {SLUGS[country.code]}",
            text=html_to_text(main_content(response.text)),
            level=None,
        )
