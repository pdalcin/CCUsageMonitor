# Development Plan (phased, resumable)

Each phase ends in a **runnable** state. Checkboxes are the source of truth for "where were we"
if work is interrupted. Tick a box only when the "Done when" is actually observed, not just coded.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Phase 0 — Scaffold & planning ✅ DONE
- [x] Verify environment (Python 3.14.6, PySide6 abi3 wheels, data sources).
- [x] Write planning docs (`00`–`04`, this file).
- [x] Create package skeleton (`src/ccmonitor/...`), `requirements.txt`, `run.ps1`, `README.md`.
- [x] `python -m ccmonitor` launches and shows an always-on-top frameless card
      (verified via offscreen headless render; window builds + shows without error).
- **Done when:** a blank draggable card floats on top of other windows and can be closed. ✅

## Phase 1 — Overlay shell ✅ DONE (needs a real-desktop drag confirmation)
- [x] `ui/theme.py`: palette, fonts, sizes (dark-first).
- [x] `ui/overlay.py`: frameless, on-top, translucent, rounded card; drag-to-move; close button.
- [x] Position persistence via `config.py` (`%APPDATA%/CCUsageMonitor/config.json`).
- [x] Multi-monitor clamp on startup (`_clamp_to_screens`).
- [x] Collapse/expand to a pill; state persisted (double-click or menu).
- **Done when:** card remembers where I left it across restarts, drags across monitors, collapses.
  ⚠ Logic implemented; confirm live drag feel on the real desktop (headless can't test mouse).

## Phase 2 — Local session data ✅ DONE
- [x] `data/session_reader.py`: locate current session JSONL, parse, return `SessionStats`.
- [x] `data/pricing.py`: per-model price table + `cost()`.
- [x] `data/service.py`: `DataService` with the 2 s local timer emitting `AppState`.
- [x] Wire live **token count**, **estimated cost**, **model**, **session time** into the card.
- **Done when:** numbers update live while I use Claude Code in the monitored project. ✅
  Verified: read this session live → opus-4-8, 4.12M tokens, ~$18.66, 23m.

## Phase 3 — Animated gauges  (mostly done)
- [x] `ui/gauges.py`: `RingGauge` with animatable `value` property + threshold colors.
- [x] Wire the two limit rings; numeric readouts kept alongside.
- [ ] Pulse-on-change / idle-vs-active "liveliness" (subtle pulse when tokens are spent).
- [ ] Optional `BarGauge` variant (rings cover v1; add only if a bar reads better anywhere).
- **Done when:** gauges animate smoothly toward new values; feels alive but not distracting.
  ⚠ Rings will stay at "—" until Phase 4 supplies real limit fractions.

## Phase 4 — Live usage limits (API) ✅ DONE
- [x] **Step 1 (consent-gated probe):** captured real `GET /api/oauth/usage` response into
      `docs/samples/oauth-usage.sample.json` (HTTP 200). Learned: `utilization` is a **percent
      0..100** (not a fraction); `resets_at` is an **ISO-8601 string**; a `limits[]` array carries
      `kind: session|weekly_all|weekly_scoped` with `percent`/`resets_at` as a fallback source.
- [x] `data/credentials.py`: read token/expiry/subscription.
- [x] `data/usage_api.py`: `fetch_usage()` against the real shape (pct→fraction, ISO→epoch,
      limits[] fallback); header discipline; 429/401/offline mapping; timeouts.
- [x] `DataService`: API timer (≥180 s) on a worker thread; merge into `AppState`; freshness badge.
- [x] Wire **session-limit %** (5h, with reset countdown) and **weekly %** (7d) into the gauges.
- **Done when:** the two limit gauges match `/usage`, and survive 429s. ✅
  Verified live: session 11%, weekly 13%, "resets in 4h 44m", status "as of just now".
  ⚠ Backoff on repeated 429 is basic (keeps last-known + dim badge); tighten in Phase 5 if needed.

## Phase 5 — Polish & UX  (in progress)
- [x] `QSystemTrayIcon`: show/hide, restore, **reset position**, quit. Left/double-click toggles
      the overlay. ✕ and OS-minimize now **hide to tray** (never quit) so the window can't become
      unreachable — the bug the user hit. First hide shows a "still running in tray" balloon.
      Falls back to close-to-quit if no system tray is available.
- [x] App/tray icon (`ui/appicon.py`, shared with the `.ico`).
- [x] Right-click overlay menu: refresh now, expand/collapse, reset position, hide to tray, quit.
- [x] Manual refresh: `⟳` title button + context/tray "Refresh now". `DataService.refresh_now()`
      refreshes local instantly, throttles the API to `MANUAL_MIN_SECONDS` (20 s) to avoid 429s,
      and flashes a transient status. Verified headless (fresh→refreshing, repeat→throttled note).
- [x] Session-reset chime: `DataService.sessionReset` (window rollover + prior usage) → overlay
      plays a `winsound` chime + status flash + tray balloon. Context-menu "Sound on reset" toggle,
      persisted (`config.sound_on_reset`). Verified detection headless (0,0,1,1,0 across baseline/
      mid-window/rollover/idle cases); live rollover can't be forced (happens ≤ every 5 h).
- [x] Robust credential discovery: search `CLAUDE_CONFIG_DIR` + APPDATA/home fallbacks + a
      user-set override (`config.credentials_path`), instead of the single hardcoded path. A
      "Fix credentials…" helper dialog (overlay + tray menu, auto-shown on first no-token/expired)
      explains how to sign in, shows where it looked, and offers "Locate file…" to point at a
      non-standard `.credentials.json`. Verified: search order/dedupe, CLAUDE_CONFIG_DIR pickup,
      bogus-override fallthrough, and signed-in/expired/not-found dialog states.
- [ ] Lock / click-through toggle; opacity control.
- [ ] Settings dialog: poll intervals, opacity, monitored project, manual-limit overrides.
- [ ] Tooltips + graceful empty/error states (per failure matrix in `01-architecture.md`).
- **Done when:** everything is reachable without editing config by hand.

## Phase 6 — Stretch (only if wanted)
- [x] Packaging: `PyInstaller` one-file `.exe` (`build.ps1` → `dist\CCUsageMonitor.exe`, windowed,
      custom icon). Double-clickable / pin-to-taskbar. Verified it launches without crashing.
- [ ] Run-at-login option (Startup folder shortcut or registry Run key).
- [ ] Token auto-refresh via `refreshToken` on `expiresAt`/401 (risky — verify it can't corrupt
      Claude Code's own credential file; treat as read-mostly, write a copy, never clobber).
- [ ] Multiple project monitoring / project switcher.
- [ ] Sparkline of recent burn rate.

---

## Risks / open questions
- **`/api/oauth/usage` shape unknown** until Phase 4 Step 1 probe. App is built to run fully
  without it until then.
- **Endpoint 429s hard** — mitigated by ≥180 s polling, caching, backoff. Accept staleness.
- **Token refresh** touches Claude Code's own credential file — deferred, handled read-only first.
- **PySide6 on 3.14** — wheels are `abi3`/cp310 so should work; confirm at Phase 0 runtime.
- **Pricing drift** — model prices change; keep the table in one file, easy to edit.
