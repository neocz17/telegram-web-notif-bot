"""Loading and validating watchers.yaml.

pydantic turns the raw YAML dict into typed objects and gives readable
errors (e.g. "watchers.0.type: Input should be 'libcal', 'rss' or 'html'")
when the config has a typo, instead of failing somewhere deep in the code.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import Item


class Filters(BaseModel):
    """Decides which fetched items you care about. All conditions must pass."""

    model_config = ConfigDict(extra="forbid")

    include: str | None = None  # regex that the title must match
    exclude: str | None = None  # regex that the title must NOT match
    fields: dict[str, str] = Field(default_factory=dict)  # field name -> regex

    @field_validator("include", "exclude")
    @classmethod
    def _valid_regex(cls, v: str | None) -> str | None:
        if v is not None:
            re.compile(v)
        return v

    @field_validator("fields")
    @classmethod
    def _valid_field_regexes(cls, v: dict[str, str]) -> dict[str, str]:
        for pattern in v.values():
            re.compile(pattern)
        return v

    def match(self, item: Item) -> bool:
        if self.include and not re.search(self.include, item.title):
            return False
        if self.exclude and re.search(self.exclude, item.title):
            return False
        for name, pattern in self.fields.items():
            if not re.search(pattern, item.fields.get(name, "")):
                return False
        return True


class WatcherConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The name is also the key in state.json - renaming a watcher makes it
    # start fresh (silent baseline again).
    name: str
    type: Literal["libcal", "rss", "html"]
    enabled: bool = True
    options: dict[str, Any] = Field(default_factory=dict)  # validated by the source
    filters: Filters = Field(default_factory=Filters)
    # Alert when an item's status rises to one of these (see models.STATUS_RANK).
    alert_on_status: list[str] = Field(default_factory=lambda: ["open", "waitlist"])
    # Send a heads-up this many minutes before an item's remind_at time
    # (for LibCal: when registration opens). 0 disables reminders.
    remind_before_minutes: int = 60


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Message you after this many failed runs in a row for one watcher
    failure_alert_after: int = 3
    # Forget items that haven't been seen for this many days
    forget_after_days: int = 14
    user_agent: str = "Mozilla/5.0 (compatible; personal-webwatch/1.0)"
    timezone: str = "Asia/Singapore"


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settings: Settings = Field(default_factory=Settings)
    watchers: list[WatcherConfig]

    @model_validator(mode="after")
    def _unique_names(self) -> "AppConfig":
        names = [w.name for w in self.watchers]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"Duplicate watcher names: {sorted(dupes)}")
        return self


def load_config(path: str | Path) -> AppConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig.model_validate(raw)
