"""Интеграция «Медиа Обрезчик» в контекстное меню Windows."""

import sys
from pathlib import Path

from trimmer.constants import AUDIO_EXTS, ENTRY_SCRIPT, VIDEO_EXTS

if sys.platform == "win32":
    import winreg


# === [БЛОК 5: КОНТЕКСТНОЕ МЕНЮ WINDOWS И ОБНОВЛЕНИЯ GITHUB] ===
def register_context_menu(enable: bool):
    if sys.platform != "win32":
        return
    py_exe = Path(sys.executable)
    pythonw = py_exe.with_name("pythonw.exe")
    runner = str(pythonw) if pythonw.exists() else str(py_exe)
    script_path = ENTRY_SCRIPT
    launcher_cmd = script_path.parent / "Медиа Обрезчик.cmd"

    app_key = r"Software\Classes\Applications\MediaTrimmerLauncher.cmd"
    all_exts = sorted(VIDEO_EXTS | AUDIO_EXTS)

    try:
        if enable:
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
