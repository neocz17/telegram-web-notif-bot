"""Shared HTTP session with sensible timeouts and automatic retries."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 30  # seconds


def make_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    # Retry GETs on flaky network errors / server hiccups, waiting 2s, 4s, 8s.
    # (POSTs are NOT retried, so a Telegram message is never sent twice.)
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = user_agent
    return session
