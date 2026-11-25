"""Видеовиджет с предпросмотром пониженного разрешения.

Предпросмотр выводится через Qt Quick: сцена рендерится бэкендом RHI,
который в ``trimmer.app`` переключён на Vulkan. QOpenGLWidget больше не
используется, поэтому весь путь отрисовки видео идёт через Vulkan.
"""

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtMultimedia import QVideoSink
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

_QML_FILE = Path(__file__).with_name("video_view.qml")


class _FrameImageProvider(QQuickImageProvider):
    """Отдаёт QML-картинке текущий кадр (скраббинг или низкое разрешение)."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._image = QImage()

    def set_image(self, image: QImage):
        self._image = image

    def requestImage(self, _image_id, _size, _requested_size):
        return self._image


class ClickableVideoWidget(QWidget):
    """Область предпросмотра на Qt Quick (Vulkan) с обработкой кликов."""

    def __init__(self, on_click, on_double_click):
        super().__init__()
        self.on_click = on_click
        self.on_double_click = on_double_click

        self._downscaled_frame_pix = None
        self.preview_pixmap = None
        self.preview_target_height = 0
        self._frame_seq = 0

        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background-color: #0D0D0D; border: none;")

        self._quick = QQuickWidget(self)
        self._quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._quick.setClearColor(QColor(13, 13, 13))
        self._quick.setFocusPolicy(Qt.NoFocus)
        self._quick.installEventFilter(self)

        self._image_provider = _FrameImageProvider()
        self._quick.engine().addImageProvider("trimmerframe", self._image_provider)
        self._quick.setSource(QUrl.fromLocalFile(str(_QML_FILE)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._quick)

        root = self._quick.rootObject()
        if root is None or self._quick.status() != QQuickWidget.Status.Ready:
            errors = "\n".join(err.toString() for err in self._quick.errors())
            raise RuntimeError(f"Не удалось загрузить video_view.qml:\n{errors}")

        self._qml_root = root
        self._video_output_item = root.findChild(QObject, "videoOutput")
        self._frame_item = root.findChild(QObject, "frameImage")

        # Полноразмерный вывод (VideoOutput внутри Qt Quick, рендер Vulkan).
        self.video_output = (
            self._video_output_item.property("videoSink")
            if self._video_output_item is not None
            else None
        )

        # Отдельный приёмник для режима пониженного разрешения: кадры
        # уменьшаются вручную и показываются через QML-картинку.
        self.video_sink = QVideoSink(self)
        self.video_sink.videoFrameChanged.connect(self._on_video_frame)

    @property
    def video_item(self):
        """Совместимый псевдоним вывода видео (раньше — QGraphicsVideoItem)."""
        return self.video_output

    # === [БЛОК 24: СОБЫТИЯ ВИДЕОВИДЖЕТА И ИНИЦИАЛИЗАЦИЯ ГЛАВНОГО ОКНА] ===
    def eventFilter(self, obj, event):
        if obj is self._quick:
            event_type = event.type()
            if event_type == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self.on_click()
            elif event_type == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self.on_double_click()
            elif event_type == QEvent.ContextMenu:
                handler = getattr(self, "on_context_menu", None)
                if callable(handler):
                    handler(event.globalPos())
                    return True
        return super().eventFilter(obj, event)

    def set_background_color(self, color):
        """Цвет фона области предпросмотра (под тему приложения)."""
        if isinstance(color, str):
            color = QColor(color)
        self._quick.setClearColor(color)
        self._qml_root.setProperty("backgroundColor", color)

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
        if self.preview_pixmap is None:
            self._show_frame_image(low_res, smooth=False)

    def _show_frame_image(self, image: QImage, smooth: bool = True):
        if self._frame_item is None:
            return
        self._frame_seq += 1
        self._image_provider.set_image(image)
        self._frame_item.setProperty("smooth", bool(smooth))
        self._frame_item.setProperty(
            "source", QUrl(f"image://trimmerframe/frame?{self._frame_seq}")
        )
        self._frame_item.setProperty("visible", True)
        if self._video_output_item is not None:
            self._video_output_item.setProperty("visible", False)

    def _show_video_output(self):
        if self._video_output_item is not None:
            self._video_output_item.setProperty("visible", True)
        if self._frame_item is not None:
            self._frame_item.setProperty("visible", False)
            self._frame_item.setProperty("source", QUrl())

    def _refresh_display(self):
        if self.preview_pixmap is not None and not self.preview_pixmap.isNull():
            self._show_frame_image(
                self.preview_pixmap.toImage(),
                smooth=self.preview_target_height == 0,
            )
        elif (
            self.preview_target_height > 0
            and self._downscaled_frame_pix is not None
            and not self._downscaled_frame_pix.isNull()
        ):
            self._show_frame_image(self._downscaled_frame_pix.toImage(), smooth=False)
        else:
            self._show_video_output()

    def set_preview_resolution(self, target_h: int):
        self.preview_target_height = target_h
        if target_h <= 0:
            self._downscaled_frame_pix = None
        self._refresh_display()

    def set_scrub_frame(self, pix: QPixmap):
        self.preview_pixmap = pix
        self._refresh_display()

    def clear_scrub_frame(self):
        if self.preview_pixmap is not None:
            self.preview_pixmap = None
            self._refresh_display()
