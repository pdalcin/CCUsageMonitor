"""Frozen-app entry point for PyInstaller.

Kept at repo root (not inside the package) so PyInstaller has a plain script to
analyze; the actual app lives in the ``ccmonitor`` package, collected via
``--paths src`` at build time.
"""

import sys

from ccmonitor.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
