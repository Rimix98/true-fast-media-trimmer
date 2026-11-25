"""Быстрая подготовка кадра предпросмотра вне GUI-потока.

Qt отдаёт кадры в NV12 (CPU-память). Полный YUV->RGB на 4K занимает ~24 мс
и раньше выполнялся в GUI-потоке, из-за чего предпросмотр дёргался. Здесь
кадр уменьшается прямо при выборке пикселей (nearest), поэтому на 4K это
~3 мс, а сама работа уходит в отдельный поток: важен последний кадр, а не
все подряд.
"""

import numpy as np
from PySide6.QtCore import QMutex, QMutexLocker, Qt, QThread, QWaitCondition, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QVideoFrame, QVideoFrameFormat

_NV12 = QVideoFrameFormat.PixelFormat.Format_NV12


def preview_size(width: int, height: int, target_h: int) -> tuple:
    """Размер кадра предпросмотра при заданной высоте (чётные стороны)."""
    width = max(2, width)
    height = max(2, height)
    th = min(height, max(2, target_h))
    tw = max(2, round(th * width / height))
    return tw - (tw % 2), th - (th % 2)


def _nv12_to_rgb(frame, tw: int, th: int) -> QImage:
    """NV12 -> RGBX8888 сразу в размере предпросмотра (без полного RGB)."""
    width, height = frame.width(), frame.height()
    y_stride = frame.bytesPerLine(0)
    uv_stride = frame.bytesPerLine(1)
    y_plane = np.frombuffer(frame.bits(0), np.uint8, y_stride * height).reshape(
        height, y_stride
    )
    uv_plane = np.frombuffer(frame.bits(1), np.uint8, uv_stride * (height // 2)).reshape(
        height // 2, uv_stride
    )

    ys = (np.arange(th, dtype=np.int64) * height) // th
    xs = (np.arange(tw, dtype=np.int64) * width) // tw
    cys = (np.arange(th, dtype=np.int64) * (height // 2)) // th
    cxs = (np.arange(tw, dtype=np.int64) * (width // 2)) // tw

    y = y_plane[np.ix_(ys, xs)].astype(np.float32)
    u = uv_plane[np.ix_(cys, 2 * cxs)].astype(np.float32) - 128.0
    v = uv_plane[np.ix_(cys, 2 * cxs + 1)].astype(np.float32) - 128.0

    rgba = np.empty((th, tw, 4), dtype=np.uint8)
    rgba[..., 0] = np.clip(y + 1.402 * v, 0.0, 255.0).astype(np.uint8)
    rgba[..., 1] = np.clip(y - 0.344136 * u - 0.714136 * v, 0.0, 255.0).astype(
        np.uint8
    )
    rgba[..., 2] = np.clip(y + 1.772 * u, 0.0, 255.0).astype(np.uint8)
    rgba[..., 3] = 255
    return QImage(rgba.data, tw, th, tw * 4, QImage.Format_RGBX8888).copy()


def convert_frame(frame, target_h: int) -> QImage:
    """Кадр QVideoFrame -> уменьшенный QImage (NV12 быстро, остальное запасным путём)."""
    if not frame.isValid() or target_h <= 0:
        return QImage()
    width, height = frame.width(), frame.height()
    if width <= 0 or height <= 0:
        return QImage()
    tw, th = preview_size(width, height, target_h)

    if (
        width % 2 == 0
        and height % 2 == 0
        and frame.pixelFormat() == _NV12
        and frame.handleType() == QVideoFrame.HandleType.NoHandle
        and frame.map(QVideoFrame.MapMode.ReadOnly)
    ):
        try:
            image = _nv12_to_rgb(frame, tw, th)
        finally:
            frame.unmap()
        if not image.isNull():
            return image

    image = frame.toImage()
    if image.isNull():
        return QImage()
    return image.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.FastTransformation)


class PreviewFrameConverter(QThread):
    """Однопоточный конвертер: в очереди всегда только последний кадр."""

    scaled = Signal(int, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._wait = QWaitCondition()
        self._frame = None
        self._generation = 0
        self._target_h = 0
        self._running = True

    def submit(self, frame, generation: int, target_h: int):
        with QMutexLocker(self._mutex):
            self._frame = frame
            self._generation = generation
            self._target_h = target_h
            self._wait.wakeOne()

    def stop(self):
        with QMutexLocker(self._mutex):
            self._running = False
            self._frame = None
            self._wait.wakeOne()
        self.wait(2000)

    def run(self):
        while True:
            with QMutexLocker(self._mutex):
                while self._running and self._frame is None:
                    self._wait.wait(self._mutex)
                if not self._running:
                    return
                frame = self._frame
                generation = self._generation
                target_h = self._target_h
                self._frame = None

            try:
                image = convert_frame(frame, target_h)
            except Exception:  # noqa: BLE001 — битый кадр не должен убивать поток
                image = QImage()
            if not image.isNull():
                self.scaled.emit(generation, image)
