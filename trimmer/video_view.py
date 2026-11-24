"""Видеовиджет с предпросмотром пониженного разрешения."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtMultimedia import QVideoSink
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView


class ClickableVideoWidget(QGraphicsView):
    def __init__(self, on_click, on_double_click):
        try:
            self.setViewport(QOpenGLWidget())
        except Exception:
            pass

        super().__init__()
        self.on_click = on_click
        self.on_double_click = on_double_click
        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background-color: #0D0D0D; border: none;")

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.video_item = QGraphicsVideoItem()
        self.scene.addItem(self.video_item)

        self.video_sink = QVideoSink(self)
        self.video_sink.videoFrameChanged.connect(self._on_video_frame)
        self._downscaled_frame_pix = None

        self.preview_pixmap = None
        self.preview_target_height = 0

    def _on_video_frame(self, frame):
        if self.preview_target_height <= 0 or not frame.isValid():
            return
        qimg = frame.toImage()
        if qimg.isNull():
            return
        h = self.preview_target_height
        aspect = qimg.width() / max(1, qimg.height())
        w = max(16, int(round(h * aspect)))
        low_res = qimg.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        self._downscaled_frame_pix = QPixmap.fromImage(low_res)
        self.viewport().update()

    def set_preview_resolution(self, target_h: int):
        self.preview_target_height = target_h
        if target_h <= 0:
            self._downscaled_frame_pix = None
        self._apply_video_viewport_scale()
        self.viewport().update()

    def _apply_video_viewport_scale(self):
        rect = self.viewport().rect()
        self.scene.setSceneRect(0, 0, max(1, rect.width()), max(1, rect.height()))
        self.video_item.setSize(rect.size())

    def set_scrub_frame(self, pix: QPixmap):
        self.preview_pixmap = pix
        self.viewport().update()

    def clear_scrub_frame(self):
        if self.preview_pixmap is not None:
            self.preview_pixmap = None
            self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        active_pix = None
        smooth = True

        if self.preview_pixmap is not None and not self.preview_pixmap.isNull():
            active_pix = self.preview_pixmap
            smooth = self.preview_target_height == 0
        elif (
            self.preview_target_height > 0
            and self._downscaled_frame_pix is not None
            and not self._downscaled_frame_pix.isNull()
        ):
            active_pix = self._downscaled_frame_pix
            smooth = False

        if active_pix is not None:
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
            vw, vh = self.viewport().width(), self.viewport().height()
            p.fillRect(0, 0, vw, vh, QColor(13, 13, 13))
            mode = Qt.SmoothTransformation if smooth else Qt.FastTransformation
            scaled = active_pix.scaled(vw, vh, Qt.KeepAspectRatio, mode)
            x = (vw - scaled.width()) // 2
            y = (vh - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)

    # === [БЛОК 24: СОБЫТИЯ ВИДЕОВИДЖЕТА И ИНИЦИАЛИЗАЦИЯ ГЛАВНОГО ОКНА] ===
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_video_viewport_scale()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_click()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_double_click()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        if hasattr(self, "on_context_menu") and callable(self.on_context_menu):
            self.on_context_menu(event.globalPos())
