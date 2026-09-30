"""Countries monitored by the index (ISO 3166-1 alpha-2 -> metadata).

Ukraine is intentionally excluded: an active war keeps its score pinned at the
maximum and would distort cross-country comparison.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Country:
    code: str
    name: str
    name_uk: str
    region: str  # peer group for regional comparison
    nato_eu: bool  # member of NATO and/or the EU (allies advise late on these)
    gov_uk_slug: str  # slug on https://www.gov.uk/foreign-travel-advice/<slug>

    @property
    def flag(self) -> str:
        return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in self.code)

    def title(self, lang: str) -> str:
        return self.name_uk if lang == "uk" else self.name


REGIONS = ("nordic_baltic", "central_eastern", "western", "southern", "balkans")

_RAW: list[tuple[str, str, str, str, bool, str]] = [
    ("AT", "Austria", "Австрія", "western", True, "austria"),
    ("BE", "Belgium", "Бельгія", "western", True, "belgium"),
    ("BG", "Bulgaria", "Болгарія", "central_eastern", True, "bulgaria"),
    ("HR", "Croatia", "Хорватія", "balkans", True, "croatia"),
    ("CY", "Cyprus", "Кіпр", "southern", True, "cyprus"),
    ("CZ", "Czechia", "Чехія", "central_eastern", True, "czech-republic"),
    ("DK", "Denmark", "Данія", "nordic_baltic", True, "denmark"),
    ("EE", "Estonia", "Естонія", "nordic_baltic", True, "estonia"),
    ("FI", "Finland", "Фінляндія", "nordic_baltic", True, "finland"),
    ("FR", "France", "Франція", "western", True, "france"),
    ("DE", "Germany", "Німеччина", "western", True, "germany"),
    ("GR", "Greece", "Греція", "southern", True, "greece"),
    ("HU", "Hungary", "Угорщина", "central_eastern", True, "hungary"),
    ("IE", "Ireland", "Ірландія", "western", True, "ireland"),
    ("IT", "Italy", "Італія", "southern", True, "italy"),
    ("LV", "Latvia", "Латвія", "nordic_baltic", True, "latvia"),
    ("LT", "Lithuania", "Литва", "nordic_baltic", True, "lithuania"),
    ("LU", "Luxembourg", "Люксембург", "western", True, "luxembourg"),
    ("MT", "Malta", "Мальта", "southern", True, "malta"),
    ("NL", "Netherlands", "Нідерланди", "western", True, "netherlands"),
    ("PL", "Poland", "Польща", "central_eastern", True, "poland"),
    ("PT", "Portugal", "Португалія", "southern", True, "portugal"),
    ("RO", "Romania", "Румунія", "central_eastern", True, "romania"),
    ("SK", "Slovakia", "Словаччина", "central_eastern", True, "slovakia"),
    ("SI", "Slovenia", "Словенія", "balkans", True, "slovenia"),
    ("ES", "Spain", "Іспанія", "southern", True, "spain"),
    ("SE", "Sweden", "Швеція", "nordic_baltic", True, "sweden"),
    # GOV.UK does not advise on the UK itself
    ("GB", "United Kingdom", "Велика Британія", "western", True, ""),
    ("NO", "Norway", "Норвегія", "nordic_baltic", True, "norway"),
    ("CH", "Switzerland", "Швейцарія", "western", False, "switzerland"),
    ("IS", "Iceland", "Ісландія", "nordic_baltic", True, "iceland"),
    ("MD", "Moldova", "Молдова", "central_eastern", False, "moldova"),
    ("RS", "Serbia", "Сербія", "balkans", False, "serbia"),
    ("ME", "Montenegro", "Чорногорія", "balkans", True, "montenegro"),
    ("MK", "North Macedonia", "Північна Македонія", "balkans", True, "north-macedonia"),
    ("AL", "Albania", "Албанія", "balkans", True, "albania"),
    (
        "BA",
        "Bosnia and Herzegovina",
        "Боснія і Герцеговина",
        "balkans",
        False,
        "bosnia-and-herzegovina",
    ),
    ("XK", "Kosovo", "Косово", "balkans", False, "kosovo"),
]

COUNTRIES: dict[str, Country] = {c[0]: Country(*c) for c in _RAW}


def get_country(code: str) -> Country:
    try:
        return COUNTRIES[code.upper()]
    except KeyError as exc:
        raise KeyError(f"Unknown or unmonitored country code: {code!r}") from exc


def peers(code: str) -> list[Country]:
    """Other countries in the same region (for regional divergence)."""
    region = get_country(code).region
    return [c for c in COUNTRIES.values() if c.region == region and c.code != code]
