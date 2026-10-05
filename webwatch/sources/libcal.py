"""Springshare LibCal event calendars (used by NLB and many other libraries).

The calendar web page loads its events with JavaScript from a JSON endpoint:
    {base_url}/ajax/calendar/list?c=<calendar>&camps=<campus>&page=N...
Reading that JSON directly is far more reliable than scraping the page.

Registration status comes from the JSON's `registration_enabled`, `seatsleft`
and `waitlist` fields. When registration is NOT enabled, the JSON can't tell
"not open yet" apart from "fully booked", so `enrich()` reads the event's own
page, which says either "Registrations open at <time>" or "fully booked".
"""
from __future__ import annotations

import html
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..http import DEFAULT_TIMEOUT
from ..models import Item
from .base import Source, SourceError

_OPENS_AT_RE = re.compile(r"Registrations?\s+opens?\s+(?:at|on)\s+([^<|]+?\d{4})", re.I)
_FULL_RE = re.compile(r"fully\s+booked", re.I)
_REG_REQUIRED_RE = re.compile(r"registration\s+is\s+required", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


class LibCalOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = "https://nlb.libcal.com"
    calendar_id: int
    # Library branch ("campus") ID - the value of the location dropdown on the
    # calendar page. Filtering here (server-side) matters: the unfiltered
    # calendar only returns the next ~280 events, so far-future sessions at a
    # specific branch are missing unless you filter by campus.
    campus_id: int | None = None
    category_ids: list[int] = Field(default_factory=list)
    audience_ids: list[int] = Field(default_factory=list)
    per_page: int = 48
    max_pages: int = 20
    # Visit each matching event's page to find "registration opens at" times.
    check_event_page: bool = True


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text))).strip()


class LibCalSource(Source):
    Options = LibCalOptions
    opts: LibCalOptions

    def _list_url(self) -> str:
        return self.opts.base_url.rstrip("/") + "/ajax/calendar/list"

    def fetch(self) -> list[Item]:
        o = self.opts
        events: dict[str, dict] = {}
        for page in range(1, o.max_pages + 1):
            params = {
                "c": o.calendar_id,
                "date": "0000-00-00",  # = "all upcoming events"
                "perpage": o.per_page,
                "page": page,
                "audience": ",".join(map(str, o.audience_ids)),
                "cats": ",".join(map(str, o.category_ids)),
                "camps": o.campus_id if o.campus_id is not None else "",
                "inc": 0,
            }
            resp = self.session.get(self._list_url(), params=params, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError as e:
                raise SourceError(f"LibCal returned non-JSON response: {resp.text[:200]!r}") from e
            if not isinstance(data, dict) or "results" not in data or "total_results" not in data:
                raise SourceError(f"Unexpected LibCal response shape: keys={list(data)[:10]}")

            results = data["results"] or []
            for ev in results:
                # dict keyed by id de-duplicates events that shift between pages
                events[str(ev["id"])] = ev
            if not results or page * o.per_page >= int(data["total_results"]):
                break
        return [self._to_item(ev) for ev in events.values()]

    def _to_item(self, ev: dict) -> Item:
        details = []
        when = ev.get("date") or ""
        if ev.get("start") and not ev.get("all_day"):
            when = f"{when}, {ev['start']}" + (f" - {ev['end']}" if ev.get("end") else "")
        if when:
            details.append(when)
        if ev.get("location"):
            details.append(ev["location"])

        status = self._status_from_json(ev)
        if status in ("open", "waitlist") and ev.get("seats") is not None:
            details.append(f"Seats left: {ev.get('seatsleft')}/{ev.get('seats')}")

        return Item(
            id=str(ev["id"]),
            title=html.unescape(ev.get("title", "")).strip(),
            url=ev.get("url"),
            status=status,
            details=details,
            fields={
                "location": ev.get("location") or "",
                "campus": ev.get("campus") or "",
                "categories": ev.get("categories") or "",
                "description": _strip_tags(ev.get("shortdesc") or ""),
                "start": ev.get("startdt") or "",
            },
        )

    @staticmethod
    def _status_from_json(ev: dict) -> str:
        if ev.get("registration_enabled"):
            left = ev.get("seatsleft")
            if left is None or int(left) > 0:
                return "open"
            return "waitlist" if ev.get("waitlist") else "full"
        # Registration isn't enabled: could be "not open yet", "fully booked"
        # or a drop-in event. enrich() works out which.
        return "closed"

    def enrich(self, item: Item) -> None:
        if item.status != "closed" or not self.opts.check_event_page or not item.url:
            return
        resp = self.session.get(item.url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        apply_event_page(item, resp.text, self.tz)


def apply_event_page(item: Item, page_html: str, tz) -> None:
    """Update item.status / remind_at from an event page's HTML."""
    no_scripts = re.sub(r"<(script|style)\b.*?</\1>", " ", page_html, flags=re.S | re.I)
    text = _strip_tags(no_scripts.replace("<", "|<"))  # '|' keeps blocks apart

    m = _OPENS_AT_RE.search(text)
    if m:
        opens_text = m.group(1).strip(" |")
        item.status = "not_open"
        item.details.append(f"Registration opens: {opens_text}")
        opens_at = parse_libcal_datetime(opens_text, tz)
        if opens_at:
            item.remind_at = opens_at
            item.remind_text = f"Registration opens at {opens_text}"
        return
    if _FULL_RE.search(text):
        item.status = "full"
        return
    if not _REG_REQUIRED_RE.search(text):
        item.status = "drop_in"


def parse_libcal_datetime(text: str, tz) -> datetime | None:
    """Parse e.g. '12:00 PM Saturday, October 10, 2026' as a local time."""
    text = re.sub(r"\s+", " ", text).strip()
    for fmt in ("%I:%M %p %A, %B %d, %Y", "%I:%M%p %A, %B %d, %Y", "%A, %B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=tz)
        except ValueError:
            continue
    return None
