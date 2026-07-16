"""Persisted settings for CCUsageMonitor.

Stored as JSON at %APPDATA%/CCUsageMonitor/config.json (falls back to
~/.ccusagemonitor/config.json on non-Windows). Everything the user can move or
tweak lives here so the overlay restores exactly as they left it.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _config_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "CCUsageMonitor"
    return Path.home() / ".ccusagemonitor"


CONFIG_PATH = _config_dir() / "config.json"


@dataclass
class Config:
    # Window placement in global virtual-desktop coordinates. None => center on
    # primary screen on first launch.
    pos_x: int | None = None
    pos_y: int | None = None
    collapsed: bool = False
    opacity: float = 0.95
    click_through: bool = False

    # Which project's session logs to watch. None => auto (most recently active
    # session across all projects under ~/.claude/projects).
    monitored_project_path: str | None = None

    # Poll intervals (seconds).
    local_poll_seconds: float = 2.0
    api_poll_seconds: float = 300.0

    # Optional manual limit overrides if the API is unavailable (fractions/None).
    manual_session_limit: float | None = None
    manual_weekly_limit: float | None = None

    # Play a chime when the 5-hour session window rolls over (usage resets).
    sound_on_reset: bool = True

    # Free-form extension bucket so we can add keys without migration pain.
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)  # atomic on Windows/NTFS
