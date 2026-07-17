"""Settings window: credential source and search priority.

Two things live here today:
  * a shortcut into the credentials helper (sign in / locate the file), and
  * the credential **search priority** — Claude Code first (recommended) or the
    experimental OMP/oh-my-pi fallback first.

Changing the priority saves immediately and forces a re-validation so the choice
takes effect at once.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..data import credentials


class SettingsDialog(QDialog):
    """Modal settings window; reflects live credential state via ``stateChanged``."""

    def __init__(self, config, service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._service = service
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(470)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        # -- Credentials --------------------------------------------------
        cred_group = QGroupBox("Claude Code credentials")
        cg = QVBoxLayout(cred_group)
        cg.setSpacing(8)
        self._cred_status = QLabel()
        self._cred_status.setWordWrap(True)
        cg.addWidget(self._cred_status)
        row = QHBoxLayout()
        b_manage = QPushButton("Manage credentials…")
        b_manage.setToolTip("Sign in, locate your .credentials.json, or re-check")
        b_manage.clicked.connect(self._manage_creds)
        row.addWidget(b_manage)
        row.addStretch(1)
        cg.addLayout(row)
        root.addWidget(cred_group)

        # -- Search priority ----------------------------------------------
        pri_group = QGroupBox("Credential search priority")
        pg = QVBoxLayout(pri_group)
        pg.setSpacing(6)
        self._rb_cc = QRadioButton("Claude Code first (recommended)")
        self._rb_omp = QRadioButton("OMP (oh-my-pi) first — experimental")
        self._grp = QButtonGroup(self)
        self._grp.setExclusive(True)
        self._grp.addButton(self._rb_cc)
        self._grp.addButton(self._rb_omp)
        pg.addWidget(self._rb_cc)
        pg.addWidget(self._rb_omp)
        hint = QLabel(
            "If Claude Code is first and its saved login has expired, the app also "
            "checks OMP for a working token as a fallback. OMP support is "
            "experimental and reads OMP's local store read-only."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        pg.addWidget(hint)
        root.addWidget(pri_group)

        # Reflect current config, then wire the change handler (wire after setting
        # the initial state so restoring it doesn't trigger a spurious refresh).
        if getattr(self._config, "credential_priority", "claude_code") == "omp":
            self._rb_omp.setChecked(True)
        else:
            self._rb_cc.setChecked(True)
        self._rb_cc.toggled.connect(self._on_priority_changed)

        # -- buttons ------------------------------------------------------
        btns = QHBoxLayout()
        btns.addStretch(1)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.accept)
        btns.addWidget(b_close)
        root.addLayout(btns)

        # Live-update the credential summary while open.
        self._service.stateChanged.connect(self._refresh_cred_status)
        self.finished.connect(
            lambda _: self._service.stateChanged.disconnect(self._refresh_cred_status)
        )
        self._refresh_cred_status()

    # -- handlers ---------------------------------------------------------
    def _on_priority_changed(self, _checked: bool) -> None:
        priority = "claude_code" if self._rb_cc.isChecked() else "omp"
        self._config.credential_priority = priority
        self._config.save()
        # Re-validate immediately so the new order takes effect without waiting for
        # the next poll (force skips the manual-refresh throttle).
        self._service.refresh_now(force=True)
        self._refresh_cred_status()

    def _refresh_cred_status(self, *_args) -> None:
        creds = credentials.load_credentials(
            self._config.credentials_path,
            priority=getattr(self._config, "credential_priority", "claude_code"),
        )
        if creds is None:
            self._cred_status.setText(
                "No Claude credentials found. Use <b>Manage credentials…</b> to sign "
                "in or point at your <code>.credentials.json</code>."
            )
        elif creds.is_omp:
            self._cred_status.setText(
                f"Using an <b>OMP</b> token (experimental) from "
                f"<code>{creds.source_path}</code>."
            )
        else:
            plan = creds.subscription_type or "your Claude account"
            expiry = " — <b>expired</b>" if creds.is_expired else ""
            self._cred_status.setText(
                f"Claude Code token for <b>{plan}</b>{expiry} at "
                f"<code>{creds.source_path}</code>."
            )

    def _manage_creds(self) -> None:
        from .credentials_dialog import CredentialsDialog

        dlg = CredentialsDialog(self._config, self._service, parent=self)
        dlg.exec()
        self._refresh_cred_status()
