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
| `config.py` | Load/save JSON settings to `%APPDATA%/CCUsageMonitor/config.json`: window x/y, collapsed?, poll intervals, opacity, monitored project path, manual-limit overrides. | stdlib |
| `data/credentials.py` | Read `~/.claude/.credentials.json`; expose token + expiry + subscription. Never logs the token. | stdlib |
| `data/session_reader.py` | Find current session JSONL; parse; return `SessionStats` (tokens by kind, model, start time, message count). | stdlib |
| `data/pricing.py` | `cost(model, usage) -> float`. Table of per-MTok prices incl. cache read/write tiers. Unknown model → 0 + flag. | — |
| `data/usage_api.py` | One function `fetch_usage(token, ua) -> UsageLimits` (5h/7d utilization, reset, limit). Handles headers, timeouts, 429/401 mapping. Pure/testable. | credentials |
| `data/service.py` | `DataService(QObject)` — owns timers + threadpool, merges sources into `AppState`, emits `stateChanged`. | all data/* |
| `ui/theme.py` | Colors, fonts, sizes, light/dark. Single source of visual truth. | — |
| `ui/gauges.py` | `RingGauge`, `BarGauge` widgets with an animatable `value` Qt property (0..1), color thresholds, pulse-on-change. | theme |
| `ui/overlay.py` | `OverlayWindow` — frameless, `WindowStaysOnTopHint`, translucent bg, drag-to-move, collapse/expand, right-click menu (settings/quit), position persistence. | gauges, config |
| `__main__.py` | Wire config → DataService → OverlayWindow; `QApplication` loop. | all |

## Overlay window specifics (Qt/Windows)

- Flags: `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`
  (`Qt.Tool` keeps it out of the taskbar/alt-tab — overlay behavior).
- `setAttribute(Qt.WA_TranslucentBackground)` for rounded corners / soft card look.
- **Dragging:** capture `mousePressEvent`/`mouseMoveEvent`; move the frameless window by delta.
  Persist final position to `config` on release.
- **Multi-monitor:** positions are stored in global virtual-desktop coordinates; on startup clamp
  into the nearest available `QScreen` geometry so it can't be lost off a disconnected monitor.
- **Collapse:** toggles between full card and a tiny pill (e.g. a single mini-ring + %). State
  persisted.
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
