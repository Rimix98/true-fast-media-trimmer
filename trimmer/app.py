"""Создание QApplication и главного окна, передача файла из аргументов командной строки."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication

from trimmer.main_window import MediaTrimmerWindow


def _enable_vulkan_rendering():
    """Переключает рендеринг Qt Quick (видеопредпросмотр) на Vulkan.

    Значение по умолчанию — Vulkan. Для отладки/совместимости его можно
    переопределить переменной окружения ``TRIMMER_GRAPHICS_API=opengl``.
    """
    backend = os.environ.get("TRIMMER_GRAPHICS_API", "vulkan").strip().lower()
    if backend in ("opengl", "gl"):
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    else:
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Vulkan)


def run_app() -> int:
    _enable_vulkan_rendering()
    app = QApplication(sys.argv)
    win = MediaTrimmerWindow()
    win.show()

    first_arg = next(iter(sys.argv[1:]), "")
    if first_arg:
        arg_path = Path(first_arg)
        if arg_path.exists() and arg_path.is_file():
            QTimer.singleShot(100, lambda: win._open_media_path(str(arg_path)))

    return app.exec()
