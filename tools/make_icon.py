"""Generate assets/icon.ico from the shared renderer in ccmonitor.ui.appicon.

Run with the project's venv python:  python tools/make_icon.py
Keeps the EXE/Explorer icon identical to the in-app tray icon.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from ccmonitor.ui.appicon import render_image  # noqa: E402


def main() -> int:
    QApplication(sys.argv)  # required for QImage/QPainter
    out = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    ok = render_image(256).save(str(out), "ICO")
    print("wrote", out, ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
