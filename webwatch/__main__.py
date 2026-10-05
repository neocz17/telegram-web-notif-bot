"""Command-line entry point.

    python -m webwatch                 # run all watchers, send Telegram messages, save state
    python -m webwatch --dry-run       # print messages instead, don't save state
    python -m webwatch --only "Jurong Library sewing"
    python -m webwatch --test-telegram # send a test message to check your setup

Telegram credentials come from environment variables (never put them in files
you commit): TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. Locally you can put them
in a `.env` file (already git-ignored).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from .config import load_config
from .http import make_session
from .notifiers import ConsoleNotifier, NotifyError, TelegramNotifier
from .runner import run
from .state import load_state, save_state


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env reader (KEY=value lines) so local runs need no extra package."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="webwatch", description="Get notified when websites add new things.")
    p.add_argument("--config", default="watchers.yaml")
    p.add_argument("--state", default="state/state.json")
    p.add_argument("--dry-run", action="store_true", help="print messages, don't send or save state")
    p.add_argument("--only", action="append", help="run only this watcher (repeatable)")
    p.add_argument("--test-telegram", action="store_true", help="send a test message and exit")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    _load_dotenv()

    try:
        config = load_config(args.config)
    except (OSError, ValidationError, ValueError) as e:
        print(f"Config error in {args.config}:\n{e}", file=sys.stderr)
        return 2

    session = make_session(config.settings.user_agent)

    if args.dry_run:
        notifier = ConsoleNotifier()
    else:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            print(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set "
                "(or use --dry-run to just print messages).",
                file=sys.stderr,
            )
            return 2
        notifier = TelegramNotifier(token, chat_id)

    if args.test_telegram:
        try:
            notifier.send("<b>webwatch</b>: test message - your setup works.")
        except NotifyError as e:
            print(f"Failed: {e}", file=sys.stderr)
            return 1
        print("Test message sent.")
        return 0

    state = load_state(args.state)
    try:
        result = run(config, state, notifier, session, only=args.only)
    except ValidationError as e:
        print(f"Invalid watcher options:\n{e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("-" * 60)
        print(f"Dry run: {result.messages_sent} message(s) would be sent; state not saved.")
    else:
        save_state(state, args.state)
        logging.info("Done: %d message(s) sent.", result.messages_sent)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
