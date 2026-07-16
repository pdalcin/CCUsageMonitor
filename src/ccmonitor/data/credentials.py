"""Read-only access to Claude Code's stored OAuth token.

Claude Code normally stores the token as JSON at ``~/.claude/.credentials.json``,
but the location varies: users can relocate the whole config dir with the
``CLAUDE_CONFIG_DIR`` environment variable, and some installs live under a
different home/APPDATA layout. We therefore search a list of candidate paths (and
honour a user-supplied override) rather than assuming a single fixed file.

The token is never logged, copied, or written back — this module only ever
*reads*.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

# Kept for backwards-compat / documentation: the default, most common location.
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


@dataclass
class Credentials:
    access_token: str
    expires_at_ms: int | None
    subscription_type: str | None
    rate_limit_tier: str | None
    source_path: Path | None = None  # where we actually found it (for diagnostics)

    @property
    def is_expired(self) -> bool:
        if not self.expires_at_ms:
            return False
        return time.time() * 1000 >= self.expires_at_ms


def _dedupe(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def credentials_search_paths(override: str | None = None) -> list[Path]:
    """Ordered list of places to look for ``.credentials.json``.

    A user-supplied ``override`` wins, then ``CLAUDE_CONFIG_DIR``, then the usual
    home/APPDATA locations. Used both to load credentials and to tell the user
    *where* we looked when we can't find them.
    """
    paths: list[Path] = []
    if override:
        paths.append(Path(override).expanduser())

    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if env_dir:
        # CLAUDE_CONFIG_DIR may point at the dir, or (rarely) the file itself.
        p = Path(env_dir).expanduser()
        paths.append(p if p.name == ".credentials.json" else p / ".credentials.json")

    paths.append(Path.home() / ".claude" / ".credentials.json")

    for env in ("APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"):
        base = os.environ.get(env)
        if base:
            paths.append(Path(base) / "claude" / ".credentials.json")
            paths.append(Path(base) / "Claude" / ".credentials.json")

    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        paths.append(Path(userprofile) / ".claude" / ".credentials.json")

    return _dedupe(paths)


def _try_load(path: Path) -> Credentials | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict):
        return None
    token = oauth.get("accessToken")
    if not token:
        return None
    return Credentials(
        access_token=token,
        expires_at_ms=oauth.get("expiresAt"),
        subscription_type=oauth.get("subscriptionType"),
        rate_limit_tier=oauth.get("rateLimitTier"),
        source_path=path,
    )


def load_credentials(override: str | None = None) -> Credentials | None:
    """Return the first valid credentials found across the search paths, or None.
    Never raises."""
    for path in credentials_search_paths(override):
        creds = _try_load(path)
        if creds is not None:
            return creds
    return None
