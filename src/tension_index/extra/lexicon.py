"""Words that identify a monitored country in English headlines, and Russian stems for
Russian-language reports about the Russian/Belarusian MFA advice."""

from __future__ import annotations

import re
from functools import lru_cache

from tension_index.countries import COUNTRIES

# code: (extra names/demonyms, capital)
EN: dict[str, tuple[list[str], str]] = {
    "AT": (["Austrian"], "Vienna"), "BE": (["Belgian"], "Brussels"),
    "BG": (["Bulgarian"], "Sofia"), "HR": (["Croatian"], "Zagreb"),
    "CY": (["Cypriot"], "Nicosia"), "CZ": (["Czech", "Czech Republic"], "Prague"),
    "DK": (["Danish", "Dane", "Danes"], "Copenhagen"), "EE": (["Estonian"], "Tallinn"),
    "FI": (["Finnish", "Finn", "Finns"], "Helsinki"), "FR": (["French"], "Paris"),
    "DE": (["German"], "Berlin"), "GR": (["Greek"], "Athens"),
    "HU": (["Hungarian"], "Budapest"), "IE": (["Irish"], "Dublin"),
    "IT": (["Italian"], "Rome"), "LV": (["Latvian"], "Riga"),
    "LT": (["Lithuanian"], "Vilnius"), "LU": (["Luxembourgish"], "Luxembourg"),
    "MT": (["Maltese"], "Valletta"), "NL": (["Dutch", "Holland"], "Amsterdam"),
    "PL": (["Polish", "Pole", "Poles"], "Warsaw"), "PT": (["Portuguese"], "Lisbon"),
    "RO": (["Romanian"], "Bucharest"), "SK": (["Slovak", "Slovakian"], "Bratislava"),
    "SI": (["Slovenian", "Slovene"], "Ljubljana"), "ES": (["Spanish"], "Madrid"),
    "SE": (["Swedish", "Swede", "Swedes"], "Stockholm"),
    "GB": (["UK", "Britain", "British"], "London"), "NO": (["Norwegian"], "Oslo"),
    "CH": (["Swiss"], "Bern"), "IS": (["Icelandic"], "Reykjavik"),
    "MD": (["Moldovan", "Transnistria", "Transnistrian"], "Chisinau"),
    "RS": (["Serbian", "Serb", "Serbs"], "Belgrade"), "ME": (["Montenegrin"], "Podgorica"),
    "MK": (["North Macedonian", "Macedonian"], "Skopje"), "AL": (["Albanian"], "Tirana"),
    "BA": (["Bosnian", "Bosnia", "Republika Srpska"], "Sarajevo"),
    "XK": (["Kosovar", "Kosovan"], "Pristina"),
}  # fmt: skip

# Russian stems (cover case endings): "в Польшу", "Польши", "Польше".
RU: dict[str, str] = {
    "AT": "Австри", "BE": "Бельги", "BG": "Болгари", "HR": "Хорвати", "CY": "Кипр",
    "CZ": "Чехи", "DK": "Дани", "EE": "Эстони", "FI": "Финлянди", "FR": "Франци",
    "DE": "Германи", "GR": "Греци", "HU": "Венгри", "IE": "Ирланди", "IT": "Итали",
    "LV": "Латви", "LT": "Литв", "LU": "Люксембург", "MT": "Мальт", "NL": "Нидерланд",
    "PL": "Польш", "PT": "Португали", "RO": "Румыни", "SK": "Словаки", "SI": "Словени",
    "ES": "Испани", "SE": "Швеци", "GB": "Великобритани", "NO": "Норвеги",
    "CH": "Швейцари", "IS": "Исланди", "MD": "Молд", "RS": "Серби", "ME": "Черногори",
    "MK": "Македони", "AL": "Албани", "BA": "Босни", "XK": "Косов",
}  # fmt: skip


@lru_cache
def _patterns() -> dict[str, re.Pattern]:
    out = {}
    for code, country in COUNTRIES.items():
        extra, capital = EN.get(code, ([], ""))
        words = [country.name, *extra, capital]
        out[code] = re.compile(r"\b(" + "|".join(re.escape(w) for w in words if w) + r")\b")
    return out


def countries_in(text: str) -> list[str]:
    """Monitored countries named in an English headline (case-sensitive: proper nouns)."""
    return [code for code, pattern in _patterns().items() if pattern.search(text)]


def countries_in_ru(text: str) -> list[str]:
    return [code for code, stem in RU.items() if stem in text]
