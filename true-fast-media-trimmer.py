# === [БЛОК 1: АВТОУСТАНОВКА МОДУЛЕЙ И ИМПОРТЫ] ===
import ctypes
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# === [БЛОК 2: ИМПОРТЫ PYSIDE6, ВЕРСИЯ И КОНСТАНТЫ] ===
import numpy as np
from PySide6.QtCore import QIODevice, QRectF, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtMultimedia import (
    QAudio,
    QAudioFormat,
    QAudioOutput,
    QAudioSink,
    QMediaPlayer,
    QVideoSink,
)
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

if sys.platform == "win32":
    import winreg

try:
    import imageio_ffmpeg

    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_BIN = "ffmpeg"

APP_VERSION = "1.0.1"
GITHUB_VERSION_URL = "https://raw.githubusercontent.com/Rimix98/true-fast-media-trimmer/refs/heads/main/version.txt"
GITHUB_SCRIPT_URL = "https://raw.githubusercontent.com/Rimix98/true-fast-media-trimmer/refs/heads/main/fast-media-trimmer.py"

SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = SCRIPT_DIR / "trimmer_settings.json"
AUDIO_EXTS = {"mp3", "ogg", "wav", "flac", "aac", "m4a", "wma", "opus"}
VIDEO_EXTS = {"mp4", "mkv", "avi", "mov", "webm", "flv", "wmv"}
VIDEO_FORMATS = ["mp4", "mkv", "mov", "webm", "avi", "gif"]
AUDIO_FORMATS = ["mp3", "wav", "ogg", "flac", "aac", "m4a"]
MUTE_DB_VAL = -1005
MAX_DB_VAL = 240
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


# === [БЛОК 5: КОНТЕКСТНОЕ МЕНЮ WINDOWS И ОБНОВЛЕНИЯ GITHUB] ===
def register_context_menu(enable: bool):
    if sys.platform != "win32":
        return
    py_exe = Path(sys.executable)
    pythonw = py_exe.with_name("pythonw.exe")
    runner = str(pythonw) if pythonw.exists() else str(py_exe)
    script_path = Path(__file__).resolve()
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


def _parse_ver_tuple(ver_str: str) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", ver_str)]
    return tuple(nums) if nums else (0,)


