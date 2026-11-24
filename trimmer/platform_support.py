"""Платформо-зависимый код: Windows API (ctypes/winreg) и флаги процессов.

Здесь собрано всё, что работает только на Windows (или требует
специфичных флагов subprocess). На Linux/macOS функции-обёртки —
безопасные no-op, а флаги процессов равны 0, поэтому остальной код
приложения платформо-независим.
"""

import ctypes
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from trimmer.constants import AUDIO_EXTS, ENTRY_SCRIPT, VIDEO_EXTS

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

IS_WINDOWS = sys.platform == "win32"


# === [БЛОК: ФЛАГИ ЗАПУСКА ПОДПРОЦЕССОВ] ===
# На Windows subprocess экспортирует константы CREATE_NO_WINDOW и
# BELOW_NORMAL_PRIORITY_CLASS. На POSIX их нет, а ненулевой creationflags
# там вызывает ValueError в subprocess — поэтому всегда возвращаем 0.
_NO_WINDOW_FLAG = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_BELOW_NORMAL_FLAG = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


def subprocess_flags(low_priority: bool = False) -> int:
    """Флаги creationflags: скрытое окно консоли (и низкий приоритет).

    На не-Windows платформах возвращает 0 — значение безопасно передавать
    в subprocess.run/Popen на любой платформе.
    """
    flags = _NO_WINDOW_FLAG
    if low_priority:
        flags |= _BELOW_NORMAL_FLAG
    return flags


# === [БЛОК: WINDOWS API — ЗАГОЛОВОК ОКНА И КОНСОЛЬ] ===
def set_windows_titlebar_theme(widget: "QWidget", is_dark: bool):
    """Тёмная/светлая тема заголовка окна (Windows 10 1809+)."""
    if not IS_WINDOWS:
        return
    try:
        hwnd = int(widget.winId())
        val = ctypes.c_int(1 if is_dark else 0)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE, 19 = прежнее имя атрибута
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(val), ctypes.sizeof(val)
        )
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 19, ctypes.byref(val), ctypes.sizeof(val)
        )
    except Exception:
        pass


def set_console_visible(visible: bool):
    """Показать/скрыть окно консоли программы (только Windows)."""
    if not IS_WINDOWS:
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


# === [БЛОК: КОНТЕКСТНОЕ МЕНЮ WINDOWS] ===
def register_context_menu(enable: bool):
    """Интеграция «Медиа Обрезчик» в меню «Открыть с помощью» (Windows)."""
    if not IS_WINDOWS:
        return
    import winreg  # модуль есть только на Windows

    py_exe = Path(sys.executable)
    pythonw = py_exe.with_name("pythonw.exe")
    runner = str(pythonw) if pythonw.exists() else str(py_exe)
    script_path = ENTRY_SCRIPT
    launcher_cmd = script_path.parent / "Медиа Обрезчик.cmd"

    app_key = r"Software\Classes\Applications\MediaTrimmerLauncher.cmd"
    all_exts = sorted(VIDEO_EXTS | AUDIO_EXTS)

    try:
        if enable:
            # лаунчер для cmd.exe: кодировка OEM (cp866) — тоже только Windows
            launcher_cmd.write_text(
                f'@echo off\r\nstart "" "{runner}" "{script_path}" %*\r\n',
                encoding="cp866",
            )
            cmd_str = f'"{launcher_cmd}" "%1"'

            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, app_key) as k:
                winreg.SetValueEx(
                    k, "FriendlyAppName", 0, winreg.REG_SZ, "Медиа Обрезчик"
                )
            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER, rf"{app_key}\DefaultIcon"
            ) as ik:
                winreg.SetValueEx(ik, "", 0, winreg.REG_SZ, f'"{runner}",0')
            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER, rf"{app_key}\shell\open\command"
            ) as ck:
                winreg.SetValueEx(ck, "", 0, winreg.REG_SZ, cmd_str)

            for ext in all_exts:
                ext_key = (
                    rf"Software\Classes\.{ext}\OpenWithList\MediaTrimmerLauncher.cmd"
                )
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, ext_key):
                    pass
        else:
            launcher_cmd.unlink(missing_ok=True)
            for sub in (
                r"shell\open\command",
                r"shell\open",
                "shell",
                "DefaultIcon",
                "",
            ):
                try:
                    target = rf"{app_key}\{sub}".rstrip("\\")
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, target)
                except Exception:
                    pass
            for ext in all_exts:
                try:
                    winreg.DeleteKey(
                        winreg.HKEY_CURRENT_USER,
                        rf"Software\Classes\.{ext}\OpenWithList\MediaTrimmerLauncher.cmd",
                    )
                except Exception:
                    pass
    except Exception:
        pass
