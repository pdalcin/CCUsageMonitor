# Requirements & Setup

## System (already satisfied on this machine)
- **OS:** Windows 11 (win32).
- **Python:** 3.14.6 (any 3.10+ works; PySide6 ships abi3 wheels). `python` and `py` on PATH.
- **Claude Code:** 2.1.206 — provides local session logs and the OAuth token. ✅ verified.

## Python dependencies
Minimal by design — see `requirements.txt`:

| Package | Version | Why |
|---|---|---|
| `PySide6` | `>=6.11,<6.12` | Qt UI. `abi3` wheels → compatible with Python 3.14. |

Everything else (JSON, `urllib`, `pathlib`, `dataclasses`, `datetime`) is stdlib — no extra installs.

**Stretch-only (not installed in v1):**
- `PyInstaller` — to build a standalone `.exe` (Phase 6).

## Install
```powershell
cd C:\Projects\CCUsageMonitor
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run
```powershell
# from repo root, with venv active
py -m ccmonitor
# or:
.\run.ps1
```
`run.ps1` activates `.venv` (creating it if missing), installs deps, and launches the module.

## Data prerequisites (no action needed — these already exist)
- `~/.claude/projects/**/*.jsonl` — written by Claude Code as you work. Needed for token/cost.
- `~/.claude/.credentials.json` — written when you log into Claude Code. Needed for live limits.

## Nothing else to request from the user
The original brief asked to prompt for install requirements if another language were chosen.
We stayed in **Python**, which is already installed, and the only new dependency (`PySide6`)
installs via `pip` with no system-level prerequisites (no Visual C++ build tools — wheels are
prebuilt). **No further requirements to request.**
