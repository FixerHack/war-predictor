"""Advisory sources. Register new sources in `REGISTRY`."""

from tension_index.sources.base import Advisory, Source
from tension_index.sources.gov_uk import GovUkSource

REGISTRY: dict[str, type[Source]] = {
    GovUkSource.name: GovUkSource,
}

__all__ = ["REGISTRY", "Advisory", "Source"]
