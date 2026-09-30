"""War / armed-conflict status on a country's own territory.

Two layers:
1. `config/conflicts.yaml` - curated, human-reviewed status (shown to users).
2. Automatic check against Wikipedia's "List of ongoing armed conflicts" (updated daily by
   editors, grouped by annual death toll), parsed from the rendered page because its tables
   are transcluded templates. Mismatches are reported to admins for review,
   never applied automatically: the list also names countries hit only by spillover
   (e.g. a drone crash), which must not turn into "war" for a public product.
"""

from __future__ import annotations

import html as html_lib
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


def section_severity(heading: str) -> str | None:
    """Map a death-toll heading to a severity. Order matters: "fewer than 100" contains "100"."""
    h = heading.lower().replace(",", "").replace("\u2013", "-").replace("\u2014", "-")
    if "fewer" in h or re.search(r"\b1-99\b", h) or "skirmish" in h or "clash" in h:
        return "clashes"
    if "10000" in h or "major war" in h:
        return "war"
    if "1000" in h or "minor war" in h:
        return "war"
    if re.search(r"\b100\b", h) or h.startswith("conflicts"):
        return "active"
    return None


_HEADING = re.compile(r"<h([2-4])\b[^>]*>(.*?)</h\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


@dataclass(slots=True)
class Heading:
    level: int
    text: str
    severity: str | None  # own or inherited from the enclosing death-toll section


def _sections(html: str) -> list[tuple[Heading, str]]:
    """Split rendered HTML into (heading, body) pairs. Subheadings (e.g. regions) inside a
    death-toll section inherit its severity until a heading of the same or higher level."""
    matches = list(_HEADING.finditer(html))
    out: list[tuple[Heading, str]] = []
    current: str | None = None
    current_level = 99
    for i, m in enumerate(matches):
        level = int(m.group(1))
        text = " ".join(html_lib.unescape(_TAG.sub("", m.group(2))).split())
        own = section_severity(text)
        if own is not None:
            current, current_level = own, level
        elif level <= current_level:
            current, current_level = None, 99
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        out.append((Heading(level, text, own or current), html[m.end() : body_end]))
    return out


def headings(html: str) -> list[Heading]:
    """Diagnostics: every heading with the severity the parser assigns to it."""
    return [h for h, _ in _sections(html)]


def _mentions(body: str, name: str) -> bool:
    # Rendered links: <a href="/wiki/Poland" title="Poland">
    return bool(
        re.search(rf'title="{re.escape(name)}"', body)
        or re.search(rf'href="/wiki/{re.escape(name.replace(" ", "_"))}"', body)
    )


def parse_wikipedia(html: str) -> dict[str, str]:
    """Return {country_code: highest severity} for monitored countries named in the list.

    Works on the rendered page (templates transcluded). Raises ValueError when no death-toll
    section is recognised: a changed layout must fail loudly, not look like "no conflicts".
    """
    found: dict[str, str] = {}
    sections = [(h, body) for h, body in _sections(html) if h.severity]
    if not sections:
        raise ValueError("no conflict sections recognised on the Wikipedia page; layout changed?")
    for heading, body in sections:
        for code in COUNTRIES:
            if any(_mentions(body, name) for name in _names(code)):
                severity = heading.severity
                assert severity is not None
                if SEVERITY.index(severity) > SEVERITY.index(found.get(code, "none")):
                    found[code] = severity
    return found


async def fetch_wikipedia(client: httpx.AsyncClient) -> str:
    """Rendered HTML of the list (tables are transcluded templates, absent from raw wikitext)."""
    response = await client.get(
        WIKI_API,
        params={
            "action": "parse",
            "page": WIKI_PAGE,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        },
    )
    response.raise_for_status()
    return response.json()["parse"]["text"]


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
