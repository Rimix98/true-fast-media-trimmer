"""Виджет аудиоволны с отображением зон обрезки."""

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


# === [БЛОК 10: ВИДЖЕТ АУДИОВОЛНЫ] ===
class AudioWaveformWidget(QWidget):
    zoom_wheel_requested = Signal(int, float)

    def __init__(self, on_seek):
        super().__init__()
        self.on_seek = on_seek
        self.pcm_cache = None
        self.wave_pixmap = None
        self.accent_color = "#FF9900"
        self.dark_mode = True
        self.duration = 0.0
        self.current_pos = 0.0
        self.start_trim = 0.0
        self.end_trim = 0.0
        self.setCursor(Qt.PointingHandCursor)

    def set_theme(self, accent: str, dark_mode: bool):
        self.accent_color = accent
        self.dark_mode = dark_mode
        if self.pcm_cache is not None:
            self.set_waveform(self.pcm_cache)
        else:
            self.update()

    def set_waveform(self, pcm_data: np.ndarray):
        self.pcm_cache = pcm_data
        w, h = 2400, 360
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        arr[:] = (15, 15, 15) if self.dark_mode else (235, 235, 238)

        c = QColor(self.accent_color)
        r, g, b = c.red(), c.green(), c.blue()
        r_hi, g_hi, b_hi = min(255, r + 45), min(255, g + 45), min(255, b + 45)

        if len(pcm_data) > 0:
            chunks = np.array_split(np.abs(pcm_data.astype(np.float32)), w)
            peaks = np.array([ch.max() if len(ch) > 0 else 0 for ch in chunks])
            max_val = peaks.max() or 1.0
            heights = (peaks / max_val) * (h * 0.85)
            cy = h // 2
            for x in range(w):
                bh = int(heights.item(x) // 2)
                if bh > 0:
                    arr[cy - bh : cy + bh, x] = (r, g, b)
                    ih = int(bh * 0.55)
                    arr[cy - ih : cy + ih, x] = (r_hi, g_hi, b_hi)
        qimg = QImage(arr.data, w, h, w * 3, QImage.Format_RGB888)
        self.wave_pixmap = QPixmap.fromImage(qimg.copy())
        self.update()

    # === [БЛОК 11: ОТРИСОВКА И УПРАВЛЕНИЕ АУДИОВОЛНОЙ] ===
    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        painter.fillRect(
            0, 0, w, h, QColor(13, 13, 13) if self.dark_mode else QColor(235, 235, 238)
        )
        if self.wave_pixmap:
            painter.drawPixmap(0, 0, w, h, self.wave_pixmap)
        if self.duration > 0:
            x1 = int((self.start_trim / self.duration) * w)
            x2 = int((self.end_trim / self.duration) * w)
            shade = QColor(0, 0, 0, 150) if self.dark_mode else QColor(0, 0, 0, 85)
            painter.fillRect(0, 0, x1, h, shade)
            painter.fillRect(x2, 0, w - x2, h, shade)
            xc = int((self.current_pos / self.duration) * w)
            cur_pen = QColor(255, 255, 255) if self.dark_mode else QColor(20, 20, 20)
            painter.setPen(QPen(cur_pen, 2))
            painter.drawLine(xc, 0, xc, h)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = 1 if event.angleDelta().y() > 0 else -1
            ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            self.zoom_wheel_requested.emit(delta, ratio)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        self._handle_mouse(event.position().x(), False)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._handle_mouse(event.position().x(), False)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._handle_mouse(event.position().x(), True)

    def _handle_mouse(self, x, immediate):
        if self.duration > 0 and self.width() > 0:
            ratio = max(0.0, min(1.0, x / self.width()))
            self.on_seek(ratio * self.duration, immediate)
