# CCUsageMonitor

A tiny, movable, always-on-top **desktop overlay** for Windows that shows your live Claude Code
session usage and your Claude plan limits — in the spirit of *Bongo Cat*: non-intrusive, lives in a
corner, draggable across monitors, collapsible.

Shows at a glance:
- **Session limit %** (5-hour window) with reset countdown
- **Weekly limit %** (7-day window)
- **Live tokens & estimated cost** for the current Claude Code session
- **Current model & session time**

The playful element is a set of **animated ring gauges** that glide and color-shift (green →
amber → red) as usage climbs. A chime plays when your 5-hour window resets.

## Uses your own Claude account — nothing is bundled or shared

This app reads **your** local Claude Code data on the machine it runs on:
- **Session tokens / cost / model / time** — parsed from Claude Code's local session logs at
  `~/.claude/projects/**/*.jsonl`. No network, no auth.
- **Session / weekly limits** — the `GET api.anthropic.com/api/oauth/usage` endpoint, authenticated
  with the OAuth token Claude Code **already stores** at `~/.claude/.credentials.json`.

The token is read **read-only, at runtime, on your machine**. It is never logged, copied, written
back, or transmitted anywhere except in the `Authorization` header of that one Anthropic request.
**There are no credentials, API keys, or personal data committed to this repository** — everyone who
runs it authenticates automatically with their own Claude Code login.

## Prerequisites

- **Windows 10/11**
- **[Claude Code](https://claude.com/claude-code)** installed and **logged in** (`claude` on PATH).
  The overlay reads the session logs and OAuth token that Claude Code creates — it does not log you
  in itself. If you're not signed in, the limit gauges show "sign in to Claude Code".
- **Python 3.10+** (only needed to build/run from source).

## Run it

This repo does **not** ship a prebuilt `.exe` (build artifacts are gitignored). Build your own:

```powershell
git clone <your-fork-url> CCUsageMonitor
cd CCUsageMonitor
.\build.ps1        # creates .venv, installs PySide6, produces dist\CCUsageMonitor.exe
```

Then double-click **`dist\CCUsageMonitor.exe`** in Explorer, or right-click → **Pin to taskbar**.
No console window; Python + Qt are bundled into the single exe.

**Dev run from source** (no packaging):

```powershell
.\run.ps1          # creates .venv, installs deps, runs py -m ccmonitor
```

## Using it

- **Drag** anywhere (any monitor) — position is remembered.
- **Double-click** to collapse to a compact pill; again to expand.
- **Right-click** for the menu: Refresh now · Collapse/Expand · Reset position · Sound on reset ·
  Test alarm sound · Fix credentials… · **Open PowerShell ▸** · Hide to tray · Quit.
- **Open PowerShell ▸** opens a PowerShell 7 window (falling back to Windows PowerShell) in the app
  folder, in any of your recent Claude project folders, or **Scan for recent Claude projects** to
  (re)populate that list from your local Claude Code history. The scanned list is remembered across
  restarts and only refreshes when you scan.
- **System-tray icon** (terracotta ring): click to show/hide; right-click for Show / Refresh / Reset
  / Quit. Closing the card (✕) or minimizing hides it to the tray — it never gets stuck off-screen.
- **`⟳` Refresh** re-checks usage on demand (local instantly; the API is throttled to avoid the
  endpoint's rate limit).

## Troubleshooting: limit gauges show "sign in to Claude Code"

The overlay reads the OAuth token Claude Code stores locally. If it can't find one:

- Make sure **Claude Code is installed and you've signed in** — open a terminal, run
  `claude`, and log in if prompted.
- The app searches `CLAUDE_CONFIG_DIR` (if you've set it), `~/.claude/.credentials.json`, and the
  usual APPDATA locations. If your credentials live somewhere else, right-click the overlay →
  **Fix credentials…** → **Locate file…** and point it straight at your `.credentials.json`. The
  chosen path is remembered.
- **A credential can exist but still be rejected** by the server — e.g. it was revoked, or your last
  Claude Code sign-in is too old to refresh. The app judges validity by the **actual usage-API
  response**, not just whether a file exists, so in that case it shows "limits: re-auth in Claude
  Code" and the helper says *"Your saved Claude login is no longer valid."* Fix it by running
  `claude` to sign in again, then click **Re-check now**. The helper has an **Open PowerShell**
  button that opens a shell in the app folder so you can run `claude` right there.
- The **Fix credentials…** dialog (also on the tray menu) shows exactly where it looked and the live
  state — signed-in-and-verified, rejected/expired, or found-but-unverified. It pops up automatically
  the first time a credential problem is detected, and **Re-check now** re-validates against Anthropic
  on demand.

### OMP (oh-my-pi) fallback — experimental

If no Claude Code login is found, the app makes a **last-resort, read-only** attempt to recover a
Claude OAuth token from [OMP / oh-my-pi](https://omp.sh)'s local SQLite store
(`~/.omp/agent/agent.db`, or under `PI_CONFIG_DIR`). If it works, you'll get a one-time warning that
you're running on OMP credentials with a **limited experience**: the session tokens/cost/model panel
stays empty (OMP doesn't write Claude Code session logs) and limits come from OMP's token. Signing in
with Claude Code is recommended. This path was developed without OMP on hand and **needs validation
by an OMP user** — please report back if it does or doesn't work for you.

## A note on the usage endpoint

`/api/oauth/usage` is an undocumented endpoint that rate-limits aggressively (HTTP 429). The app
polls it no more than every ~3–5 minutes and caches the last good result, so it stays within a
polite budget. If Anthropic changes or removes it, the limit gauges degrade gracefully and the local
token/cost/model data keeps working.

## License

This project's own code is licensed under the **Apache License 2.0** — see [`LICENSE`](LICENSE).

Note that the packaged exe bundles **PySide6 / Qt**, which is **LGPLv3**: redistributing the built
`.exe` carries LGPL obligations (see the Qt for Python licensing terms). Redistributing the source
in this repo does not.

## Project docs

- `docs/00-overview.md` — what & why, tech decisions, layout
- `docs/01-architecture.md` — modules, threading, failure/degradation matrix
- `docs/03-requirements.md` — deps & setup
- `docs/04-data-sources.md` — verified data sources + the usage endpoint
</content>
</invoke>
