"""Single source of visual truth: colors, fonts, sizing.

Dark-first (an overlay usually floats over dark editors), tuned for readability
at small sizes. Threshold colors drive the gauges: green when there's headroom,
amber as it fills, red near the limit.
"""

from __future__ import annotations

from PySide6.QtGui import QColor

# --- palette ---------------------------------------------------------------
CARD_BG = QColor(22, 24, 28, 235)      # near-opaque dark card
CARD_BORDER = QColor(255, 255, 255, 28)
TEXT = QColor(236, 238, 242)
TEXT_DIM = QColor(150, 156, 166)
TRACK = QColor(255, 255, 255, 30)       # unfilled portion of a gauge

# Anthropic-ish warm accent for the "brand" ring.
ACCENT = QColor(217, 119, 87)           # terracotta

# Usage threshold colors (fraction of limit used).
GAUGE_OK = QColor(90, 200, 140)         # green
GAUGE_WARN = QColor(230, 180, 70)       # amber
GAUGE_CRIT = QColor(230, 90, 80)        # red

STALE = QColor(120, 124, 132)           # dimmed when data is old/unavailable


def usage_color(fraction: float) -> QColor:
    """Green < 0.6, amber < 0.85, else red."""
    if fraction < 0.60:
        return GAUGE_OK
    if fraction < 0.85:
        return GAUGE_WARN
    return GAUGE_CRIT


# --- sizing ----------------------------------------------------------------
CARD_RADIUS = 14
CARD_PADDING = 12
CARD_WIDTH = 240
PILL_WIDTH = 96
PILL_HEIGHT = 40

FONT_FAMILY = "Segoe UI"
FONT_MONO = "Cascadia Mono, Consolas, monospace"
