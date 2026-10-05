"""The main loop: fetch -> filter -> compare with state -> notify -> update state."""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html import escape
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from .config import AppConfig, Settings, WatcherConfig
from .models import Item, status_label, status_rank
from .notifiers import Notifier, NotifyError
from .sources import SOURCES, Source
from .state import empty_watcher_state

log = logging.getLogger(__name__)

SourceFactory = Callable[[WatcherConfig, requests.Session, ZoneInfo], Source]
BASELINE_LIST_LIMIT = 10


def build_source(w: WatcherConfig, session: requests.Session, tz: ZoneInfo) -> Source:
    return SOURCES[w.type](w.options, session, tz)


@dataclass
class RunResult:
    notify_failed: list[str] = field(default_factory=list)
    failing: list[str] = field(default_factory=list)  # at/over the alert threshold
    messages_sent: int = 0

    @property
    def exit_code(self) -> int:
        # A non-zero exit marks the GitHub Actions run red, and GitHub emails
        # you about failed scheduled runs - a backup alert channel.
        return 1 if (self.notify_failed or self.failing) else 0


# ---------------------------------------------------------------- formatting

def format_item(item: Item) -> str:
    title = escape(item.title)
    lines = [f'<a href="{escape(item.url, quote=True)}">{title}</a>' if item.url else f"<b>{title}</b>"]
    lines += [escape(d) for d in item.details]
    if item.status and item.status != "closed":
        lines.append(f"Status: {escape(status_label(item.status))}")
    return "\n".join(lines)


def _join_items(items: list[Item]) -> str:
    return "\n\n".join(format_item(i) for i in items)


def msg_new(name: str, items: list[Item]) -> str:
    head = f"New in {name}" if len(items) == 1 else f"{len(items)} new in {name}"
    return f"<b>{escape(head)}</b>\n\n{_join_items(items)}"


def msg_status(name: str, item: Item, old_status: str | None) -> str:
    head = "Registration is OPEN - book now" if item.status == "open" else status_label(item.status)
    was = f"\n(was: {escape(status_label(old_status) or 'unknown')})" if old_status else ""
    return f"<b>{escape(head)}</b> - {escape(name)}{was}\n\n{format_item(item)}"


def msg_reminder(name: str, item: Item, now: datetime) -> str:
    assert item.remind_at is not None
    mins = max(1, round((item.remind_at - now).total_seconds() / 60))
    text = item.remind_text or "Reminder"
    return f"<b>Heads up: {escape(text)} (in ~{mins} min)</b> - {escape(name)}\n\n{format_item(item)}"


def msg_baseline(name: str, items: list[Item]) -> str:
    head = f"<b>Now watching: {escape(name)}</b>\nI'll message you when something new appears."
    if not items:
        return head + "\nNothing matches right now."
    shown = items[:BASELINE_LIST_LIMIT]
    more = len(items) - len(shown)
    tail = f"\n\n...and {more} more" if more > 0 else ""
    return f"{head}\nCurrently matching ({len(items)}):\n\n{_join_items(shown)}{tail}"


def msg_failing(name: str, failures: int, error: str) -> str:
    return (
        f"<b>Watcher failing: {escape(name)}</b>\n"
        f"{failures} runs in a row failed. The site may be down or its layout changed.\n"
        f"Last error: <code>{escape(error[:500])}</code>"
    )


def msg_recovered(name: str) -> str:
    return f"<b>Watcher recovered: {escape(name)}</b>\nIt's working again."


# ---------------------------------------------------------------- core logic

def _days_since(day: str | None, today: date) -> int:
    if not day:
        return 10**6
    try:
        return (today - date.fromisoformat(day)).days
    except ValueError:
        return 10**6


