"""Programmatic app icon — a terracotta usage ring on a dark rounded tile.

Rendered in code (no image file) so the tray icon works identically whether we
run from source or from the frozen one-file exe, with nothing to bundle or locate
on disk. ``tools/make_icon.py`` reuses ``render_image`` to emit ``assets/icon.ico``
for the EXE/Explorer icon.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap


def render_image(size: int, fraction: float = 0.68) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    pad = size * 0.06
    tile = QRectF(pad, pad, size - 2 * pad, size - 2 * pad)
    path = QPainterPath()
    path.addRoundedRect(tile, size * 0.22, size * 0.22)
    p.fillPath(path, QColor(24, 26, 30))

    thick = max(1.0, size * 0.10)
    m = size * 0.26
    ring = QRectF(m, m, size - 2 * m, size - 2 * m)
    track = QPen(QColor(255, 255, 255, 40), thick)
    track.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(track)
    p.drawArc(ring, 0, 360 * 16)
    prog = QPen(QColor(217, 119, 87), thick)  # terracotta
    prog.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(prog)
    p.drawArc(ring, 90 * 16, -int(fraction * 360 * 16))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(236, 238, 242))
    r = size * 0.05
    p.drawEllipse(QRectF(size / 2 - r, size / 2 - r, 2 * r, 2 * r))
    p.end()
    return img


def app_qicon() -> QIcon:
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(render_image(s)))
    return icon
