"""Interface languages: Ukrainian and English are written by hand (the source texts), the
others are machine-translated by `tension-index translate` into locale files.

COUNTRY_LANGS lists each monitored country's official languages that we support: event
summaries are also written in them, so people there read about their country in their
language. Russian is not offered (owner's decision, 2026-11-17).
"""

from __future__ import annotations

SOURCE = ("uk", "en")
LANGUAGES: dict[str, str] = {
    "uk": "Українська", "en": "English", "de": "Deutsch", "fr": "Français", "nl": "Nederlands",
    "it": "Italiano", "es": "Español", "pt": "Português", "pl": "Polski", "cs": "Čeština",
    "sk": "Slovenčina", "hu": "Magyar", "ro": "Română", "bg": "Български", "el": "Ελληνικά",
    "hr": "Hrvatski", "sl": "Slovenščina", "sr": "Српски", "bs": "Bosanski", "mk": "Македонски",
    "sq": "Shqip", "da": "Dansk", "sv": "Svenska", "nb": "Norsk", "fi": "Suomi", "et": "Eesti",
    "lv": "Latviešu", "lt": "Lietuvių", "is": "Íslenska", "mt": "Malti",
}  # fmt: skip
# English names, for prompts.
ENGLISH_NAMES: dict[str, str] = {
    "uk": "Ukrainian", "en": "English", "de": "German", "fr": "French", "nl": "Dutch",
    "it": "Italian", "es": "Spanish", "pt": "Portuguese (European)", "pl": "Polish",
    "cs": "Czech", "sk": "Slovak", "hu": "Hungarian", "ro": "Romanian", "bg": "Bulgarian",
    "el": "Greek", "hr": "Croatian", "sl": "Slovenian", "sr": "Serbian (Cyrillic)",
    "bs": "Bosnian (Latin)", "mk": "Macedonian", "sq": "Albanian", "da": "Danish",
    "sv": "Swedish", "nb": "Norwegian Bokmål", "fi": "Finnish", "et": "Estonian",
    "lv": "Latvian", "lt": "Lithuanian", "is": "Icelandic", "mt": "Maltese",
}  # fmt: skip
COUNTRY_LANGS: dict[str, tuple[str, ...]] = {
    "AT": ("de",), "BE": ("nl", "fr", "de"), "BG": ("bg",), "HR": ("hr",), "CY": ("el",),
    "CZ": ("cs",), "DK": ("da",), "EE": ("et",), "FI": ("fi", "sv"), "FR": ("fr",),
    "DE": ("de",), "GR": ("el",), "HU": ("hu",), "IE": ("en",), "IT": ("it",), "LV": ("lv",),
    "LT": ("lt",), "LU": ("fr", "de"), "MT": ("mt", "en"), "NL": ("nl",), "PL": ("pl",),
    "PT": ("pt",), "RO": ("ro",), "SK": ("sk",), "SI": ("sl",), "ES": ("es",), "SE": ("sv",),
    "GB": ("en",), "NO": ("nb",), "CH": ("de", "fr", "it"), "IS": ("is",), "MD": ("ro",),
    "RS": ("sr",), "ME": ("sr", "bs"), "MK": ("mk",), "AL": ("sq",), "BA": ("bs", "hr", "sr"),
    "XK": ("sq", "sr"),
}  # fmt: skip


def local_languages(country: str) -> tuple[str, ...]:
    """The country's languages beyond the source ones (summaries are written in these too)."""
    return tuple(lang for lang in COUNTRY_LANGS.get(country, ()) if lang not in SOURCE)


def normalize(code: str | None) -> str | None:
    """A browser / Telegram language code ("pt-BR", "no", "sr-Latn") -> one of ours, or None."""
    if not code:
        return None
    base = code.replace("_", "-").split("-")[0].lower()
    base = {"no": "nb", "nn": "nb", "hbs": "sr", "cnr": "sr"}.get(base, base)
    return base if base in LANGUAGES else None
