"""Настройки по умолчанию, палитры темы, загрузка и сохранение."""

import json

from PySide6.QtGui import QColor

from trimmer.constants import SCRIPT_DIR, SETTINGS_FILE

# === [БЛОК 3: ПАЛИТРА И НАСТРОЙКИ ПО УМОЛЧАНИЮ] ===
PALETTE_LIGHT = ["#FF9900", "#3B82F6", "#10B981", "#EF4444", "#A855F7"]
PALETTE_DARK = ["#C26A00", "#1D4ED8", "#047857", "#B91C1C"]

DEFAULT_SETTINGS = {
    "accent": "#FF9900",
    "dark_mode": True,
    "default_dir": str(SCRIPT_DIR),
    "last_export_dir": str(SCRIPT_DIR),
    "open_last_dir": True,
    "sync_seek_with_trim": False,
    "scrub_audio": False,
    "show_console": False,
    "context_menu": False,
    "preload_frames_dialog": False,
    "scrub_resolution": "360p",
}


def load_app_settings() -> dict:
    data = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception:
            pass
    return data


def save_app_settings(data: dict):
    try:
        SETTINGS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def get_contrast_text_color(hex_color: str) -> str:
    c = QColor(hex_color)
    luminance = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return "#111111" if luminance > 140 else "#FFFFFF"
