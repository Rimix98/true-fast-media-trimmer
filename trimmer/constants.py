"""Базовые константы приложения: FFMpeg, версия, пути, форматы, дБ."""

import shutil
from pathlib import Path

try:
    import imageio_ffmpeg

    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_BIN = "ffmpeg"


def _find_ffprobe():
    """ffprobe для быстрого чтения метаданных (если он есть в системе)."""
    exe_name = "ffprobe.exe" if FFMPEG_BIN.lower().endswith(".exe") else "ffprobe"
    try:
        sibling = Path(FFMPEG_BIN).resolve().parent / exe_name
        if sibling.is_file():
            return str(sibling)
    except Exception:
        pass
    return shutil.which("ffprobe")


FFPROBE_BIN = _find_ffprobe()

APP_VERSION = "1.0.2"
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/Rimix98/true-fast-media-trimmer/refs/heads/main/version.txt"
GITHUB_SCRIPT_URL = "https://raw.githubusercontent.com/Rimix98/true-fast-media-trimmer/refs/heads/main/fast-media-trimmer.py"

SCRIPT_DIR = Path(__file__).resolve().parent.parent  # корень репозитория (каталог пакета)
ENTRY_SCRIPT = SCRIPT_DIR / "main.py"  # скрипт-лаунчер, запускающий пакет
SETTINGS_FILE = SCRIPT_DIR / "trimmer_settings.json"
AUDIO_EXTS = {"mp3", "ogg", "wav", "flac", "aac", "m4a", "wma", "opus"}
VIDEO_EXTS = {"mp4", "mkv", "avi", "mov", "webm", "flv", "wmv"}
VIDEO_FORMATS = ["mp4", "mkv", "mov", "webm", "avi", "gif"]
AUDIO_FORMATS = ["mp3", "wav", "ogg", "flac", "aac", "m4a"]
MUTE_DB_VAL = -1005
MAX_DB_VAL = 240
