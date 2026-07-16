# CCUsageMonitor — Overview

A small, movable, always-on-top **desktop overlay** for Windows that shows, at a glance:

- **Session limit % used** — progress toward the current Claude 5-hour usage window, with time-until-reset.
- **Weekly limit % used** — progress toward the 7-day usage window.
- **Live tokens / cost** — tokens and estimated $ burned in the *current* Claude Code session (read from local session logs).
- **Current model + session time** — which model is active and how long the session has run.

Design inspiration: **Bongo Cat** — tiny, non-intrusive, lives in a corner, draggable across monitors, minimizable. Our "ludic" element is a set of **animated gauges** (rings/bars that fill and pulse as usage changes) rather than a character.

## Goals / non-goals

**Goals**
- Non-intrusive, compact (fits a screen corner), high-readability at small size.
- Draggable anywhere, including across multiple monitors; remembers position.
- Minimize / collapse to a tiny pill; restore on click.
- Zero-friction data: reads what Claude Code already stores locally; queries live limits with the token Claude Code already holds.

**Non-goals (v1)**
- No historical charts / analytics dashboard (that's what `ccusage` does).
- No writing/telemetry back to Anthropic beyond the read-only usage query.
- No cross-platform (Windows-first; code stays reasonably portable but untested elsewhere).

## Tech decisions (locked)

| Decision | Choice | Why |
|---|---|---|
| Language | **Python 3.14** | User preference; already installed (`3.14.6`). |
| GUI toolkit | **PySide6 6.11** (Qt, LGPL) | `abi3` wheels run on 3.14; best-in-class frameless/transparent/always-on-top overlay support; smooth animation via `QPropertyAnimation`. |
| HTTP | **stdlib `urllib`** | One less dependency; the only call is a single GET to the usage endpoint. |
| Live limits source | **`GET api.anthropic.com/api/oauth/usage`** | Undocumented endpoint powering `/usage`; uses the OAuth token Claude Code already stored. See `04-data-sources.md`. |
| Session/cost source | **Local `~/.claude/projects/**/*.jsonl`** | Each assistant turn records `message.usage` token counts + model. No auth. |

## Repository layout

```
CCUsageMonitor/
├── docs/                     # planning + progress (this folder)
├── assets/                   # icons, fonts if any
├── src/ccmonitor/
│   ├── __main__.py           # entry point (python -m ccmonitor)
│   ├── config.py             # persisted settings (window pos, poll interval, ...)
│   ├── data/
│   │   ├── credentials.py    # read ~/.claude/.credentials.json OAuth token
│   │   ├── session_reader.py # parse local JSONL -> current-session token totals
│   │   ├── usage_api.py      # poll /api/oauth/usage -> 5h + 7d limit state
│   │   └── pricing.py        # token -> $ estimate per model
│   └── ui/
│       ├── overlay.py        # frameless, draggable, always-on-top window
│       ├── gauges.py         # animated ring / bar widgets
│       └── theme.py          # colors, fonts, sizing
├── requirements.txt
├── run.ps1                   # convenience launcher
└── README.md
```
