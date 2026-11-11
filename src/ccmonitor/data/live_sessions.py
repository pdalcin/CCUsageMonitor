"""Enumerate the Claude Code sessions running on this machine right now.

Every interactive Claude Code process registers itself in
``~/.claude/sessions/<pid>.json`` (pid, sessionId, cwd, name, status busy/idle,
version, ``procStart``). The file outlives a crashed process, so each entry is
checked against the OS: the pid must be alive *and* — when ``procStart`` is
present — its creation time must match, so a recycled pid isn't mistaken for the
old session.

Per-session tokens / cost / model / effort come from that session's transcript
via ``session_reader`` (incremental, so polling several busy sessions is cheap).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import session_reader
from .session_reader import SessionStats

CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"

# procStart is a Windows FILETIME (100 ns ticks); allow a little rounding slack.
_PROC_START_TOLERANCE = 10_000_000  # 1 s


@dataclass
class LiveSession:
    pid: int
    session_id: str
    cwd: str
    name: str
    status: str                      # "busy" | "idle" | whatever Claude Code reports
    version: str | None
    started_at: datetime | None
    stats: SessionStats | None       # None when the transcript isn't on disk yet

    @property
    def model(self) -> str | None:
        return self.stats.primary_model if self.stats else None

    @property
    def effort(self) -> str | None:
        if self.stats and self.stats.effort:
            return self.stats.effort
        return session_reader.default_effort(self.model)


def _process_creation_filetime(pid: int) -> int | None:
    """Creation time of a live process as a FILETIME int, or None if it's gone.
    Returns -1 when the process exists but its times can't be read."""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied still means it exists; anything else means it's gone.
        return -1 if ctypes.get_last_error() == 5 else None
    try:
        code = wintypes.DWORD()
        if k32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != STILL_ACTIVE:
            return None
        ft = [wintypes.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(handle, *(ctypes.byref(f) for f in ft)):
            return -1
        created = ft[0]
        return (created.dwHighDateTime << 32) | created.dwLowDateTime
    finally:
        k32.CloseHandle(handle)


def _is_running(pid: int, proc_start) -> bool:
    if sys.platform != "win32":
        import os
        try:
            os.kill(pid, 0)
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    created = _process_creation_filetime(pid)
    if created is None:
        return False
    if created < 0:
        return True
    try:
        expected = int(proc_start)
    except (TypeError, ValueError):
        return True
    return abs(created - expected) <= _PROC_START_TOLERANCE


def _transcript_for(session_id: str, cwd: str) -> Path | None:
    projects = session_reader.CLAUDE_PROJECTS_DIR
    direct = projects / session_reader.encode_project_path(cwd) / f"{session_id}.jsonl"
    if direct.is_file():
        return direct
    # Encoding can differ (e.g. non-ASCII paths); fall back to a search by id.
    for match in projects.glob(f"*/{session_id}.jsonl"):
        return match
    return None


def list_live_sessions() -> list[LiveSession]:
    """Running Claude Code sessions, busy first, then most recently started."""
    if not CLAUDE_SESSIONS_DIR.is_dir():
        return []
    out: list[LiveSession] = []
    for f in CLAUDE_SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            pid = int(data.get("pid"))
        except (TypeError, ValueError):
            continue
        session_id = data.get("sessionId")
        if not session_id or not _is_running(pid, data.get("procStart")):
            continue
        cwd = str(data.get("cwd") or "")
        started = data.get("startedAt")
        started_at = (
            datetime.fromtimestamp(started / 1000, tz=timezone.utc)
            if isinstance(started, (int, float))
            else None
        )
        transcript = _transcript_for(session_id, cwd)
        out.append(
            LiveSession(
                pid=pid,
                session_id=session_id,
                cwd=cwd,
                name=str(data.get("name") or Path(cwd).name or session_id[:8]),
                status=str(data.get("status") or "unknown"),
                version=data.get("version"),
                started_at=started_at,
                stats=session_reader.read_session(transcript) if transcript else None,
            )
        )
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    out.sort(key=lambda s: (s.status != "busy", -(s.started_at or epoch).timestamp()))
    return out
