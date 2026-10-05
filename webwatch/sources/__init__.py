"""Registry mapping the `type:` in watchers.yaml to a Source class."""
from __future__ import annotations

from .base import Source, SourceError
from .html import HtmlSource
from .libcal import LibCalSource
from .rss import RssSource

SOURCES: dict[str, type[Source]] = {
    "libcal": LibCalSource,
    "rss": RssSource,
    "html": HtmlSource,
}

__all__ = ["SOURCES", "Source", "SourceError"]
