"""DataService — merges local session data and (later) live limits into AppState.

Local reads are cheap and run on a QTimer on the main thread. The usage-API poll
is expensive and rate-limited, so it runs on a worker thread and is **disabled by
default** until the Phase 4 consent-gated probe (set ``api_enabled=True`` to turn
it on). The UI connects to ``stateChanged`` and re-renders.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from . import credentials, session_reader, usage_api
from .session_reader import SessionStats
from .usage_api import UsageLimits, Window


@dataclass
class AppState:
    session: SessionStats | None = None
    limits: UsageLimits | None = None
    limits_fetched_at: float | None = None   # monotonic-ish wall time of last good fetch
    limits_status: str = "loading"             # mirrors usage_api status; "loading" before 1st fetch
    subscription: str | None = None
    token_present: bool = False
    token_expired: bool = False
    credentials_via_omp: bool = False           # token came from OMP fallback, not Claude Code
    refreshing: bool = False                    # a manual API refresh is in flight

    @property
    def limits_age_seconds(self) -> float | None:
        if self.limits_fetched_at is None:
            return None
        return max(0.0, time.time() - self.limits_fetched_at)


class _UsageWorker(QRunnable):
    """Runs one fetch_usage() off the main thread; delivers via callback signal."""

    class _Signals(QObject):
        done = Signal(object)

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token
        self.signals = self._Signals()

    def run(self) -> None:  # noqa: D401 - Qt entry point
        result = usage_api.fetch_usage(self._token)
        self.signals.done.emit(result)


class DataService(QObject):
    stateChanged = Signal(object)  # emits AppState
    sessionReset = Signal()        # the 5-hour session window rolled over (usage reset)

    # A user-initiated refresh may hit the API this often at most. The endpoint
    # 429s hard, so we keep a floor well under the periodic interval but high
    # enough that mashing the button can't get the user rate-limited.
    MANUAL_MIN_SECONDS = 20.0

    # A session reset is a utilization drop of at least this many points (fraction).
    # Within a window usage only climbs, so any real decrease means a new window.
    RESET_UTIL_DROP = 0.10

    def __init__(self, config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._state = AppState()
        self._pool = QThreadPool.globalInstance()
        self._last_api_attempt = 0.0  # wall time of the last API poll (any outcome)
        # For detecting a session-window rollover between successful fetches.
        self._last_session_reset: int | None = None
        self._last_session_util = 0.0
        # Live-limits API enabled: response shape captured + parser tightened
        # (docs/samples/oauth-usage.sample.json). Polls at >= MIN_POLL_SECONDS.
        self.api_enabled = True

        self._local_timer = QTimer(self)
        self._local_timer.timeout.connect(self._poll_local)
        self._api_timer = QTimer(self)
        self._api_timer.timeout.connect(self._poll_api)

    @property
    def state(self) -> AppState:
        return self._state

    def start(self) -> None:
        self._poll_local()
        self._local_timer.start(int(self._config.local_poll_seconds * 1000))
        if self.api_enabled:
            interval = max(usage_api.MIN_POLL_SECONDS, self._config.api_poll_seconds)
            self._poll_api()
            self._api_timer.start(int(interval * 1000))
        self.stateChanged.emit(self._state)

    def stop(self) -> None:
        self._local_timer.stop()
        self._api_timer.stop()

    # -- local ---------------------------------------------------------------
    def _poll_local(self) -> None:
        try:
            stats = session_reader.read_current_session(
                self._config.monitored_project_path
            )
        except Exception:
            stats = None
        self._state.session = stats
        self.stateChanged.emit(self._state)

    # -- api -----------------------------------------------------------------
    def _poll_api(self) -> None:
        self._last_api_attempt = time.time()
        creds = credentials.load_credentials(
            self._config.credentials_path,
            priority=getattr(self._config, "credential_priority", "claude_code"),
        )
        self._state.token_present = creds is not None
        self._state.credentials_via_omp = bool(creds is not None and creds.is_omp)
        if creds is None:
            self._state.limits_status = "no_token"
            self._state.refreshing = False
            self.stateChanged.emit(self._state)
            return
        self._state.subscription = creds.subscription_type
        self._state.token_expired = creds.is_expired
        if creds.is_expired:
            self._state.limits_status = "unauthorized"
            self._state.refreshing = False
            self.stateChanged.emit(self._state)
            return
        worker = _UsageWorker(creds.access_token)
        worker.signals.done.connect(self._on_api_result)
        self._pool.start(worker)

    def _on_api_result(self, limits: UsageLimits) -> None:
        self._state.limits_status = limits.status
        self._state.refreshing = False
        if limits.ok:
            self._state.limits = limits
            self._state.limits_fetched_at = time.time()
            self._detect_session_reset(limits.session)
        # on failure we keep the last good limits but update status (stale badge)
        self.stateChanged.emit(self._state)

    def _detect_session_reset(self, session: Window) -> None:
        """Fire ``sessionReset`` when the 5-hour window rolls over.

        Two independent signals, either of which means a new window began:
          1. ``resets_at`` jumps forward to a later time; and
          2. utilization drops materially — within a window usage only climbs, so a
             real decrease is a reset. This catches the common case where the reset
             lands the session idle and ``resets_at`` comes back null/stale, so
             signal 1 alone would miss it (the bug: no chime at the 0% reset).

        We only chime if the window that just ended had actually accrued usage."""
        new_reset = session.resets_at_epoch
        new_util = session.utilization
        prev_reset = self._last_session_reset
        prev_util = self._last_session_util

        rolled_over = False
        if new_reset is not None and prev_reset is not None and new_reset > prev_reset + 60:
            rolled_over = True
        if new_util is not None and prev_util - new_util >= self.RESET_UTIL_DROP:
            rolled_over = True

        if rolled_over and prev_util > 0.0:
            self.sessionReset.emit()

        if new_reset is not None:
            self._last_session_reset = new_reset
        if new_util is not None:
            self._last_session_util = new_util

    # -- manual refresh ------------------------------------------------------
    def refresh_now(self, force: bool = False) -> str:
        """User-initiated refresh. Always refreshes the cheap local data now; also
        hits the rate-limited usage API unless we polled it very recently. ``force``
        skips that throttle — used for credential re-validation after a fresh login,
        where an immediate API hit is exactly what the user is asking for. Returns a
        short human-readable note describing what happened (for a transient status)."""
        self._poll_local()
        if not self.api_enabled:
            return "refreshed"
        since = time.time() - self._last_api_attempt
        if not force and since < self.MANUAL_MIN_SECONDS:
            wait = int(self.MANUAL_MIN_SECONDS - since) + 1
            return f"just updated — retry in {wait}s"
        self._state.refreshing = True
        self.stateChanged.emit(self._state)
        self._poll_api()
        # Re-space the periodic timer so an automatic poll doesn't fire right behind
        # this manual one and risk a 429.
        if self._api_timer.isActive():
            interval = max(usage_api.MIN_POLL_SECONDS, self._config.api_poll_seconds)
            self._api_timer.start(int(interval * 1000))
        return "refreshing…"
