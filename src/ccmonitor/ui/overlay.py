"""OverlayWindow — the frameless, always-on-top, draggable card.

Renders an ``AppState``: two ring gauges (5-hour session limit, 7-day weekly
limit) with both reset countdowns, plus text readouts for live tokens, estimated
cost, current model, reasoning effort, and session time. Draggable anywhere across
monitors; position persists.

Three view modes (``Config.view_mode``): ``compact`` (a small pill), ``expanded``
(the card) and ``full`` (the card plus a panel listing every Claude Code session
running on this machine).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..data.session_reader import default_effort
from . import theme
from .gauges import RingGauge


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def fmt_cost(v: float, complete: bool) -> str:
    s = f"${v:,.2f}"
    return s if complete else s + "?"


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def short_model(model: str | None) -> str:
    if not model:
        return "—"
    m = model.replace("claude-", "")
    return m


def fmt_reset(epoch: int | None) -> str:
    if not epoch:
        return ""
    import time
    remaining = epoch - time.time()
    if remaining <= 0:
        return "resets soon"
    d, rem = divmod(int(remaining), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"resets in {d}d {h}h"
    return f"resets in {h}h {m}m" if h else f"resets in {m}m"


def short_path(path: str) -> str:
    """Compact a folder path for a label: '…\\parent\\leaf'."""
    parts = path.replace("/", "\\").rstrip("\\").split("\\")
    if len(parts) <= 2:
        return path
    return "…\\" + "\\".join(parts[-2:])


VIEW_MODES = ("compact", "expanded", "full")


class _Readout(QWidget):
    """A small stacked label: big value on top, dim caption under."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.value = QLabel("—")
        vf = QFont(theme.FONT_FAMILY)
        vf.setPixelSize(15)
        vf.setBold(True)
        self.value.setFont(vf)
        self.value.setStyleSheet(f"color: {theme.TEXT.name()};")
        self.caption = QLabel(caption)
        cf = QFont(theme.FONT_FAMILY)
        cf.setPixelSize(10)
        self.caption.setFont(cf)
        self.caption.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        lay.addWidget(self.value)
        lay.addWidget(self.caption)

    def set(self, value: str) -> None:
        self.value.setText(value)


