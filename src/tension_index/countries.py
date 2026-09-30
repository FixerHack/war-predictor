"""Countries monitored by the index (ISO 3166-1 alpha-2 -> metadata).

Ukraine is intentionally excluded: an active war keeps its score pinned at the
maximum and would distort cross-country comparison.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Country:
    code: str
    name: str
    group: str  # "eu", "efta_uk", "eastern", "balkans"
    gov_uk_slug: str  # slug on https://www.gov.uk/foreign-travel-advice/<slug>


_RAW: list[tuple[str, str, str, str]] = [
    # EU-27
    ("AT", "Austria", "eu", "austria"),
    ("BE", "Belgium", "eu", "belgium"),
    ("BG", "Bulgaria", "eu", "bulgaria"),
    ("HR", "Croatia", "eu", "croatia"),
    ("CY", "Cyprus", "eu", "cyprus"),
    ("CZ", "Czechia", "eu", "czech-republic"),
    ("DK", "Denmark", "eu", "denmark"),
    ("EE", "Estonia", "eu", "estonia"),
    ("FI", "Finland", "eu", "finland"),
    ("FR", "France", "eu", "france"),
    ("DE", "Germany", "eu", "germany"),
    ("GR", "Greece", "eu", "greece"),
    ("HU", "Hungary", "eu", "hungary"),
    ("IE", "Ireland", "eu", "ireland"),
    ("IT", "Italy", "eu", "italy"),
    ("LV", "Latvia", "eu", "latvia"),
    ("LT", "Lithuania", "eu", "lithuania"),
    ("LU", "Luxembourg", "eu", "luxembourg"),
    ("MT", "Malta", "eu", "malta"),
    ("NL", "Netherlands", "eu", "netherlands"),
    ("PL", "Poland", "eu", "poland"),
    ("PT", "Portugal", "eu", "portugal"),
    ("RO", "Romania", "eu", "romania"),
    ("SK", "Slovakia", "eu", "slovakia"),
    ("SI", "Slovenia", "eu", "slovenia"),
    ("ES", "Spain", "eu", "spain"),
    ("SE", "Sweden", "eu", "sweden"),
    # UK + EFTA
    ("GB", "United Kingdom", "efta_uk", ""),  # GOV.UK does not advise on the UK itself
    ("NO", "Norway", "efta_uk", "norway"),
    ("CH", "Switzerland", "efta_uk", "switzerland"),
    ("IS", "Iceland", "efta_uk", "iceland"),
    # Eastern neighbourhood
    ("MD", "Moldova", "eastern", "moldova"),
    # Western Balkans
    ("RS", "Serbia", "balkans", "serbia"),
    ("ME", "Montenegro", "balkans", "montenegro"),
    ("MK", "North Macedonia", "balkans", "north-macedonia"),
    ("AL", "Albania", "balkans", "albania"),
    ("BA", "Bosnia and Herzegovina", "balkans", "bosnia-and-herzegovina"),
    ("XK", "Kosovo", "balkans", "kosovo"),
]

COUNTRIES: dict[str, Country] = {c[0]: Country(*c) for c in _RAW}


def get_country(code: str) -> Country:
    try:
        return COUNTRIES[code.upper()]
    except KeyError as exc:
        raise KeyError(f"Unknown or unmonitored country code: {code!r}") from exc
