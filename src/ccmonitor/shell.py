"""Open PowerShell windows and discover recent Claude projects.

Two small utilities the overlay uses:

  * ``find_powershell`` / ``open_powershell`` — launch a fresh PowerShell window
    with a chosen working directory. We prefer **PowerShell 7** (``pwsh``) and
    fall back to the built-in **Windows PowerShell** (``powershell.exe``). The
    window is detached (its own console) so closing the overlay never kills it.

  * ``scan_claude_projects`` — read Claude Code's local session logs to find the
    folders you've recently worked in that contain a ``CLAUDE.md``, so the menu
    can offer to open a shell there. Scanning is **explicit** (never automatic);
    callers cache the result in the app config so the menu survives restarts.

Everything here is read-only with respect to the user's files and degrades to an
empty result / ``False`` rather than raising.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .data.session_reader import CLAUDE_PROJECTS_DIR


def find_powershell() -> str | None:
    """Return a PowerShell executable: PowerShell 7 (``pwsh``) if present, else
    Windows PowerShell (``powershell.exe``). ``None`` if neither can be found."""
    for exe in ("pwsh", "powershell"):
        found = shutil.which(exe)
        if found:
            return found
    # Last resort: the canonical Windows PowerShell path (in case PATH is odd).
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    fallback = (
        Path(system_root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    return str(fallback) if fallback.exists() else None


def app_folder() -> Path:
    """The folder to treat as 'the app folder' when opening a shell.

    Frozen (PyInstaller onefile): the directory holding the ``.exe``. From source:
    the repo root (``src/ccmonitor/shell.py`` -> two levels up)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def open_powershell(folder: str | Path) -> bool:
    """Open a new PowerShell window whose working directory is *folder*.

    Returns ``True`` if a shell was launched, ``False`` if no PowerShell was found
    or the launch failed. The window stays open (``-NoExit``) so the user can run
    ``claude`` to sign in."""
    ps = find_powershell()
    if ps is None:
        return False

    folder = Path(folder)
    cwd = str(folder) if folder.is_dir() else None
    # Embed the destination in the startup command (single-quotes doubled to
    # escape), so we land in the right place even if we couldn't set ``cwd``.
    escaped = str(folder).replace("'", "''")
    command = f"Set-Location -LiteralPath '{escaped}'"
    try:
        subprocess.Popen(  # noqa: S603 - launching a known shell, not user input
            [ps, "-NoExit", "-Command", command],
            cwd=cwd,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    except OSError:
        return False
    return True


def scan_claude_projects(limit: int = 5) -> list[str]:
    """Return up to *limit* recently-active project folders that hold a
    ``CLAUDE.md``, newest first.

    Reads Claude Code's per-project session logs under ``~/.claude/projects``.
    Each log records the real working directory (``cwd``); we take the newest log
    per project, resolve its ``cwd``, keep those that still exist and contain a
    ``CLAUDE.md``, and sort by recency. Purely read-only."""
    if not CLAUDE_PROJECTS_DIR.is_dir():
        return []

    # (mtime, cwd) for the newest session log in each project directory.
    candidates: list[tuple[float, str]] = []
    for d in CLAUDE_PROJECTS_DIR.iterdir():
        if not d.is_dir():
            continue
        newest_file: Path | None = None
        newest_mtime = -1.0
        for f in d.glob("*.jsonl"):
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            if mtime > newest_mtime:
                newest_mtime, newest_file = mtime, f
        if newest_file is None:
            continue
        cwd = _read_cwd(newest_file)
        if cwd:
            candidates.append((newest_mtime, cwd))

    candidates.sort(key=lambda t: t[0], reverse=True)
    seen: set[str] = set()
    results: list[str] = []
    for _mtime, cwd in candidates:
        key = os.path.normcase(os.path.normpath(cwd))
        if key in seen:
            continue
        seen.add(key)
        if _has_claude_md(Path(cwd)):
            results.append(cwd)
        if len(results) >= limit:
            break
    return results


def _read_cwd(jsonl: Path) -> str | None:
    """Extract the ``cwd`` field from a session log (first record that has one).

    Only the first handful of lines are inspected — ``cwd`` is written on early
    records and session files can be large."""
    try:
        with jsonl.open("r", encoding="utf-8") as handle:
            for i, line in enumerate(handle):
                if i > 50:
                    break
                if '"cwd"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = rec.get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        return None
    return None


def _has_claude_md(folder: Path) -> bool:
    try:
        # Windows' filesystem is case-insensitive, so one check covers CLAUDE.md /
        # CLAUDE.MD / claude.md alike.
        return folder.is_dir() and (folder / "CLAUDE.md").is_file()
    except OSError:
        return False
