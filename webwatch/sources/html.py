"""Generic HTML pages, described with CSS selectors in watchers.yaml.

Selector spec format used in options:
    ".price"        -> text of the first element matching .price inside the item
    "a@href"        -> the href attribute of the first <a> inside the item
    "@data-id"      -> attribute of the item element itself
    ""              -> text of the item element itself

Only works for pages whose content is in the HTML the server sends. If the
page fills itself in with JavaScript, look for the JSON request it makes
(browser DevTools > Network > Fetch/XHR) and write a source for that instead.
"""
from __future__ import annotations

import hashlib
from typing import Literal
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field

from ..http import DEFAULT_TIMEOUT
from ..models import Item
from .base import Source, SourceError


class HtmlOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    item_selector: str  # CSS selector matching each listing/card
    title: str = ""  # selector spec for the title (see module docstring)
    link: str | None = "a@href"
    fields: dict[str, str] = Field(default_factory=dict)  # name -> selector spec
    id_from: Literal["link", "title"] = "link"
    # If fewer items than this are found, treat it as an error: the site's
    # layout probably changed and the selectors no longer match.
    min_items: int = 1


def select_value(el, spec: str | None) -> str | None:
    if spec is None:
        return None
    selector, _, attr = spec.rpartition("@") if "@" in spec else (spec, "", "")
    target = el.select_one(selector) if selector.strip() else el
    if target is None:
        return None
    if attr:
        value = target.get(attr)
        if isinstance(value, list):
            value = " ".join(value)
        return value.strip() if value else None
    return target.get_text(" ", strip=True) or None


class HtmlSource(Source):
    Options = HtmlOptions
    opts: HtmlOptions

    def fetch(self) -> list[Item]:
        resp = self.session.get(self.opts.url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return parse_html(resp.text, self.opts)


def parse_html(page: str, o: HtmlOptions) -> list[Item]:
    soup = BeautifulSoup(page, "html.parser")
    elements = soup.select(o.item_selector)
    if len(elements) < o.min_items:
        raise SourceError(
            f"Found {len(elements)} items for selector {o.item_selector!r} "
            f"(expected at least {o.min_items}) - has the page layout changed?"
        )
    items = []
    for el in elements:
        title = select_value(el, o.title) or "(untitled)"
        link = select_value(el, o.link)
        if link:
            link = urljoin(o.url, link)
        fields = {name: select_value(el, spec) or "" for name, spec in o.fields.items()}
        key_source = link if (o.id_from == "link" and link) else title
        items.append(
            Item(
                id=hashlib.sha1(key_source.encode()).hexdigest()[:16],
                title=title,
                url=link,
                details=[f"{k}: {v}" for k, v in fields.items() if v],
                fields=fields,
            )
        )
    return items
