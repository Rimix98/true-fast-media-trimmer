#!/usr/bin/env python3
"""Генерирует packaging/media_trimmer.png и packaging/media_trimmer.ico.

Запускать только при смене логотипа:
    python packaging/make_icon.py   (нужны PySide6 и Pillow)
"""

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath

HERE = Path(__file__).resolve().parent
SIZE = 256
ACCENT = "#FF9900"  # акцентный цвет приложения (см. trimmer/settings.py)


def make_image() -> QImage:
    img = QImage(SIZE, SIZE, QImage.Format_RGBA8888)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)

    # фон — скруглённый квадрат
    bg = QPainterPath()
    bg.addRoundedRect(QRectF(0, 0, SIZE, SIZE), 56, 56)
    p.fillPath(bg, QColor("#1E1E1E"))

    # маркеры обрезки слева и справа
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(ACCENT)))
    p.drawRoundedRect(QRectF(44, 44, 26, 168), 12, 12)
    p.drawRoundedRect(QRectF(186, 44, 26, 168), 12, 12)

    # треугольник «воспроизведение» между маркерами
    tri = QPainterPath()
    tri.moveTo(100, 82)
    tri.lineTo(170, 128)
    tri.lineTo(100, 174)
    tri.closeSubpath()
    p.fillPath(tri, QColor("#FFFFFF"))

    p.end()
    return img


def main() -> int:
    img = make_image()
    png = HERE / "media_trimmer.png"
    if not img.save(str(png)):
        print(f"Не удалось сохранить {png}", file=sys.stderr)
        return 1

    try:
        from PIL import Image
    except ImportError:
        print("Pillow не установлен — .ico не создан (PNG готов:)")
        return 0

    pil = Image.open(png).convert("RGBA")
    pil.save(
        HERE / "media_trimmer.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Готово: {png} и {HERE / 'media_trimmer.ico'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