def check_github_update() -> tuple:
    try:
        req = urllib.request.Request(
            GITHUB_VERSION_URL, headers={"User-Agent": "MediaTrimmerUpdater"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            remote_ver = resp.read().decode("utf-8", errors="ignore").strip()
        if not remote_ver or len(remote_ver) > 25:
            return False, "", "Некорректный формат файла version.txt на GitHub."
        return True, remote_ver, ""
    except Exception as e:
        return False, "", f"Не удалось подключиться к GitHub:\n{e}"


def download_and_restart_update() -> tuple:
    try:
        req = urllib.request.Request(
            GITHUB_SCRIPT_URL, headers={"User-Agent": "MediaTrimmerUpdater"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            new_code = resp.read().decode("utf-8")
        if "MediaTrimmerWindow" not in new_code:
            return False, "Скачанный файл повреждён или не является кодом программы."
        Path(__file__).resolve().write_text(new_code, encoding="utf-8")
        return True, ""
    except Exception as e:
        return False, f"Ошибка при скачивании обновления:\n{e}"


# === [БЛОК 6.1: ЭКСТРАКТОР КАДРОВ ДЛЯ СЕТКИ И СКРАББИНГА] ===
class FrameScrubWorker(QThread):
    frame_ready = Signal(int, int, QImage)
    batch_progress = Signal(int, int)

    def __init__(self, use_gpu: bool = True):
        super().__init__()
        self.use_gpu = use_gpu
        self.is_playing = False
        self.file_path = ""
        self.load_id = 0
        self.src_w = 1920
        self.src_h = 1080
        self.target_h = 360
        self.fps = 30.0
        self.urgent_queue = []
        self.single_queue = []
        self.bulk_job = None
        self.lock = threading.Lock()
        self.running = True
        self.track_progress = False
        self.total_tracked = 0
        self.done_tracked = 0

    def set_playback_active(self, is_playing: bool):
        with self.lock:
            self.is_playing = is_playing

    def configure(
        self,
        file_path: str,
        load_id: int,
        target_h: int,
        fps: float = 30.0,
        src_w: int = 1920,
        src_h: int = 1080,
    ):
        with self.lock:
            self.file_path = file_path
            self.load_id = load_id
            self.target_h = target_h
            self.fps = max(10.0, fps)
            self.src_w = max(16, src_w)
            self.src_h = max(16, src_h)
            self.urgent_queue.clear()
            self.single_queue.clear()
            self.bulk_job = None
            self.track_progress = False
            self.total_tracked = 0
            self.done_tracked = 0

    def update_anchor(self, _anchor_sec: float):
        pass

    def request_tiered_grid(
        self, total_dur_sec: float, _center_sec: float, track_initial: bool = False
    ):
        with self.lock:
            if not self.file_path or total_dur_sec <= 0.2:
                if track_initial:
                    self.batch_progress.emit(1, 1)
                return
            target_cnt = min(
                50, max(20, int(total_dur_sec / 180.0) if total_dur_sec > 3600 else 40)
            )
            step_sec = max(1.0, total_dur_sec / target_cnt)
            actual_cnt = max(1, int(total_dur_sec / step_sec))
            self.bulk_job = (total_dur_sec, step_sec, actual_cnt)
            if track_initial:
                self.track_progress = True
                self.total_tracked = actual_cnt
                self.done_tracked = 0

    def request_frames(self, sec_millis_list: list, high_priority: bool = True):
        with self.lock:
            if not self.file_path or not sec_millis_list:
                return
            if high_priority:
                self.urgent_queue = [next(iter(sec_millis_list))]
            else:
                self.single_queue = [next(iter(sec_millis_list))]

    def stop_worker(self):
        self.running = False
        with self.lock:
            self.urgent_queue.clear()
            self.single_queue.clear()
            self.bulk_job = None

    def _calc_out_size(self, cur_target_h: int, src_w: int, src_h: int) -> tuple:
        if cur_target_h <= 0 or cur_target_h >= src_h:
            w = (src_w // 2) * 2
            h = (src_h // 2) * 2
            return max(16, w), max(16, h)
        aspect = src_w / max(1, src_h)
        w = int(round((cur_target_h * aspect) / 2.0)) * 2
        h = (cur_target_h // 2) * 2
        return max(16, w), max(16, h)

    def _get_proc_flags_and_hw(self) -> tuple:
        no_win = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        below_norm = (
            0x00004000 if hasattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS") else 0
        )
        with self.lock:
            playing = self.is_playing
        if playing or not self.use_gpu:
            return (no_win | below_norm), ["-threads", "4"]
        return no_win, ["-hwaccel", "auto"]

    def _read_exact_bytes(self, pipe, num_bytes: int) -> bytes:
        chunks = []
        rem = num_bytes
        while rem > 0:
            part = pipe.read(rem)
            if not part:
                break
            chunks.append(part)
            rem -= len(part)
        return b"".join(chunks)

    def _run_urgent_20sec_strip(
        self, cur_file: str, cur_load: int, out_w: int, out_h: int, center_sec: float
    ):
        flags, hw_args = self._get_proc_flags_and_hw()
        target_fps = 12
        step_ms = int(round(1000.0 / target_fps))
        batch_start = max(0.0, center_sec - 10.0)
        span_sec = 20.0
        frame_bytes = out_w * out_h * 3
        cmd = [
            FFMPEG_BIN,
            "-loglevel",
            "quiet",
            *hw_args,
            "-ss",
            f"{batch_start:.3f}",
            "-i",
            cur_file,
            "-an",
            "-sn",
            "-dn",
            "-t",
            f"{span_sec:.3f}",
            "-vf",
            f"fps={target_fps},scale={out_w}:{out_h}:flags=fast_bilinear",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=frame_bytes * 2,
                creationflags=flags,
            )
            idx = 0
            max_frames = int(span_sec * target_fps) + 2
            while self.running and cur_load == self.load_id and idx < max_frames:
                with self.lock:
                    if self.urgent_queue:
                        break
                raw = self._read_exact_bytes(proc.stdout, frame_bytes)
                if len(raw) < frame_bytes:
                    break
                qimg = QImage(raw, out_w, out_h, out_w * 3, QImage.Format_RGB888).copy()
                if not qimg.isNull():
                    self.frame_ready.emit(
                        cur_load, int(round(batch_start * 1000)) + idx * step_ms, qimg
                    )
                idx += 1
            proc.kill()
            proc.wait(timeout=0.2)
        except Exception:
            pass

    # === [БЛОК 6.2: ЦИКЛ ПОТОКА КАДРОВ И ПОТОКОВЫЙ АУДИОДЕКОДЕР] ===
    def run(self):
        while self.running:
            with self.lock:
                cur_load = self.load_id
                cur_file = self.file_path
                cur_th = self.target_h
                sw, sh = self.src_w, self.src_h
                urgent_sm = None
                single_sm = None
                bulk_info = None

                if cur_file:
                    if self.urgent_queue:
                        urgent_sm = self.urgent_queue.pop(0)
                    elif self.single_queue:
                        single_sm = self.single_queue.pop(0)
                    elif self.bulk_job is not None:
                        bulk_info = self.bulk_job
                        self.bulk_job = None

            if not cur_file or (
                urgent_sm is None and single_sm is None and bulk_info is None
            ):
                self.msleep(8)
                continue

            out_w, out_h = self._calc_out_size(cur_th, sw, sh)

            if urgent_sm is not None:
                self._run_urgent_20sec_strip(
                    cur_file, cur_load, out_w, out_h, urgent_sm / 1000.0
                )
                continue

            if single_sm is not None:
                flags, hw_args = self._get_proc_flags_and_hw()
                frame_bytes = out_w * out_h * 3
                cmd = [
                    FFMPEG_BIN,
                    "-loglevel",
                    "quiet",
                    *hw_args,
                    "-ss",
                    f"{single_sm / 1000.0:.3f}",
                    "-i",
                    cur_file,
                    "-an",
                    "-sn",
                    "-dn",
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={out_w}:{out_h}:flags=fast_bilinear",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "pipe:1",
                ]
                try:
                    res = subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        creationflags=flags,
                        timeout=2.0,
                    )
                    if cur_load == self.load_id and len(res.stdout) >= frame_bytes:
                        qimg = QImage(
                            res.stdout[:frame_bytes],
                            out_w,
                            out_h,
                            out_w * 3,
                            QImage.Format_RGB888,
                        ).copy()
                        if not qimg.isNull():
                            self.frame_ready.emit(cur_load, single_sm, qimg)
                except Exception:
                    pass
                continue

            if bulk_info is not None:
                _dur, step_sec, actual_cnt = bulk_info
                flags, hw_args = self._get_proc_flags_and_hw()
                frame_bytes = out_w * out_h * 3
                out_fps = 1.0 / step_sec
                cmd = [
                    FFMPEG_BIN,
                    "-loglevel",
                    "quiet",
                    *hw_args,
                    "-skip_frame",
                    "nokey",
                    "-i",
                    cur_file,
                    "-an",
                    "-sn",
                    "-dn",
                    "-vf",
                    f"fps={out_fps:.6f},scale={out_w}:{out_h}:flags=fast_bilinear",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "pipe:1",
                ]
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        bufsize=frame_bytes * 2,
                        creationflags=flags,
                    )
                    idx = 0
                    while (
                        self.running and cur_load == self.load_id and idx < actual_cnt
                    ):
                        with self.lock:
                            if self.urgent_queue or self.single_queue:
                                self.bulk_job = (_dur, step_sec, actual_cnt)
                                break
                        raw = self._read_exact_bytes(proc.stdout, frame_bytes)
                        if len(raw) < frame_bytes:
                            break
                        qimg = QImage(
                            raw, out_w, out_h, out_w * 3, QImage.Format_RGB888
                        ).copy()
                        if not qimg.isNull():
                            self.frame_ready.emit(
                                cur_load, int(round(idx * step_sec * 1000)), qimg
                            )
                        idx += 1
                        with self.lock:
                            if self.track_progress and cur_load == self.load_id:
                                self.done_tracked = min(self.total_tracked, idx)
                                self.batch_progress.emit(
                                    self.done_tracked, self.total_tracked
                                )
                    proc.kill()
                    proc.wait(timeout=0.2)
                except Exception:
                    pass
                with self.lock:
                    if (
                        self.track_progress
                        and cur_load == self.load_id
                        and self.bulk_job is None
                    ):
                        self.batch_progress.emit(self.total_tracked, self.total_tracked)
                        self.track_progress = False


class GainAudioStream(QIODevice):
    def __init__(self, file_path: str, track_idx: int, sample_rate=32000, channels=2):
        super().__init__()
        self.file_path = file_path
        self.track_idx = track_idx
        self.sample_rate = sample_rate
        self.channels = channels
        self.gain = 1.0
        self.proc = None
        self.open(QIODevice.ReadOnly)

    def isSequential(self) -> bool:
        return True

    def bytesAvailable(self) -> int:
        return 8192 + super().bytesAvailable()

    def stop_proc(self):
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(timeout=0.2)
            except Exception:
                pass
            self.proc = None

    def set_position_sec(self, sec: float):
        self.stop_proc()
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        cmd = [
            FFMPEG_BIN,
            "-loglevel",
            "quiet",
            "-ss",
            f"{max(0.0, sec):.3f}",
            "-i",
            self.file_path,
            "-vn",
            "-sn",
            "-dn",
            "-map",
            f"0:a:{self.track_idx}",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            str(self.channels),
            "-ar",
            str(self.sample_rate),
            "pipe:1",
        ]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=4096,
                creationflags=flags,
            )
        except Exception:
            self.proc = None

    def close(self):
        self.stop_proc()
        super().close()

    def readData(self, maxlen: int) -> bytes:
        if self.proc is None or self.proc.stdout is None:
            return bytes(maxlen)
        raw = self.proc.stdout.read(maxlen)
        if not raw:
            return b""
        if self.gain <= 0.0001:
            return bytes(len(raw))
        if abs(self.gain - 1.0) < 0.005:
            return raw

        chunk = np.frombuffer(raw, dtype=np.int16)
        amplified = chunk.astype(np.float32) * self.gain
        if self.gain > 1.0:
            amplified = np.tanh(amplified / 32768.0) * 32767.0
        else:
            amplified = np.clip(amplified, -32768.0, 32767.0)
        return amplified.astype(np.int16).tobytes()


# === [БЛОК 7: ФОНОВЫЙ ПОТОК FFMPEG С РАСШИРЕННЫМ ЛОГОМ ОШИБОК] ===
class FFmpegTaskThread(QThread):
    progress_updated = Signal(int, str)
    finished_ok = Signal()
    finished_cancelled = Signal()
    finished_err = Signal(str)

    def __init__(self, cmd, total_duration_sec):
        super().__init__()
        self.cmd = cmd
        self.total_duration_sec = max(0.1, total_duration_sec)
        self.proc = None
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True
        if self.proc is not None:
            try:
                self.proc.kill()
            except Exception:
                pass

    def run(self):
        try:
            flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
            self.proc = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=flags,
            )
            start_t = time.time()
            time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
            last_lines = []
            for line in self.proc.stdout:
                if self.is_cancelled:
                    break
                clean_l = line.strip()
                if clean_l:
                    last_lines.append(clean_l)
                    if len(last_lines) > 10:
                        last_lines.pop(0)
                m = time_re.search(line)
                if m:
                    cur_sec = (
                        int(m.group(1)) * 3600
                        + int(m.group(2)) * 60
                        + float(m.group(3))
                    )
                    pct = min(
                        99, max(1, int((cur_sec / self.total_duration_sec) * 100))
                    )
                    elapsed = time.time() - start_t
                    if pct > 2 and elapsed > 0.4:
                        eta_sec = int((elapsed / pct) * (100 - pct))
                        mins, secs = divmod(max(0, eta_sec), 60)
                        eta_str = f"Осталось: ~{mins:02d}:{secs:02d}"
                    else:
                        eta_str = "Расчёт времени..."
                    self.progress_updated.emit(pct, eta_str)
            self.proc.wait()
            if self.is_cancelled:
                self.finished_cancelled.emit()
            elif self.proc.returncode == 0:
                self.progress_updated.emit(100, "Готово!")
                self.finished_ok.emit()
            else:
                err_detail = "\n".join(last_lines[-8:])
                self.finished_err.emit(f"Код {self.proc.returncode}:\n{err_detail}")
        except Exception as e:
            self.finished_cancelled.emit() if self.is_cancelled else self.finished_err.emit(
                str(e)
            )


# === [БЛОК 8: ДИАЛОГ ПРОГРЕСС-БАРА] ===
class ProgressDialog(QDialog):
    def __init__(
        self, parent, title_text: str, header_text: str, accent: str, dark_mode: bool
    ):
        super().__init__(parent)
        self.setWindowTitle(title_text)
        self.setFixedSize(380, 145)
        self.setModal(True)
        set_windows_titlebar_theme(self, dark_mode)

        bg = "#1E1E1E" if dark_mode else "#F4F4F5"
        fg = "#EEEEEE" if dark_mode else "#18181B"
        bar_bg = "#111111" if dark_mode else "#E4E4E7"
        self.setStyleSheet(f"background-color: {bg}; color: {fg}; font-family: Arial;")

        lay = QVBoxLayout(self)
        self.lbl_head = QLabel(header_text)
        self.lbl_head.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {accent};"
        )
        lay.addWidget(self.lbl_head)

        self.p_bar = QProgressBar()
        self.p_bar.setRange(0, 100)
        self.p_bar.setValue(0)
        self.p_bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid #555; border-radius: 4px; text-align: center; background: {bar_bg}; height: 20px; }}"
            f"QProgressBar::chunk {{ background-color: {accent}; }}"
        )
        lay.addWidget(self.p_bar)

        bottom_row = QHBoxLayout()
        self.lbl_eta = QLabel("Подготовка...")
        self.lbl_eta.setStyleSheet("font-size: 11px;")
        bottom_row.addWidget(self.lbl_eta, 1)

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setStyleSheet(
            "background-color: #B91C1C; color: #FFFFFF; padding: 5px 14px; border-radius: 3px; font-weight: bold;"
        )
        bottom_row.addWidget(self.btn_cancel)
        lay.addLayout(bottom_row)

    def update_state(self, pct: int, eta_text: str):
        self.p_bar.setValue(pct)
        self.lbl_eta.setText(eta_text)


# === [БЛОК 9: ПОЛЗУНОК ПЕРЕМОТКИ С КЛИКОМ В ЛЮБОЕ МЕСТО И ПОКАДРОВОЙ ТОЧНОСТЬЮ] ===
class ClickableSeekSlider(QSlider):
    seek_requested = Signal(float)
    zoom_wheel_requested = Signal(int, float)

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.setRange(0, 1000000)
        self.is_dragging = False
        self.setCursor(Qt.PointingHandCursor)

    def _pos_to_ratio(self, x: float) -> float:
        pad = 14
        tw = max(1, self.width() - pad * 2)
        return max(0.0, min(1.0, (x - pad) / tw))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = 1 if event.angleDelta().y() > 0 else -1
            ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            self.zoom_wheel_requested.emit(delta, ratio)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            ratio = self._pos_to_ratio(event.position().x())
            self.setValue(int(ratio * 1000000))
            self.seek_requested.emit(ratio)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            ratio = self._pos_to_ratio(event.position().x())
            self.setValue(int(ratio * 1000000))
            self.seek_requested.emit(ratio)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_dragging:
            ratio = self._pos_to_ratio(event.position().x())
            self.setValue(int(ratio * 1000000))
            self.is_dragging = False
            self.seek_requested.emit(ratio)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


# === [БЛОК 10: ВИДЖЕТ АУДИОВОЛНЫ] ===
class AudioWaveformWidget(QWidget):
    zoom_wheel_requested = Signal(int, float)

    def __init__(self, on_seek):
        super().__init__()
        self.on_seek = on_seek
        self.pcm_cache = None
        self.wave_pixmap = None
        self.accent_color = "#FF9900"
        self.dark_mode = True
        self.duration = 0.0
        self.current_pos = 0.0
        self.start_trim = 0.0
        self.end_trim = 0.0
        self.setCursor(Qt.PointingHandCursor)

    def set_theme(self, accent: str, dark_mode: bool):
        self.accent_color = accent
        self.dark_mode = dark_mode
        if self.pcm_cache is not None:
            self.set_waveform(self.pcm_cache)
        else:
            self.update()

    def set_waveform(self, pcm_data: np.ndarray):
        self.pcm_cache = pcm_data
        w, h = 2400, 360
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        arr[:] = (15, 15, 15) if self.dark_mode else (235, 235, 238)

        c = QColor(self.accent_color)
        r, g, b = c.red(), c.green(), c.blue()
        r_hi, g_hi, b_hi = min(255, r + 45), min(255, g + 45), min(255, b + 45)

        if len(pcm_data) > 0:
            chunks = np.array_split(np.abs(pcm_data.astype(np.float32)), w)
            peaks = np.array([ch.max() if len(ch) > 0 else 0 for ch in chunks])
            max_val = peaks.max() or 1.0
            heights = (peaks / max_val) * (h * 0.85)
            cy = h // 2
            for x in range(w):
                bh = int(heights.item(x) // 2)
                if bh > 0:
                    arr[cy - bh : cy + bh, x] = (r, g, b)
                    ih = int(bh * 0.55)
                    arr[cy - ih : cy + ih, x] = (r_hi, g_hi, b_hi)
        qimg = QImage(arr.data, w, h, w * 3, QImage.Format_RGB888)
        self.wave_pixmap = QPixmap.fromImage(qimg.copy())
        self.update()

    # === [БЛОК 11: ОТРИСОВКА И УПРАВЛЕНИЕ АУДИОВОЛНОЙ] ===
    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        painter.fillRect(
            0, 0, w, h, QColor(13, 13, 13) if self.dark_mode else QColor(235, 235, 238)
        )
        if self.wave_pixmap:
            painter.drawPixmap(0, 0, w, h, self.wave_pixmap)
        if self.duration > 0:
            x1 = int((self.start_trim / self.duration) * w)
            x2 = int((self.end_trim / self.duration) * w)
            shade = QColor(0, 0, 0, 150) if self.dark_mode else QColor(0, 0, 0, 85)
            painter.fillRect(0, 0, x1, h, shade)
            painter.fillRect(x2, 0, w - x2, h, shade)
            xc = int((self.current_pos / self.duration) * w)
            cur_pen = QColor(255, 255, 255) if self.dark_mode else QColor(20, 20, 20)
            painter.setPen(QPen(cur_pen, 2))
            painter.drawLine(xc, 0, xc, h)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = 1 if event.angleDelta().y() > 0 else -1
            ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            self.zoom_wheel_requested.emit(delta, ratio)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        self._handle_mouse(event.position().x(), False)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._handle_mouse(event.position().x(), False)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._handle_mouse(event.position().x(), True)

    def _handle_mouse(self, x, immediate):
        if self.duration > 0 and self.width() > 0:
            ratio = max(0.0, min(1.0, x / self.width()))
            self.on_seek(ratio * self.duration, immediate)


# === [БЛОК 12: МУЛЬТИ-ОТРЕЗКОВЫЙ ПОЛЗУНОК ОБРЕЗКИ С КОНТЕКСТНЫМ МЕНЮ ПО ПКМ] ===
class DualTrimSlider(QWidget):
    zoom_wheel_requested = Signal(int, float)

    def __init__(self, on_trim_changed):
        super().__init__()
        self.on_trim_changed = on_trim_changed
        self.setFixedHeight(38)
        self.accent_color = "#FF9900"
        self.dark_mode = True
        self.sync_seek = False
        self.duration = 0.0
        self.playhead_sec = 0.0
        self.video_fps = 30.0

        # Список всех отрезков на таймлайне: [[start_sec, end_sec], ...]
        self.segments = []
        self.active_seg_idx = 0
        self.active_handle = None  # "start" | "end"
        self.setCursor(Qt.PointingHandCursor)

    @property
    def start_trim(self) -> float:
        if 0 <= self.active_seg_idx < len(self.segments):
            return self.segments[self.active_seg_idx][0]
        return 0.0

    @start_trim.setter
    def start_trim(self, val: float):
        if not self.segments:
            self.segments = [[val, max(val, self.duration)]]
            self.active_seg_idx = 0
        elif 0 <= self.active_seg_idx < len(self.segments):
            self.segments[self.active_seg_idx][0] = val

    @property
    def end_trim(self) -> float:
        if 0 <= self.active_seg_idx < len(self.segments):
            return self.segments[self.active_seg_idx][1]
        return self.duration

    @end_trim.setter
    def end_trim(self, val: float):
        if not self.segments:
            self.segments = [[0.0, val]]
            self.active_seg_idx = 0
        elif 0 <= self.active_seg_idx < len(self.segments):
            self.segments[self.active_seg_idx][1] = val

    def reset_segments(self, dur: float):
        self.duration = max(0.0, dur)
        self.segments = [[0.0, self.duration]] if self.duration > 0 else []
        self.active_seg_idx = 0
        self.active_handle = None
        self.update()

    def get_sorted_segments(self) -> list:
        valid = [
            (round(s, 3), round(e, 3)) for s, e in self.segments if (e - s) >= 0.02
        ]
        valid.sort(key=lambda item: item[0])
        return valid

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad = 14
        tw = max(1, w - pad * 2)
        y = h // 2

        track_bg = QColor(58, 58, 62) if self.dark_mode else QColor(200, 200, 205)
        p.setPen(QPen(track_bg, 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pad, y, w - pad, y)

        if self.duration > 0 and self.segments:
            accent_q = QColor(self.accent_color)
            dim_accent = QColor(accent_q)
            dim_accent.setAlpha(155)

            for idx, (seg_s, seg_e) in enumerate(self.segments):
                x1 = pad + (seg_s / self.duration) * tw
                x2 = pad + (seg_e / self.duration) * tw
                is_active = idx == self.active_seg_idx

                # Полупрозрачная подложка зоны отрезка
                fill_c = QColor(accent_q)
                fill_c.setAlpha(55 if is_active else 28)
                p.fillRect(QRectF(x1, y - 10, max(2.0, x2 - x1), 20), fill_c)

                # Линия отрезка
                p.setPen(
                    QPen(
                        accent_q if is_active else dim_accent,
                        6,
                        Qt.SolidLine,
                        Qt.RoundCap,
                    )
                )
                p.drawLine(int(x1), y, int(x2), y)

                # Ручки начала и конца каждого отрезка
                for hx in (x1, x2):
                    p.setBrush(
                        QColor(255, 255, 255) if is_active else QColor(225, 225, 230)
                    )
                    p.setPen(QPen(accent_q if is_active else dim_accent, 2))
                    p.drawRoundedRect(QRectF(hx - 6, y - 12, 12, 24), 3, 3)

            xp = pad + (self.playhead_sec / self.duration) * tw
            tick_c = (
                QColor(255, 255, 255, 190)
                if self.dark_mode
                else QColor(20, 20, 20, 190)
            )
            p.setPen(QPen(tick_c, 2))
            p.drawLine(int(xp), y - 11, int(xp), y + 11)

    # === [БЛОК 13: СОБЫТИЯ МЫШИ, ПЕРЕМЕЩЕНИЕ ОТРЕЗКА ЦЕЛИКОМ И КОНТЕКСТНОЕ МЕНЮ (ПКМ)] ===
    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = 1 if event.angleDelta().y() > 0 else -1
            ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            self.zoom_wheel_requested.emit(delta, ratio)
            event.accept()
        else:
            super().wheelEvent(event)

    def _x_to_sec(self, mx: float) -> float:
        pad = 14
        tw = max(1, self.width() - pad * 2)
        ratio = max(0.0, min(1.0, (mx - pad) / tw))
        return ratio * self.duration

    def _find_segment_at_sec(self, sec: float) -> int:
        for idx, (s, e) in enumerate(self.segments):
            if s <= sec <= e:
                return idx
        return -1

    def _add_cut_at_sec(self, click_sec: float):
        if self.duration <= 0.1:
            return
        fps = getattr(self, "video_fps", 60.0)
        min_gap = (1.0 / fps) if fps > 0 else 0.02
        default_len = max(0.5, min(self.duration * 0.08, 12.0))

        ordered = sorted(self.segments, key=lambda item: item[0])

        for idx, seg in enumerate(ordered):
            if seg[0] < click_sec < seg[1] and (seg[1] - seg[0]) > min_gap * 4:
                new_s = click_sec
                new_e = min(seg[1], click_sec + default_len)
                if (seg[1] - new_e) >= min_gap * 2:
                    tail_e = seg[1]
                    seg[1] = max(seg[0] + min_gap, new_s - min_gap)
                    new_e = min(tail_e - min_gap, new_s + default_len)
                    self.segments.append([new_s, max(new_s + min_gap, new_e)])
                    self.segments.append(
                        [min(tail_e - min_gap, new_e + min_gap), tail_e]
                    )
                else:
                    seg[1] = max(seg[0] + min_gap, new_s - min_gap)
                    self.segments.append([new_s, new_e])
                self.segments.sort(key=lambda item: item[0])
                self.active_seg_idx = next(
                    (
                        i
                        for i, x in enumerate(self.segments)
                        if abs(x[0] - new_s) < 0.01
                    ),
                    len(self.segments) - 1,
                )
                self.update()
                self.on_trim_changed("start", True)
                return

        left_bound = 0.0
        right_bound = self.duration
        for s, e in ordered:
            if e <= click_sec:
                left_bound = max(left_bound, e + min_gap)
            if s >= click_sec:
                right_bound = min(right_bound, s - min_gap)
                break

        if right_bound - left_bound < min_gap * 2:
            return

        new_s = max(left_bound, min(click_sec, right_bound - min_gap * 2))
        new_e = min(right_bound, new_s + default_len)
        self.segments.append([new_s, new_e])
        self.segments.sort(key=lambda item: item[0])
        self.active_seg_idx = next(
            (i for i, x in enumerate(self.segments) if abs(x[0] - new_s) < 0.01),
            len(self.segments) - 1,
        )
        self.update()
        self.on_trim_changed("start", True)

    def contextMenuEvent(self, event):
        if self.duration <= 0:
            return
        click_sec = self._x_to_sec(event.pos().x())
        hit_idx = self._find_segment_at_sec(click_sec)

        menu = QMenu(self)
        act_add = menu.addAction("➕ Добавить обрезку здесь")
        act_del = None
        act_reset = None

        if hit_idx >= 0 and len(self.segments) > 1:
            act_del = menu.addAction(f"🗑 Удалить обрезку #{hit_idx + 1}")
        if len(self.segments) > 1:
            menu.addSeparator()
            act_reset = menu.addAction("🧹 Сбросить до одной обрезки")

        chosen = menu.exec(event.globalPos())
        if chosen == act_add:
            self._add_cut_at_sec(click_sec)
        elif act_del is not None and chosen == act_del:
            self.segments.pop(hit_idx)
            self.active_seg_idx = max(
                0, min(self.active_seg_idx, len(self.segments) - 1)
            )
            self.update()
            self.on_trim_changed("start", True)
        elif act_reset is not None and chosen == act_reset:
            self.reset_segments(self.duration)
            self.on_trim_changed("start", True)

    def mousePressEvent(self, event):
        if self.duration <= 0 or not self.segments:
            return
        if event.button() != Qt.LeftButton:
            return

        pad = 14
        tw = max(1, self.width() - pad * 2)
        mx = event.position().x()
        handle_hit_px = 10.0

        # 1. Сначала проверяем точное попадание по ручкам начала/конца любого отрезка
        best_dist = handle_hit_px + 1.0
        best_seg = -1
        best_handle = None

        for idx, (seg_s, seg_e) in enumerate(self.segments):
            x1 = pad + (seg_s / self.duration) * tw
            x2 = pad + (seg_e / self.duration) * tw
            d1 = abs(mx - x1)
            d2 = abs(mx - x2)
            if d1 <= handle_hit_px and d1 < best_dist:
                best_dist = d1
                best_seg = idx
                best_handle = "start"
            if d2 <= handle_hit_px and d2 < best_dist:
                best_dist = d2
                best_seg = idx
                best_handle = "end"

        if best_seg >= 0:
            self.active_seg_idx = best_seg
            self.active_handle = best_handle
            self.update()
            self.mouseMoveEvent(event)
            return

        # 2. Если нажали в любое место внутри тела обрезки — выделяем её и готовим перемещение целиком!
        for idx, (seg_s, seg_e) in enumerate(self.segments):
            x1 = pad + (seg_s / self.duration) * tw
            x2 = pad + (seg_e / self.duration) * tw
            if x1 <= mx <= x2:
                self.active_seg_idx = idx
                self.active_handle = "move"
                self._drag_grab_offset_sec = self._x_to_sec(mx) - seg_s
                self._drag_seg_len_sec = seg_e - seg_s
                self.update()
                self.on_trim_changed("start", False)
                return

    def mouseMoveEvent(self, event):
        if not self.active_handle or self.duration <= 0 or not self.segments:
            return
        pad = 14
        tw = max(1, self.width() - pad * 2)
        mx = event.position().x()

        fps = getattr(self, "video_fps", 60.0)
        min_gap = (1.0 / fps) if fps > 0 else 0.016
        idx = self.active_seg_idx
        seg_s, seg_e = self.segments[idx]

        prev_end = max(
            [
                s[1] + min_gap
                for i, s in enumerate(self.segments)
                if i != idx and s[1] <= seg_s
            ],
            default=0.0,
        )
        next_start = min(
            [
                s[0] - min_gap
                for i, s in enumerate(self.segments)
                if i != idx and s[0] >= seg_e
            ],
            default=self.duration,
        )

        if self.active_handle == "move":
            seg_len = getattr(self, "_drag_seg_len_sec", seg_e - seg_s)
            grab_off = getattr(self, "_drag_grab_offset_sec", 0.0)
            raw_new_s = self._x_to_sec(mx) - grab_off

            # Мягкое прилипание начала или конца перетаскиваемого отрезка к ползунку длительности
            if not self.sync_seek:
                xp = pad + (self.playhead_sec / self.duration) * tw
                x_new_s = pad + (raw_new_s / self.duration) * tw
                x_new_e = pad + ((raw_new_s + seg_len) / self.duration) * tw
                if abs(x_new_s - xp) <= 5.0:
                    raw_new_s = self.playhead_sec
                elif abs(x_new_e - xp) <= 5.0:
                    raw_new_s = self.playhead_sec - seg_len

            if fps > 0:
                raw_new_s = round(raw_new_s * fps) / fps

            max_allowed_s = max(prev_end, next_start - seg_len)
            clamped_s = max(prev_end, min(raw_new_s, max_allowed_s))
            clamped_e = min(next_start, clamped_s + seg_len)

            self.segments[idx][0] = clamped_s
            self.segments[idx][1] = clamped_e
            self.update()
            self.on_trim_changed("start", False)
            return

        xp = pad + (self.playhead_sec / self.duration) * tw
        if not self.sync_seek and abs(mx - xp) <= 5.0:
            sec = self.playhead_sec
        else:
            ratio = max(0.0, min(1.0, (mx - pad) / tw))
            sec = ratio * self.duration

        if fps > 0:
            sec = round(sec * fps) / fps

        if self.active_handle == "start":
            self.segments[idx][0] = max(prev_end, min(sec, seg_e - min_gap))
        else:
            self.segments[idx][1] = min(next_start, max(sec, seg_s + min_gap))

        self.update()
        self.on_trim_changed(self.active_handle, False)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.active_handle:
            h = "start" if self.active_handle == "move" else self.active_handle
            self.active_handle = None
            self.on_trim_changed(h, True)


# === [БЛОК 14: ОКНО МИКШЕРА ЗВУКОВЫХ ДОРОЖЕК] ===
class AudioTracksDialog(QDialog):
    def __init__(
        self,
        parent,
        track_count,
        track_dbs,
        output_groups,
        on_db_changed,
        on_groups_changed,
        accent,
        dark_mode,
    ):
        super().__init__(parent)
        self.setWindowTitle("Звуковые дорожки и микшер (дБ)")
        self.resize(680, 320)
        self.setMinimumSize(520, 310)
        set_windows_titlebar_theme(self, dark_mode)

        self.track_count = track_count
        self.track_dbs = track_dbs
        self.output_groups = output_groups
        self.on_db_changed = on_db_changed
        self.on_groups_changed = on_groups_changed
        self.accent = accent
        self.dark_mode = dark_mode
        self.checkboxes = {}

        bg = "#1A1A1A" if dark_mode else "#F4F4F5"
        fg = "#EEEEEE" if dark_mode else "#18181B"
        scr_bg = "#121212" if dark_mode else "#E4E4E7"
        btn_sec = "#333333" if dark_mode else "#D4D4D8"
        btn_fg = get_contrast_text_color(accent)

        self.setStyleSheet(f"background-color: {bg}; color: {fg}; font-family: Arial;")
        layout = QVBoxLayout(self)

        lbl_top = QLabel(
            "Шкала в децибелах: от -∞ dB (тишина) и -100 dB до +24.0 dB (по умолчанию 0.0 dB):"
        )
        lbl_top.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 12px;")
        lbl_top.setWordWrap(True)
        layout.addWidget(lbl_top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(
            f"border: 1px solid #444444; background-color: {scr_bg};"
        )
        layout.addWidget(self.scroll, 1)

        btn_row = QHBoxLayout()
        btn_merge = QPushButton("🔗 Объединить выбранные в одну дорожку")
        btn_merge.setStyleSheet(
            f"background-color: {accent}; color: {btn_fg}; font-weight: bold; padding: 7px 14px; border-radius: 4px;"
        )
        btn_merge.clicked.connect(self.merge_selected)
        btn_row.addWidget(btn_merge)

        btn_reset = QPushButton("Сбросить все объединения")
        btn_reset.setStyleSheet(
            f"background-color: {btn_sec}; color: {fg}; padding: 7px 14px; border-radius: 4px;"
        )
        btn_reset.clicked.connect(self.reset_groups)
        btn_row.addWidget(btn_reset)
        layout.addLayout(btn_row)

        self._rebuild_cards()

    # === [БЛОК 15: ОТРИСОВКА КАРТОЧЕК ДОРОЖЕК В МИКШЕРЕ] ===
    def _rebuild_cards(self):
        self.checkboxes.clear()
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(8)

        card_bg = "#1E1E1E" if self.dark_mode else "#FFFFFF"
        card_merged_bg = "#241D14" if self.dark_mode else "#FFFBEB"
        fg = "#FFFFFF" if self.dark_mode else "#18181B"

        for out_idx, grp in enumerate(self.output_groups):
            is_merged = len(grp) > 1
            card = QFrame()
            if is_merged:
                card.setStyleSheet(
                    f"QFrame {{ background-color: {card_merged_bg}; border: 2px solid {self.accent}; border-radius: 6px; }}"
                )
            else:
                card.setStyleSheet(
                    f"QFrame {{ background-color: {card_bg}; border: 1px solid #555555; border-radius: 6px; }}"
                )

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(6)

            header = QHBoxLayout()
            if is_merged:
                title = QLabel(f"📦 Выходная дорожка {out_idx + 1}")
                title.setStyleSheet(
                    f"color: {self.accent}; font-weight: bold; font-size: 12px; border: none;"
                )
                header.addWidget(title, 1)

                btn_split = QPushButton("Разъединить")
                btn_split.setStyleSheet(
                    "background-color: #7F1D1D; color: #FECACA; padding: 3px 8px; border-radius: 3px; font-size: 11px;"
                )
                btn_split.clicked.connect(
                    lambda checked=False, g_i=out_idx: self.split_group(g_i)
                )
                header.addWidget(btn_split)
            else:
                title = QLabel(f"🎵 Выходная дорожка {out_idx + 1}")
                title.setStyleSheet(
                    "color: #888888; font-weight: bold; font-size: 11px; border: none;"
                )
                header.addWidget(title, 1)

            card_layout.addLayout(header)
            # === [БЛОК 16: ПОЛЗУНКИ ДБ ВНУТРИ КАРТОЧЕК ДОРОЖЕК] ===
            for t_idx in grp:
                row = QHBoxLayout()
                cb = QCheckBox(f"Дорожка {t_idx + 1}")
                cb.setStyleSheet(
                    f"font-size: 12px; border: none; color: {fg}; font-weight: bold;"
                )
                self.checkboxes[t_idx] = cb
                row.addWidget(cb, 0)

                cur_raw = self.track_dbs.get(t_idx, 0)
                lbl_val = QLabel(format_db_label(cur_raw))
                lbl_val.setFixedWidth(68)
                lbl_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                lbl_val.setStyleSheet(
                    "color: #22C55E; font-weight: bold; border: none;"
                    if cur_raw > 0
                    else f"color: {self.accent}; font-weight: bold; border: none;"
                )

                slider = QSlider(Qt.Horizontal)
                slider.setRange(MUTE_DB_VAL, MAX_DB_VAL)
                slider.setSingleStep(5)
                slider.setPageStep(20)
                slider.setValue(cur_raw)

                btn_zero = QPushButton("0 dB")
                btn_zero.setFixedWidth(42)
                btn_zero.setStyleSheet(
                    "background-color: #333333; color: #EEEEEE; font-size: 10px; padding: 2px; border-radius: 3px;"
                )

                def _make_handler(idx_t, lbl, sld):
                    def _changed(val):
                        if -15 <= val <= 15 and val != 0:
                            sld.blockSignals(True)
                            sld.setValue(0)
                            sld.blockSignals(False)
                            val = 0
                        self.track_dbs[idx_t] = val
                        lbl.setText(format_db_label(val))
                        lbl.setStyleSheet(
                            "color: #22C55E; font-weight: bold; border: none;"
                            if val > 0
                            else f"color: {self.accent}; font-weight: bold; border: none;"
                        )
                        self.on_db_changed(idx_t, val)

                    return _changed

                slider.valueChanged.connect(_make_handler(t_idx, lbl_val, slider))
                btn_zero.clicked.connect(
                    lambda checked=False, sld=slider: sld.setValue(0)
                )

                row.addWidget(slider, 1)
                row.addWidget(lbl_val)
                row.addWidget(btn_zero)
                card_layout.addLayout(row)

            vbox.addWidget(card)

        vbox.addStretch(1)
        self.scroll.setWidget(container)

    # === [БЛОК 17: ОБЪЕДИНЕНИЕ И РАЗЪЕДИНЕНИЕ ДОРОЖЕК] ===
    def split_group(self, group_index):
        grp = self.output_groups[group_index]
        new_groups = []
        for idx, g in enumerate(self.output_groups):
            if idx == group_index:
                for t in grp:
                    new_groups.append([t])
            else:
                new_groups.append(g)
        self.output_groups.clear()
        self.output_groups.extend(new_groups)
        self._rebuild_cards()
        self.on_groups_changed()

    def merge_selected(self):
        selected = [idx for idx, cb in self.checkboxes.items() if cb.isChecked()]
        if len(selected) < 2:
            QMessageBox.information(
                self,
                "Подсказка",
                "Отметьте галочками минимум 2 дорожки, чтобы объединить их.",
            )
            return
        sel_set = set(selected)
        new_groups = []
        merged_inserted = False
        for grp in self.output_groups:
            remaining = [t for t in grp if t not in sel_set]
            if not merged_inserted and any(t in sel_set for t in grp):
                new_groups.append(sorted(selected))
                merged_inserted = True
            if remaining:
                new_groups.append(remaining)
        self.output_groups.clear()
        self.output_groups.extend(new_groups)
        self._rebuild_cards()
        self.on_groups_changed()

    def reset_groups(self):
        self.output_groups.clear()
        for idx in range(self.track_count):
            self.output_groups.append([idx])
        self._rebuild_cards()
        self.on_groups_changed()


# === [БЛОК 18: ОКНО НАСТРОЕК ЭКСПОРТА (ЧАСТЬ 1)] ===
class ExportDialog(QDialog):
    def __init__(
        self,
        parent,
        file_path: Path,
        is_video: bool,
        is_trimmed: bool,
        segments_count: int,
        accent: str,
        dark_mode: bool,
    ):
        super().__init__(parent)
        self.setWindowTitle("Экспорт медиафайла")
        self.setFixedWidth(460)
        set_windows_titlebar_theme(self, dark_mode)

        bg = "#1E1E1E" if dark_mode else "#F4F4F5"
        fg = "#EEEEEE" if dark_mode else "#18181B"
        inp_bg = "#121212" if dark_mode else "#FFFFFF"
        btn_fg = get_contrast_text_color(accent)
        self.setStyleSheet(f"background-color: {bg}; color: {fg}; font-family: Arial;")

        self.result_config = None
        lay = QVBoxLayout(self)
        lay.setSpacing(7)

        lbl_name = QLabel("Название файла:")
        lbl_name.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 12px;")
        lay.addWidget(lbl_name)

        self.edit_name = QLineEdit(f"{file_path.stem}_обрезано")
        self.edit_name.setStyleSheet(
            f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 6px 8px; border-radius: 4px; font-size: 13px;"
        )
        lay.addWidget(self.edit_name)

        self.combo_multi = None
        if segments_count > 1:
            lbl_multi = QLabel(f"Режим нарезки ({segments_count} отмеченных отрезков):")
            lbl_multi.setStyleSheet(
                "font-weight: bold; color: #22C55E; font-size: 12px; margin-top: 4px;"
            )
            lay.addWidget(lbl_multi)

            self.combo_multi = QComboBox()
            self.combo_multi.addItems(
                [
                    f"Склеить все {segments_count} отрезков в один файл",
                    f"Сохранить как {segments_count} отдельных файлов",
                ]
            )
            self.combo_multi.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #22C55E; padding: 6px; border-radius: 4px;"
            )
            lay.addWidget(self.combo_multi)

        row_fmt = QHBoxLayout()
        col_f1 = QVBoxLayout()
        lbl_fmt = QLabel("Формат:")
        lbl_fmt.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 12px;")
        col_f1.addWidget(lbl_fmt)

        self.combo_fmt = QComboBox()
        formats = VIDEO_FORMATS if is_video else AUDIO_FORMATS
        self.combo_fmt.addItems(formats)
        orig_ext = file_path.suffix.lower().lstrip(".")
        if orig_ext in formats:
            self.combo_fmt.setCurrentText(orig_ext)
        self.combo_fmt.setStyleSheet(
            f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
        )
        col_f1.addWidget(self.combo_fmt)
        row_fmt.addLayout(col_f1)
        # === [БЛОК 19: ОКНО НАСТРОЕК ЭКСПОРТА (ЧАСТЬ 2)] ===
        self.combo_res = None
        if is_video:
            col_f2 = QVBoxLayout()
            lbl_res = QLabel("Разрешение:")
            lbl_res.setStyleSheet(
                f"font-weight: bold; color: {accent}; font-size: 12px;"
            )
            col_f2.addWidget(lbl_res)

            self.combo_res = QComboBox()
            self.combo_res.addItems(
                [
                    "Оригинал",
                    "4320p (8K)",
                    "2160p (4K)",
                    "1440p (2K)",
                    "1080p",
                    "720p",
                    "480p",
                    "240p",
                    "144p",
                ]
            )
            self.combo_res.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
            )
            col_f2.addWidget(self.combo_res)
            row_fmt.addLayout(col_f2)

        lay.addLayout(row_fmt)

        self.combo_fps = None
        self.combo_crf = None
        self.combo_vbitrate = None
        self.combo_speed = None
        self.cb_no_audio = None

        if is_video:
            row_v1 = QHBoxLayout()
            c_fps = QVBoxLayout()
            c_fps.addWidget(QLabel("FPS:"))
            self.combo_fps = QComboBox()
            self.combo_fps.addItems(["Оригинал", "60 FPS", "30 FPS", "24 FPS"])
            self.combo_fps.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
            )
            c_fps.addWidget(self.combo_fps)
            row_v1.addLayout(c_fps)

            c_vbr = QVBoxLayout()
            c_vbr.addWidget(QLabel("Битрейт видео:"))
            self.combo_vbitrate = QComboBox()
            self.combo_vbitrate.addItems(
                [
                    "Авто (по CRF)",
                    "20 Мбит/с (20M)",
                    "12 Мбит/с (12M)",
                    "8 Мбит/с (8M)",
                    "5 Мбит/с (5M)",
                    "2.5 Мбит/с (2500k)",
                ]
            )
            self.combo_vbitrate.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
            )
            c_vbr.addWidget(self.combo_vbitrate)
            row_v1.addLayout(c_vbr)
            lay.addLayout(row_v1)

            lay.addWidget(QLabel("Качество сжатия:"))
            self.combo_crf = QComboBox()
            self.combo_crf.addItems(
                [
                    "Высокое качество (CRF 18)",
                    "Сбалансированное (CRF 23)",
                    "Малый размер файла (CRF 28)",
                ]
            )
            self.combo_crf.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
            )
            lay.addWidget(self.combo_crf)

            lay.addWidget(QLabel("Режим скорости экспорта:"))
            self.combo_speed = QComboBox()
            self.combo_speed.addItems(
                [
                    "Мгновенно без перекодирования (по ключевым кадрам, 1-2 сек)",
                    f"Полное перекодирование до доли секунды ({BEST_GPU_ENCODER})",
                ]
            )
            self.combo_speed.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
            )
            lay.addWidget(self.combo_speed)

        row_aud = QHBoxLayout()
        c_abr = QVBoxLayout()
        lbl_abr = QLabel("Битрейт аудио:")
        lbl_abr.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 11px;")
        c_abr.addWidget(lbl_abr)
        self.combo_abitrate = QComboBox()
        self.combo_abitrate.addItems(
            ["192 kbps", "320 kbps", "256 kbps", "128 kbps", "96 kbps", "64 kbps"]
        )
        self.combo_abitrate.setStyleSheet(
            f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
        )
        c_abr.addWidget(self.combo_abitrate)
        row_aud.addLayout(c_abr)

        c_ach = QVBoxLayout()
        lbl_ach = QLabel("Каналы звука:")
        lbl_ach.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 11px;")
        c_ach.addWidget(lbl_ach)
        self.combo_achannels = QComboBox()
        self.combo_achannels.addItems(["Оригинал", "Стерео (2.0)", "Моно (1.0)"])
        self.combo_achannels.setStyleSheet(
            f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
        )
        c_ach.addWidget(self.combo_achannels)
        row_aud.addLayout(c_ach)
        lay.addLayout(row_aud)

        if is_video:
            self.cb_no_audio = QCheckBox("Удалить звук (экспорт без аудиодорожек)")
            self.cb_no_audio.setStyleSheet("font-size: 12px; margin-top: 2px;")
            lay.addWidget(self.cb_no_audio)

        btn_export = QPushButton("Экспорт")
        btn_export.setStyleSheet(
            f"background-color: {accent}; color: {btn_fg}; font-size: 14px; font-weight: bold; padding: 10px; border-radius: 5px; margin-top: 8px;"
        )
        btn_export.clicked.connect(self._on_submit)
        lay.addWidget(btn_export)

    def _on_submit(self):
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Внимание", "Введите название файла!")
            return
        abr_raw = self.combo_abitrate.currentText()
        abr_num = re.search(r"\d+", abr_raw)
        self.result_config = {
            "name": name,
            "format": self.combo_fmt.currentText(),
            "resolution": self.combo_res.currentText()
            if self.combo_res
            else "Оригинал",
            "fps": self.combo_fps.currentText() if self.combo_fps else "Оригинал",
            "crf": self.combo_crf.currentText()
            if self.combo_crf
            else "Высокое качество (CRF 18)",
            "vbitrate": self.combo_vbitrate.currentText()
            if self.combo_vbitrate
            else "Авто (по CRF)",
            "abitrate": abr_num.group(0) if abr_num else "192",
            "achannels": self.combo_achannels.currentText(),
            "speed_mode": self.combo_speed.currentText() if self.combo_speed else "",
            "multi_mode": self.combo_multi.currentText() if self.combo_multi else "",
            "no_audio": self.cb_no_audio.isChecked() if self.cb_no_audio else False,
        }
        self.accept()


