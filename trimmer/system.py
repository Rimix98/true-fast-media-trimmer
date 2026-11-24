"""Системные функции Windows, дБ-подписи и выбор аппаратного кодировщика."""

import ctypes
import subprocess
import sys

from PySide6.QtWidgets import QWidget

from trimmer.constants import FFMPEG_BIN, MUTE_DB_VAL


# === [БЛОК 4: СИСТЕМНЫЕ ФУНКЦИИ WINDOWS И ЭНКОДЕР] ===
def set_windows_titlebar_theme(widget: QWidget, is_dark: bool):
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        val = ctypes.c_int(1 if is_dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(val), ctypes.sizeof(val)
        )
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 19, ctypes.byref(val), ctypes.sizeof(val)
        )
    except Exception:
        pass


def set_console_visible(visible: bool):
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return
        root_hwnd = ctypes.windll.user32.GetAncestor(hwnd, 3) or hwnd
        cmd_show = 5 if visible else 0
        ctypes.windll.user32.ShowWindow(hwnd, cmd_show)
        if root_hwnd != hwnd:
            ctypes.windll.user32.ShowWindow(root_hwnd, cmd_show)
    except Exception:
        pass


def format_db_label(raw_val: int) -> str:
    if raw_val <= MUTE_DB_VAL:
        return "-∞ dB"
    db = raw_val / 10.0
    if db > 0:
        return f"+{db:.1f} dB"
    return f"{db:.1f} dB"


def detect_best_video_encoder() -> str:
    flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    candidates = [
        ("h264_nvenc", ["-preset", "p1"]),
        ("h264_amf", ["-quality", "speed"]),
        ("h264_qsv", ["-preset", "veryfast"]),
    ]
    for codec, extra in candidates:
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=640x360:d=0.1",
            "-c:v",
            codec,
            *extra,
            "-f",
            "null",
            "-",
        ]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                timeout=8,
            )
            if res.returncode == 0:
                return codec
        except Exception:
            pass
    return "libx264"


BEST_GPU_ENCODER = detect_best_video_encoder()
