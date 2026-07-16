"""Live usage limits via the undocumented ``/api/oauth/usage`` endpoint.

IMPORTANT: this endpoint rate-limits aggressively and *requires* a valid
``User-Agent: claude-code/<version>`` header (see docs/04-data-sources.md). It is
NOT polled automatically until its real response shape has been captured under
explicit user consent (development plan Phase 4, Step 1). Until then the app runs
entirely on local session data.

``fetch_usage`` is written defensively against the *expected* shape and returns a
normalized ``UsageLimits``. Once ``docs/samples/oauth-usage.sample.json`` exists,
tighten ``_parse`` to the real field names.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from .. import CLAUDE_CODE_UA_VERSION

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
# Never poll faster than this; the endpoint 429s hard below ~180s.
MIN_POLL_SECONDS = 180.0


@dataclass
class Window:
    """One rate-limit window (e.g. the 5-hour or the 7-day)."""
    utilization: float | None = None   # fraction 0..1 of the limit used
    resets_at_epoch: int | None = None  # unix seconds when the window resets


@dataclass
class UsageLimits:
    session: Window          # 5-hour window
    weekly: Window           # 7-day window
    ok: bool                 # True if the fetch succeeded
    status: str = "ok"       # "ok" | "rate_limited" | "unauthorized" | "error" | "offline"
    detail: str = ""


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": f"claude-code/{CLAUDE_CODE_UA_VERSION}",
        "Accept": "application/json",
    }


def _pct_to_fraction(v) -> float | None:
    """The API reports utilization as a percent (0..100); we want a 0..1 fraction."""
    try:
        if v is None:
            return None
        return max(0.0, min(1.0, float(v) / 100.0))
    except (TypeError, ValueError):
        return None


def _iso_to_epoch(v) -> int | None:
    """Parse an ISO-8601 `resets_at` string into unix seconds."""
    if not v or not isinstance(v, str):
        return None
    try:
        return int(datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _window(block: dict | None) -> Window:
    if not isinstance(block, dict):
        return Window()
    return Window(
        utilization=_pct_to_fraction(block.get("utilization")),
        resets_at_epoch=_iso_to_epoch(block.get("resets_at")),
    )


def _parse(payload: dict) -> UsageLimits:
    """Normalize the real `/api/oauth/usage` shape into UsageLimits.

    Primary source: the `five_hour` / `seven_day` blocks (utilization is a percent,
    resets_at is ISO-8601). Falls back to the `limits[]` array (kind == "session" /
    "weekly_all") if a block is missing.
    """
    session = _window(payload.get("five_hour"))
    weekly = _window(payload.get("seven_day"))

    # Fallback via the limits[] array if the primary blocks were absent/empty.
    if session.utilization is None or weekly.utilization is None:
        for item in payload.get("limits", []) or []:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            w = Window(
                utilization=_pct_to_fraction(item.get("percent")),
                resets_at_epoch=_iso_to_epoch(item.get("resets_at")),
            )
            if kind == "session" and session.utilization is None:
                session = w
            elif kind == "weekly_all" and weekly.utilization is None:
                weekly = w

    return UsageLimits(session=session, weekly=weekly, ok=True, status="ok")


def fetch_usage(token: str, timeout: float = 10.0) -> UsageLimits:
    """Single GET to the usage endpoint. Maps failures to a status; never raises."""
    empty = UsageLimits(session=Window(), weekly=Window(), ok=False)
    req = urllib.request.Request(USAGE_URL, headers=_headers(token), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            empty.status, empty.detail = "rate_limited", "429 from usage endpoint"
        elif e.code in (401, 403):
            empty.status, empty.detail = "unauthorized", f"{e.code}; re-auth in Claude Code"
        else:
            empty.status, empty.detail = "error", f"HTTP {e.code}"
        return empty
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        empty.status, empty.detail = "offline", str(e)
        return empty
    except json.JSONDecodeError as e:
        empty.status, empty.detail = "error", f"bad JSON: {e}"
        return empty

    return _parse(payload if isinstance(payload, dict) else {})
