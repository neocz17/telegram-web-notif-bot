"""RSS / Atom feeds - many blogs, shops and news sites publish one."""
from __future__ import annotations

import feedparser
from pydantic import BaseModel, ConfigDict

from ..http import DEFAULT_TIMEOUT
from ..models import Item
from .base import Source, SourceError


class RssOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str


class RssSource(Source):
    Options = RssOptions
    opts: RssOptions

    def fetch(self) -> list[Item]:
        resp = self.session.get(self.opts.url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return parse_feed(resp.content)


def parse_feed(content: bytes | str) -> list[Item]:
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise SourceError(f"Could not parse feed: {feed.bozo_exception}")
    items = []
    for e in feed.entries:
        key = e.get("id") or e.get("link") or e.get("title")
        if not key:
            continue
        details = [e["published"]] if e.get("published") else []
        items.append(
            Item(
                id=str(key),
                title=(e.get("title") or "(untitled)").strip(),
                url=e.get("link"),
                details=details,
                fields={"summary": e.get("summary", "")},
            )
        )
    return items
