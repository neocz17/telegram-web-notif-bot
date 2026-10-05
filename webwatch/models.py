"""Core data types shared by sources, the runner and notifiers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# How "bookable" a status is. When an item's status moves to a HIGHER rank
# (e.g. not_open -> open, full -> waitlist), the runner can send an alert.
# Any status not listed here (full, not_open, drop_in, None, ...) has rank 0.
STATUS_RANK = {"open": 2, "waitlist": 1}

STATUS_LABELS = {
    "open": "Registration OPEN",
    "waitlist": "Full - waitlist available",
    "full": "Fully booked",
    "not_open": "Registration not open yet",
    "closed": "Registration not available",
    "drop_in": "No registration needed",
}


def status_rank(status: str | None) -> int:
    return STATUS_RANK.get(status or "", 0)


def status_label(status: str | None) -> str:
    if status is None:
        return ""
    return STATUS_LABELS.get(status, status)


@dataclass
class Item:
    """One thing on a watched page: an event, a product, a listing...

    `id` must be stable across runs - it is how we know whether we've seen
    the item before (e.g. an event ID, or the item's URL).
    """

    id: str
    title: str
    url: str | None = None
    status: str | None = None
    # Extra human-readable lines shown in notifications (date, venue, price...)
    details: list[str] = field(default_factory=list)
    # Named values that filters can match against (e.g. {"location": "..."})
    fields: dict[str, str] = field(default_factory=dict)
    # Optional moment to remind the user about (e.g. registration opening time).
    # Must be timezone-aware.
    remind_at: datetime | None = None
    remind_text: str | None = None
