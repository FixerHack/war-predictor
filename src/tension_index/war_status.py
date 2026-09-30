"""War / armed-conflict status on a country's own territory.

Two layers:
1. `config/conflicts.yaml` - curated, human-reviewed status (shown to users).
2. Automatic check against Wikipedia's "List of ongoing armed conflicts" (updated daily by
   editors, grouped by annual death toll). Mismatches are reported to admins for review,
   never applied automatically: the list also names countries hit only by spillover
   (e.g. a drone crash), which must not turn into "war" for a public product.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx
import yaml

from tension_index.countries import COUNTRIES

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "conflicts.yaml"
SEVERITY = ("none", "frozen", "clashes", "active", "war")
ICONS = {"none": "🟢", "frozen": "🧊", "clashes": "🟠", "active": "🔴", "war": "🟥"}

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_PAGE = "List_of_ongoing_armed_conflicts"


@dataclass(slots=True)
class WarStatus:
    country: str
    status: str
    note_uk: str = ""
    note_en: str = ""
    source: str = ""
    borders_war: list[str] = field(default_factory=list)
    borders_aggressor: list[str] = field(default_factory=list)

    def note(self, lang: str) -> str:
        return self.note_uk if lang == "uk" else self.note_en


@lru_cache
def load(path: Path = CONFIG_PATH) -> dict[str, WarStatus]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    default = data.get("default", {"status": "none"})
    result = {}
    for code in COUNTRIES:
        entry = {**default, **(data.get("countries", {}).get(code) or {})}
        if entry["status"] not in SEVERITY:
            raise ValueError(f"{code}: unknown status {entry['status']!r}")
        result[code] = WarStatus(country=code, **entry)
    return result


def get(code: str) -> WarStatus:
    return load()[code]


# --- Automatic check: Wikipedia -------------------------------------------------------------

# Aliases as they appear in Wikipedia flag templates / links.
_ALIASES = {
    "CZ": ["Czech Republic", "Czechia"],
    "MK": ["North Macedonia", "Macedonia"],
    "BA": ["Bosnia and Herzegovina", "Bosnia"],
    "GB": ["United Kingdom", "UK"],
}


def _names(code: str) -> list[str]:
    return _ALIASES.get(code, [COUNTRIES[code].name])


def _section_severity(heading: str) -> str | None:
    h = heading.lower().replace(",", "")
    if h.startswith("10000") or "major war" in h:
        return "war"
    if h.startswith("1000") or "minor war" in h:
        return "war"
    if h.startswith("100") or h.startswith("conflicts"):
        return "active"
    if h.startswith("fewer") or h.startswith("1–99") or "skirmish" in h:
        return "clashes"
    return None


_HEADING = re.compile(r"^==\s*([^=].*?)\s*==\s*$", re.M)


def parse_wikipedia(wikitext: str) -> dict[str, str]:
    """Return {country_code: highest severity} for monitored countries named in the list."""
    found: dict[str, str] = {}
    parts = _HEADING.split(wikitext)
    # parts = [intro, heading1, body1, heading2, body2, ...]
    for heading, body in zip(parts[1::2], parts[2::2], strict=False):
        severity = _section_severity(heading)
        if severity is None:
            continue
        for code in COUNTRIES:
            for name in _names(code):
                # {{flag|Poland}}, {{flagicon|Poland}}, {{flagcountry|Poland}}, [[Poland]]
                pattern = (
                    rf"\{{\{{\s*flag\w*\s*\|\s*{re.escape(name)}\s*[|}}]|\[\[{re.escape(name)}[\]|]"
                )
                if re.search(pattern, body, re.I):
                    if SEVERITY.index(severity) > SEVERITY.index(found.get(code, "none")):
                        found[code] = severity
                    break
    return found


async def fetch_wikipedia(client: httpx.AsyncClient) -> str:
    response = await client.get(
        WIKI_API,
        params={
            "action": "parse",
            "page": WIKI_PAGE,
            "prop": "wikitext",
            "format": "json",
            "formatversion": "2",
        },
    )
    response.raise_for_status()
    return response.json()["parse"]["wikitext"]


def mismatches(curated: dict[str, WarStatus], detected: dict[str, str]) -> list[str]:
    """Human-readable differences between the curated file and the automatic tracker."""
    out = []
    for code, status in curated.items():
        auto = detected.get(code, "none")
        # "frozen" situations have no deaths, so they are expected to be absent from the list.
        if auto == status.status or (status.status == "frozen" and auto == "none"):
            continue
        out.append(f"{code}: curated={status.status}, wikipedia={auto}")
    return out
