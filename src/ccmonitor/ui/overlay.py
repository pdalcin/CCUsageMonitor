"""OverlayWindow — the frameless, always-on-top, draggable card.

Renders an ``AppState``: two ring gauges (5-hour session limit, 7-day weekly
limit) plus text readouts for live tokens, estimated cost, current model, and
session time. Draggable anywhere across monitors; position persists; collapses to
a compact pill.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPainterPath
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
    h, rem = divmod(int(remaining), 3600)
    m = rem // 60
    return f"resets in {h}h {m}m" if h else f"resets in {m}m"


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

        self._build_full()
        self._build_pill()
        self._apply_collapsed(config.collapsed)
        self._restore_position()

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
        collapse_btn = QPushButton("—")
        collapse_btn.setFixedSize(18, 18)
        collapse_btn.clicked.connect(lambda: self._apply_collapsed(True))
        collapse_btn.setStyleSheet(self._btn_css())
        title_row.addWidget(collapse_btn)
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
        rings.addWidget(self.ring_session)
        rings.addWidget(self.ring_week)
        root.addLayout(rings)

        self.reset_label = QLabel("")
        rf = QFont(theme.FONT_FAMILY)
        rf.setPixelSize(15)
        self.reset_label.setFont(rf)
        self.reset_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reset_label.setStyleSheet(f"color: {theme.TEXT_DIM.name()};")
        root.addWidget(self.reset_label)

        # readouts grid
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        self.ro_tokens = _Readout("tokens")
        self.ro_cost = _Readout("est. cost")
        self.ro_model = _Readout("model")
        self.ro_time = _Readout("session")
        grid.addWidget(self.ro_tokens, 0, 0)
        grid.addWidget(self.ro_cost, 0, 1)
        grid.addWidget(self.ro_model, 1, 0)
        grid.addWidget(self.ro_time, 1, 1)
        root.addLayout(grid)

        self.status_label = QLabel("")
        sf = QFont(theme.FONT_FAMILY)
        sf.setPixelSize(9)
        self.status_label.setFont(sf)
        self.status_label.setStyleSheet(f"color: {theme.STALE.name()};")
        root.addWidget(self.status_label)

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

    def _apply_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.full.setVisible(not collapsed)
        self.pill.setVisible(collapsed)
        self._fit_to(self.pill if collapsed else self.full)
        self._config.collapsed = collapsed
        self._config.save()

    def _fit_to(self, widget: QWidget) -> None:
        """Size the window to exactly wrap the visible child, and the child to fill
        it — so the inner layout never gets squeezed or leaves dead space."""
        widget.adjustSize()
        widget.move(0, 0)
        self.setFixedSize(widget.size())

    # -- state rendering ----------------------------------------------------
    def update_state(self, state) -> None:
        s = state.session
        if s:
            self.ro_tokens.set(fmt_tokens(s.total_tokens))
            self.ro_cost.set(fmt_cost(s.estimated_cost, s.cost_is_complete))
            self.ro_model.set(short_model(s.primary_model))
            self.ro_time.set(fmt_duration(s.session_duration_seconds))
        else:
            for ro in (self.ro_tokens, self.ro_cost, self.ro_model, self.ro_time):
                ro.set("—")

        limits = state.limits
        if limits and limits.session.utilization is not None:
            self.ring_session.set_value(limits.session.utilization)
            self.pill_ring.set_value(limits.session.utilization)
            self.pill_label.setText(f"{int(round(limits.session.utilization * 100))}%")
            self.reset_label.setText(fmt_reset(limits.session.resets_at_epoch))
        else:
            self.ring_session.set_value(None, center_text="—")
            self.pill_ring.set_value(None, center_text="")
            self.pill_label.setText("—")
        if limits and limits.weekly.utilization is not None:
            self.ring_week.set_value(limits.weekly.utilization)
        else:
            self.ring_week.set_value(None, center_text="—")

        self.status_label.setText(self._effective_status(state))

        # The pill's width depends on the % label ("9%" vs "100%"); re-fit so the
        # window keeps wrapping it exactly instead of clipping or leaving a gap.
        if self._collapsed:
            self._fit_to(self.pill)

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
        radius = theme.CARD_RADIUS if not self._collapsed else theme.PILL_HEIGHT / 2
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
        self._apply_collapsed(not self._collapsed)

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
        act_collapse = QAction("Expand" if self._collapsed else "Collapse", self)
        act_collapse.triggered.connect(lambda: self._apply_collapsed(not self._collapsed))
        menu.addAction(act_collapse)
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
        """Compact a folder path for a menu label: '…\\parent\\leaf'."""
        parts = path.replace("/", "\\").rstrip("\\").split("\\")
        if len(parts) <= 2:
            return path
        return "…\\" + "\\".join(parts[-2:])

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
