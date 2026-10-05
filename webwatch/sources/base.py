"""Base class every source (website type) implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import requests
from pydantic import BaseModel

from ..models import Item


class SourceError(Exception):
    """The site responded in a way we don't understand (layout/API changed?)."""


class Source(ABC):
    # Each subclass defines a pydantic model describing its `options:` block.
    Options: ClassVar[type[BaseModel]]

    def __init__(self, options: dict[str, Any], session: requests.Session, tz: ZoneInfo):
        self.opts = self.Options.model_validate(options)
        self.session = session
        self.tz = tz

    @abstractmethod
    def fetch(self) -> list[Item]:
        """Return every item currently on the page. Raise on failure."""

    def enrich(self, item: Item) -> None:
        """Optional extra work, run only on items that passed the filters.

        Use this for anything expensive (e.g. fetching each item's detail
        page) so we don't do it for hundreds of items we don't care about.
        """
        return None
