"""Read-only access to Claude Code's stored OAuth token.

We read ``~/.claude/.credentials.json`` to obtain the bearer token used for the
usage-API request (docs/04-data-sources.md). The token is never logged, copied,
or written back — this module only ever *reads*.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


@dataclass
class Credentials:
    access_token: str
    expires_at_ms: int | None
    subscription_type: str | None
    rate_limit_tier: str | None

    @property
    def is_expired(self) -> bool:
        if not self.expires_at_ms:
            return False
        return time.time() * 1000 >= self.expires_at_ms


def load_credentials() -> Credentials | None:
    """Return credentials, or None if unavailable/malformed. Never raises."""
    try:
        data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
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
    )
