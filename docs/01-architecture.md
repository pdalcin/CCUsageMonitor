# Architecture

## Runtime shape

Single-process PySide6 app. One always-on-top frameless window. A background poller feeds a
shared state object; the UI reads it on a timer and animates gauges toward new values.

```
            ┌─────────────────────────────────────────────┐
            │                Qt main thread                │
            │                                              │
  ┌──────┐  │   ┌────────────┐      ┌──────────────────┐   │
  │ disk │──┼──▶│ DataService │────▶│  AppState (dataclass)│─┼──▶ OverlayWindow
  └──────┘  │   │  (QObject)  │      └──────────────────┘   │      └─ Gauge widgets
  ┌──────┐  │   │            │              ▲               │         (QPropertyAnimation)
  │ API  │──┼──▶│  QTimers:  │──────────────┘               │
  └──────┘  │   │  local 2s  │   emits stateChanged         │
            │   │  api 300s  │                              │
            │   └────────────┘                              │
            └─────────────────────────────────────────────┘
```

- **Local reads (session_reader)** are cheap → poll every ~2 s on a `QTimer`. Reading a JSONL and
  summing usage for one session is milliseconds; fine on the main thread. If it ever isn't, move to
  a `QThreadPool` worker.
- **API reads (usage_api)** are expensive/rate-limited → poll every 300 s on a separate `QTimer`,
  executed in a worker thread (`QThreadPool` + signal back) so the UI never blocks on the network.
- **AppState** is a plain dataclass holding the latest merged snapshot (local + api + freshness
  timestamps + error flags). `DataService` emits `stateChanged(AppState)`; the window re-renders.

## Modules & responsibilities

| Module | Responsibility | Depends on |
|---|---|---|
| `config.py` | Load/save JSON settings to `%APPDATA%/CCUsageMonitor/config.json`: window x/y, `view_mode` (compact/expanded/full; migrated from the old `collapsed` flag), poll intervals, opacity, monitored project path, manual-limit overrides. | stdlib |
| `data/credentials.py` | Read `~/.claude/.credentials.json`; expose token + expiry + subscription. Never logs the token. | stdlib |
| `data/session_reader.py` | Find current session JSONL; parse; return `SessionStats` (tokens by kind, model, effort, start time, message count). Parses are cached per file and resumed from the last byte read, so polling large/busy logs only costs their new lines. | stdlib |
| `data/live_sessions.py` | List running Claude Code sessions from `~/.claude/sessions/<pid>.json`, keeping only entries whose pid is alive with a matching creation time; attach each one's `SessionStats`. | session_reader |
| `data/pricing.py` | `cost(model, usage) -> float`. Table of per-MTok prices incl. cache read/write tiers. Unknown model → 0 + flag. | — |
| `data/usage_api.py` | One function `fetch_usage(token, ua) -> UsageLimits` (5h/7d utilization, reset, limit). Handles headers, timeouts, 429/401 mapping. Pure/testable. | credentials |
| `data/service.py` | `DataService(QObject)` — owns timers + threadpool, merges sources into `AppState`, emits `stateChanged`. Enumerates live sessions on each local poll only while `track_live_sessions` is on (the overlay's full view). | all data/* |
| `ui/theme.py` | Colors, fonts, sizes, light/dark. Single source of visual truth. | — |
| `ui/gauges.py` | `RingGauge`, `BarGauge` widgets with an animatable `value` Qt property (0..1), color thresholds, pulse-on-change. | theme |
| `ui/overlay.py` | `OverlayWindow` — frameless, `WindowStaysOnTopHint`, translucent bg, drag-to-move, compact/expanded/full views, right-click menu (settings/quit), position persistence. | gauges, config |
| `__main__.py` | Single-instance guard; wire config → DataService → OverlayWindow; tray; `QApplication` loop. | all |

## Overlay window specifics (Qt/Windows)

- Flags: `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`
  (`Qt.Tool` keeps it out of the taskbar/alt-tab — overlay behavior).
- `setAttribute(Qt.WA_TranslucentBackground)` for rounded corners / soft card look.
- **Dragging:** capture `mousePressEvent`/`mouseMoveEvent`; move the frameless window by delta.
  Persist final position to `config` on release.
- **Multi-monitor:** positions are stored in global virtual-desktop coordinates; on startup clamp
  into the nearest available `QScreen` geometry so it can't be lost off a disconnected monitor.
- **View modes:** `compact` (a pill: mini-ring + %), `expanded` (the card) and `full` (the card,
  widened, plus a running-sessions panel). `set_view_mode()` is the single switch; the mode is
  persisted. When a larger view would hang off its screen the window is nudged back inside without
  saving that position.
- **Single instance:** at startup `__main__` connects to a per-user `QLocalServer` name
  (`CCUsageMonitor-<user>`). If one answers, it sends `activate` and exits; the running copy calls
  `OverlayWindow.show_full()` (show + raise + full view). Otherwise this copy starts listening.
- **Minimize to tray (stretch):** `QSystemTrayIcon` to fully hide/show.
- **Click-through / lock (stretch):** optional mode that ignores mouse so it's purely decorative.

## Threading rules
- Qt widgets touched only on the main thread.
- Network done in worker; results delivered via queued signal → main thread updates AppState.
- No shared mutable state without going through signals.

## Failure & degradation matrix

| Condition | Behavior |
|---|---|
| No `.credentials.json` / no token | Hide limit gauges (or show "—"); local tokens/cost still work. Tooltip explains. |
| API 429 | Keep last-known limits, dim them, show "as of Xm ago"; back off. |
| API 401 (token expired) | Badge: "re-auth in Claude Code"; keep local data live. |
| No session JSONL yet | Gauges at 0 / "no active session"; keep polling. |
| Unknown model in pricing | Show tokens, cost shows "?"; log which model to add. |
| Monitor unplugged | Clamp window back on-screen at next launch. |
