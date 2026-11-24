"""Ползунок перемотки: клик в любое место и покадровая точность."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSlider


# === [БЛОК 9: ПОЛЗУНОК ПЕРЕМОТКИ С КЛИКОМ В ЛЮБОЕ МЕСТО И ПОКАДРОВОЙ ТОЧНОСТЬЮ] ===
class ClickableSeekSlider(QSlider):
    seek_requested = Signal(float)
    zoom_wheel_requested = Signal(int, float)

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.setRange(0, 1000000)
        self.is_dragging = False
        self.setCursor(Qt.PointingHandCursor)

    def _pos_to_ratio(self, x: float) -> float:
        pad = 14
        tw = max(1, self.width() - pad * 2)
        return max(0.0, min(1.0, (x - pad) / tw))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = 1 if event.angleDelta().y() > 0 else -1
            ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            self.zoom_wheel_requested.emit(delta, ratio)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            ratio = self._pos_to_ratio(event.position().x())
            self.setValue(int(ratio * 1000000))
            self.seek_requested.emit(ratio)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            ratio = self._pos_to_ratio(event.position().x())
            self.setValue(int(ratio * 1000000))
            self.seek_requested.emit(ratio)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_dragging:
            ratio = self._pos_to_ratio(event.position().x())
            self.setValue(int(ratio * 1000000))
            self.is_dragging = False
            self.seek_requested.emit(ratio)
            event.accept()
        else:
            super().mouseReleaseEvent(event)
