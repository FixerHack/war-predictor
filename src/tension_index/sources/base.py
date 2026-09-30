"""Common interface for travel-advisory sources."""

from __future__ import annotations

import abc
import re
from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

from tension_index.countries import Country


@dataclass(slots=True)
class Advisory:
    country: str
    url: str
    text: str
    title: str | None = None
    level: str | None = None  # publisher-specific level key (see config/weights.yaml)
    source_updated: str | None = None


class SourceFormatError(ValueError):
    """The response did not look as expected (layout/API change). Run `tension-index probe`."""


class Source(abc.ABC):
    """One publishing government. Implementations only fetch and parse; storage and
    diffing happen in the collector. `name` doubles as the publisher key in weights.yaml."""

    name: str = ""
    label: str = ""
    timeout: float | None = None  # seconds; None = the client default

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.raw: dict[str, str] = {}  # url -> last response body, for `probe`

    async def prepare(self) -> None:  # noqa: B027 - optional hook
        """Load a shared index once per run (sources publishing all countries in one file)."""

    @abc.abstractmethod
    def supports(self, country: Country) -> bool: ...

    @abc.abstractmethod
    async def fetch(self, country: Country) -> Advisory: ...

    async def get(self, url: str, **params: str) -> httpx.Response:
        kwargs = {"timeout": self.timeout} if self.timeout else {}
        response = await self.client.get(url, params=params or None, **kwargs)
        self.raw[str(response.url)] = response.text
        response.raise_for_status()
        return response

    async def get_json(self, url: str, **params: str) -> object:
        response = await self.get(url, **params)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceFormatError(f"{self.name}: not JSON at {url}") from exc


class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "div", "section"}
    _SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def main_content(html: str) -> str:
    """The <main> (or first <article>) element of a page, so menus and footers don't
    produce spurious changes. Falls back to the whole document."""
    for tag in ("main", "article"):
        m = re.search(rf"<{tag}\b[^>]*>(.*)</{tag}>", html, re.S | re.I)
        if m:
            return m.group(1)
    return html
