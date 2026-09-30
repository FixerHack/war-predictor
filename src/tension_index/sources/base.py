"""Common interface for travel-advisory sources."""

from __future__ import annotations

import abc
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
    level: str | None = None  # source-specific level/alert status, stored verbatim
    source_updated: str | None = None


class Source(abc.ABC):
    """One publishing government (e.g. UK FCDO). Implementations must be side-effect free:
    fetch and parse only; storage and diffing happen in the collector."""

    name: str = ""
    label: str = ""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    @abc.abstractmethod
    def supports(self, country: Country) -> bool: ...

    @abc.abstractmethod
    async def fetch(self, country: Country) -> Advisory: ...


class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "div", "section"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = (line.strip() for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)