class _SessionRow(QWidget):
    """One running Claude Code session in the full view's sessions panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(1)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.name = QLabel("")
        nf = QFont(theme.FONT_FAMILY)
        nf.setPixelSize(12)
        nf.setBold(True)
        self.name.setFont(nf)
        top.addWidget(self.name, 1)
        self.status = QLabel("")
        sf = QFont(theme.FONT_FAMILY)
        sf.setPixelSize(10)
        self.status.setFont(sf)
        top.addWidget(self.status)
        lay.addLayout(top)

        small = QFont(theme.FONT_FAMILY)
        small.setPixelSize(10)
        self.path = QLabel("")
        self.path.setFont(small)
        self.path.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        lay.addWidget(self.path)
        self.detail = QLabel("")
        self.detail.setFont(small)
        self.detail.setStyleSheet(f"color: {theme.TEXT.name()};")
        lay.addWidget(self.detail)

    def set(self, live, is_current: bool) -> None:
        marker = "▸ " if is_current else ""
        color = theme.ACCENT if is_current else theme.TEXT
        self.name.setText(marker + live.name)
        self.name.setStyleSheet(f"color: {color.name()};")
        dot = theme.GAUGE_OK if live.status == "busy" else theme.TEXT_DIM
        self.status.setText(f"● {live.status}")
        self.status.setStyleSheet(f"color: {dot.name()};")
        self.path.setText(short_path(live.cwd))
        self.setToolTip(f"{live.cwd}\nsession {live.session_id}\npid {live.pid}")
        st = live.stats
        parts = [short_model(live.model), live.effort or "—"]
        if st is not None:
            parts += [
                fmt_tokens(st.total_tokens),
                fmt_cost(st.estimated_cost, st.cost_is_complete),
                fmt_duration(st.session_duration_seconds),
            ]
        self.detail.setText("  ·  ".join(parts))


class OverlayWindow(QWidget):
    # Emitted when the user asks to tuck the overlay away (✕ button, OS minimize).
    # The app (which owns the tray icon) decides how to surface it again.
    requestHideToTray = Signal()
    # Emitted to surface a desktop notification (title, message) via the tray.
    requestNotify = Signal(str, str)

    def __init__(self, config, service) -> None:
        super().__init__()
        self._config = config
        self._service = service
        self._drag_offset: QPoint | None = None
        # Set True by the app once a system-tray icon exists; enables hide-to-tray
        # (otherwise ✕/close quits, so the window can never become unreachable).
        self.allow_tray_hide = False
        self._quitting = False
        # A short-lived status message (e.g. "refreshing…") that overrides the
        # normal freshness line for a few seconds after a manual refresh.
        self._transient_msg: str | None = None
        self._transient_until = 0.0
        # Auto-show the credentials helper only once per problem (re-arm on OK).
        self._creds_prompted = False
        self._creds_dialog = None
        # Warn once if we ended up authenticating through the OMP fallback.
        self._omp_warned = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(config.opacity)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        self._mode = config.view_mode if config.view_mode in VIEW_MODES else "expanded"
        self._build_full()
        self._build_pill()
        self.set_view_mode(self._mode)
        self._restore_position()
        self._keep_on_screen()

        service.stateChanged.connect(self.update_state)
        service.sessionReset.connect(self._on_session_reset)

    # -- layout -------------------------------------------------------------
    def _build_full(self) -> None:
        self.full = QWidget(self)
        root = QVBoxLayout(self.full)
        root.setContentsMargins(
            theme.CARD_PADDING, theme.CARD_PADDING, theme.CARD_PADDING, theme.CARD_PADDING
        )
        root.setSpacing(8)

        # title row
        title_row = QHBoxLayout()
        title = QLabel("Claude Usage")
        tf = QFont(theme.FONT_FAMILY)
        tf.setPixelSize(12)
        tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        title_row.addWidget(title)
        title_row.addStretch(1)
        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedSize(18, 18)
        refresh_btn.setToolTip("Refresh now")
        refresh_btn.clicked.connect(self.refresh_now)
        refresh_btn.setStyleSheet(self._btn_css())
        title_row.addWidget(refresh_btn)
        compact_btn = QPushButton("—")
        compact_btn.setFixedSize(18, 18)
        compact_btn.setToolTip("Compact")
        compact_btn.clicked.connect(lambda: self.set_view_mode("compact"))
        compact_btn.setStyleSheet(self._btn_css())
        title_row.addWidget(compact_btn)
        self.full_btn = QPushButton("⤢")
        self.full_btn.setFixedSize(18, 18)
        self.full_btn.clicked.connect(
            lambda: self.set_view_mode("expanded" if self._mode == "full" else "full")
        )
        self.full_btn.setStyleSheet(self._btn_css())
        title_row.addWidget(self.full_btn)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(18, 18)
        close_btn.setToolTip("Hide to tray")
        close_btn.clicked.connect(self._on_close_clicked)
        close_btn.setStyleSheet(self._btn_css())
        title_row.addWidget(close_btn)
        root.addLayout(title_row)

        # two rings
        rings = QHBoxLayout()
        rings.setSpacing(10)
        self.ring_session = RingGauge(label="session · 5h", diameter=88)
        self.ring_week = RingGauge(label="week · 7d", diameter=88)
        rings.addStretch(1)
        rings.addWidget(self.ring_session)
        rings.addWidget(self.ring_week)
        rings.addStretch(1)
        root.addLayout(rings)

        self.reset_label = QLabel("")
        rf = QFont(theme.FONT_FAMILY)
        rf.setPixelSize(15)
        self.reset_label.setFont(rf)
        self.reset_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reset_label.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        root.addWidget(self.reset_label)
        self.week_reset_label = QLabel("")
        self.week_reset_label.setFont(rf)
        self.week_reset_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.week_reset_label.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        root.addWidget(self.week_reset_label)

        # readouts grid
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        self.ro_tokens = _Readout("tokens")
        self.ro_cost = _Readout("est. cost")
        self.ro_model = _Readout("model")
        self.ro_effort = _Readout("effort")
        self.ro_time = _Readout("session")
        grid.addWidget(self.ro_tokens, 0, 0)
        grid.addWidget(self.ro_cost, 0, 1)
        grid.addWidget(self.ro_model, 1, 0)
        grid.addWidget(self.ro_effort, 1, 1)
        grid.addWidget(self.ro_time, 2, 0)
        root.addLayout(grid)

        self.status_label = QLabel("")
        sf = QFont(theme.FONT_FAMILY)
        sf.setPixelSize(9)
        self.status_label.setFont(sf)
        self.status_label.setStyleSheet(f"color: {theme.STALE.name()};")
        root.addWidget(self.status_label)

        # Full view only: every Claude Code session running on this machine.
        self.sessions_panel = QWidget(self.full)
        sp = QVBoxLayout(self.sessions_panel)
        sp.setContentsMargins(0, 4, 0, 0)
        sp.setSpacing(0)
        rule = QWidget(self.sessions_panel)
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {theme.CARD_BORDER.name(QColor.NameFormat.HexArgb)};")
        sp.addWidget(rule)
        self.sessions_title = QLabel("")
        stf = QFont(theme.FONT_FAMILY)
        stf.setPixelSize(12)
        stf.setBold(True)
        self.sessions_title.setFont(stf)
        self.sessions_title.setStyleSheet(f"color: {theme.TEXT_DIM.name()}; padding-top: 6px;")
        sp.addWidget(self.sessions_title)
        self._session_rows: list[_SessionRow] = []
        self._sessions_layout = QVBoxLayout()
        self._sessions_layout.setSpacing(0)
        sp.addLayout(self._sessions_layout)
        self.sessions_more = QLabel("")
        mf = QFont(theme.FONT_FAMILY)
        mf.setPixelSize(10)
        self.sessions_more.setFont(mf)
        self.sessions_more.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        sp.addWidget(self.sessions_more)
        root.addWidget(self.sessions_panel)

        self.full.setFixedWidth(theme.CARD_WIDTH)
        self.full.adjustSize()

    def _build_pill(self) -> None:
        self.pill = QWidget(self)
        lay = QHBoxLayout(self.pill)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)
        self.pill_ring = RingGauge(diameter=30, thickness=5)
        lay.addWidget(self.pill_ring)
        self.pill_label = QLabel("—")
        pf = QFont(theme.FONT_FAMILY)
        pf.setPixelSize(12)
        pf.setBold(True)
        self.pill_label.setFont(pf)
        self.pill_label.setStyleSheet(f"color: {theme.TEXT.name()};")
        lay.addWidget(self.pill_label)
        self.pill.adjustSize()

    def _btn_css(self) -> str:
        return (
            f"QPushButton {{ color: {theme.TEXT_DIM.name()}; border: none;"
            f" background: transparent; font-size: 11px; }}"
            f"QPushButton:hover {{ color: {theme.TEXT.name()}; }}"
        )

    def set_view_mode(self, mode: str) -> None:
        """Switch between compact (pill), expanded (card) and full (card + all
        running sessions). Persisted so the overlay reopens the way it was left."""
        if mode not in VIEW_MODES:
            return
        self._mode = mode
        compact = mode == "compact"
        full = mode == "full"
        self.full.setVisible(not compact)
        self.pill.setVisible(compact)
        self.sessions_panel.setVisible(full)
        self.full.setFixedWidth(theme.CARD_WIDTH_FULL if full else theme.CARD_WIDTH)
        self.full_btn.setText("⤡" if full else "⤢")
        self.full_btn.setToolTip("Expand (hide sessions)" if full else "Full expand (all sessions)")
        # Only pay for enumerating sessions while they're on screen.
        self._service.set_track_live_sessions(full)
        if full:
            self._render_sessions(self._service.state)
        self._fit_to(self.pill if compact else self.full)
        self._keep_on_screen()
        if self._config.view_mode != mode:
            self._config.view_mode = mode
            self._config.save()
        self.update()

    def show_full(self) -> None:
        """Bring the overlay up fully expanded (used when a second launch is made)."""
        self.show_and_raise()
        self.set_view_mode("full")

    def _fit_to(self, widget: QWidget) -> None:
        """Size the window to exactly wrap the visible child, and the child to fill
        it — so the inner layout never gets squeezed or leaves dead space."""
        widget.adjustSize()
        widget.move(0, 0)
        self.setFixedSize(widget.size())

    def _keep_on_screen(self) -> None:
        """When a bigger view would hang off the bottom/right of its screen, nudge the
        window back inside (without saving — the user's chosen spot stays put)."""
        screen = QApplication.screenAt(self.frameGeometry().topLeft())
        if screen is None:
            return
        g = screen.availableGeometry()
        x = max(min(self.x(), g.right() - self.width()), g.left())
        y = max(min(self.y(), g.bottom() - self.height()), g.top())
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    # -- state rendering ----------------------------------------------------
    def update_state(self, state) -> None:
        s = state.session
        if s:
            self.ro_tokens.set(fmt_tokens(s.total_tokens))
            self.ro_cost.set(fmt_cost(s.estimated_cost, s.cost_is_complete))
            self.ro_model.set(short_model(s.primary_model))
            self.ro_effort.set(s.effort or default_effort(s.primary_model) or "—")
            self.ro_time.set(fmt_duration(s.session_duration_seconds))
        else:
            for ro in (self.ro_tokens, self.ro_cost, self.ro_model, self.ro_effort, self.ro_time):
                ro.set("—")

        limits = state.limits
        if limits and limits.session.utilization is not None:
            self.ring_session.set_value(limits.session.utilization)
            self.pill_ring.set_value(limits.session.utilization)
            self.pill_label.setText(f"{int(round(limits.session.utilization * 100))}%")
            reset = fmt_reset(limits.session.resets_at_epoch)
            self.reset_label.setText(f"5h {reset}" if reset else "")
        else:
            self.ring_session.set_value(None, center_text="—")
            self.pill_ring.set_value(None, center_text="")
            self.pill_label.setText("—")
        if limits and limits.weekly.utilization is not None:
            self.ring_week.set_value(limits.weekly.utilization)
            reset = fmt_reset(limits.weekly.resets_at_epoch)
            self.week_reset_label.setText(f"week {reset}" if reset else "")
        else:
            self.ring_week.set_value(None, center_text="—")

        self.status_label.setText(self._effective_status(state))

        # The pill's width depends on the % label ("9%" vs "100%"); re-fit so the
        # window keeps wrapping it exactly instead of clipping or leaving a gap.
        if self._mode == "compact":
            self._fit_to(self.pill)
        elif self._mode == "full":
            self._render_sessions(state)

        # First time we notice missing/expired credentials, offer the helper.
        if state.limits_status in ("no_token", "unauthorized"):
            if not self._creds_prompted:
                self._creds_prompted = True
                QTimer.singleShot(0, self.open_credentials_dialog)
        elif state.limits_status == "ok":
            self._creds_prompted = False  # re-arm for a future expiry
            # If the working token came from the OMP fallback, warn once.
            if getattr(state, "credentials_via_omp", False) and not self._omp_warned:
                self._omp_warned = True
                QTimer.singleShot(0, self._warn_omp)

    # Rows shown in the sessions panel before the rest fold into "+N more".
    MAX_SESSION_ROWS = 8

    def _render_sessions(self, state) -> None:
        sessions = list(getattr(state, "live_sessions", None) or [])
        n = len(sessions)
        self.sessions_title.setText(
            f"Claude Code sessions · {n} running" if n else "No Claude Code sessions running"
        )
        current_id = state.session.session_id if state.session else None
        shown = sessions[: self.MAX_SESSION_ROWS]
        while len(self._session_rows) < len(shown):
            row = _SessionRow(self.sessions_panel)
            self._sessions_layout.addWidget(row)
            self._session_rows.append(row)
        for i, row in enumerate(self._session_rows):
            if i < len(shown):
                row.set(shown[i], shown[i].session_id == current_id)
                row.show()
            else:
                row.hide()
        extra = n - len(shown)
        self.sessions_more.setText(f"+{extra} more" if extra > 0 else "")
        self.sessions_more.setVisible(extra > 0)
        old_height = self.height()
        self._fit_to(self.full)
        if self.height() != old_height:
            self._keep_on_screen()

    def _effective_status(self, state) -> str:
        import time
        if self._transient_msg and time.time() < self._transient_until:
            return self._transient_msg
        self._transient_msg = None
        return self._status_text(state)

    def _status_text(self, state) -> str:
        st = state.limits_status
        age = state.limits_age_seconds
        if getattr(state, "refreshing", False):
            return "limits: refreshing…"
        if st == "disabled":
            return "limits: local-only (API off)"
        if st == "loading" and age is None:
            return "limits: loading…"
        if st == "no_token":
            return "limits: sign in to Claude Code"
        if st == "unauthorized":
            return "limits: re-auth in Claude Code"
        if st == "rate_limited":
            return f"limits: rate-limited · {self._age(age)}"
        if st in ("offline", "error"):
            return f"limits: unavailable · {self._age(age)}"
        if age is not None:
            return f"limits: as of {self._age(age)}"
        return ""

    @staticmethod
    def _age(age: float | None) -> str:
        if age is None:
            return "never"
        if age < 90:
            return "just now"
        return f"{int(age // 60)}m ago"

    # -- window paint (rounded translucent card) ----------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = theme.PILL_HEIGHT / 2 if self._mode == "compact" else theme.CARD_RADIUS
        path.addRoundedRect(rect, radius, radius)
        p.fillPath(path, theme.CARD_BG)
        p.strokePath(path, QApplication.palette().window().color().lighter())
        p.setPen(theme.CARD_BORDER.name())
        p.drawPath(path)

    # -- drag to move (frameless) -------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self.set_view_mode("expanded" if self._mode == "compact" else "compact")

    # -- position persistence + multi-monitor clamp -------------------------
    def _restore_position(self) -> None:
        if self._config.pos_x is None or self._config.pos_y is None:
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.right() - self.width() - 24, screen.top() + 24)
            return
        self.move(self._clamp_to_screens(self._config.pos_x, self._config.pos_y))

    def _clamp_to_screens(self, x: int, y: int) -> QPoint:
        pt = QPoint(x, y)
        for screen in QApplication.screens():
            if screen.availableGeometry().contains(pt):
                return pt
        # off all screens (monitor unplugged) -> snap into primary
        g = QApplication.primaryScreen().availableGeometry()
        return QPoint(
            min(max(x, g.left()), g.right() - self.width()),
            min(max(y, g.top()), g.bottom() - self.height()),
        )

    def _save_position(self) -> None:
        self._config.pos_x = self.x()
        self._config.pos_y = self.y()
        self._config.save()

    # -- credentials helper -------------------------------------------------
    def open_credentials_dialog(self) -> None:
        """Show the 'find your Claude credentials' helper (once at a time)."""
        if self._creds_dialog is not None:
            self._creds_dialog.raise_()
            self._creds_dialog.activateWindow()
            return
        from .credentials_dialog import CredentialsDialog

        self.show_and_raise()
        dlg = CredentialsDialog(self._config, self._service, parent=self)
        self._creds_dialog = dlg
        try:
            dlg.exec()
        finally:
            self._creds_dialog = None

    def open_settings_dialog(self) -> None:
        """Show the Settings window (credentials + search priority)."""
        from .settings_dialog import SettingsDialog

        self.show_and_raise()
        dlg = SettingsDialog(self._config, self._service, parent=self)
        dlg.exec()

    def _warn_omp(self) -> None:
        """One-time heads-up that we're authenticating via OMP, not Claude Code."""
        from PySide6.QtWidgets import QMessageBox

        self.show_and_raise()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Signed in via OMP")
        box.setText("Using OMP (oh-my-pi) credentials as a fallback")
        box.setInformativeText(
            "No Claude Code login was found, so the overlay is using the Claude OAuth "
            "token stored by OMP (oh-my-pi).\n\n"
            "Your experience will be limited:\n"
            "•  The session tokens / cost / model / time panel stays empty — OMP does not "
            "write Claude Code's session logs.\n"
            "•  The usage limits are read using OMP's token and may not exactly match your "
            "Claude Code plan view.\n\n"
            "For the full experience, sign in with Claude Code (run  claude  in a terminal), "
            "then reopen the overlay."
        )
        fix = box.addButton("Fix credentials…", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is fix:
            self.open_credentials_dialog()

    # -- session reset notification -----------------------------------------
    def _on_session_reset(self) -> None:
        """The 5-hour session window rolled over: chime + flash + tray balloon."""
        if self._config.sound_on_reset:
            from .. import notify
            notify.play_reset_sound()
        self._flash_status("session limit reset ✦")
        self.requestNotify.emit(
            "Session limit reset",
            "Your 5-hour usage window just reset — you're back to a fresh limit.",
        )

    # -- manual refresh -----------------------------------------------------
    def refresh_now(self) -> None:
        """Re-check usage now (local always; API unless polled very recently)."""
        note = self._service.refresh_now()
        self._flash_status(note)

    def _flash_status(self, note: str) -> None:
        import time
        self._transient_msg = f"limits: {note}"
        self._transient_until = time.time() + 3.0
        self.status_label.setText(self._transient_msg)
        # Re-render once after it expires so the line reverts even with no new emit.
        QTimer.singleShot(3100, lambda: self.update_state(self._service.state))

    # -- show / hide / quit lifecycle (tray-aware) --------------------------
    def _on_close_clicked(self) -> None:
        if self.allow_tray_hide and not self._quitting:
            self.requestHideToTray.emit()
        else:
            self._quitting = True
            self.close()

    def show_and_raise(self) -> None:
        """Bring the overlay back into view, un-minimized and on a real screen."""
        self.ensure_on_screen()
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def reset_position(self) -> None:
        """Snap to the default top-right of the primary screen (recover a lost window)."""
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.right() - self.width() - 24, geo.top() + 24)
        self._save_position()

    def ensure_on_screen(self) -> None:
        """If the window's top-left isn't on any connected screen, snap it back."""
        pt = self.frameGeometry().topLeft()
        for screen in QApplication.screens():
            if screen.availableGeometry().contains(pt):
                return
        self.reset_position()

    def prepare_quit(self) -> None:
        self._quitting = True

    def closeEvent(self, event) -> None:
        # Never let a close leave the app running with no window AND no way back:
        # while a tray icon exists, closing hides to tray instead of quitting.
        if self.allow_tray_hide and not self._quitting:
            event.ignore()
            self.requestHideToTray.emit()
        else:
            event.accept()

    def changeEvent(self, event) -> None:
        # A Qt.Tool window has no taskbar button, so an OS minimize (e.g. Win+D,
        # showMinimized) would make it unrecoverable. Intercept and hide-to-tray.
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.allow_tray_hide
        ):
            QTimer.singleShot(0, self._recover_from_minimize)
        super().changeEvent(event)

    def _recover_from_minimize(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.hide()
        self.requestHideToTray.emit()

    # -- context menu -------------------------------------------------------
    def _show_menu(self, pos) -> None:
        menu = QMenu(self)
        act_refresh = QAction("Refresh now", self)
        act_refresh.triggered.connect(self.refresh_now)
        menu.addAction(act_refresh)
        menu.addSeparator()
        modes = QActionGroup(menu)
        for mode, label in (("compact", "Compact"), ("expanded", "Expand"), ("full", "Full expand")):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self._mode == mode)
            act.triggered.connect(lambda _=False, m=mode: self.set_view_mode(m))
            modes.addAction(act)
            menu.addAction(act)
        menu.addSeparator()
        act_reset = QAction("Reset position", self)
        act_reset.triggered.connect(self.reset_position)
        menu.addAction(act_reset)
        act_sound = QAction("Sound on reset", self)
        act_sound.setCheckable(True)
        act_sound.setChecked(self._config.sound_on_reset)
        act_sound.toggled.connect(self._set_sound_on_reset)
        menu.addAction(act_sound)
        act_test = QAction("Test alarm sound", self)
        act_test.triggered.connect(self.test_alarm)
        menu.addAction(act_test)
        act_settings = QAction("Settings…", self)
        act_settings.triggered.connect(self.open_settings_dialog)
        menu.addAction(act_settings)
        act_creds = QAction("Fix credentials…", self)
        act_creds.triggered.connect(self.open_credentials_dialog)
        menu.addAction(act_creds)
        menu.addMenu(self.build_powershell_menu(menu))
        act_hide = QAction("Hide to tray", self)
        act_hide.triggered.connect(self._on_close_clicked)
        menu.addAction(act_hide)
        menu.addSeparator()
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_quit)
        menu.exec(self.mapToGlobal(pos))

    # -- open-PowerShell submenu --------------------------------------------
    def build_powershell_menu(self, parent: QMenu) -> QMenu:
        """Second-level menu: open PowerShell in the app folder, in any of the
        recently-scanned Claude project folders, or (re)scan to populate them.

        Reused by both the overlay context menu and the tray menu. It repopulates
        itself on ``aboutToShow`` so a scan taken from either place is reflected
        immediately without rebuilding the whole menu."""
        sub = QMenu("Open PowerShell", parent)
        sub.aboutToShow.connect(lambda: self._populate_powershell_menu(sub))
        self._populate_powershell_menu(sub)
        return sub

    def _populate_powershell_menu(self, sub: QMenu) -> None:
        sub.clear()
        act_app = QAction("App Folder", sub)
        act_app.triggered.connect(lambda: self._open_powershell(None))
        sub.addAction(act_app)

        recents = list(self._config.recent_project_paths or [])
        if recents:
            sub.addSeparator()
            for path in recents[:5]:
                act = QAction(self._shorten_path(path), sub)
                act.setToolTip(path)
                act.triggered.connect(lambda _=False, p=path: self._open_powershell(p))
                sub.addAction(act)

        sub.addSeparator()
        act_scan = QAction("Scan for recent Claude projects", sub)
        act_scan.triggered.connect(self._scan_claude_projects)
        sub.addAction(act_scan)

    @staticmethod
    def _shorten_path(path: str) -> str:
        return short_path(path)

    def _open_powershell(self, folder) -> None:
        """Open a PowerShell window (PS7 if available) in *folder*, or the app
        folder when *folder* is None."""
        from .. import shell

        target = shell.app_folder() if folder is None else folder
        if shell.open_powershell(target):
            self._flash_status("opened PowerShell ▸")
        else:
            self._flash_status("no PowerShell found")

    def _scan_claude_projects(self) -> None:
        """Explicitly scan Claude Code's logs for recent CLAUDE.md project folders
        and cache them in the config so the menu stays filled across restarts."""
        from .. import shell

        found = shell.scan_claude_projects(limit=5)
        self._config.recent_project_paths = found
        self._config.save()
        n = len(found)
        self._flash_status(f"found {n} recent project{'s' if n != 1 else ''}")

    def _set_sound_on_reset(self, enabled: bool) -> None:
        self._config.sound_on_reset = enabled
        self._config.save()

    def test_alarm(self) -> None:
        """Play the reset chime on demand so the user can confirm it's audible.
        Plays regardless of the 'Sound on reset' toggle — it's an explicit test."""
        from .. import notify
        notify.play_reset_sound()
        self._flash_status("testing alarm sound ♪")

    def _quit(self) -> None:
        self._quitting = True
        QApplication.instance().quit()
