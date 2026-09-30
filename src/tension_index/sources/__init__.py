"""Advisory sources. Register new sources in `REGISTRY` (key = publisher in weights.yaml)."""

from tension_index.sources.au import AuSource
from tension_index.sources.base import Advisory, Source, SourceFormatError
from tension_index.sources.ca import CaSource
from tension_index.sources.de import DeSource
from tension_index.sources.fr import FrSource
from tension_index.sources.gov_uk import GovUkSource
from tension_index.sources.us import UsSource

REGISTRY: dict[str, type[Source]] = {
    cls.name: cls for cls in (GovUkSource, DeSource, UsSource, CaSource, AuSource, FrSource)
}

__all__ = ["REGISTRY", "Advisory", "Source", "SourceFormatError"]
