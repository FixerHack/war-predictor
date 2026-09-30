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
from html.parser import HTMLParser
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


def _mentions(fragment: str, name: str) -> bool:
    # Rendered links: <a href="/wiki/Poland" title="Poland">
    return bool(
        re.search(rf'title="{re.escape(name)}"', fragment)
        or re.search(rf'href="/wiki/{re.escape(name.replace(" ", "_"))}"', fragment)
    )


@dataclass(slots=True)
class _Cell:
    header: bool
    html: str
    rowspan: int = 1
    colspan: int = 1

    @property
    def text(self) -> str:
        return " ".join(html_lib.unescape(_TAG.sub(" ", self.html)).split())


class _TableParser(HTMLParser):
    """Collects rows of top-level `wikitable` tables; nested tables stay inside cell HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.tables: list[list[list[_Cell]]] = []
        self._depth = 0  # nesting depth of <table> inside a wikitable
        self._cell: _Cell | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "table":
            if self._depth == 0 and "wikitable" in (a.get("class") or ""):
                self.tables.append([])
                self._depth = 1
                return
            if self._depth:
                self._depth += 1
        if not self._depth:
            return
        if self._depth == 1 and tag == "tr":
            self.tables[-1].append([])
            return
        if self._depth == 1 and tag in ("td", "th") and self.tables[-1]:
            span = lambda key: int(re.sub(r"\D", "", a.get(key) or "1") or 1)  # noqa: E731
            self._cell = _Cell(tag == "th", "", span("rowspan"), span("colspan"))
            self.tables[-1][-1].append(self._cell)
            return
        if self._cell is not None:
            self._cell.html += self.get_starttag_text() or ""

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if tag == "table":
            self._depth -= 1
            if self._depth == 0:
                self._cell = None
                return
        if self._depth == 1 and tag in ("td", "th", "tr"):
            self._cell = None
            return
        if self._cell is not None:
            self._cell.html += f"</{tag}>"

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.html += data

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")


def _grid(rows: list[list[_Cell]]) -> list[list[_Cell | None]]:
    """Expand rowspan/colspan so that each row has one entry per column."""
    out: list[list[_Cell | None]] = []
    carry: dict[int, tuple[_Cell, int]] = {}  # column -> (cell, rows still covered)
    for row in rows:
        line: list[_Cell | None] = []
        cells = iter(row)
        col = 0
        pending = True
        while pending or col in carry:
            if col in carry:
                cell, left = carry[col]
                line.append(cell)
                if left > 1:
                    carry[col] = (cell, left - 1)
                else:
                    del carry[col]
                col += 1
                continue
            cell = next(cells, None)
            if cell is None:
                pending = False
                continue
            for _ in range(cell.colspan):
                line.append(cell)
                if cell.rowspan > 1:
                    carry[col] = (cell, cell.rowspan - 1)
                col += 1
        out.append(line)
    return out


@dataclass(slots=True)
class Mention:
    country: str
    severity: str
    section: str
    conflict: str
    column: str  # header of the column the country was found in ("*" = whole table)
    cell: str = ""  # text of that cell, for --explain


def mentions(html: str) -> list[Mention]:
    """Every monitored country named in the Location column of the death-toll tables.

    Only "Location" counts: belligerents and notes also link to countries (e.g. France as
    a party to a conflict abroad), which says nothing about fighting on their territory.
    A table without a Location column is scanned whole, so a layout change over-reports
    (and reaches a human) rather than silently missing a war.
    """
    sections = [(h, body) for h, body in _sections(html) if h.severity]
    if not sections:
        raise ValueError("no conflict sections recognised on the Wikipedia page; layout changed?")
    out: list[Mention] = []
    for heading, body in sections:
        severity = heading.severity
        assert severity is not None
        parser = _TableParser()
        parser.feed(body)
        for table in parser.tables:
            grid = _grid(table)
            header_idx = next(
                (i for i, r in enumerate(grid) if r and all(c and c.header for c in r)), None
            )
            headers = (
                [c.text.lower() if c else "" for c in grid[header_idx]]
                if header_idx is not None
                else []
            )
            loc_cols = [i for i, h in enumerate(headers) if "location" in h]
            # "Start of conflict" also contains "conflict": prefer a header without start/year.
            conflict_cols = [i for i, h in enumerate(headers) if "conflict" in h]
            name_col = next(
                (i for i in conflict_cols if not re.search(r"start|year|began", headers[i])),
                conflict_cols[0] if conflict_cols else None,
            )
            for row in grid[(header_idx or 0) + (1 if header_idx is not None else 0) :]:
                if not row:
                    continue
                cols = loc_cols or range(len(row))
                conflict = (
                    row[name_col].text
                    if name_col is not None and name_col < len(row) and row[name_col]
                    else ""
                )
                for code in COUNTRIES:
                    for col in cols:
                        cell = row[col] if col < len(row) else None
                        if cell and any(_mentions(cell.html, n) for n in _names(code)):
                            column = headers[col] if loc_cols else "*"
                            out.append(
                                Mention(code, severity, heading.text, conflict, column, cell.text)
                            )
                            break
    return out


def parse_wikipedia(html: str) -> dict[str, str]:
    """Return {country_code: highest severity} from the Location columns (see `mentions`)."""
    found: dict[str, str] = {}
    for m in mentions(html):
        if SEVERITY.index(m.severity) > SEVERITY.index(found.get(m.country, "none")):
            found[m.country] = m.severity
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
