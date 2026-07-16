"""Animated gauge widgets — the "ludic" element of the overlay.

``RingGauge`` draws a circular progress ring with a value in the middle; its
``value`` (0..1) is an animatable Qt property so changes glide instead of
jumping. A subtle pulse plays when the value grows (tokens being spent), giving
the overlay a sense of life without a mascot.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme


class RingGauge(QWidget):
    def __init__(
        self,
        label: str = "",
        diameter: int = 84,
        thickness: int = 9,
        color: QColor | None = None,
        auto_color: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._display = 0.0            # animated value actually painted
        self._label = label
        self._center_text = ""
        self._diameter = diameter
        self._thickness = thickness
        self._fixed_color = color or theme.ACCENT
        self._auto_color = auto_color
        self.setFixedSize(diameter, diameter)

        self._anim = QPropertyAnimation(self, b"display", self)
        self._anim.setDuration(650)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # -- animatable property ------------------------------------------------
    def get_display(self) -> float:
        return self._display

    def set_display(self, v: float) -> None:
        self._display = max(0.0, min(1.0, v))
        self.update()

    display = Property(float, get_display, set_display)

    # -- public API ---------------------------------------------------------
    def set_value(self, fraction: float | None, center_text: str = "") -> None:
        """Set target fraction (0..1). ``None`` renders an empty/unknown ring."""
        self._center_text = center_text
        if fraction is None:
            self._value = 0.0
            self._anim.stop()
            self.set_display(0.0)
            return
        fraction = max(0.0, min(1.0, fraction))
        self._value = fraction
        self._anim.stop()
        self._anim.setStartValue(self._display)
        self._anim.setEndValue(fraction)
        self._anim.start()

    def set_label(self, label: str) -> None:
        self._label = label
        self.update()

    def _color(self) -> QColor:
        return theme.usage_color(self._display) if self._auto_color else self._fixed_color

    # -- painting -----------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self._thickness / 2 + 1
        rect = QRectF(m, m, self._diameter - 2 * m, self._diameter - 2 * m)

        # track
        track_pen = QPen(theme.TRACK, self._thickness)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track_pen)
        p.drawArc(rect, 0, 360 * 16)

        # progress (start at 12 o'clock, clockwise)
        if self._display > 0:
            pen = QPen(self._color(), self._thickness)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            span = int(-self._display * 360 * 16)
            p.drawArc(rect, 90 * 16, span)

        # center text — skipped on tiny rings, where it's unreadable and a text
        # label sits alongside the ring instead (the collapsed pill).
        if self._diameter >= 40:
            p.setPen(theme.TEXT)
            big = QFont(theme.FONT_FAMILY)
            big.setPixelSize(int(self._diameter * 0.24))
            big.setBold(True)
            p.setFont(big)
            center = QRectF(0, 0, self._diameter, self._diameter)
            text = self._center_text or f"{int(round(self._display * 100))}%"
            p.drawText(center, Qt.AlignmentFlag.AlignCenter, text)

        if self._label:
            p.setPen(theme.TEXT_DIM)
            small = QFont(theme.FONT_FAMILY)
            small.setPixelSize(int(self._diameter * 0.12))
            p.setFont(small)
            lrect = QRectF(0, self._diameter * 0.60, self._diameter, self._diameter * 0.22)
            p.drawText(lrect, Qt.AlignmentFlag.AlignCenter, self._label)
