"""Shared test helpers: fake HTTP responses so tests never hit the network."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from webwatch.config import Settings, WatcherConfig
from webwatch.models import Item
from webwatch.notifiers import NotifyError
from webwatch.sources.base import Source

SGT = ZoneInfo("Asia/Singapore")


class FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200):
        self.text = text
        self.content = text.encode()
        self.status_code = status_code

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Returns canned responses based on a substring of the requested URL."""

    def __init__(self, routes: dict[str, str | FakeResponse]):
        self.routes = routes
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        for key, resp in self.routes.items():
            if key in url:
                return resp if isinstance(resp, FakeResponse) else FakeResponse(resp)
        return FakeResponse("not found", 404)


class ListSource(Source):
    """A source whose items are set directly by the test."""

    from pydantic import BaseModel as _BM

    class Options(_BM):
        pass

    def __init__(self, items=None, error: Exception | None = None):
        self.items = items or []
        self.error = error

    def fetch(self):
        if self.error:
            raise self.error
        return [Item(**vars(i)) for i in self.items]  # fresh copies each run


class RecordingNotifier:
    def __init__(self, fail: bool = False):
        self.sent: list[str] = []
        self.fail = fail

    def send(self, text: str) -> None:
        if self.fail:
            raise NotifyError("boom")
        self.sent.append(text)


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def watcher():
    return WatcherConfig(name="test", type="html")


def at(*args) -> datetime:
    return datetime(*args, tzinfo=SGT)
