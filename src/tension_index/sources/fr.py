"""France: Conseils aux voyageurs (diplomatie.gouv.fr). No API: two pages per country.

- "Dernières minutes et alertes": the alerts text.
- "Sécurité": its "Zones de vigilance" section states the colour of the whole country
  ("La Pologne figure en vigilance normale") and of zones ("Les voyages en Transnistrie sont
  déconseillés sauf raison impérative"). The level is the more severe of the two: the
  country colour (vert/jaune/orange/rouge) or a zone colour (`orange_parts`, ...); a
  country without a stated colour is green, as on the ministry's map.
"""

from __future__ import annotations

import re

from tension_index.countries import Country
from tension_index.sources.base import (
    Advisory,
    Source,
    SourceFormatError,
    html_to_text,
    main_content,
)

PAGE = "https://www.diplomatie.gouv.fr/fr/information-par-pays/{slug}/dernieres-minutes-et-alertes"
SECURITY = (
    "https://www.diplomatie.gouv.fr/fr/information-par-pays/{slug}/conseils-aux-voyageurs-securite"
)
# Most severe first; the ministry's four map colours.
_LEVELS = (
    ("rouge", re.compile(r"formellement d[ée]conseill", re.I)),
    ("orange", re.compile(r"d[ée]conseill[ée]e?s? sauf raison imp[ée]rative", re.I)),
    ("jaune", re.compile(r"vigilance renforc[ée]e", re.I)),
    ("vert", re.compile(r"vigilance normale", re.I)),
)
_SEVERITY = {"vert": 0, "jaune": 1, "orange": 2, "rouge": 3}
_WHOLE = re.compile(r"ensemble du (pays|territoire)|figure en|tout le pays", re.I)
_ZONES_START = re.compile(r"^zones de vigilance", re.I)
_ZONES_END = re.compile(r"^risques encourus", re.I)
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


def vigilance_zones(text: str) -> list[str]:
    """Lines of the "Zones de vigilance" section of the security page (without its date)."""
    out: list[str] = []
    inside = False
    for line in (ln.strip() for ln in text.splitlines()):
        if _ZONES_START.match(line):
            inside = True
        elif inside and _ZONES_END.match(line):
            break
        elif inside and line and not _START.match(line):
            out.append(line)
    return out


def vigilance_level(zones: list[str]) -> str | None:
    """Level key from the zones section; None when the section is missing (layout change)."""
    if not zones:
        return None
    country, parts = "vert", ""
    for line in zones:
        found = next((key for key, pattern in _LEVELS if pattern.search(line)), None)
        if found is None:
            continue
        if _WHOLE.search(line):
            if _SEVERITY[found] > _SEVERITY[country]:
                country = found
        elif not parts or _SEVERITY[found] > _SEVERITY[parts]:
            parts = found
    if parts and _SEVERITY[parts] > _SEVERITY[country]:
        return f"{parts}_parts"
    return country


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
        slug = SLUGS[country.code]
        url = PAGE.format(slug=slug)
        alerts = alerts_text(html_to_text(main_content((await self.get(url)).text)))
        # A failed security page fails the country (no level), never a silent "level gone".
        security = await self.get(SECURITY.format(slug=slug))
        zones = vigilance_zones(html_to_text(main_content(security.text)))
        level = vigilance_level(zones)
        if level is None:
            raise SourceFormatError(f"fr {slug}: no 'Zones de vigilance' section")
        return Advisory(
            country=country.code,
            url=url,
            title=f"Conseils aux voyageurs: {slug}",
            text=alerts + "\n\nZones de vigilance:\n" + "\n".join(zones),
            level=level,
        )