def process_watcher(
    w: WatcherConfig,
    wstate: dict[str, Any],
    source: Source,
    notifier: Notifier,
    settings: Settings,
    now: datetime,
    result: RunResult,
) -> dict[str, Any]:
    """Run one watcher and return its NEW state.

    If sending notifications fails, the OLD state is returned so that the
    same notifications are retried on the next run instead of being lost.
    """
    prev = copy.deepcopy(wstate)
    prev_items: dict[str, dict] = prev.get("items", {})

    # 1. Fetch + filter + enrich
    try:
        items = source.fetch()
        matched = [i for i in items if w.filters.match(i)]
        log.info("[%s] fetched %d items, %d match filters", w.name, len(items), len(matched))
        for item in matched:
            try:
                source.enrich(item)
            except Exception as e:  # one bad detail page shouldn't fail the run
                log.warning("[%s] could not enrich %s: %s", w.name, item.id, e)
                old = prev_items.get(item.id)
                if old:
                    item.status = old.get("status")
    except Exception as e:
        failures = prev.get("consecutive_failures", 0) + 1
        log.error("[%s] failed (%d in a row): %s", w.name, failures, e)
        prev["consecutive_failures"] = failures
        prev["last_error"] = f"{type(e).__name__}: {e}"[:500]
        if failures >= settings.failure_alert_after:
            result.failing.append(w.name)
        if failures == settings.failure_alert_after:
            try:
                notifier.send(msg_failing(w.name, failures, prev["last_error"]))
                result.messages_sent += 1
            except NotifyError as ne:
                log.error("[%s] could not send failure alert: %s", w.name, ne)
                result.notify_failed.append(w.name)
        return prev

    # 2. Compare with what we saw last time
    today = now.date()
    now_iso = now.isoformat(timespec="seconds")
    initialized = prev.get("initialized", False)
    new_items: dict[str, dict] = {}
    new_found: list[Item] = []
    messages: list[str] = []

    for item in matched:
        old = prev_items.get(item.id)
        rec = {
            "title": item.title,
            "status": item.status,
            "first_seen": old.get("first_seen", now_iso) if old else now_iso,
            "last_seen": today.isoformat(),
            "reminded_for": old.get("reminded_for") if old else None,
        }
        if initialized:
            if old is None:
                new_found.append(item)
            elif (
                item.status in w.alert_on_status
                and status_rank(item.status) > status_rank(old.get("status"))
            ):
                messages.append(msg_status(w.name, item, old.get("status")))

        if item.remind_at and w.remind_before_minutes > 0:
            key = item.remind_at.isoformat()
            window_start = item.remind_at - timedelta(minutes=w.remind_before_minutes)
            if rec["reminded_for"] != key and window_start <= now < item.remind_at:
                messages.append(msg_reminder(w.name, item, now))
                rec["reminded_for"] = key
        new_items[item.id] = rec

    if not initialized:
        messages.insert(0, msg_baseline(w.name, matched))
    elif new_found:
        messages.insert(0, msg_new(w.name, new_found))

    # Keep items that briefly disappeared, so they don't count as "new" when
    # they come back. Forget them after a while (e.g. past events).
    for item_id, old in prev_items.items():
        if item_id not in new_items and _days_since(old.get("last_seen"), today) <= settings.forget_after_days:
            new_items[item_id] = old

    if prev.get("consecutive_failures", 0) >= settings.failure_alert_after:
        messages.append(msg_recovered(w.name))

    # 3. Notify - only commit the new state if every message went out
    try:
        for m in messages:
            notifier.send(m)
            result.messages_sent += 1
    except NotifyError as e:
        log.error("[%s] notification failed, will retry next run: %s", w.name, e)
        result.notify_failed.append(w.name)
        return wstate

    return {
        "initialized": True,
        "consecutive_failures": 0,
        "last_error": None,
        "items": new_items,
    }


def run(
    config: AppConfig,
    state: dict[str, Any],
    notifier: Notifier,
    session: requests.Session,
    now: datetime | None = None,
    source_factory: SourceFactory = build_source,
    only: list[str] | None = None,
) -> RunResult:
    """Run all enabled watchers, updating `state` in place."""
    tz = ZoneInfo(config.settings.timezone)
    now = now or datetime.now(tz)
    result = RunResult()

    watchers = [w for w in config.watchers if w.enabled and (not only or w.name in only)]
    # Build every source first so option typos fail fast, before any network calls.
    sources = {w.name: source_factory(w, session, tz) for w in watchers}

    for w in watchers:
        wstate = state["watchers"].get(w.name) or empty_watcher_state()
        state["watchers"][w.name] = process_watcher(
            w, wstate, sources[w.name], notifier, config.settings, now, result
        )

    # Changes at most once a day; also keeps the repo "active" so GitHub
    # doesn't pause the schedule after 60 days without commits.
    state["last_run_date"] = now.date().isoformat()
    return result
