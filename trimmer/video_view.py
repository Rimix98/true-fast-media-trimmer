"""Видеовиджет с предпросмотром пониженного разрешения.

Предпросмотр выводится через Qt Quick: сцена рендерится бэкендом RHI,
который в ``trimmer.app`` переключён на Vulkan. QOpenGLWidget больше не
используется, поэтому весь путь отрисовки видео идёт через Vulkan.

Кадры пониженного разрешения готовятся в отдельном потоке
(``trimmer.preview_convert``) и приходят в QML уже готовым QImage — без
QPixmap и лишних копий.
"""

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QUrl
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtMultimedia import QVideoFrame, QVideoSink
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget

from trimmer.preview_convert import PreviewFrameConverter, convert_frame

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

        self._downscaled_frame_img = QImage()
        self.preview_image = QImage()
        self.preview_target_height = 0
        self._frame_seq = 0
        self._preview_generation = 0
        self._last_shown_key = None

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
        # уменьшаются в фоновом потоке и показываются через QML-картинку.
        self.video_sink = QVideoSink(self)
        self.video_sink.videoFrameChanged.connect(self._on_video_frame)
        self._converter = PreviewFrameConverter(self)
        self._converter.scaled.connect(self._on_preview_scaled)
        self._converter.start()

    @property
    def video_item(self):
        """Совместимый псевдоним вывода видео (раньше — QGraphicsVideoItem)."""
        return self.video_output

    def shutdown(self):
        """Останавливает фоновый конвертер перед закрытием окна."""
        self._converter.stop()

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
        # Конвертируем только то, что реально покажем: при скрытом виджете
        # или поверх кадра скраббинга работа была бы впустую.
        if (
            self.preview_target_height <= 0
            or not frame.isValid()
            or not self._quick.isVisible()
            or not self.preview_image.isNull()
        ):
            return

        self._preview_generation += 1
        if frame.handleType() == QVideoFrame.HandleType.NoHandle:
            self._converter.submit(
                frame, self._preview_generation, self.preview_target_height
            )
        else:
            # GPU-кадр нельзя читать из чужого потока — конвертируем здесь.
            self._on_preview_scaled(
                self._preview_generation,
                convert_frame(frame, self.preview_target_height),
            )

    def _on_preview_scaled(self, generation: int, image: QImage):
        if (
            self.preview_target_height <= 0
            or generation < self._preview_generation
            or image.isNull()
        ):
            return  # режим уже сменился или кадр устарел, пока конвертировался
        self._downscaled_frame_img = image
        if self.preview_image.isNull():
            self._show_frame_image(image, smooth=False)

    def _show_frame_image(self, image: QImage, smooth: bool = True):
        if self._frame_item is None or image.isNull():
            return
        key = (image.cacheKey(), bool(smooth))
        if key == self._last_shown_key and self._frame_item.property("visible"):
            return  # тот же кадр уже на экране — не перезагружаем текстуру
        self._last_shown_key = key
        self._frame_seq += 1
        self._image_provider.set_image(image)
        if bool(self._frame_item.property("smooth")) != bool(smooth):
            self._frame_item.setProperty("smooth", bool(smooth))
        self._frame_item.setProperty(
            "source", QUrl(f"image://trimmerframe/frame?{self._frame_seq}")
        )
        if not self._frame_item.property("visible"):
            self._frame_item.setProperty("visible", True)
        if self._video_output_item is not None and self._video_output_item.property(
            "visible"
        ):
            self._video_output_item.setProperty("visible", False)

    def _show_video_output(self):
        self._last_shown_key = None
        if self._video_output_item is not None:
            self._video_output_item.setProperty("visible", True)
        if self._frame_item is not None:
            self._frame_item.setProperty("visible", False)
            self._frame_item.setProperty("source", QUrl())

    def _refresh_display(self):
        if not self.preview_image.isNull():
            self._show_frame_image(
                self.preview_image,
                smooth=self.preview_target_height == 0,
            )
        elif self.preview_target_height > 0 and not self._downscaled_frame_img.isNull():
            self._show_frame_image(self._downscaled_frame_img, smooth=False)
        else:
            self._show_video_output()

    def set_preview_resolution(self, target_h: int):
        self.preview_target_height = target_h
        self._preview_generation += 1
        if target_h <= 0:
            self._downscaled_frame_img = QImage()
        self._refresh_display()

    def set_scrub_frame(self, image):
        if isinstance(image, QPixmap):
            image = image.toImage()
        self.preview_image = image
        self._refresh_display()

    def clear_scrub_frame(self):
        if not self.preview_image.isNull():
            self.preview_image = QImage()
            self._refresh_display()
