"""Entry point: python -m ccmonitor

Wires config -> DataService -> OverlayWindow, adds a system-tray icon (the always-
available way to show/hide/quit the overlay), and runs the Qt loop.

Single instance: the first copy listens on a per-user local socket. A later launch
connects, asks it to come forward fully expanded, and exits instead of opening a
second overlay.
"""

from __future__ import annotations

import getpass
import sys

from PySide6.QtCore import QByteArray
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from PySide6.QtGui import QAction

from .config import Config
from .data.service import DataService
from .ui.appicon import app_qicon
from .ui.overlay import OverlayWindow


def _build_tray(app: QApplication, window: OverlayWindow) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(app_qicon(), app)
    tray.setToolTip("CCUsageMonitor — Claude usage overlay")

    menu = QMenu()
    act_show = QAction("Show overlay", menu)
    act_show.triggered.connect(window.show_and_raise)
    menu.addAction(act_show)

    act_refresh = QAction("Refresh now", menu)
    act_refresh.triggered.connect(lambda: (window.show_and_raise(), window.refresh_now()))
    menu.addAction(act_refresh)

    act_settings = QAction("Settings…", menu)
    act_settings.triggered.connect(window.open_settings_dialog)
    menu.addAction(act_settings)

    act_creds = QAction("Fix credentials…", menu)
    act_creds.triggered.connect(window.open_credentials_dialog)
    menu.addAction(act_creds)

    menu.addMenu(window.build_powershell_menu(menu))

    act_test = QAction("Test alarm sound", menu)
    act_test.triggered.connect(window.test_alarm)
    menu.addAction(act_test)

    act_reset = QAction("Reset position", menu)
    act_reset.triggered.connect(lambda: (window.show_and_raise(), window.reset_position()))
    menu.addAction(act_reset)

    menu.addSeparator()
    act_quit = QAction("Quit", menu)

    def _quit() -> None:
        window.prepare_quit()
        app.quit()

    act_quit.triggered.connect(_quit)
    menu.addAction(act_quit)
    tray.setContextMenu(menu)

    # Left-click / double-click the tray icon toggles the overlay's visibility.
    def _activated(reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if window.isVisible():
                window.hide()
            else:
                window.show_and_raise()

    tray.activated.connect(_activated)

    # When the overlay asks to tuck away (✕, OS minimize), hide it and — the first
    # time only — tell the user where it went.
    shown_hint = {"done": False}

    def _hide_to_tray() -> None:
        window.hide()
        if not shown_hint["done"] and tray.supportsMessages():
            tray.showMessage(
                "CCUsageMonitor",
                "Still running here. Click this tray icon to bring the overlay back.",
                app_qicon(),
                4000,
            )
            shown_hint["done"] = True

    window.requestHideToTray.connect(_hide_to_tray)

    # Surface app notifications (e.g. session-limit reset) as tray balloons.
    def _notify(title: str, message: str) -> None:
        if tray.supportsMessages():
            tray.showMessage(title, message, app_qicon(), 6000)

    window.requestNotify.connect(_notify)
    return tray


def _instance_key() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return f"CCUsageMonitor-{user}"


_ACTIVATE = b"activate\n"


def _signal_running_instance(key: str) -> bool:
    """True if another copy is already running (it has been asked to show itself)."""
    sock = QLocalSocket()
    sock.connectToServer(key)
    if not sock.waitForConnected(500):
        return False
    if sys.platform == "win32":
        # We were just launched by the user, so we hold foreground rights; pass them
        # on so the running copy may actually take focus instead of only flashing.
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    sock.write(QByteArray(_ACTIVATE))
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def _listen_for_launches(app: QApplication, key: str, on_activate) -> QLocalServer | None:
    server = QLocalServer(app)
    # Only this user may connect; a crashed run can leave a stale pipe name behind.
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(key):
        QLocalServer.removeServer(key)
        if not server.listen(key):
            return None

    def _on_connection() -> None:
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: _on_ready(c))
            conn.disconnected.connect(conn.deleteLater)
            if conn.bytesAvailable():  # already arrived before readyRead was hooked up
                _on_ready(conn)

    def _on_ready(conn: QLocalSocket) -> None:
        if bytes(conn.readAll().data()).startswith(_ACTIVATE.strip()):
            on_activate()

    server.newConnection.connect(_on_connection)
    return server


def main() -> int:
    app = QApplication(sys.argv)

    key = _instance_key()
    if _signal_running_instance(key):
        return 0

    config = Config.load()
    service = DataService(config)
    window = OverlayWindow(config, service)
    server = _listen_for_launches(app, key, window.show_full)  # noqa: F841 - kept alive

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        # Tray owns the lifecycle: hiding/closing the window must not quit the app.
        app.setQuitOnLastWindowClosed(False)
        window.allow_tray_hide = True
        window.setWindowIcon(app_qicon())
        tray = _build_tray(app, window)
        tray.show()
    else:
        # No tray on this system: fall back to close-to-quit so nothing gets stuck.
        app.setQuitOnLastWindowClosed(True)

    window.show()
    service.start()

    rc = app.exec()
    if tray is not None:
        tray.hide()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
