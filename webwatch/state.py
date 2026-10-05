"""Persistent memory of what we've already seen, stored as a JSON file.

JSON (rather than SQLite) because GitHub Actions has no disk that survives
between runs: the workflow commits this file back to the repo after each run,
and a readable text file gives clean git diffs.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

STATE_VERSION = 1


def empty_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "last_run_date": None, "watchers": {}}


def empty_watcher_state() -> dict[str, Any]:
    return {
        "initialized": False,
        "consecutive_failures": 0,
        "last_error": None,
        "items": {},
    }


def load_state(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return empty_state()
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("watchers", {})
    data.setdefault("last_run_date", None)
    return data


def save_state(state: dict[str, Any], path: str | Path) -> None:
    """Write atomically: write a temp file then rename, so a crash mid-write
    can never leave a half-written (corrupt) state file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".state-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
