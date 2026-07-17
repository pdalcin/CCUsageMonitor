"""Help dialog for resolving Claude credential problems.

Validity is judged by the **live usage-API result**, not just the presence of a
token file: a credential can exist and be un-expired by its ``expiresAt`` yet
still be rejected by the server (revoked, re-authed elsewhere, or a login too old
to refresh). Only a real request settles it, so this dialog reflects the
service's last API status and its "Retry" actively re-validates against Anthropic.

We never perform Claude's OAuth login ourselves — that belongs to Claude Code, and
duplicating it risks corrupting its credential store. We explain how to sign in,
show where we looked, and let the user point us at a non-standard file.
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
    """Modal helper reflecting the live credential/API state.

    Reads ``service.state.limits_status`` for the authoritative verdict and calls
    ``service.refresh_now()`` to re-validate; updates live via ``stateChanged``.
    """

    def __init__(self, config, service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._service = service
        self.setWindowTitle("Claude credentials")
        self.setModal(True)
        self.setMinimumWidth(470)

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

        btns = QHBoxLayout()
        btns.setSpacing(8)
        b_locate = QPushButton("Locate file…")
        b_locate.setToolTip("Point directly at your .credentials.json")
        b_locate.clicked.connect(self._locate)
        b_get = QPushButton("Get Claude Code")
        b_get.clicked.connect(lambda: QDesktopServices.openUrl(CLAUDE_CODE_URL))
        b_shell = QPushButton("Open PowerShell")
        b_shell.setToolTip(
            "Open a PowerShell window in the app folder so you can run "
            "`claude` and sign in"
        )
        b_shell.clicked.connect(self._open_shell)
        b_retry = QPushButton("Re-check now")
        b_retry.clicked.connect(self._retry)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.reject)
        btns.addWidget(b_locate)
        btns.addWidget(b_get)
        btns.addWidget(b_shell)
        btns.addStretch(1)
        btns.addWidget(b_retry)
        btns.addWidget(b_close)
        root.addLayout(btns)

        # Live-update while open; the service re-emits on every poll / refresh.
        self._service.stateChanged.connect(self._on_state)
        self.finished.connect(lambda _: self._service.stateChanged.disconnect(self._on_state))

        self._note_text = ""
        self._refresh_view()

    # -- live state ---------------------------------------------------------
    def _on_state(self, _state) -> None:
        # A poll/refresh landed; if it resolved to a working token, clear any
        # stale "re-checking" note.
        if self._service.state.limits_status == "ok":
            self._note_text = ""
        self._refresh_view()

    def _refresh_view(self) -> None:
        creds = credentials.load_credentials(
            self._config.credentials_path,
            priority=getattr(self._config, "credential_priority", "claude_code"),
        )
        status = self._service.state.limits_status
        refreshing = self._service.state.refreshing
        show_paths = False

        if creds is None:
            self._headline.setText("Couldn't find your Claude credentials")
            self._body.setText(
                "This overlay reads the OAuth token that <b>Claude Code</b> stores on "
                "your machine — it doesn't log in on its own. To fix this:<br>"
                "&nbsp;&nbsp;1. Install <a href='%s'>Claude Code</a> if you haven't.<br>"
                "&nbsp;&nbsp;2. Open a terminal, run <code>claude</code>, and sign in.<br>"
                "&nbsp;&nbsp;3. Click <b>Re-check now</b> below.<br><br>"
                "If your config lives somewhere non-standard (e.g. a custom "
                "<code>CLAUDE_CONFIG_DIR</code>), use <b>Locate file…</b> to point us "
                "straight at your <code>.credentials.json</code>." % CLAUDE_CODE_URL
            )
            show_paths = True

        elif status == "unauthorized" or creds.is_expired:
            # Present but not accepted: the authoritative failure the user hit.
            if status == "unauthorized":
                why = (
                    "the server <b>rejected it</b> — it may have been revoked, or your last "
                    "Claude Code sign-in is too old to refresh"
                )
            else:
                why = "it has <b>expired</b>"
            self._headline.setText("Your saved Claude login is no longer valid")
            self._body.setText(
                f"A token was found at <code>{creds.source_path}</code>, but {why}.<br><br>"
                "This is why usage won't load even though a credential exists. Fix it by "
                "re-authenticating in Claude Code:<br>"
                "&nbsp;&nbsp;1. Open a terminal and run <code>claude</code> (sign in if prompted).<br>"
                "&nbsp;&nbsp;2. Come back and click <b>Re-check now</b>."
            )

        elif status == "ok":
            if creds.is_omp:
                self._headline.setText("Signed in via OMP (working, but limited)")
                self._body.setText(
                    "No Claude Code login was found, so the overlay is using the Claude token "
                    f"from <b>OMP (oh-my-pi)</b> at <code>{creds.source_path}</code>.<br><br>"
                    "Limits are loading, but the session tokens/cost/model panel stays empty. "
                    "For the full experience, sign in with Claude Code."
                )
            else:
                plan = creds.subscription_type or "your Claude account"
                self._headline.setText("You're signed in and usage is loading ✓")
                self._body.setText(
                    f"Verified a working Claude token for <b>{plan}</b> at:<br>"
                    f"<code>{creds.source_path}</code>"
                )

        else:
            # Token present but not yet confirmed (first load, offline, rate-limited…).
            reason = {
                "loading": "checking it now…",
                "offline": "you appear to be offline",
                "rate_limited": "the usage endpoint is rate-limiting us",
                "error": "the usage request failed",
                "disabled": "the limits API is turned off",
            }.get(status, "it hasn't been verified yet")
            self._headline.setText("Found a token — verifying…")
            self._body.setText(
                f"A token was found at <code>{creds.source_path}</code>, but we haven't "
                f"confirmed it works ({reason}).<br><br>"
                "Click <b>Re-check now</b> to validate it against Anthropic. If it keeps "
                "failing, re-authenticate in Claude Code (<code>claude</code>)."
            )

        if show_paths:
            searched = credentials.credentials_search_paths(self._config.credentials_path)
            self._paths.setText("Looked in:\n" + "\n".join(f"  • {p}" for p in searched))
            self._paths.show()
        else:
            self._paths.hide()

        note = "Re-checking with Anthropic…" if refreshing else self._note_text
        if note:
            self._note.setText(note)
            self._note.setStyleSheet("color: palette(highlight);")
            self._note.show()
        else:
            self._note.clear()
            self._note.hide()

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
        if credentials.load_credentials_from(chosen) is None:
            self._note_text = (
                "That file doesn't contain a Claude OAuth token — pick your "
                "Claude Code .credentials.json."
            )
            self._refresh_view()
            return
        self._config.credentials_path = chosen
        self._config.save()
        self._note_text = ""
        self._service.refresh_now(force=True)  # validate the newly chosen file against the API
        self._refresh_view()

    def _open_shell(self) -> None:
        # Open a PowerShell (PS7 if available) in the app folder so the user can
        # run `claude` to sign in, then come back and Re-check.
        from .. import shell

        if shell.open_powershell(shell.app_folder()):
            self._note_text = (
                "Opened a PowerShell window. Run  claude  to sign in, then click "
                "Re-check now."
            )
        else:
            self._note_text = (
                "Couldn't find PowerShell on this system. Open a terminal manually "
                "and run  claude  to sign in."
            )
        self._refresh_view()

    def _retry(self) -> None:
        # Actively re-validate: refresh_now re-reads the file AND hits the API, so a
        # token that was rejected shows up as still-bad, and a fresh login shows ok.
        self._service.refresh_now(force=True)
        self._refresh_view()
