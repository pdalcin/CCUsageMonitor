"""Help dialog shown when the Claude Code OAuth token can't be found (or expired).

We can't safely perform Claude's OAuth login ourselves — that flow belongs to
Claude Code, and duplicating it risks corrupting its credential store. Instead we
explain how to get logged in, show exactly where we looked, and let the user point
us straight at their ``.credentials.json`` if it lives somewhere unusual.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..data import credentials

CLAUDE_CODE_URL = "https://claude.com/claude-code"


class CredentialsDialog(QDialog):
    """Modal helper for resolving a missing/expired credential.

    ``on_resolved`` is called (no args) whenever the user takes an action that
    makes a valid token available, so the app can re-poll immediately.
    """

    def __init__(self, config, on_resolved, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._on_resolved = on_resolved
        self.setWindowTitle("Claude credentials")
        self.setModal(True)
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(10)

        self._headline = QLabel()
        hf = QFont()
        hf.setPointSize(11)
        hf.setBold(True)
        self._headline.setFont(hf)
        self._headline.setWordWrap(True)
        root.addWidget(self._headline)

        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setOpenExternalLinks(True)
        root.addWidget(self._body)

        self._paths = QLabel()
        self._paths.setWordWrap(True)
        self._paths.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        mf = QFont("Consolas")
        mf.setStyleHint(QFont.StyleHint.Monospace)
        mf.setPointSize(8)
        self._paths.setFont(mf)
        self._paths.setStyleSheet("color: palette(mid);")
        root.addWidget(self._paths)

        self._note = QLabel()
        self._note.setWordWrap(True)
        root.addWidget(self._note)

        # buttons
        btns = QHBoxLayout()
        btns.setSpacing(8)
        b_locate = QPushButton("Locate file…")
        b_locate.setToolTip("Point directly at your .credentials.json")
        b_locate.clicked.connect(self._locate)
        b_get = QPushButton("Get Claude Code")
        b_get.clicked.connect(lambda: QDesktopServices.openUrl(CLAUDE_CODE_URL))
        b_retry = QPushButton("Retry")
        b_retry.clicked.connect(self._retry)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.reject)
        btns.addWidget(b_locate)
        btns.addWidget(b_get)
        btns.addStretch(1)
        btns.addWidget(b_retry)
        btns.addWidget(b_close)
        root.addLayout(btns)

        self._refresh_view()

    # -- state-aware content ------------------------------------------------
    def _refresh_view(self, note: str = "") -> None:
        creds = credentials.load_credentials(self._config.credentials_path)
        if creds is not None and not creds.is_expired:
            plan = creds.subscription_type or "your Claude account"
            self._headline.setText("You're signed in ✓")
            self._body.setText(
                f"Found a valid Claude token for <b>{plan}</b> at:<br>"
                f"<code>{creds.source_path}</code><br><br>"
                "The overlay's limit gauges should be working. If they aren't, click "
                "<b>Retry</b> to re-check."
            )
        elif creds is not None and creds.is_expired:
            self._headline.setText("Your Claude session has expired")
            self._body.setText(
                "We found your credentials but the token has expired. Re-authenticate "
                "in Claude Code, then click <b>Retry</b>:<br><br>"
                "Open a terminal and run <code>claude</code> — if you're logged out it "
                "will prompt you to sign in again."
            )
        else:
            self._headline.setText("Couldn't find your Claude credentials")
            self._body.setText(
                "This overlay reads the OAuth token that <b>Claude Code</b> stores on "
                "your machine — it doesn't log in on its own. To fix this:<br>"
                "&nbsp;&nbsp;1. Install <a href='%s'>Claude Code</a> if you haven't.<br>"
                "&nbsp;&nbsp;2. Open a terminal, run <code>claude</code>, and sign in.<br>"
                "&nbsp;&nbsp;3. Click <b>Retry</b> below.<br><br>"
                "If your config lives somewhere non-standard (e.g. a custom "
                "<code>CLAUDE_CONFIG_DIR</code>), use <b>Locate file…</b> to point us "
                "straight at your <code>.credentials.json</code>." % CLAUDE_CODE_URL
            )

        searched = credentials.credentials_search_paths(self._config.credentials_path)
        self._paths.setText(
            "Looked in:\n" + "\n".join(f"  • {p}" for p in searched)
        )
        if note:
            self._note.setText(note)
            self._note.setStyleSheet("color: palette(highlight);")
        else:
            self._note.clear()

    # -- actions ------------------------------------------------------------
    def _locate(self) -> None:
        start = str(credentials.credentials_search_paths(self._config.credentials_path)[0])
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Select Claude Code .credentials.json",
            start,
            "Credentials (.credentials.json credentials.json);;JSON (*.json);;All files (*)",
        )
        if not chosen:
            return
        # Validate before saving: only accept a file that actually holds a token.
        if credentials.load_credentials(chosen) is None:
            self._refresh_view(
                "That file doesn't contain a Claude OAuth token — pick your "
                "Claude Code .credentials.json."
            )
            return
        self._config.credentials_path = chosen
        self._config.save()
        self._succeed()

    def _retry(self) -> None:
        creds = credentials.load_credentials(self._config.credentials_path)
        if creds is not None and not creds.is_expired:
            self._succeed()
        else:
            self._refresh_view("Still not found — is Claude Code installed and signed in?")

    def _succeed(self) -> None:
        if callable(self._on_resolved):
            self._on_resolved()
        self.accept()
