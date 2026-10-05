"""Where messages go. Add a class with a `send(text)` method to support a new
channel (ntfy, Discord, email...)."""
from __future__ import annotations

import re
from typing import Protocol

import requests

TELEGRAM_MAX_LEN = 4096


class Notifier(Protocol):
    def send(self, text: str) -> None: ...


class NotifyError(Exception):
    pass


class TelegramNotifier:
    """Sends messages via the Telegram Bot API (one HTTPS POST per message).

    Messages use Telegram's HTML formatting: <b>, <i>, <a href="...">.
    """

    def __init__(self, token: str, chat_id: str, session: requests.Session | None = None):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.session = session or requests.Session()

    def send(self, text: str) -> None:
        for chunk in _split(text, TELEGRAM_MAX_LEN):
            try:
                resp = self.session.post(
                    self.url,
                    json={
                        "chat_id": self.chat_id,
                        "text": chunk,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=30,
                )
            except requests.RequestException as e:
                # Don't include the URL in the error: it contains the bot token.
                raise NotifyError(f"Telegram request failed: {type(e).__name__}") from None
            if resp.status_code != 200:
                raise NotifyError(f"Telegram API error {resp.status_code}: {resp.text[:300]}")


class ConsoleNotifier:
    """Prints messages instead of sending them (for --dry-run / local testing)."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)
        plain = re.sub(r'<a href="([^"]*)">(.*?)</a>', r"\2 (\1)", text)
        plain = re.sub(r"</?(?:b|i|code)>", "", plain)
        print("-" * 60)
        print(plain.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))


def _split(text: str, limit: int) -> list[str]:
    """Split long text on blank lines so each part fits Telegram's limit."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                parts.append(current)
            current = block[:limit]
    if current:
        parts.append(current)
    return parts
