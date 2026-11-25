# -*- mode: python ; coding: utf-8 -*-
"""Спецификация PyInstaller для «Медиа Обрезчик».

Один spec и для Windows-exe, и для AppImage:
- `MEDIA_TRIMMER_ONEFILE=1` — один файл MediaTrimmer.exe (Windows);
- без переменной — каталог onedir (основа для AppImage).
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

SPEC_DIR = Path(SPECPATH)
ROOT = SPEC_DIR.parent
APP_NAME = "MediaTrimmer"
ONEFILE = os.environ.get("MEDIA_TRIMMER_ONEFILE", "") == "1"

ICON_ICO = SPEC_DIR / "media_trimmer.ico"

# imageio_ffmpeg держит бинарник ffmpeg внутри пакета — собираем вручную,
# иначе в сборке не окажется FFMPEG_BIN.
ffmpeg_datas, ffmpeg_binaries, ffmpeg_hidden = collect_all("imageio_ffmpeg")

# QML-модули, нужные видеопредпросмотру (Qt Quick + Qt Multimedia).
qml_datas = collect_data_files(
    "PySide6",
    includes=[
        "Qt/qml/QtCore/**",
        "Qt/qml/QtQml/**",
        "Qt/qml/QtQuick/**",
        "Qt/qml/QtMultimedia/**",
    ],
)

app_datas = [(str(ROOT / "trimmer" / "video_view.qml"), "trimmer")] + qml_datas

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=ffmpeg_binaries,
    datas=app_datas + ffmpeg_datas,
    hiddenimports=ffmpeg_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

icon = str(ICON_ICO) if ICON_ICO.is_file() else None

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
