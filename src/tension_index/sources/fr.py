"""France: Conseils aux voyageurs (diplomatie.gouv.fr). No API: the country page text is
stored and the colour level (vert/jaune/orange/rouge) is left to the classifier."""

from __future__ import annotations

import re

from tension_index.countries import Country
from tension_index.sources.base import Advisory, Source, html_to_text, main_content

PAGE = "https://www.diplomatie.gouv.fr/fr/information-par-pays/{slug}/dernieres-minutes-et-alertes"
# Page furniture around the alerts (navigation, survey, sign-up box).
_START = re.compile(r"^(information toujours valable|dernière mise à jour le)", re.I)
_UI = {
    "imprimer", "vous voyagez à l'étranger ?", "s'inscrire sur fil d'ariane", "donnez-nous votre avis",
    "répondre à l'enquête utilisateurs", "fermer",
}  # fmt: skip
_UI_PREFIX = ("pour recevoir des alertes", "aidez-nous à améliorer", "voir le fil d")


def alerts_text(text: str) -> str:
    """The alerts only: everything after the last "last updated" header line, minus page
    furniture (print button, sign-up and survey boxes)."""
    lines = text.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if _START.match(ln.strip()):
            start = i + 1

    def is_ui(ln: str) -> bool:
        low = ln.strip().lower().replace("’", "'")
        return low in _UI or low.startswith(_UI_PREFIX)

    return "\n".join(ln for ln in lines[start:] if not is_ui(ln))


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
            text=alerts_text(html_to_text(main_content(response.text))),
            level=None,
        )
