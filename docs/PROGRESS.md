# PROGRESS — live status log

> Interruption-safe tracker. Newest entry on top. If work resumes, read this first, then
> `02-development-plan.md` checkboxes. Update both when you finish a step.

## Current state
- **Phases 0–4 DONE + Phase 6 packaging DONE.** Fully working overlay with **live local data**
  (tokens/cost/model/time) AND **live API limits** (session 5h %, weekly 7d %, reset countdown).
- **Shipped a double-clickable `dist\CCUsageMonitor.exe`** (PyInstaller, windowed, custom icon).
- **System-tray icon added** (Phase 5): fixes the "hid it and couldn't get it back" bug. ✕ and
  OS-minimize hide-to-tray instead of quitting; tray menu has Show / Refresh now / Reset position /
  Quit; tray click toggles the overlay; `app.setQuitOnLastWindowClosed(False)` so hiding never quits.
- **Manual refresh added** (Phase 5): `⟳` button in the card title row + "Refresh now" in the
  overlay context menu and the tray menu. `DataService.refresh_now()` always re-reads local data
  instantly, and hits the usage API unless it polled within `MANUAL_MIN_SECONDS` (20 s) — so mashing
  it can't trigger a 429. Shows a transient status ("refreshing…" / "just updated — retry in Ns").
- **Collapsed-pill layout fixed**: window now sizes to match the pill child exactly (`_fit_to`,
  re-run on every update since the `%` label width changes), and `RingGauge` skips its center number
  on rings < 40 px — the 30 px pill ring was drawing an unreadable 7 px number that overlapped/
  duplicated the label beside it.
- **Session-reset chime added**: `DataService.sessionReset` fires when the 5-hour window rolls over
  (`resets_at` jumps forward > 60 s) *and* the prior window had usage (no chime when idle). Overlay
  plays a Windows chime (`notify.play_reset_sound`, stdlib `winsound`, best-effort), flashes a status
  line, and raises a tray balloon. Toggle: context menu → "Sound on reset" (persisted, default on).
- **Pending / next:**
  - Confirm live drag/collapse *feel* + real-font rendering on the desktop (headless can't test
    the mouse or Segoe UI).
  - Phase 3 pulse-on-change "liveliness"; Phase 5 settings dialog + click-through/opacity.
  - Token auto-refresh (currently degrades to "re-auth in Claude Code" when the token expires).

## How to run
**Easiest (what the user wanted):** double-click **`dist\CCUsageMonitor.exe`** in Explorer, or
right-click it → *Pin to taskbar*. No console, no commandline.

**Rebuild the exe after code changes:** `.\build.ps1`  → refreshes `dist\CCUsageMonitor.exe`.

**Dev run (from source):** `.\run.ps1` (creates `.venv`, installs PySide6, runs `py -m ccmonitor`).

The overlay appears top-right; drag it anywhere/any monitor, double-click to collapse to a pill,
right-click for the menu (collapse/expand, quit).

## Log

### 2026-07-12
- Verified environment: Python 3.14.6, `pip` 26.1; PySide6 6.11.1 resolves as `cp310-abi3`
  wheels (runs on 3.14); Claude Code 2.1.206.
- Confirmed data sources against the live machine:
  - Local session JSONL at `~/.claude/projects/C--Projects-CCUsageMonitor/<sid>.jsonl`;
    `assistant` records carry `message.usage` (input/output/cache tokens) + `message.model`.
  - `~/.claude/.credentials.json` → `claudeAiOauth.accessToken` (`sk-ant-oat01…`),
    `subscriptionType=pro`, `rateLimitTier=default_claude_ai`.
  - Live-limits endpoint identified: `GET api.anthropic.com/api/oauth/usage` (needs
    `User-Agent: claude-code/2.1.206`; 429s hard → poll ≥180 s, cache + backoff).
- Decisions from user: OAuth-token live limits · animated gauges (no mascot) · show all four
  metrics (session %, weekly %, live tokens/cost, model + session time).
- Wrote planning docs `00`–`04` + this file.
- Built package: `config`, `data/{credentials,pricing,session_reader,usage_api,service}`,
  `ui/{theme,gauges,overlay}`, `__main__`. Installed PySide6 6.11.1 into `.venv` (imports on 3.14).
- Verified end-to-end via offscreen render: window builds, local data flows in, readouts correct,
  full + pill previews saved. Phases 0–2 done, Phase 3 mostly done.
- Ran consent-gated Phase 4 probe: `GET /api/oauth/usage` → HTTP 200, saved sample. Real shape:
  `five_hour`/`seven_day` blocks with `utilization` as **percent** + `resets_at` **ISO string**;
  plus a `limits[]` array (kind session/weekly_all). Rewrote parser (pct→fraction, ISO→epoch,
  limits[] fallback) and enabled the API in DataService. Verified live end-to-end: rings 11%/13%,
  reset countdown, freshness badge. Phase 4 done.
- Phase 6 packaging: added `launcher.py`, `tools/make_icon.py` (terracotta ring .ico), `build.ps1`.
  Built `dist\CCUsageMonitor.exe` (48 MB, windowed/onefile) and verified it launches without
  crashing. This is now the primary way to run it (double-click / pin to taskbar).
- Fix (user-reported): hiding the overlay left no way to restore it (Qt.Tool = no taskbar button,
  no tray icon existed). Added `ui/appicon.py` (shared icon renderer) + `QSystemTrayIcon` in
  `__main__`; overlay gained `requestHideToTray` signal, `show_and_raise`, `reset_position`,
  `ensure_on_screen`, tray-aware `closeEvent`/`changeEvent`. Verified hide/show/reset/quit
  transitions headless; rebuilt exe; launched on the real desktop (tray icon present).

## Parking lot / TODO-later
- Capture real `/api/oauth/usage` JSON shape (Phase 4 Step 1, consent-gated) →
  `docs/samples/oauth-usage.sample.json`.
- Confirm PySide6 actually imports & renders on 3.14 at first `python -m ccmonitor`.
- Decide pill (collapsed) visual.
