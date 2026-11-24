"""Создание QApplication и главного окна, передача файла из аргументов командной строки."""

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from trimmer.main_window import MediaTrimmerWindow


def run_app() -> int:
    app = QApplication(sys.argv)
    win = MediaTrimmerWindow()
    win.show()

    first_arg = next(iter(sys.argv[1:]), "")
    if first_arg:
        arg_path = Path(first_arg)
        if arg_path.exists() and arg_path.is_file():
            QTimer.singleShot(100, lambda: win._open_media_path(str(arg_path)))

    return app.exec()