# === [БЛОК 20: ОКНО НАСТРОЕК ПРОГРАММЫ (ЧАСТЬ 1)] ===
class SettingsDialog(QDialog):
    def __init__(self, parent, settings: dict, on_settings_applied):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setFixedWidth(480)
        self.settings = settings
        self.on_settings_applied = on_settings_applied
        set_windows_titlebar_theme(self, self.settings.get("dark_mode", True))

        self.lay = QVBoxLayout(self)
        self.lay.setSpacing(10)

        self.lbl_theme_sec = QLabel("1. Тема и цветовой акцент:")
        self.lay.addWidget(self.lbl_theme_sec)

        theme_mode_row = QHBoxLayout()
        self.btn_dark = QPushButton("🌙 Тёмная тема")
        self.btn_light = QPushButton("☀ Светлая тема")
        self.btn_dark.clicked.connect(lambda: self._set_dark_mode(True))
        self.btn_light.clicked.connect(lambda: self._set_dark_mode(False))
        theme_mode_row.addWidget(self.btn_dark)
        theme_mode_row.addWidget(self.btn_light)
        self.lay.addLayout(theme_mode_row)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.color_buttons = []

        for col, hex_c in enumerate(PALETTE_LIGHT):
            btn = QPushButton()
            btn.setFixedSize(46, 34)
            btn.clicked.connect(lambda checked=False, c=hex_c: self._set_accent(c))
            grid.addWidget(btn, 0, col)
            self.color_buttons.append((btn, hex_c))

        for col, hex_c in enumerate(PALETTE_DARK):
            btn = QPushButton()
            btn.setFixedSize(46, 34)
            btn.clicked.connect(lambda checked=False, c=hex_c: self._set_accent(c))
            grid.addWidget(btn, 1, col)
            self.color_buttons.append((btn, hex_c))

        # === [БЛОК 21: ОКНО НАСТРОЕК ПРОГРАММЫ (ЧАСТЬ 2)] ===
        self.btn_custom_color = QPushButton("+")
        self.btn_custom_color.setFixedSize(46, 34)
        self.btn_custom_color.setStyleSheet(
            "background-color: #D4D4D8; color: #111111; font-size: 18px; font-weight: bold; border: 1px solid #888; border-radius: 5px;"
        )
        self.btn_custom_color.clicked.connect(self._pick_custom_color)
        grid.addWidget(self.btn_custom_color, 1, 4)
        self.lay.addLayout(grid)

        self.lbl_dir_sec = QLabel("2. Папка по умолчанию (для открытия и экспорта):")
        self.lay.addWidget(self.lbl_dir_sec)

        dir_row = QHBoxLayout()
        self.edit_dir = QLineEdit(self.settings.get("default_dir", str(SCRIPT_DIR)))
        self.edit_dir.setReadOnly(True)
        dir_row.addWidget(self.edit_dir, 1)

        btn_browse = QPushButton("Обзор...")
        btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(btn_browse)
        self.lay.addLayout(dir_row)

        self.cb_last_dir = QCheckBox(
            "Открывать последнюю папку (при экспорте и открытии)"
        )
        self.cb_last_dir.setChecked(self.settings.get("open_last_dir", True))
        self.cb_last_dir.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_last_dir)

        self.lbl_beh_sec = QLabel("3. Поведение ползунков и предпросмотр кадров:")
        self.lay.addWidget(self.lbl_beh_sec)

        self.cb_sync_trim = QCheckBox(
            "Привязывать ползунок длительности к границам начала и конца обрезки"
        )
        self.cb_sync_trim.setChecked(self.settings.get("sync_seek_with_trim", False))
        self.cb_sync_trim.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_sync_trim)

        self.cb_scrub_audio = QCheckBox("Включить звук при перемотке медиафайла")
        self.cb_scrub_audio.setChecked(self.settings.get("scrub_audio", False))
        self.cb_scrub_audio.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_scrub_audio)

        self.cb_preload_frames = QCheckBox(
            "Предзагружать опорные кадры от начала до конца при открытии (с окном прогресса)"
        )
        self.cb_preload_frames.setChecked(
            self.settings.get("preload_frames_dialog", False)
        )
        self.cb_preload_frames.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_preload_frames)

        scrub_res_row = QHBoxLayout()
        scrub_res_row.addWidget(QLabel("Разрешение опорных кадров:"))
        self.combo_scrub_res = QComboBox()
        self.combo_scrub_res.addItems(
            [
                "Оригинал",
                "4320p (8K)",
                "2160p (4K)",
                "1440p (2K)",
                "1080p",
                "720p",
                "480p",
                "360p",
                "240p",
                "144p",
            ]
        )
        cur_sr = self.settings.get("scrub_resolution", "360p")
        if self.combo_scrub_res.findText(cur_sr) >= 0:
            self.combo_scrub_res.setCurrentText(cur_sr)
        self.combo_scrub_res.currentTextChanged.connect(self._on_flags_changed)
        scrub_res_row.addWidget(self.combo_scrub_res)
        self.lay.addLayout(scrub_res_row)

        self.lbl_dev_sec = QLabel("4. Интеграция и обновления:")
        self.lay.addWidget(self.lbl_dev_sec)

        self.cb_ctx_menu = QCheckBox(
            "Добавить «Медиа Обрезчик» в меню «Открыть с помощью»"
        )
        self.cb_ctx_menu.setChecked(self.settings.get("context_menu", False))
        self.cb_ctx_menu.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_ctx_menu)

        self.cb_show_console = QCheckBox("Отображение консоли программы")
        self.cb_show_console.setChecked(self.settings.get("show_console", False))
        self.cb_show_console.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_show_console)

        upd_row = QHBoxLayout()
        self.lbl_ver_info = QLabel(f"Текущая версия: {APP_VERSION}")
        self.lbl_ver_info.setStyleSheet("font-size: 11px; color: #888888;")
        upd_row.addWidget(self.lbl_ver_info, 1)

        self.btn_check_upd = QPushButton("🔄 Проверить обновления")
        self.btn_check_upd.clicked.connect(self._on_check_updates_clicked)
        upd_row.addWidget(self.btn_check_upd)
        self.lay.addLayout(upd_row)

        self._refresh_dialog_style()

    # === [БЛОК 22: ОБРАБОТЧИКИ ОКНА НАСТРОЕК И ПРОВЕРКА ОБНОВЛЕНИЙ] ===
    def _set_dark_mode(self, is_dark: bool):
        self.settings["dark_mode"] = is_dark
        set_windows_titlebar_theme(self, is_dark)
        self._save_and_apply()

    def _set_accent(self, hex_color: str):
        self.settings["accent"] = hex_color
        self._save_and_apply()

    def _pick_custom_color(self):
        chosen = QColorDialog.getColor(
            QColor(self.settings.get("accent", "#FF9900")),
            self,
            "Выберите свой цвет темы",
        )
        if chosen.isValid():
            self.settings["accent"] = chosen.name().upper()
            self._save_and_apply()

    def _browse_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку по умолчанию", self.edit_dir.text()
        )
        if folder:
            self.settings["default_dir"] = folder
            self.settings["last_export_dir"] = folder
            self.edit_dir.setText(folder)
            self._save_and_apply()

    def _on_flags_changed(self):
        old_res = self.settings.get("scrub_resolution", "360p")
        new_res = self.combo_scrub_res.currentText()
        self.settings["open_last_dir"] = self.cb_last_dir.isChecked()
        self.settings["sync_seek_with_trim"] = self.cb_sync_trim.isChecked()
        self.settings["scrub_audio"] = self.cb_scrub_audio.isChecked()
        self.settings["preload_frames_dialog"] = self.cb_preload_frames.isChecked()
        self.settings["scrub_resolution"] = new_res
        self.settings["context_menu"] = self.cb_ctx_menu.isChecked()
        self.settings["show_console"] = self.cb_show_console.isChecked()
        register_context_menu(self.settings["context_menu"])
        set_console_visible(self.settings["show_console"])
        self._save_and_apply()

        if old_res != new_res and hasattr(
            self.parent(), "_on_settings_scrub_res_changed"
        ):
            self.parent()._on_settings_scrub_res_changed(new_res)

    def _save_and_apply(self):
        save_app_settings(self.settings)
        self._refresh_dialog_style()
        self.on_settings_applied()

    def _on_check_updates_clicked(self):
        self.btn_check_upd.setEnabled(False)
        self.btn_check_upd.setText("Проверка...")
        QApplication.processEvents()

        ok, remote_ver, err_msg = check_github_update()
        self.btn_check_upd.setEnabled(True)
        self.btn_check_upd.setText("🔄 Проверить обновления")

        if not ok:
            QMessageBox.warning(self, "Проверка обновлений", err_msg)
            return

        if _parse_ver_tuple(remote_ver) <= _parse_ver_tuple(APP_VERSION):
            box = QMessageBox(self)
            box.setWindowTitle("Обновления")
            box.setText(f"Это последняя версия обрезчика! (v{APP_VERSION})")
            box.addButton("Отмена", QMessageBox.RejectRole)
            box.exec()
            return

        box = QMessageBox(self)
        box.setWindowTitle("Доступно обновление")
        box.setText(f"Обновить обрезчик?  {APP_VERSION}  →  {remote_ver}")
        btn_install = box.addButton("Установить", QMessageBox.AcceptRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()

        if box.clickedButton() == btn_install:
            dl_ok, dl_err = download_and_restart_update()
            if not dl_ok:
                QMessageBox.critical(self, "Ошибка обновления", dl_err)
                return
            QMessageBox.information(
                self,
                "Обновление установлено",
                f"Обрезчик обновлён до версии {remote_ver}!\nСейчас программа перезапустится.",
            )
            subprocess.Popen([sys.executable, str(Path(__file__).resolve())])
            QApplication.quit()

    # === [БЛОК 23: ОФОРМЛЕНИЕ ОКНА НАСТРОЕК И ВИДЕОВИДЖЕТ С ПРЕДПРОСМОТРОМ] ===
    def _refresh_dialog_style(self):
        is_dark = self.settings.get("dark_mode", True)
        accent = self.settings.get("accent", "#FF9900")
        btn_fg = get_contrast_text_color(accent)
        bg = "#1E1E1E" if is_dark else "#F4F4F5"
        fg = "#EEEEEE" if is_dark else "#18181B"
        inp = "#121212" if is_dark else "#FFFFFF"

        self.setStyleSheet(f"background-color: {bg}; color: {fg}; font-family: Arial;")
        for lbl in (
            self.lbl_theme_sec,
            self.lbl_dir_sec,
            self.lbl_beh_sec,
            self.lbl_dev_sec,
        ):
            lbl.setStyleSheet(
                f"font-weight: bold; color: {accent}; font-size: 12px; margin-top: 4px;"
            )

        self.edit_dir.setStyleSheet(
            f"background-color: {inp}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 3px;"
        )

        active_btn = f"background-color: {accent}; color: {btn_fg}; font-weight: bold; padding: 6px; border-radius: 4px;"
        inactive_btn = "background-color: #333333; color: #CCCCCC; padding: 6px; border-radius: 4px;"
        self.btn_dark.setStyleSheet(active_btn if is_dark else inactive_btn)
        self.btn_light.setStyleSheet(active_btn if not is_dark else inactive_btn)

        for btn, hex_c in self.color_buttons:
            border = (
                "3px solid #FFFFFF"
                if (hex_c.upper() == accent.upper() and is_dark)
                else (
                    "3px solid #111111"
                    if hex_c.upper() == accent.upper()
                    else "1px solid #555555"
                )
            )
            btn.setStyleSheet(
                f"background-color: {hex_c}; border: {border}; border-radius: 5px;"
            )


class ClickableVideoWidget(QGraphicsView):
    def __init__(self, on_click, on_double_click):
        try:
            self.setViewport(QOpenGLWidget())
        except Exception:
            pass

        super().__init__()
        self.on_click = on_click
        self.on_double_click = on_double_click
        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background-color: #0D0D0D; border: none;")

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.video_item = QGraphicsVideoItem()
        self.scene.addItem(self.video_item)

        self.video_sink = QVideoSink(self)
        self.video_sink.videoFrameChanged.connect(self._on_video_frame)
        self._downscaled_frame_pix = None

        self.preview_pixmap = None
        self.preview_target_height = 0

    def _on_video_frame(self, frame):
        if self.preview_target_height <= 0 or not frame.isValid():
            return
        qimg = frame.toImage()
        if qimg.isNull():
            return
        h = self.preview_target_height
        aspect = qimg.width() / max(1, qimg.height())
        w = max(16, int(round(h * aspect)))
        low_res = qimg.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        self._downscaled_frame_pix = QPixmap.fromImage(low_res)
        self.viewport().update()

    def set_preview_resolution(self, target_h: int):
        self.preview_target_height = target_h
        if target_h <= 0:
            self._downscaled_frame_pix = None
        self._apply_video_viewport_scale()
        self.viewport().update()

    def _apply_video_viewport_scale(self):
        rect = self.viewport().rect()
        self.scene.setSceneRect(0, 0, max(1, rect.width()), max(1, rect.height()))
        self.video_item.setSize(rect.size())

    def set_scrub_frame(self, pix: QPixmap):
        self.preview_pixmap = pix
        self.viewport().update()

    def clear_scrub_frame(self):
        if self.preview_pixmap is not None:
            self.preview_pixmap = None
            self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        active_pix = None
        smooth = True

        if self.preview_pixmap is not None and not self.preview_pixmap.isNull():
            active_pix = self.preview_pixmap
            smooth = self.preview_target_height == 0
        elif (
            self.preview_target_height > 0
            and self._downscaled_frame_pix is not None
            and not self._downscaled_frame_pix.isNull()
        ):
            active_pix = self._downscaled_frame_pix
            smooth = False

        if active_pix is not None:
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.SmoothPixmapTransform, smooth)
            vw, vh = self.viewport().width(), self.viewport().height()
            p.fillRect(0, 0, vw, vh, QColor(13, 13, 13))
            mode = Qt.SmoothTransformation if smooth else Qt.FastTransformation
            scaled = active_pix.scaled(vw, vh, Qt.KeepAspectRatio, mode)
            x = (vw - scaled.width()) // 2
            y = (vh - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)

    # === [БЛОК 24: СОБЫТИЯ ВИДЕОВИДЖЕТА И ИНИЦИАЛИЗАЦИЯ ГЛАВНОГО ОКНА] ===
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_video_viewport_scale()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_click()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_double_click()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        if hasattr(self, "on_context_menu") and callable(self.on_context_menu):
            self.on_context_menu(event.globalPos())


class MediaTrimmerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Медиа Обрезчик")
        self.resize(980, 650)
        self.setMinimumSize(680, 380)
        self.setAcceptDrops(True)

        self.settings = load_app_settings()
        set_console_visible(self.settings.get("show_console", False))
        set_windows_titlebar_theme(self, self.settings.get("dark_mode", True))

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.audio_out.setVolume(0.8)
        self.player.setAudioOutput(self.audio_out)

        self.file_path = None
        self.is_video = False
        self.duration = 0.0
        self.video_fps = 30.0
        self.video_src_w = 1920
        self.video_src_h = 1080
        self.master_volume = 0.8
        self.timeline_zoom = 100
        self.max_timeline_zoom = 1000
        self.cache_dir = SCRIPT_DIR / ".trimmer_cache"
        self.cache_dir.mkdir(exist_ok=True)
        self._cleanup_cache_files()
        self.load_counter = 0

        self._zoom_cursor_ratio = None
        self._target_tl_scroll = None
        self._target_wave_scroll = None
        self._smooth_scroll_timer = QTimer(self)
        self._smooth_scroll_timer.setInterval(16)
        self._smooth_scroll_timer.timeout.connect(self._tick_smooth_scroll)

        self.frame_cache = {}
        self._last_scrub_centis = -1
        self._scrub_anchor_sec = 0.0

        self.gpu_scrub_worker = FrameScrubWorker(use_gpu=True)
        self.cpu_scrub_worker = FrameScrubWorker(use_gpu=False)
        self.gpu_scrub_worker.frame_ready.connect(self._on_scrub_frame_ready)
        self.cpu_scrub_worker.frame_ready.connect(self._on_scrub_frame_ready)
        self.gpu_scrub_worker.start()
        self.cpu_scrub_worker.start()

        # === [БЛОК 25: ТАЙМЕР ПЕРЕМОТКИ И ПОСТРОЕНИЕ ВЕРХНЕЙ ПАНЕЛИ] ===
        self._pending_seek_sec = None
        self._seek_throttle_timer = QTimer(self)
        self._seek_throttle_timer.setInterval(65)
        self._seek_throttle_timer.setSingleShot(True)
        self._seek_throttle_timer.timeout.connect(self._flush_pending_seek)

        self.track_count = 0
        self.track_dbs = {}
        self.output_groups = []
        self.track_boost_layers = []
        self.worker_thread = None

        self._build_ui()
        self._apply_theme()

        self.player.positionChanged.connect(self._on_pos_changed)
        self.player.durationChanged.connect(self._on_dur_changed)
        self.player.playbackStateChanged.connect(self._on_state_changed)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(6)

        self.top_bar = QWidget()
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(8, 6, 8, 6)

        self.btn_open = QPushButton("📂 Открыть аудио / видео")
        self.btn_open.clicked.connect(self.load_file)
        top_layout.addWidget(self.btn_open)

        self.lbl_title = QLabel("Файл не выбран")
        self.lbl_title.setStyleSheet(
            "font-size: 13px; font-weight: bold; padding-left: 8px;"
        )
        top_layout.addWidget(self.lbl_title, 1)

        self.combo_preview_q = QComboBox()
        self.combo_preview_q.addItems(
            [
                "Предпросмотр: Оригинал",
                "Предпросмотр: 720p",
                "Предпросмотр: 480p",
                "Предпросмотр: 360p",
            ]
        )
        self.combo_preview_q.currentIndexChanged.connect(
            self._on_preview_quality_changed
        )
        self.combo_preview_q.hide()
        top_layout.addWidget(self.combo_preview_q)

        self.btn_tracks = QPushButton("Дорожки")
        self.btn_tracks.clicked.connect(self.open_tracks_dialog)
        self.btn_tracks.hide()
        top_layout.addWidget(self.btn_tracks)

        self.btn_settings = QPushButton("⚙ Настройки")
        self.btn_settings.clicked.connect(self.open_settings_dialog)
        top_layout.addWidget(self.btn_settings)

        main_layout.addWidget(self.top_bar)

        # === [БЛОК 26: ОБЛАСТЬ ВИДЕО, АУДИОВОЛНЫ И ПАНЕЛЬ УПРАВЛЕНИЯ] ===
        self.stack = QStackedWidget()
        self.video_widget = ClickableVideoWidget(
            self.toggle_play, self.toggle_fullscreen
        )
        self.video_widget.on_context_menu = self._open_video_context_menu
        self.video_widget.setMinimumHeight(140)
        self.player.setVideoOutput(self.video_widget.video_item)

        self.wave_scroll = QScrollArea()
        self.wave_scroll.setWidgetResizable(False)
        self.wave_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.wave_scroll.setStyleSheet("border: none;")
        self.wave_widget = AudioWaveformWidget(self.seek_to)
        self.wave_widget.zoom_wheel_requested.connect(self._step_zoom)
        self.wave_scroll.setWidget(self.wave_widget)

        self.stack.addWidget(self.video_widget)
        self.stack.addWidget(self.wave_scroll)
        main_layout.addWidget(self.stack, 1)

        self.fs_seek_slider = ClickableSeekSlider()
        self.fs_seek_slider.setFixedHeight(20)
        self.fs_seek_slider.seek_requested.connect(self._on_seek_ratio)
        self.fs_seek_slider.hide()
        main_layout.addWidget(self.fs_seek_slider)

        self.ctrl_bar = QWidget()
        ctrl_layout = QHBoxLayout(self.ctrl_bar)
        ctrl_layout.setContentsMargins(8, 5, 8, 5)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(42)
        self.btn_play.clicked.connect(self.toggle_play)
        ctrl_layout.addWidget(self.btn_play)

        self.lbl_time = QLabel("00:00.00  |  00:00.00")
        ctrl_layout.addWidget(self.lbl_time)

        self.lbl_trim_info = QLabel("Обрезка: 00:00.00 — 00:00.00")
        ctrl_layout.addWidget(self.lbl_trim_info)
        # === [БЛОК 27: ГРОМКОСТЬ, ПОЛНЫЙ ЭКРАН И ТАЙМЛАЙН ОБРЕЗКИ] ===
        self.lbl_vol_icon = QLabel("♪")
        ctrl_layout.addWidget(self.lbl_vol_icon)

        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(80)
        self.vol_slider.setMinimumWidth(90)
        self.vol_slider.valueChanged.connect(self._on_master_volume)
        ctrl_layout.addWidget(self.vol_slider, 1)

        self.lbl_master_pct = QLabel("80%")
        self.lbl_master_pct.setFixedWidth(38)
        ctrl_layout.addWidget(self.lbl_master_pct)

        self.btn_full = QPushButton("⛶")
        self.btn_full.setFixedWidth(36)
        self.btn_full.clicked.connect(self.toggle_fullscreen)
        self.btn_full.hide()
        ctrl_layout.addWidget(self.btn_full)
        main_layout.addWidget(self.ctrl_bar)

        self.bottom_panel = QWidget()
        bot_layout = QVBoxLayout(self.bottom_panel)
        bot_layout.setContentsMargins(0, 0, 0, 0)
        bot_layout.setSpacing(6)

        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(False)
        self.timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.timeline_scroll.setStyleSheet("border: none;")

        self.timeline_container = QWidget()
        tl_vbox = QVBoxLayout(self.timeline_container)
        tl_vbox.setContentsMargins(0, 2, 0, 2)
        tl_vbox.setSpacing(2)

        self.seek_slider = ClickableSeekSlider()
        self.seek_slider.setFixedHeight(22)
        self.seek_slider.seek_requested.connect(self._on_seek_ratio)
        self.seek_slider.zoom_wheel_requested.connect(self._step_zoom)
        self.seek_slider.hide()
        tl_vbox.addWidget(self.seek_slider)

        self.trim_slider = DualTrimSlider(self._on_trim_changed)
        self.trim_slider.zoom_wheel_requested.connect(self._step_zoom)
        tl_vbox.addWidget(self.trim_slider)

        self.timeline_scroll.setWidget(self.timeline_container)
        self.timeline_scroll.setFixedHeight(58)
        bot_layout.addWidget(self.timeline_scroll)
        # === [БЛОК 28: НИЖНЯЯ ПАНЕЛЬ (ПОДСКАЗКА ПКМ, ЭКСПОРТ ПО ЦЕНТРУ И ЗУМ СПРАВА)] ===
        export_grid = QGridLayout()
        export_grid.setContentsMargins(0, 0, 0, 0)
        export_grid.setColumnStretch(0, 1)
        export_grid.setColumnStretch(1, 0)
        export_grid.setColumnStretch(2, 1)

        hint_box = QHBoxLayout()
        self.lbl_cut_hint = QLabel("ПКМ по шкале — добавить или удалить обрезку")
        self.lbl_cut_hint.setStyleSheet(
            "font-size: 11px; color: #888888; background: transparent;"
        )
        hint_box.addWidget(self.lbl_cut_hint)
        hint_box.addStretch(1)
        export_grid.addLayout(hint_box, 0, 0)

        self.btn_export = QPushButton("Экспорт")
        self.btn_export.clicked.connect(self.open_export_dialog)
        export_grid.addWidget(self.btn_export, 0, 1, Qt.AlignCenter)

        zoom_box = QHBoxLayout()
        zoom_box.addStretch(1)
        self.lbl_zoom_icon = QLabel("🔍")
        zoom_box.addWidget(self.lbl_zoom_icon)

        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(100, 1000)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(115)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        zoom_box.addWidget(self.zoom_slider)

        self.lbl_zoom_pct = QLabel("100%")
        self.lbl_zoom_pct.setFixedWidth(42)
        zoom_box.addWidget(self.lbl_zoom_pct)

        export_grid.addLayout(zoom_box, 0, 2)
        bot_layout.addLayout(export_grid)
        main_layout.addWidget(self.bottom_panel)

        QShortcut(QKeySequence("Ctrl++"), self, activated=lambda: self._step_zoom(25))
        QShortcut(QKeySequence("Ctrl+="), self, activated=lambda: self._step_zoom(25))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self._step_zoom(-25))

    # === [БЛОК 29: СОБЫТИЯ ОКНА, DRAG & DROP И УМНЫЙ ПЛАВНЫЙ ЗУМ] ===
    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._update_zoomed_widths)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._recalculate_dynamic_zoom_limit()
        self._update_zoomed_widths()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    ext = Path(url.toLocalFile()).suffix.lower().lstrip(".")
                    if ext in VIDEO_EXTS or ext in AUDIO_EXTS:
                        event.acceptProposedAction()
                        return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                ext = p.suffix.lower().lstrip(".")
                if ext in VIDEO_EXTS or ext in AUDIO_EXTS:
                    event.acceptProposedAction()
                    self._open_media_path(str(p))
                    return

    def _recalculate_dynamic_zoom_limit(self):
        if self.duration <= 0:
            self.max_timeline_zoom = 1000
        else:
            vp_w = max(200, self.timeline_scroll.viewport().width())
            fps = max(10.0, self.video_fps) if self.is_video else 50.0
            total_frames = self.duration * fps
            target_max_px = total_frames * 2.0
            calc_max = int(round((target_max_px / vp_w) * 100.0))
            self.max_timeline_zoom = max(300, min(150000, calc_max))

        self.zoom_slider.setRange(100, self.max_timeline_zoom)
        if self.zoom_slider.value() > self.max_timeline_zoom:
            self.zoom_slider.setValue(self.max_timeline_zoom)

    def _calc_smooth_zoom_step(self, cur_zoom: int) -> int:
        if cur_zoom < 600:
            return 50
        if cur_zoom < 2000:
            return max(75, int(cur_zoom * 0.12))
        if cur_zoom < 10000:
            return max(250, int(cur_zoom * 0.14))
        return max(1200, int(cur_zoom * 0.16))

    def _step_zoom(self, direction: int, cursor_ratio: float = None):
        cur = self.zoom_slider.value()
        step = self._calc_smooth_zoom_step(cur)
        new_val = max(
            100, min(self.max_timeline_zoom, cur + (step if direction > 0 else -step))
        )
        self._zoom_cursor_ratio = cursor_ratio
        self.zoom_slider.setValue(new_val)

    def _on_zoom_changed(self, val: int):
        self.timeline_zoom = val
        self.lbl_zoom_pct.setText(f"{val}%")
        self._update_zoomed_widths()

    # === [БЛОК 30: ОБНОВЛЕНИЕ МАСШТАБА (ПОД КУРСОРОМ ИЛИ ПЛАВНО К ПОЛЗУНКУ) И ПРИМЕНЕНИЕ ТЕМЫ] ===
    def _tick_smooth_scroll(self):
        done = True
        if self._target_tl_scroll is not None:
            sb = self.timeline_scroll.horizontalScrollBar()
            cur = sb.value()
            diff = self._target_tl_scroll - cur
            if abs(diff) <= 2:
                sb.setValue(self._target_tl_scroll)
                self._target_tl_scroll = None
            else:
                step = int(diff * 0.28)
                if step == 0:
                    step = 1 if diff > 0 else -1
                sb.setValue(cur + step)
                done = False

        if self._target_wave_scroll is not None:
            wsb = self.wave_scroll.horizontalScrollBar()
            wcur = wsb.value()
            wdiff = self._target_wave_scroll - wcur
            if abs(wdiff) <= 2:
                wsb.setValue(self._target_wave_scroll)
                self._target_wave_scroll = None
            else:
                wstep = int(wdiff * 0.28)
                if wstep == 0:
                    wstep = 1 if wdiff > 0 else -1
                wsb.setValue(wcur + wstep)
                done = False

        if done:
            self._smooth_scroll_timer.stop()

    def _update_zoomed_widths(self):
        factor = self.timeline_zoom / 100.0
        vp_w = max(100, self.timeline_scroll.viewport().width())
        old_tl_w = max(1, self.timeline_container.width())
        old_sb_val = self.timeline_scroll.horizontalScrollBar().value()
        new_tl_w = int(vp_w * factor)

        tl_h = 78 if self.is_video else 54
        self.timeline_scroll.setFixedHeight(tl_h)
        self.timeline_container.setFixedSize(new_tl_w, tl_h - 16)

        base_wave_w = max(100, self.wave_scroll.viewport().width())
        base_wave_h = max(100, self.wave_scroll.viewport().height())
        old_wave_w = max(1, self.wave_widget.width())
        old_wsb_val = self.wave_scroll.horizontalScrollBar().value()
        new_wave_w = int(base_wave_w * factor)
        self.wave_widget.setFixedSize(new_wave_w, base_wave_h)

        if self._zoom_cursor_ratio is not None:
            c_ratio = self._zoom_cursor_ratio
            self._zoom_cursor_ratio = None
            self._target_tl_scroll = None
            self._target_wave_scroll = None
            self._smooth_scroll_timer.stop()

            cursor_screen_offset_tl = (c_ratio * old_tl_w) - old_sb_val
            new_sb_tl = int(round((c_ratio * new_tl_w) - cursor_screen_offset_tl))
            self.timeline_scroll.horizontalScrollBar().setValue(max(0, new_sb_tl))

            cursor_screen_offset_wv = (c_ratio * old_wave_w) - old_wsb_val
            new_sb_wv = int(round((c_ratio * new_wave_w) - cursor_screen_offset_wv))
            self.wave_scroll.horizontalScrollBar().setValue(max(0, new_sb_wv))
        else:
            ratio = (
                (self.player.position() / 1000.0) / self.duration
                if self.duration > 0
                else 0.0
            )
            self._target_tl_scroll = max(
                0, min(max(0, new_tl_w - vp_w), int(ratio * new_tl_w) - vp_w // 2)
            )
            self._target_wave_scroll = max(
                0,
                min(
                    max(0, new_wave_w - base_wave_w),
                    int(ratio * new_wave_w) - base_wave_w // 2,
                ),
            )
            if not self._smooth_scroll_timer.isActive():
                self._smooth_scroll_timer.start()

    def _apply_theme(self):
        is_dark = self.settings.get("dark_mode", True)
        accent = self.settings.get("accent", "#FF9900")
        btn_fg = get_contrast_text_color(accent)
        set_windows_titlebar_theme(self, is_dark)

        win_bg = "#181818" if is_dark else "#F4F4F5"
        panel_bg = "#222222" if is_dark else "#E4E4E7"
        fg = "#EEEEEE" if is_dark else "#18181B"
        sub_fg = "#BBBBBB" if is_dark else "#52525B"
        btn_sec_bg = "#333333" if is_dark else "#D4D4D8"
        time_bg = "#111111" if is_dark else "#FFFFFF"

        self.setStyleSheet(
            f"QMainWindow, QWidget {{ background-color: {win_bg}; color: {fg}; font-family: Arial; }}"
        )
        self.top_bar.setStyleSheet(f"background-color: {panel_bg}; border-radius: 4px;")
        self.ctrl_bar.setStyleSheet(
            f"background-color: {panel_bg}; border-radius: 4px;"
        )
        self.video_widget.setStyleSheet(
            "background-color: #0D0D0D; border: none;"
            if is_dark
            else "background-color: #E4E4E7; border: none;"
        )
        # === [БЛОК 31: СТИЛИ КНОПОК И ПОЛЗУНКОВ ГЛАВНОГО ОКНА] ===
        self.btn_open.setStyleSheet(
            f"background-color: {accent}; color: {btn_fg}; font-weight: bold; padding: 6px 14px; border-radius: 3px;"
        )
        self.btn_play.setStyleSheet(
            f"background-color: {accent}; color: {btn_fg}; font-family: 'Segoe UI Symbol'; font-size: 15px; font-weight: bold; padding: 5px; border-radius: 3px;"
        )
        self.btn_export.setStyleSheet(
            f"background-color: {accent}; color: {btn_fg}; font-size: 13px; font-weight: bold; padding: 8px 32px; border-radius: 4px;"
        )
        self.btn_tracks.setStyleSheet(
            f"background-color: {btn_sec_bg}; color: {accent}; font-weight: bold; padding: 6px 12px; border-radius: 3px;"
        )
        self.combo_preview_q.setStyleSheet(
            f"background-color: {btn_sec_bg}; color: {fg}; padding: 5px; border-radius: 3px;"
        )
        self.btn_settings.setStyleSheet(
            f"background-color: {btn_sec_bg}; color: {fg}; font-weight: bold; padding: 6px 12px; border-radius: 3px;"
        )
        self.btn_full.setStyleSheet(
            f"background-color: {btn_sec_bg}; color: {fg}; font-size: 14px; font-weight: bold; padding: 4px; border-radius: 3px;"
        )

        self.lbl_time.setStyleSheet(
            f"background-color: {time_bg}; color: {accent}; font-family: Consolas; font-size: 14px; font-weight: bold; padding: 5px 12px; border-radius: 3px;"
        )
        self.lbl_trim_info.setStyleSheet(
            f"color: {sub_fg}; font-size: 11px; padding: 0 10px; background: transparent;"
        )
        self.lbl_vol_icon.setStyleSheet(
            f"color: {accent}; font-size: 14px; font-weight: bold; background: transparent;"
        )
        self.lbl_master_pct.setStyleSheet(
            f"color: {accent}; font-weight: bold; font-size: 11px; background: transparent;"
        )
        self.lbl_zoom_icon.setStyleSheet(
            f"color: {accent}; font-size: 12px; background: transparent;"
        )
        self.lbl_zoom_pct.setStyleSheet(
            f"color: {accent}; font-weight: bold; font-size: 11px; background: transparent;"
        )

        groove_bg = "#333333" if is_dark else "#CBD5E1"
        slider_css = f"""
            QSlider::groove:horizontal {{ height: 6px; background: {groove_bg}; border-radius: 3px; }}
            QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 3px; }}
            QSlider::handle:horizontal {{ background: #FFFFFF; border: 2px solid {accent}; width: 12px; margin: -4px 0; border-radius: 7px; }}
        """
        self.seek_slider.setStyleSheet(slider_css)
        self.fs_seek_slider.setStyleSheet(slider_css)

        self.wave_widget.set_theme(accent, is_dark)
        self.trim_slider.accent_color = accent
        self.trim_slider.dark_mode = is_dark
        self.trim_slider.sync_seek = self.settings.get("sync_seek_with_trim", False)
        self.trim_slider.update()

    # === [БЛОК 32: ВРЕМЯ ДО СОТЫХ СЕКУНДЫ, ГОРЯЧИЕ КЛАВИШИ, ПОЛНЫЙ ЭКРАН И ДИАЛОГИ] ===
    def _format_time(self, sec):
        sec = max(0.0, sec)
        total_secs = int(sec)
        hrs = total_secs // 3600
        mins = (total_secs % 3600) // 60
        rem = sec - (hrs * 3600 + mins * 60)
        if hrs > 0 or self.duration >= 3600:
            return f"{hrs:02d}:{mins:02d}:{rem:05.2f}"
        return f"{mins:02d}:{rem:05.2f}"

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key_F11
            or event.key() == Qt.Key_Escape
            and self.isFullScreen()
        ):
            self.toggle_fullscreen()
        elif event.key() == Qt.Key_Space:
            self.toggle_play()
        elif event.key() == Qt.Key_Left:
            step = 1.0 if (event.modifiers() & Qt.ShiftModifier) else 0.01
            self.seek_to(
                max(0.0, round((self.player.position() / 1000.0) - step, 2)), True
            )
        elif event.key() == Qt.Key_Right:
            step = 1.0 if (event.modifiers() & Qt.ShiftModifier) else 0.01
            self.seek_to(
                min(self.duration, round((self.player.position() / 1000.0) + step, 2)),
                True,
            )

    def toggle_fullscreen(self):
        if not self.is_video:
            return
        if self.isFullScreen():
            self.showNormal()
            self.top_bar.show()
            self.bottom_panel.show()
            self.fs_seek_slider.hide()
            self.btn_full.setText("⛶")
        else:
            self.top_bar.hide()
            self.bottom_panel.hide()
            self.fs_seek_slider.show()
            self.btn_full.setText("🗗")
            self.showFullScreen()

    def open_settings_dialog(self):
        dlg = SettingsDialog(self, self.settings, self._apply_theme)
        dlg.exec()

    def open_tracks_dialog(self):
        if self.track_count <= 0:
            QMessageBox.information(
                self, "Дорожки", "В этом файле не найдено звуковых дорожек."
            )
            return
        self._ensure_track_boost_layers()
        dlg = AudioTracksDialog(
            self,
            self.track_count,
            self.track_dbs,
            self.output_groups,
            self._on_single_track_db,
            self._update_tracks_btn_label,
            self.settings.get("accent", "#FF9900"),
            self.settings.get("dark_mode", True),
        )
        dlg.exec()

    # === [БЛОК 33: ПОТОКОВЫЙ МИКШЕР И ОЧИСТКА КЭША] ===
    def _ensure_track_boost_layers(self):
        if self.track_boost_layers or not self.is_video or self.track_count <= 0:
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(32000)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Int16)

        for idx in range(self.track_count):
            stream = GainAudioStream(
                str(self.file_path), idx, sample_rate=32000, channels=2
            )
            sink = QAudioSink(fmt, self)
            sink.setVolume(self.master_volume)
            self.track_boost_layers.append((sink, stream))

        if self.player.playbackState() == QMediaPlayer.PlayingState:
            pos_sec = self.player.position() / 1000.0
            for sink, stream in self.track_boost_layers:
                stream.set_position_sec(pos_sec)
                sink.start(stream)
        self._apply_all_volumes()

    def _cleanup_cache_files(self):
        if self.cache_dir.exists():
            for f in self.cache_dir.iterdir():
                try:
                    f.unlink()
                except Exception:
                    pass

    def closeEvent(self, event):
        self.player.stop()
        self.gpu_scrub_worker.stop_worker()
        self.cpu_scrub_worker.stop_worker()
        self._clear_track_players()
        self._cleanup_cache_files()
        try:
            self.cache_dir.rmdir()
        except Exception:
            pass
        super().closeEvent(event)

    def _clear_track_players(self):
        for sink, stream in self.track_boost_layers:
            sink.stop()
            stream.close()
            sink.deleteLater()
            stream.deleteLater()
        self.track_boost_layers.clear()

    # === [БЛОК 34: УПРАВЛЕНИЕ ГРОМКОСТЬЮ И ЧТЕНИЕ ИНФОРМАЦИИ О МЕДИА] ===
    def _raw_db_to_real_gain(self, raw_val: int) -> float:
        if raw_val <= MUTE_DB_VAL:
            return 0.0
        db = raw_val / 10.0
        return min(16.0, 10.0 ** (db / 20.0))

    def _needs_custom_audio_mixer(self) -> bool:
        if not self.is_video or self.track_count <= 0:
            return False
        if self.track_count > 1:
            return True
        return self.track_dbs.get(0, 0) != 0

    def _apply_all_volumes(self):
        if self._needs_custom_audio_mixer():
            self._ensure_track_boost_layers()
            self.audio_out.setVolume(0.0)
            for idx, (sink, stream) in enumerate(self.track_boost_layers):
                raw_db = self.track_dbs.get(idx, 0)
                stream.gain = self._raw_db_to_real_gain(raw_db) * self.master_volume
                sink.setVolume(self.master_volume)
        else:
            if self.track_boost_layers:
                self._clear_track_players()
            self.audio_out.setVolume(min(1.0, self.master_volume))

    def _on_master_volume(self, val):
        self.master_volume = val / 100.0
        self.lbl_master_pct.setText(f"{val}%")
        self._apply_all_volumes()

    def _on_single_track_db(self, t_idx, raw_val):
        self.track_dbs[t_idx] = raw_val
        self._apply_all_volumes()
        if (
            self.player.playbackState() == QMediaPlayer.PlayingState
            and self.track_boost_layers
        ):
            pos_sec = self.player.position() / 1000.0
            for sink, stream in self.track_boost_layers:
                if sink.state() != QAudio.State.ActiveState:
                    stream.set_position_sec(pos_sec)
                    sink.start(stream)

    def _update_tracks_btn_label(self):
        src_cnt = self.track_count
        out_cnt = len(self.output_groups)
        if out_cnt < src_cnt:
            self.btn_tracks.setText(f"Дорожки ({src_cnt} → {out_cnt})")
        else:
            self.btn_tracks.setText(f"Дорожки ({src_cnt})")

    def _probe_media_info(self, path_str):
        cmd = [FFMPEG_BIN, "-i", path_str]
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags
        )
        info = res.stderr.decode("utf-8", errors="ignore")
        dur = 0.0
        dur_m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
        if dur_m:
            dur = (
                int(dur_m.group(1)) * 3600
                + int(dur_m.group(2)) * 60
                + float(dur_m.group(3))
            )

        fps = 30.0
        fps_m = re.search(r"Video:.*?(\d+(?:\.\d+)?)\s*fps", info)
        if fps_m:
            try:
                parsed_fps = float(fps_m.group(1))
                if 5.0 <= parsed_fps <= 240.0:
                    fps = parsed_fps
            except Exception:
                pass

        src_w, src_h = 1920, 1080
        res_m = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", info)
        if res_m:
            try:
                src_w, src_h = int(res_m.group(1)), int(res_m.group(2))
            except Exception:
                pass

        audio_cnt = sum(1 for line in info.splitlines() if "Audio:" in line)
        return dur, audio_cnt, fps, src_w, src_h

    # === [БЛОК 35: ЗАПУСК FFMPEG С ПРОГРЕССОМ И ПАПКИ ПО УМОЛЧАНИЮ] ===
    def _run_ffmpeg_with_progress(
        self, cmd, total_dur, title, header, cleanup_paths=None, silent_err=False
    ) -> bool:
        dlg = ProgressDialog(
            self,
            title,
            header,
            self.settings.get("accent", "#FF9900"),
            self.settings.get("dark_mode", True),
        )
        thread = FFmpegTaskThread(cmd, total_dur)
        self.worker_thread = thread
        result_ok = {"status": False}

        thread.progress_updated.connect(dlg.update_state)
        dlg.btn_cancel.clicked.connect(thread.cancel)

        def _ok():
            result_ok["status"] = True
            dlg.accept()

        def _cancel():
            if cleanup_paths:
                for p in cleanup_paths:
                    try:
                        Path(p).unlink(missing_ok=True)
                    except Exception:
                        pass
            dlg.reject()

        def _err(msg):
            dlg.reject()
            if not silent_err:
                QMessageBox.critical(self, "Ошибка", f"Операция прервана:\n{msg}")

        thread.finished_ok.connect(_ok)
        thread.finished_cancelled.connect(_cancel)
        thread.finished_err.connect(_err)
        thread.start()
        dlg.exec()
        return result_ok["status"]

    def _get_target_dir(self) -> str:
        if self.settings.get("open_last_dir", True):
            last_p = Path(self.settings.get("last_export_dir", str(SCRIPT_DIR)))
            if last_p.exists():
                return str(last_p)
        def_p = Path(self.settings.get("default_dir", str(SCRIPT_DIR)))
        return str(def_p) if def_p.exists() else str(SCRIPT_DIR)

    # === [БЛОК 36.1: ОТКРЫТИЕ ФАЙЛОВ И СИНХРОНИЗАЦИЯ НАСТРОЕК] ===
    def load_file(self):
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Выберите аудио или видео", self._get_target_dir()
        )
        if path_str:
            self._open_media_path(path_str)

    def _get_preview_height(self) -> int:
        res_map = {
            "4320p (8K)": 4320,
            "2160p (4K)": 2160,
            "1440p (2K)": 1440,
            "1080p": 1080,
            "720p": 720,
            "480p": 480,
            "360p": 360,
            "240p": 240,
            "144p": 144,
        }
        cfg_sr = self.settings.get("scrub_resolution", "360p")
        if "Оригинал" in cfg_sr:
            return 0
        return res_map.get(cfg_sr, 360)

    def _on_settings_scrub_res_changed(self, _new_res: str):
        if not self.is_video or not self.file_path:
            return
        self._restart_scrub_grid(
            with_modal_progress=self.settings.get("preload_frames_dialog", False)
        )
        cur_sec = self.trim_slider.playhead_sec
        if self.player.playbackState() != QMediaPlayer.PlayingState:
            self._show_nearest_cached_frame(cur_sec, request_dense_strip=True)

    def _open_media_path(self, path_str: str):
        candidate = Path(path_str)
        if not candidate.exists():
            return

        self.player.stop()
        self._clear_track_players()
        self._cleanup_cache_files()
        self.trim_slider.reset_segments(0.0)
        self.frame_cache.clear()
        self._last_scrub_centis = -1
        self._scrub_anchor_sec = 0.0
        self.video_widget.clear_scrub_frame()
        self.load_counter += 1

        ext = candidate.suffix.lower().lstrip(".")
        is_vid = ext in VIDEO_EXTS
        probed_dur, probed_audio_cnt, probed_fps, probed_w, probed_h = (
            self._probe_media_info(str(candidate))
        )

        self.file_path = candidate
        self.duration = probed_dur
        self.video_fps = probed_fps
        self.video_src_w = probed_w
        self.video_src_h = probed_h
        self.trim_slider.video_fps = probed_fps
        self.lbl_title.setText(self.file_path.name)

        if is_vid:
            self.is_video = True
            self.stack.setCurrentIndex(0)
            self.seek_slider.show()
            self.btn_full.show()
            self.btn_tracks.show()

            self.combo_preview_q.blockSignals(True)
            self.combo_preview_q.setCurrentIndex(0)
            self.combo_preview_q.blockSignals(False)
            self.combo_preview_q.show()

            self.track_count = probed_audio_cnt
            self.track_dbs = {i: 0 for i in range(self.track_count)}
            self.output_groups = [[i] for i in range(self.track_count)]
            self._update_tracks_btn_label()

            if probed_audio_cnt > 1:
                self._ensure_track_boost_layers()

            self._recalculate_dynamic_zoom_limit()
            self._restart_scrub_grid(
                with_modal_progress=self.settings.get("preload_frames_dialog", False)
            )
        else:
            self.gpu_scrub_worker.configure("", self.load_counter, 0)
            self.cpu_scrub_worker.configure("", self.load_counter, 0)
            wav_path = self.cache_dir / f"wave_{self.load_counter}.wav"
            cmd = [
                FFMPEG_BIN,
                "-y",
                "-vn",
                "-sn",
                "-dn",
                "-threads",
                "0",
                "-i",
                str(candidate),
                "-ac",
                "1",
                "-ar",
                "8000",
                str(wav_path),
            ]
            ok = self._run_ffmpeg_with_progress(
                cmd,
                probed_dur,
                "Загрузка аудио",
                f"Построение волны: {candidate.name}",
                cleanup_paths=[wav_path],
            )
            if not ok:
                return

            self.is_video = False
            if self.isFullScreen():
                self.toggle_fullscreen()
            self.stack.setCurrentIndex(1)
            self.seek_slider.hide()
            self.fs_seek_slider.hide()
            self.btn_full.hide()
            self.btn_tracks.hide()
            self.combo_preview_q.hide()
            self.track_count = 0
            self.output_groups = []
            self._recalculate_dynamic_zoom_limit()

            if wav_path.exists() and wav_path.stat().st_size > 44:
                raw = wav_path.read_bytes()
                pcm = np.frombuffer(raw.__getitem__(slice(44, None)), dtype=np.int16)
                self.wave_widget.set_waveform(pcm)

        self._apply_all_volumes()
        if self.is_video:
            self.video_widget.set_preview_resolution(0)
            self.player.setVideoOutput(self.video_widget.video_item)
        self.player.setSource(QUrl.fromLocalFile(str(self.file_path)))
        self.player.pause()
        self.player.setPosition(0)
        self._update_zoomed_widths()

    # === [БЛОК 36.2: ЗАПУСК ОПОРНЫХ КАДРОВ И ОКНО ПРОГРЕССА С ETA] ===
    def _restart_scrub_grid(self, with_modal_progress: bool = False):
        if not self.is_video or not self.file_path or self.duration <= 0:
            return
        self.frame_cache.clear()
        h = self._get_preview_height()
        sw = getattr(self, "video_src_w", 1920)
        sh = getattr(self, "video_src_h", 1080)
        self.gpu_scrub_worker.configure(
            str(self.file_path), self.load_counter, h, self.video_fps, sw, sh
        )
        self.cpu_scrub_worker.configure(
            str(self.file_path), self.load_counter, h, self.video_fps, sw, sh
        )

        self.gpu_scrub_worker.request_frames(
            [int(round(self._scrub_anchor_sec * 1000))], high_priority=True
        )

        if with_modal_progress:
            res_name = self.settings.get("scrub_resolution", "360p")
            dlg = ProgressDialog(
                self,
                "Быстрая индексация кадров",
                f"Загрузка опорных кадров ({res_name})...",
                self.settings.get("accent", "#FF9900"),
                self.settings.get("dark_mode", True),
            )
            state = {"cancelled": False, "start_t": time.time()}

            def _on_prog(done_cnt, total_cnt):
                if state["cancelled"]:
                    return
                pct = min(100, int((done_cnt / max(1, total_cnt)) * 100))
                elapsed = time.time() - state["start_t"]
                if pct > 3 and elapsed > 0.2:
                    eta_sec = int((elapsed / pct) * (100 - pct))
                    mins, secs = divmod(max(0, eta_sec), 60)
                    eta_str = f"Опорные: {done_cnt}/{total_cnt}  •  Осталось: ~{mins:02d}:{secs:02d}"
                else:
                    eta_str = f"Опорные: {done_cnt}/{total_cnt}  •  Расчёт времени..."
                dlg.update_state(pct, eta_str)
                if done_cnt >= total_cnt:
                    dlg.accept()

            def _on_cancel():
                state["cancelled"] = True
                self.gpu_scrub_worker.configure(
                    str(self.file_path), self.load_counter, h, self.video_fps, sw, sh
                )
                self.cpu_scrub_worker.configure(
                    str(self.file_path), self.load_counter, h, self.video_fps, sw, sh
                )
                dlg.reject()

            self.cpu_scrub_worker.batch_progress.connect(_on_prog)
            dlg.btn_cancel.clicked.connect(_on_cancel)

            self.cpu_scrub_worker.request_tiered_grid(
                self.duration, self._scrub_anchor_sec, track_initial=True
            )
            dlg.exec()

            try:
                self.cpu_scrub_worker.batch_progress.disconnect(_on_prog)
            except Exception:
                pass
        else:
            self.cpu_scrub_worker.request_tiered_grid(
                self.duration, self._scrub_anchor_sec, track_initial=False
            )

    # === [БЛОК 36.3: НАКОПИТЕЛЬНЫЙ КЭШ КАДРОВ, КОНТЕКСТНОЕ МЕНЮ ВИДЕО (ПКМ) И ПРЕДПРОСМОТР] ===
    def _on_scrub_frame_ready(self, load_id: int, sec_millis: int, qimg: QImage):
        if load_id != self.load_counter:
            return
        pix = QPixmap.fromImage(qimg)
        if len(self.frame_cache) > 2500:
            oldest_key = next(iter(self.frame_cache))
            self.frame_cache.pop(oldest_key, None)
        self.frame_cache[sec_millis] = pix

        if (
            self._last_scrub_centis >= 0
            and abs(sec_millis - self._last_scrub_centis) <= 350
        ):
            if self.player.playbackState() != QMediaPlayer.PlayingState:
                self.video_widget.set_scrub_frame(pix)

    def _show_nearest_cached_frame(self, sec: float, request_dense_strip: bool = False):
        if not self.is_video or not self.file_path or self.duration <= 0:
            return
        target_ms = int(round(sec * 1000))
        self._last_scrub_centis = target_ms

        nearest_diff = 999999999
        if target_ms in self.frame_cache:
            self.video_widget.set_scrub_frame(self.frame_cache[target_ms])
            nearest_diff = 0
        elif self.frame_cache:
            nearest_key = min(self.frame_cache.keys(), key=lambda k: abs(k - target_ms))
            nearest_diff = abs(nearest_key - target_ms)
            self.video_widget.set_scrub_frame(self.frame_cache[nearest_key])

        if request_dense_strip:
            self.gpu_scrub_worker.request_frames([target_ms], high_priority=True)
            for delta in (-15, 15, -25, 25, -45, 45, -90, 90, -180, 180):
                cand_sec = sec + delta
                if 0.0 <= cand_sec <= self.duration:
                    cand_ms = int(round(cand_sec * 1000))
                    if all(abs(k - cand_ms) > 2500 for k in self.frame_cache.keys()):
                        self.gpu_scrub_worker.request_frames(
                            [cand_ms], high_priority=False
                        )
        elif nearest_diff > 1500:
            self.gpu_scrub_worker.request_frames([target_ms], high_priority=False)

    def _extract_current_fullres_qimage(self) -> QImage:
        if not self.is_video or not self.file_path:
            return QImage()
        cur_sec = self.trim_slider.playhead_sec
        tmp_png = (
            self.cache_dir / f"snap_tmp_{self.load_counter}_{int(cur_sec * 1000)}.png"
        )
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-ss",
            f"{cur_sec:.3f}",
            "-i",
            str(self.file_path),
            "-frames:v",
            "1",
            str(tmp_png),
        ]
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            timeout=4,
        )
        img = QImage(str(tmp_png)) if tmp_png.exists() else QImage()
        tmp_png.unlink(missing_ok=True)
        return img

    def copy_frame_to_clipboard(self):
        img = self._extract_current_fullres_qimage()
        if not img.isNull():
            QApplication.clipboard().setImage(img)
            self.lbl_title.setText(
                f"📋 Кадр скопирован в буфер обмена ({self.file_path.name})"
            )
            QTimer.singleShot(
                2500,
                lambda: self.lbl_title.setText(
                    self.file_path.name if self.file_path else "Файл не выбран"
                ),
            )

    def quick_save_frame_to_folder(self):
        if not self.is_video or not self.file_path:
            return
        cur_sec = self.trim_slider.playhead_sec
        out_png = (
            Path(self._get_target_dir()) / f"{self.file_path.stem}_{cur_sec:.2f}s.png"
        )
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-ss",
            f"{cur_sec:.3f}",
            "-i",
            str(self.file_path),
            "-frames:v",
            "1",
            str(out_png),
        ]
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            timeout=4,
        )
        if out_png.exists():
            self.lbl_title.setText(f"⚡ Скриншот сохранён: {out_png.name}")
            QTimer.singleShot(
                2500,
                lambda: self.lbl_title.setText(
                    self.file_path.name if self.file_path else "Файл не выбран"
                ),
            )

    def save_frame_screenshot(self):
        if not self.is_video or not self.file_path:
            return
        cur_sec = self.trim_slider.playhead_sec
        default_path = str(
            Path(self._get_target_dir()) / f"{self.file_path.stem}_{cur_sec:.2f}s.png"
        )
        out_file, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить кадр как...",
            default_path,
            "PNG изображение (*.png);;JPEG изображение (*.jpg)",
        )
        if not out_file:
            return
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        cmd = [
            FFMPEG_BIN,
            "-y",
            "-ss",
            f"{cur_sec:.3f}",
            "-i",
            str(self.file_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            out_file,
        ]
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            timeout=4,
        )
        QMessageBox.information(
            self, "Скриншот", f"Кадр сохранён:\n{Path(out_file).name}"
        )

    def _open_video_context_menu(self, global_pos):
        if not self.is_video or not self.file_path:
            return
        menu = QMenu(self)
        act_copy = menu.addAction("📋 Копировать кадр в буфер обмена")
        act_save_as = menu.addAction("💾 Сохранить кадр как...")
        act_quick = menu.addAction("⚡ Быстрый скриншот в папку сохранения")
        menu.addSeparator()
        act_fs = menu.addAction(
            "🗗 Выйти из полного экрана" if self.isFullScreen() else "⛶ На весь экран"
        )

        chosen = menu.exec(global_pos)
        if chosen == act_copy:
            self.copy_frame_to_clipboard()
        elif chosen == act_save_as:
            self.save_frame_screenshot()
        elif chosen == act_quick:
            self.quick_save_frame_to_folder()
        elif chosen == act_fs:
            self.toggle_fullscreen()

    def _on_preview_quality_changed(self, _idx: int):
        if not self.is_video:
            return
        q_text = self.combo_preview_q.currentText()
        target_h = (
            720
            if "720p" in q_text
            else (480 if "480p" in q_text else (360 if "360p" in q_text else 0))
        )
        self.video_widget.set_preview_resolution(target_h)
        if target_h > 0:
            self.player.setVideoOutput(self.video_widget.video_sink)
        else:
            self.player.setVideoOutput(self.video_widget.video_item)

    # === [БЛОК 37: ПОКАДРОВАЯ ПЕРЕМОТКА, ПЕРЕХОД МЕЖДУ ОТРЕЗКАМИ И ВОСПРОИЗВЕДЕНИЕ] ===
    def _on_dur_changed(self, dur_ms):
        self.duration = dur_ms / 1000.0
        self.trim_slider.reset_segments(self.duration)
        self.wave_widget.duration = self.duration
        self.wave_widget.start_trim = 0.0
        self.wave_widget.end_trim = self.duration
        self.wave_widget.update()
        self._update_labels(0.0)
        if self.is_video:
            self._recalculate_dynamic_zoom_limit()

    def _on_pos_changed(self, pos_ms):
        cur = pos_ms / 1000.0
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            ordered = sorted(self.trim_slider.segments, key=lambda item: item)
            if ordered:
                cur_idx = max(0, min(self.trim_slider.active_seg_idx, len(ordered) - 1))
                cur_s, cur_e = ordered[cur_idx]

                if cur >= cur_e - 0.015:
                    next_idx = -1
                    for i, (seg_s, seg_e) in enumerate(ordered):
                        if i > cur_idx and (seg_e - seg_s) >= 0.02:
                            next_idx = i
                            break

                    if next_idx >= 0:
                        next_s = ordered[next_idx][0]
                        self.trim_slider.segments = ordered
                        self.trim_slider.active_seg_idx = next_idx
                        self.trim_slider.playhead_sec = next_s
                        self.trim_slider.update()
                        self.wave_widget.start_trim = ordered[next_idx][0]
                        self.wave_widget.end_trim = ordered[next_idx][1]
                        self.wave_widget.current_pos = next_s
                        self.wave_widget.update()
                        self._update_labels(next_s)

                        self.player.setPosition(int(round(next_s * 1000)))
                        for sink, stream in self.track_boost_layers:
                            stream.set_position_sec(next_s)
                        return
                    else:
                        first_s = ordered[0][0]
                        self.trim_slider.segments = ordered
                        self.trim_slider.active_seg_idx = 0
                        self.player.pause()
                        self.seek_to(first_s, True)
                        return

        if (
            not self.seek_slider.is_dragging
            and not self.fs_seek_slider.is_dragging
            and self.duration > 0
        ):
            pos_val = int((cur / self.duration) * 1000000)
            self.seek_slider.setValue(pos_val)
            self.fs_seek_slider.setValue(pos_val)
        self.trim_slider.playhead_sec = cur
        self.trim_slider.update()
        self.wave_widget.current_pos = cur
        self.wave_widget.update()
        self._update_labels(cur)

    def _on_state_changed(self, state):
        is_play = state == QMediaPlayer.PlayingState
        self.gpu_scrub_worker.set_playback_active(is_play)
        self.cpu_scrub_worker.set_playback_active(is_play)
        self.btn_play.setText("⏸" if is_play else "▶")
        if is_play:
            self._last_scrub_centis = -1
            self.video_widget.clear_scrub_frame()
        pos_sec = self.player.position() / 1000.0
        for sink, stream in self.track_boost_layers:
            if is_play:
                stream.set_position_sec(pos_sec)
                if sink.state() != QAudio.State.ActiveState:
                    sink.start(stream)
            else:
                sink.stop()
                stream.stop_proc()

    def _on_seek_ratio(self, ratio: float):
        if self.duration > 0:
            is_drag = self.seek_slider.is_dragging or self.fs_seek_slider.is_dragging
            sec = round(ratio * self.duration, 2)
            self.seek_to(sec, not is_drag)

    def _on_trim_changed(self, handle, immediate=True):
        self.wave_widget.start_trim = self.trim_slider.start_trim
        self.wave_widget.end_trim = self.trim_slider.end_trim
        self.wave_widget.update()
        target = (
            self.trim_slider.start_trim
            if handle == "start"
            else self.trim_slider.end_trim
        )

        if self.settings.get("sync_seek_with_trim", False):
            self.seek_to(target, immediate)
        else:
            if (
                self.is_video
                and self.player.playbackState() != QMediaPlayer.PlayingState
            ):
                self._show_nearest_cached_frame(target, request_dense_strip=immediate)
            self._update_labels(self.trim_slider.playhead_sec)

    def _play_scrub_audio_snippet(self, sec: float):
        if not self.settings.get("scrub_audio", False):
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            return
        self.player.setPosition(int(sec * 1000))
        for sink, stream in self.track_boost_layers:
            stream.set_position_sec(sec)
            if sink.state() != QAudio.State.ActiveState:
                sink.start(stream)
        self.player.play()
        QTimer.singleShot(95, self._stop_scrub_audio_snippet)

    def _stop_scrub_audio_snippet(self):
        if (
            self.seek_slider.is_dragging
            or self.fs_seek_slider.is_dragging
            or self._pending_seek_sec is not None
        ):
            self.player.pause()

    def _flush_pending_seek(self):
        if self._pending_seek_sec is not None:
            sec = self._pending_seek_sec
            self._pending_seek_sec = None
            if (
                self.is_video
                and self.player.playbackState() != QMediaPlayer.PlayingState
            ):
                need_new_strip = abs(sec - self._scrub_anchor_sec) > 9.0
                if need_new_strip:
                    self._scrub_anchor_sec = sec
                self._show_nearest_cached_frame(sec, request_dense_strip=need_new_strip)
                if self.settings.get("scrub_audio", False):
                    self._play_scrub_audio_snippet(sec)
            else:
                self.player.setPosition(int(sec * 1000))
                for sink, stream in self.track_boost_layers:
                    stream.set_position_sec(sec)
                if self.settings.get("scrub_audio", False):
                    self._play_scrub_audio_snippet(sec)

    def seek_to(self, sec, immediate=True):
        sec = max(0.0, min(self.duration, sec))
        self.trim_slider.playhead_sec = sec
        self.trim_slider.update()
        self._update_labels(sec)
        if self.duration > 0:
            pos_val = int((sec / self.duration) * 1000000)
            if not self.seek_slider.is_dragging:
                self.seek_slider.setValue(pos_val)
            if not self.fs_seek_slider.is_dragging:
                self.fs_seek_slider.setValue(pos_val)

        if immediate:
            self._scrub_anchor_sec = sec
            self._pending_seek_sec = None
            self._seek_throttle_timer.stop()
            if (
                self.is_video
                and self.player.playbackState() != QMediaPlayer.PlayingState
            ):
                self._show_nearest_cached_frame(sec, request_dense_strip=True)
            self.player.setPosition(int(sec * 1000))
            for sink, stream in self.track_boost_layers:
                stream.set_position_sec(sec)
            if (
                self.settings.get("scrub_audio", False)
                and self.player.playbackState() != QMediaPlayer.PlayingState
            ):
                self._play_scrub_audio_snippet(sec)
        else:
            if (
                self.is_video
                and self.player.playbackState() != QMediaPlayer.PlayingState
            ):
                self._show_nearest_cached_frame(sec, request_dense_strip=False)
            self._pending_seek_sec = sec
            if not self._seek_throttle_timer.isActive():
                self._seek_throttle_timer.start()

    def toggle_play(self):
        if self.duration <= 0:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self._last_scrub_centis = -1
            self.video_widget.clear_scrub_frame()
            self.player.pause()
        else:
            self._last_scrub_centis = -1
            self.video_widget.clear_scrub_frame()
            cur = self.player.position() / 1000.0
            ordered = sorted(self.trim_slider.segments, key=lambda item: item[0])
            if ordered:
                self.trim_slider.segments = ordered
                # Проверяем, находится ли ползунок внутри какого-либо отрезка
                inside_idx = -1
                for i, (seg_s, seg_e) in enumerate(ordered):
                    if seg_s - 0.02 <= cur < seg_e - 0.05:
                        inside_idx = i
                        break

                if inside_idx >= 0:
                    self.trim_slider.active_seg_idx = inside_idx
                else:
                    # Ищем ближайший отрезок впереди ползунка или прыгаем на самый первый
                    next_idx = next(
                        (i for i, (s, _e) in enumerate(ordered) if s >= cur), 0
                    )
                    self.trim_slider.active_seg_idx = next_idx
                    start_sec = ordered[next_idx][0]
                    self.player.setPosition(int(round(start_sec * 1000)))
                    for sink, stream in self.track_boost_layers:
                        stream.set_position_sec(start_sec)

                self.trim_slider.update()
                self._update_labels(self.player.position() / 1000.0)
            self.player.play()

    # === [БЛОК 38: МЕТКИ ВРЕМЕНИ, ПОИСК КЛЮЧЕВЫХ КАДРОВ И АУДИОФИЛЬТРЫ] ===
    def _update_labels(self, cur):
        self.lbl_time.setText(
            f"{self._format_time(cur)}  |  {self._format_time(self.duration)}"
        )
        cnt = len(self.trim_slider.segments)
        if cnt > 1:
            idx_n = self.trim_slider.active_seg_idx + 1
            self.lbl_trim_info.setText(
                f"Отрезок #{idx_n}/{cnt}: {self._format_time(self.trim_slider.start_trim)} — {self._format_time(self.trim_slider.end_trim)}"
            )
        else:
            self.lbl_trim_info.setText(
                f"Обрезка: {self._format_time(self.trim_slider.start_trim)} — {self._format_time(self.trim_slider.end_trim)}"
            )

    def _build_ffmpeg_vol_filter(self, t_idx: int) -> str:
        raw_val = self.track_dbs.get(t_idx, 0)
        if raw_val <= MUTE_DB_VAL:
            return "volume=0"
        db = raw_val / 10.0
        if db <= 0.0:
            return f"volume={db:.1f}dB"
        return f"volume={db:.1f}dB,alimiter=limit=0.95:level=disabled"

    def _snap_to_keyframe(self, target_sec: float) -> float:
        if target_sec <= 0.1:
            return 0.0
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        scan_from = max(0.0, target_sec - 1.0)
        cmd = [
            FFMPEG_BIN,
            "-read_intervals",
            f"{scan_from:.2f}%+6.0",
            "-skip_frame",
            "nokey",
            "-select_streams",
            "v:0",
            "-i",
            str(self.file_path),
            "-vf",
            "showinfo",
            "-f",
            "null",
            "-",
        ]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=flags,
                timeout=4,
            )
            info = res.stderr.decode("utf-8", errors="ignore")
            pts_list = [
                float(m.group(1))
                for m in re.finditer(r"pts_time:(\d+(?:\.\d+)?)", info)
            ]
            for pts in pts_list:
                if pts >= target_sec - 0.1:
                    return max(0.0, pts - 0.01)
        except Exception:
            pass
        return target_sec

    # === [БЛОК 39: ЕДИНОЕ ОКНО ЭКСПОРТА МЕДИАФАЙЛА, НАРЕЗКА ОТРЕЗКОВ И ТОЧКА ВХОДА] ===
    def _run_batch_export_single_dialog(
        self, tasks: list, total_all_dur: float, title: str
    ) -> bool:
        """Выполняет все этапы экспорта и склейки в ОДНОМ окне прогресса без мигания"""
        dlg = ProgressDialog(
            self,
            title,
            "Подготовка экспорта...",
            self.settings.get("accent", "#FF9900"),
            self.settings.get("dark_mode", True),
        )
        state = {
            "cancelled": False,
            "ok": True,
            "cur_proc": None,
            "done_dur": 0.0,
            "start_t": time.time(),
        }

        def _on_cancel():
            state["cancelled"] = True
            proc = state["cur_proc"]
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
            dlg.reject()

        dlg.btn_cancel.clicked.connect(_on_cancel)
        dlg.show()
        QApplication.processEvents()

        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        safe_total = max(0.1, total_all_dur)

        for header_txt, cmd, step_dur, fallback_cmd, cleanup_list in tasks:
            if state["cancelled"]:
                state["ok"] = False
                break

            dlg.lbl_head.setText(header_txt)
            QApplication.processEvents()

            step_ok = False
            for attempt_cmd in [cmd, fallback_cmd] if fallback_cmd else [cmd]:
                if state["cancelled"]:
                    break
                last_lines = []
                try:
                    proc = subprocess.Popen(
                        attempt_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="ignore",
                        creationflags=flags,
                    )
                    state["cur_proc"] = proc
                    for line in proc.stdout:
                        if state["cancelled"]:
                            break
                        clean_l = line.strip()
                        if clean_l:
                            last_lines.append(clean_l)
                            if len(last_lines) > 8:
                                last_lines.pop(0)
                        m = time_re.search(line)
                        if m:
                            cur_sec = (
                                int(m.group(1)) * 3600
                                + int(m.group(2)) * 60
                                + float(m.group(3))
                            )
                            overall_cur = state["done_dur"] + min(step_dur, cur_sec)
                            pct = min(99, max(1, int((overall_cur / safe_total) * 100)))
                            elapsed = time.time() - state["start_t"]
                            if pct > 2 and elapsed > 0.4:
                                eta_sec = int((elapsed / pct) * (100 - pct))
                                mins, secs = divmod(max(0, eta_sec), 60)
                                eta_str = f"Общий прогресс: {pct}%  •  Осталось: ~{mins:02d}:{secs:02d}"
                            else:
                                eta_str = (
                                    f"Общий прогресс: {pct}%  •  Расчёт времени..."
                                )
                            dlg.update_state(pct, eta_str)
                        QApplication.processEvents()

                    proc.wait()
                    state["cur_proc"] = None
                    if not state["cancelled"] and proc.returncode == 0:
                        step_ok = True
                        break
                except Exception as e:
                    last_lines.append(str(e))

            if state["cancelled"] or not step_ok:
                state["ok"] = False
                for p in cleanup_list:
                    try:
                        Path(p).unlink(missing_ok=True)
                    except Exception:
                        pass
                if not state["cancelled"]:
                    dlg.reject()
                    QMessageBox.critical(
                        self,
                        "Ошибка",
                        "Операция прервана:\n" + "\n".join(last_lines[-6:]),
                    )
                break

            state["done_dur"] += step_dur

        if state["ok"] and not state["cancelled"]:
            dlg.update_state(100, "Готово!")
            QApplication.processEvents()
            dlg.accept()
        return state["ok"] and not state["cancelled"]

    def open_export_dialog(self):
        if not self.file_path or self.duration <= 0:
            QMessageBox.warning(self, "Внимание", "Сначала откройте файл!")
            return

        segments = self.trim_slider.get_sorted_segments() or [(0.0, self.duration)]
        is_trimmed = (
            len(segments) > 1
            or (segments[0][0] > 0.05)
            or (segments[-1][1] < self.duration - 0.05)
        )

        dlg = ExportDialog(
            self,
            self.file_path,
            self.is_video,
            is_trimmed,
            len(segments),
            self.settings.get("accent", "#FF9900"),
            self.settings.get("dark_mode", True),
        )
        if dlg.exec() != QDialog.Accepted or not dlg.result_config:
            return

        cfg = dlg.result_config
        ext = cfg.get("format")
        save_base_dir = Path(self._get_target_dir())
        default_full = str(save_base_dir / f"{cfg.get('name')}.{ext}")
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Куда сохранить файл", default_full, f"*.{ext}"
        )
        if not out_path:
            return

        try:
            free_bytes = shutil.disk_usage(Path(out_path).parent).free
            if free_bytes < 50 * 1024 * 1024:
                QMessageBox.warning(
                    self,
                    "Недостаточно места на диске",
                    f"На диске {Path(out_path).drive} осталось менее 50 МБ свободного места ({free_bytes // (1024 * 1024)} МБ).",
                )
                return
        except Exception:
            pass

        self.settings["last_export_dir"] = str(Path(out_path).parent)
        save_app_settings(self.settings)

        out_p_obj = Path(out_path)
        merge_segments = len(segments) > 1 and "Склеить" in cfg.get("multi_mode", "")
        temp_parts = []
        tasks = []
        has_gpu = BEST_GPU_ENCODER != "libx264"
        total_clips_dur = sum(max(0.1, e - s) for s, e in segments)

        for seg_idx, (seg_s, seg_e) in enumerate(segments, 1):
            clip_len = max(0.1, seg_e - seg_s)
            if merge_segments:
                part_path = (
                    self.cache_dir / f"seg_part_{self.load_counter}_{seg_idx}.{ext}"
                )
                temp_parts.append(part_path)
            elif len(segments) > 1:
                part_path = out_p_obj.with_name(
                    f"{out_p_obj.stem}_часть{seg_idx}{out_p_obj.suffix}"
                )
            else:
                part_path = out_p_obj

            hdr = (
                f"Обработка отрезка {seg_idx} из {len(segments)}: {part_path.name}"
                if len(segments) > 1
                else f"Сохранение: {part_path.name}"
            )
            cmd = self._build_segment_ffmpeg_cmd(
                cfg, seg_s, clip_len, ext, str(part_path), force_cpu=False
            )
            fb_cmd = (
                self._build_segment_ffmpeg_cmd(
                    cfg, seg_s, clip_len, ext, str(part_path), force_cpu=True
                )
                if has_gpu
                else None
            )
            tasks.append((hdr, cmd, clip_len, fb_cmd, [part_path]))

        concat_txt = None
        if merge_segments and len(temp_parts) > 1:
            concat_txt = self.cache_dir / f"concat_{self.load_counter}.txt"
            lines = [f"file '{p.as_posix()}'" for p in temp_parts]
            concat_txt.write_text("\n".join(lines), encoding="utf-8")
            merge_cmd = [
                FFMPEG_BIN,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_txt),
                "-c",
                "copy",
                str(out_p_obj),
            ]
            tasks.append(
                (
                    f"Финальная склейка {len(temp_parts)} отрезков в {out_p_obj.name}...",
                    merge_cmd,
                    max(0.5, total_clips_dur * 0.08),
                    None,
                    [out_p_obj],
                )
            )

        grand_total_dur = sum(t[2] for t in tasks)
        self.btn_export.setEnabled(False)
        all_ok = self._run_batch_export_single_dialog(
            tasks,
            grand_total_dur,
            "Экспорт и склейка" if merge_segments else "Экспорт файла",
        )

        for tp in temp_parts:
            tp.unlink(missing_ok=True)
        if concat_txt is not None:
            concat_txt.unlink(missing_ok=True)

        self.btn_export.setEnabled(True)
        if all_ok:
            QMessageBox.information(self, "Готово", "Экспорт успешно завершён!")

    def _build_segment_ffmpeg_cmd(
        self,
        cfg: dict,
        start_sec: float,
        clip_len: float,
        ext: str,
        out_path_str: str,
        force_cpu: bool = False,
    ) -> list:
        abr_kbps = str(cfg.get("abitrate", "192"))
        ach_str = cfg.get("achannels", "Оригинал")
        ach_args = (
            ["-ac", "1"]
            if "Моно" in ach_str
            else (["-ac", "2"] if "Стерео" in ach_str else [])
        )

        if not self.is_video:
            cmd = [
                FFMPEG_BIN,
                "-y",
                "-ss",
                f"{start_sec:.3f}",
                "-i",
                str(self.file_path),
                "-t",
                f"{clip_len:.3f}",
                *ach_args,
            ]
            if ext in {"mp3", "aac", "m4a", "ogg", "opus"}:
                cmd.extend(["-b:a", f"{abr_kbps}k"])
            cmd.append(out_path_str)
            return cmd

        crf_str = cfg.get("crf", "")
        crf_val = "28" if "28" in crf_str else ("23" if "23" in crf_str else "18")

        vbr_str = cfg.get("vbitrate", "Авто (по CRF)")
        vbr_match = re.search(r"\((\d+(?:\.\d+)?[Mk])\)", vbr_str)
        v_bitrate_args = ["-b:v", vbr_match.group(1)] if vbr_match else []

        vf_chain = []
        res_str = cfg.get("resolution", "Оригинал")
        res_map = {
            "4320p (8K)": 4320,
            "2160p (4K)": 2160,
            "1440p (2K)": 1440,
            "1080p": 1080,
            "720p": 720,
            "480p": 480,
            "240p": 240,
            "144p": 144,
        }
        if res_str in res_map:
            vf_chain.append(f"scale=-2:{res_map.get(res_str)}")

        fps_str = cfg.get("fps", "Оригинал")
        if "60" in fps_str:
            vf_chain.append("fps=60")
        elif "30" in fps_str:
            vf_chain.append("fps=30")
        elif "24" in fps_str:
            vf_chain.append("fps=24")

        orig_ext = self.file_path.suffix.lower().lstrip(".")
        want_copy = "Мгновенно" in cfg.get("speed_mode", "")
        can_stream_copy = (
            want_copy and not vf_chain and not v_bitrate_args and ext == orig_ext
        )

        if can_stream_copy:
            kf_start = self._snap_to_keyframe(start_sec)
            adj_len = max(0.2, (start_sec + clip_len) - kf_start)
            cmd = [
                FFMPEG_BIN,
                "-y",
                "-ss",
                f"{kf_start:.3f}",
                "-i",
                str(self.file_path),
                "-t",
                f"{adj_len:.3f}",
                "-map",
                "0:v:0",
                "-c:v",
                "copy",
                "-use_editlist",
                "0",
                "-avoid_negative_ts",
                "make_zero",
            ]
        else:
            encoder = "libx264" if force_cpu else BEST_GPU_ENCODER
            if encoder == "h264_nvenc":
                v_codec_args = ["-c:v", "h264_nvenc", "-preset", "p1", "-cq", crf_val]
                vf_chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2,format=nv12")
            elif encoder == "h264_amf":
                auto_bv = (
                    []
                    if v_bitrate_args
                    else [
                        "-b:v",
                        "12M"
                        if crf_val == "18"
                        else ("7M" if crf_val == "23" else "4M"),
                    ]
                )
                v_codec_args = ["-c:v", "h264_amf", *auto_bv]
                vf_chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2,format=nv12")
            elif encoder == "h264_qsv":
                v_codec_args = [
                    "-c:v",
                    "h264_qsv",
                    "-preset",
                    "veryfast",
                    "-global_quality",
                    crf_val,
                ]
                vf_chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2,format=nv12")
            else:
                v_codec_args = [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    crf_val,
                    "-threads",
                    "0",
                ]
                vf_chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p")

            cmd = [
                FFMPEG_BIN,
                "-y",
                "-ss",
                f"{max(0.0, start_sec - 2.0):.3f}",
                "-i",
                str(self.file_path),
                "-ss",
                f"{min(2.0, start_sec):.3f}",
                "-t",
                f"{clip_len:.3f}",
                "-map",
                "0:v:0",
                *v_codec_args,
                *v_bitrate_args,
                "-vf",
                ",".join(vf_chain),
            ]

        if cfg.get("no_audio") or ext == "gif" or not self.output_groups:
            cmd.append("-an")
        else:
            no_audio_edits = (
                len(self.output_groups) == self.track_count
                and all(
                    len(g) == 1 and g == [i] and self.track_dbs.get(i, 0) == 0
                    for i, g in enumerate(self.output_groups)
                )
                and not ach_args
                and abr_kbps == "192"
            )
            if no_audio_edits and ext in {"mp4", "mkv", "mov"}:
                cmd.extend(["-map", "0:a", "-c:a", "copy"])
            else:
                filters = []
                for out_i, grp in enumerate(self.output_groups):
                    if len(grp) == 1:
                        t_idx = next(iter(grp))
                        vf = self._build_ffmpeg_vol_filter(t_idx)
                        filters.append(f"[0:a:{t_idx}]{vf}[aout{out_i}]")
                    else:
                        in_labels = []
                        for t_idx in grp:
                            vf = self._build_ffmpeg_vol_filter(t_idx)
                            lbl = f"[v_{out_i}_{t_idx}]"
                            filters.append(f"[0:a:{t_idx}]{vf}{lbl}")
                            in_labels.append(lbl)
                        joined = "".join(in_labels)
                        filters.append(
                            f"{joined}amix=inputs={len(grp)}:duration=first:dropout_transition=0[aout{out_i}]"
                        )

                cmd.extend(["-filter_complex", ";".join(filters)])
                for out_i in range(len(self.output_groups)):
                    cmd.extend(["-map", f"[aout{out_i}]"])
                cmd.extend(["-c:a", "aac", "-b:a", f"{abr_kbps}k", *ach_args])

        if ext in {"mp4", "mov"} and not can_stream_copy:
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(out_path_str)
        return cmd


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MediaTrimmerWindow()
    win.show()

    first_arg = next(iter(sys.argv[1:]), "")
    if first_arg:
        arg_path = Path(first_arg)
        if arg_path.exists() and arg_path.is_file():
            QTimer.singleShot(100, lambda: win._open_media_path(str(arg_path)))

    sys.exit(app.exec())
