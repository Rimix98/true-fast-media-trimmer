import ctypes
import json
import re
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
from PySide6.QtCore import QIODevice, Qt, QThread, QTimer, QUrl, QRectF, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioOutput, QAudioSink, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox,
    QDialog, QFileDialog, QFrame, QGraphicsScene,
    QGraphicsView, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSlider, QStackedWidget,
    QVBoxLayout, QWidget
)

if sys.platform == "win32":
    import winreg

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_BIN = "ffmpeg"

SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = SCRIPT_DIR / "trimmer_settings.json"
AUDIO_EXTS = {"mp3", "ogg", "wav", "flac", "aac", "m4a", "wma", "opus"}
VIDEO_EXTS = {"mp4", "mkv", "avi", "mov", "webm", "flv", "wmv"}
VIDEO_FORMATS = ["mp4", "mkv", "mov", "webm", "avi", "gif"]
AUDIO_FORMATS = ["mp3", "wav", "ogg", "flac", "aac", "m4a"]
MUTE_DB_VAL = -1005
MAX_DB_VAL = 240
PALETTE_LIGHT = ["#FF9900", "#3B82F6", "#10B981", "#EF4444", "#A855F7"]
PALETTE_DARK = ["#C26A00", "#1D4ED8", "#047857", "#B91C1C"]

DEFAULT_SETTINGS = {
    "accent": "#FF9900",
    "dark_mode": True,
    "default_dir": str(SCRIPT_DIR),
    "last_export_dir": str(SCRIPT_DIR),
    "open_last_dir": True,
    "sync_seek_with_trim": False,
    "show_console": False,
    "context_menu": False,
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
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_contrast_text_color(hex_color: str) -> str:
    c = QColor(hex_color)
    luminance = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return "#111111" if luminance > 140 else "#FFFFFF"
def set_windows_titlebar_theme(widget: QWidget, is_dark: bool):
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        val = ctypes.c_int(1 if is_dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(val), ctypes.sizeof(val))
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
    """Определяет доступный аппаратный GPU-энкодер (NVIDIA / AMD / Intel) для сверхбыстрого экспорта"""
    flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    candidates = [
        ("h264_nvenc", ["-preset", "p1"]),
        ("h264_amf", ["-quality", "speed"]),
        ("h264_qsv", ["-preset", "veryfast"]),
    ]
    for codec, extra in candidates:
        cmd = [
            FFMPEG_BIN, "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=0.1",
            "-c:v", codec, *extra, "-f", "null", "-"
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, timeout=12)
            if res.returncode == 0:
                return codec
        except Exception:
            pass
    return "libx264"


BEST_GPU_ENCODER = detect_best_video_encoder()


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
                encoding="cp866"
            )
            cmd_str = f'"{launcher_cmd}" "%1"'

            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, app_key) as k:
                winreg.SetValueEx(k, "FriendlyAppName", 0, winreg.REG_SZ, "Медиа Обрезчик")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{app_key}\DefaultIcon") as ik:
                winreg.SetValueEx(ik, "", 0, winreg.REG_SZ, f'"{runner}",0')
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{app_key}\shell\open\command") as ck:
                winreg.SetValueEx(ck, "", 0, winreg.REG_SZ, cmd_str)

            for ext in all_exts:
                ext_key = rf"Software\Classes\.{ext}\OpenWithList\MediaTrimmerLauncher.cmd"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, ext_key):
                    pass
        else:
            launcher_cmd.unlink(missing_ok=True)
            for sub in (r"shell\open\command", r"shell\open", "shell", "DefaultIcon", ""):
                try:
                    target = rf"{app_key}\{sub}".rstrip("\\")
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, target)
                except Exception:
                    pass
            for ext in all_exts:
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\.{ext}\OpenWithList\MediaTrimmerLauncher.cmd")
                except Exception:
                    pass
    except Exception:
        pass
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
        return 65536 + super().bytesAvailable()

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
            FFMPEG_BIN, "-loglevel", "quiet",
            "-ss", f"{max(0.0, sec):.3f}",
            "-i", self.file_path,
            "-vn", "-sn", "-dn",
            "-map", f"0:a:{self.track_idx}",
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", str(self.channels), "-ar", str(self.sample_rate),
            "pipe:1"
        ]
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=32768, creationflags=flags
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
                self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="ignore", creationflags=flags
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
                    if len(last_lines) > 4:
                        last_lines.pop(0)
                m = time_re.search(line)
                if m:
                    cur_sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                    pct = min(99, max(1, int((cur_sec / self.total_duration_sec) * 100)))
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
                err_detail = "\n".join(last_lines[-3:])
                self.finished_err.emit(f"Код {self.proc.returncode}:\n{err_detail}")

        except Exception as e:
            self.finished_cancelled.emit() if self.is_cancelled else self.finished_err.emit(str(e))
class ProgressDialog(QDialog):
    def __init__(self, parent, title_text: str, header_text: str, accent: str, dark_mode: bool):
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
        self.lbl_head.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {accent};")
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
        self.btn_cancel.setStyleSheet("background-color: #B91C1C; color: #FFFFFF; padding: 5px 14px; border-radius: 3px; font-weight: bold;")
        bottom_row.addWidget(self.btn_cancel)
        lay.addLayout(bottom_row)

    def update_state(self, pct: int, eta_text: str):
        self.p_bar.setValue(pct)
        self.lbl_eta.setText(eta_text)
class ClickableSeekSlider(QSlider):
    seek_requested = Signal(float)
    zoom_wheel_requested = Signal(int)

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.setRange(0, 10000)
        self.is_dragging = False
        self.setCursor(Qt.PointingHandCursor)

    def _pos_to_ratio(self, x: float) -> float:
        pad = 14
        tw = max(1, self.width() - pad * 2)
        return max(0.0, min(1.0, (x - pad) / tw))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = 25 if event.angleDelta().y() > 0 else -25
            self.zoom_wheel_requested.emit(delta)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = True
            ratio = self._pos_to_ratio(event.position().x())
            self.setValue(int(ratio * 10000))
            self.seek_requested.emit(ratio)
            event.accept()
        else:
            super().mousePressEvent(event)
    def mouseMoveEvent(self, event):
        if self.is_dragging:
            ratio = self._pos_to_ratio(event.position().x())
            self.setValue(int(ratio * 10000))
            self.seek_requested.emit(ratio)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_dragging:
            ratio = self._pos_to_ratio(event.position().x())
            self.setValue(int(ratio * 10000))
            self.is_dragging = False
            self.seek_requested.emit(ratio)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class AudioWaveformWidget(QWidget):
    zoom_wheel_requested = Signal(int)

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
                    arr[cy - bh:cy + bh, x] = (r, g, b)
                    ih = int(bh * 0.55)
                    arr[cy - ih:cy + ih, x] = (r_hi, g_hi, b_hi)
        qimg = QImage(arr.data, w, h, w * 3, QImage.Format_RGB888)
        self.wave_pixmap = QPixmap.fromImage(qimg.copy())
        self.update()
    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(13, 13, 13) if self.dark_mode else QColor(235, 235, 238))
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
            delta = 25 if event.angleDelta().y() > 0 else -25
            self.zoom_wheel_requested.emit(delta)
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
class DualTrimSlider(QWidget):
    zoom_wheel_requested = Signal(int)

    def __init__(self, on_trim_changed):
        super().__init__()
        self.on_trim_changed = on_trim_changed
        self.setFixedHeight(36)
        self.accent_color = "#FF9900"
        self.dark_mode = True
        self.sync_seek = False
        self.duration = 0.0
        self.start_trim = 0.0
        self.end_trim = 0.0
        self.playhead_sec = 0.0
        self.active_handle = None
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad = 14
        tw = max(1, w - pad * 2)
        y = h // 2

        track_bg = QColor(68, 68, 68) if self.dark_mode else QColor(200, 200, 205)
        p.setPen(QPen(track_bg, 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pad, y, w - pad, y)

        if self.duration > 0:
            x1 = pad + (self.start_trim / self.duration) * tw
            x2 = pad + (self.end_trim / self.duration) * tw
            xp = pad + (self.playhead_sec / self.duration) * tw
        else:
            x1, x2, xp = pad, w - pad, pad
        accent_q = QColor(self.accent_color)
        p.setPen(QPen(accent_q, 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(int(x1), y, int(x2), y)

        if self.duration > 0:
            tick_c = QColor(255, 255, 255, 160) if self.dark_mode else QColor(30, 30, 30, 160)
            p.setPen(QPen(tick_c, 2))
            p.drawLine(int(xp), y - 9, int(xp), y + 9)

        for hx in (x1, x2):
            p.setBrush(QColor(255, 255, 255))
            p.setPen(QPen(accent_q, 2))
            p.drawRoundedRect(QRectF(hx - 7, y - 12, 14, 24), 3, 3)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = 25 if event.angleDelta().y() > 0 else -25
            self.zoom_wheel_requested.emit(delta)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        if self.duration <= 0:
            return
        pad = 14
        tw = max(1, self.width() - pad * 2)
        x1 = pad + (self.start_trim / self.duration) * tw
        x2 = pad + (self.end_trim / self.duration) * tw
        mx = event.position().x()
        self.active_handle = "start" if abs(mx - x1) <= abs(mx - x2) else "end"
        self.mouseMoveEvent(event)
    def mouseMoveEvent(self, event):
        if not self.active_handle or self.duration <= 0:
            return
        pad = 14
        tw = max(1, self.width() - pad * 2)
        mx = event.position().x()

        xp = pad + (self.playhead_sec / self.duration) * tw
        if not self.sync_seek and abs(mx - xp) <= 5.0:
            sec = self.playhead_sec
        else:
            ratio = max(0.0, min(1.0, (mx - pad) / tw))
            sec = ratio * self.duration

        if self.active_handle == "start":
            self.start_trim = min(sec, self.end_trim - 0.1)
        else:
            self.end_trim = max(sec, self.start_trim + 0.1)
        self.update()
        self.on_trim_changed(self.active_handle, False)

    def mouseReleaseEvent(self, event):
        if self.active_handle:
            h = self.active_handle
            self.active_handle = None
            self.on_trim_changed(h, True)
class AudioTracksDialog(QDialog):
    def __init__(self, parent, track_count, track_dbs, output_groups, on_db_changed, on_groups_changed, accent, dark_mode):
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

        lbl_top = QLabel("Шкала в децибелах: от -∞ dB (тишина) и -100 dB до +24.0 dB (по умолчанию 0.0 dB):")
        lbl_top.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 12px;")
        lbl_top.setWordWrap(True)
        layout.addWidget(lbl_top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"border: 1px solid #444444; background-color: {scr_bg};")
        layout.addWidget(self.scroll, 1)

        btn_row = QHBoxLayout()
        btn_merge = QPushButton("🔗 Объединить выбранные в одну дорожку")
        btn_merge.setStyleSheet(f"background-color: {accent}; color: {btn_fg}; font-weight: bold; padding: 7px 14px; border-radius: 4px;")
        btn_merge.clicked.connect(self.merge_selected)
        btn_row.addWidget(btn_merge)

        btn_reset = QPushButton("Сбросить все объединения")
        btn_reset.setStyleSheet(f"background-color: {btn_sec}; color: {fg}; padding: 7px 14px; border-radius: 4px;")
        btn_reset.clicked.connect(self.reset_groups)
        btn_row.addWidget(btn_reset)
        layout.addLayout(btn_row)

        self._rebuild_cards()
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
                card.setStyleSheet(f"QFrame {{ background-color: {card_merged_bg}; border: 2px solid {self.accent}; border-radius: 6px; }}")
            else:
                card.setStyleSheet(f"QFrame {{ background-color: {card_bg}; border: 1px solid #555555; border-radius: 6px; }}")

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(6)

            header = QHBoxLayout()
            if is_merged:
                title = QLabel(f"📦 Выходная дорожка {out_idx + 1}")
                title.setStyleSheet(f"color: {self.accent}; font-weight: bold; font-size: 12px; border: none;")
                header.addWidget(title, 1)

                btn_split = QPushButton("Разъединить")
                btn_split.setStyleSheet("background-color: #7F1D1D; color: #FECACA; padding: 3px 8px; border-radius: 3px; font-size: 11px;")
                btn_split.clicked.connect(lambda checked=False, g_i=out_idx: self.split_group(g_i))
                header.addWidget(btn_split)
            else:
                title = QLabel(f"🎵 Выходная дорожка {out_idx + 1}")
                title.setStyleSheet("color: #888888; font-weight: bold; font-size: 11px; border: none;")
                header.addWidget(title, 1)

            card_layout.addLayout(header)
            for t_idx in grp:
                row = QHBoxLayout()
                cb = QCheckBox(f"Дорожка {t_idx + 1}")
                cb.setStyleSheet(f"font-size: 12px; border: none; color: {fg}; font-weight: bold;")
                self.checkboxes[t_idx] = cb
                row.addWidget(cb, 0)

                cur_raw = self.track_dbs.get(t_idx, 0)
                lbl_val = QLabel(format_db_label(cur_raw))
                lbl_val.setFixedWidth(68)
                lbl_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                lbl_val.setStyleSheet("color: #22C55E; font-weight: bold; border: none;" if cur_raw > 0 else f"color: {self.accent}; font-weight: bold; border: none;")

                slider = QSlider(Qt.Horizontal)
                slider.setRange(MUTE_DB_VAL, MAX_DB_VAL)
                slider.setSingleStep(5)
                slider.setPageStep(20)
                slider.setValue(cur_raw)

                btn_zero = QPushButton("0 dB")
                btn_zero.setFixedWidth(42)
                btn_zero.setStyleSheet("background-color: #333333; color: #EEEEEE; font-size: 10px; padding: 2px; border-radius: 3px;")

                def _make_handler(idx_t, lbl, sld):
                    def _changed(val):
                        if -15 <= val <= 15 and val != 0:
                            sld.blockSignals(True)
                            sld.setValue(0)
                            sld.blockSignals(False)
                            val = 0
                        self.track_dbs[idx_t] = val
                        lbl.setText(format_db_label(val))
                        lbl.setStyleSheet("color: #22C55E; font-weight: bold; border: none;" if val > 0 else f"color: {self.accent}; font-weight: bold; border: none;")
                        self.on_db_changed(idx_t, val)
                    return _changed

                slider.valueChanged.connect(_make_handler(t_idx, lbl_val, slider))
                btn_zero.clicked.connect(lambda checked=False, sld=slider: sld.setValue(0))

                row.addWidget(slider, 1)
                row.addWidget(lbl_val)
                row.addWidget(btn_zero)
                card_layout.addLayout(row)

            vbox.addWidget(card)

        vbox.addStretch(1)
        self.scroll.setWidget(container)
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
            QMessageBox.information(self, "Подсказка", "Отметьте галочками минимум 2 дорожки, чтобы объединить их.")
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
class ExportDialog(QDialog):
    def __init__(self, parent, file_path: Path, is_video: bool, is_trimmed: bool, accent: str, dark_mode: bool):
        super().__init__(parent)
        self.setWindowTitle("Экспорт медиафайла")
        self.setFixedWidth(440)
        set_windows_titlebar_theme(self, dark_mode)

        bg = "#1E1E1E" if dark_mode else "#F4F4F5"
        fg = "#EEEEEE" if dark_mode else "#18181B"
        inp_bg = "#121212" if dark_mode else "#FFFFFF"
        btn_fg = get_contrast_text_color(accent)
        self.setStyleSheet(f"background-color: {bg}; color: {fg}; font-family: Arial;")

        self.result_config = None
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        lbl_name = QLabel("Название видео:" if is_video else "Название аудио:")
        lbl_name.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 12px;")
        lay.addWidget(lbl_name)

        self.edit_name = QLineEdit(f"{file_path.stem}_обрезано")
        self.edit_name.setStyleSheet(f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 6px 8px; border-radius: 4px; font-size: 13px;")
        lay.addWidget(self.edit_name)

        lbl_fmt = QLabel("Формат:")
        lbl_fmt.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 12px; margin-top: 4px;")
        lay.addWidget(lbl_fmt)

        self.combo_fmt = QComboBox()
        formats = VIDEO_FORMATS if is_video else AUDIO_FORMATS
        self.combo_fmt.addItems(formats)
        orig_ext = file_path.suffix.lower().lstrip(".")
        if orig_ext in formats:
            self.combo_fmt.setCurrentText(orig_ext)
        self.combo_fmt.setStyleSheet(f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 6px; border-radius: 4px; font-size: 13px;")
        lay.addWidget(self.combo_fmt)
        self.combo_res = None
        if is_video and is_trimmed:
            lbl_res = QLabel("Качество:")
            lbl_res.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 12px; margin-top: 4px;")
            lay.addWidget(lbl_res)

            self.combo_res = QComboBox()
            self.combo_res.addItems([
                "Оригинал", "4320p (8K)", "2160p (4K)", "1440p (2K)",
                "1080p", "720p", "480p", "240p", "144p"
            ])
            self.combo_res.setStyleSheet(f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 6px; border-radius: 4px; font-size: 13px;")
            lay.addWidget(self.combo_res)

        self.combo_fps = None
        self.combo_crf = None
        self.cb_no_audio = None
        if is_video:
            lbl_fps = QLabel("Частота кадров (FPS):")
            lbl_fps.setStyleSheet("font-weight: bold; font-size: 11px; margin-top: 4px;")
            lay.addWidget(lbl_fps)

            self.combo_fps = QComboBox()
            self.combo_fps.addItems(["Оригинал", "60 FPS", "30 FPS", "24 FPS"])
            self.combo_fps.setStyleSheet(f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;")
            lay.addWidget(self.combo_fps)

            lbl_crf = QLabel("Сжатие / Битрейт:")
            lbl_crf.setStyleSheet("font-weight: bold; font-size: 11px; margin-top: 4px;")
            lay.addWidget(lbl_crf)

            self.combo_crf = QComboBox()
            self.combo_crf.addItems([
                "Высокое качество (CRF 18)",
                "Сбалансированное (CRF 23)",
                "Малый размер файла (CRF 28)"
            ])
            self.combo_crf.setStyleSheet(f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;")
            lay.addWidget(self.combo_crf)
            
            lbl_mode = QLabel("Режим скорости экспорта:")
            lbl_mode.setStyleSheet("font-weight: bold; font-size: 11px; margin-top: 4px;")
            lay.addWidget(lbl_mode)

            self.combo_speed = QComboBox()
            self.combo_speed.addItems([
                "Мгновенно без перекодирования (по ключевым кадрам, 1-2 сек)",
                f"Полное перекодирование до доли секунды ({BEST_GPU_ENCODER})"
            ])

            self.combo_speed.setStyleSheet(f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;")
            lay.addWidget(self.combo_speed)


            self.cb_no_audio = QCheckBox("Удалить звук (экспорт без аудиодорожек)")
            self.cb_no_audio.setStyleSheet("font-size: 12px; margin-top: 4px;")
            lay.addWidget(self.cb_no_audio)

        btn_export = QPushButton("Экспорт")
        btn_export.setStyleSheet(f"background-color: {accent}; color: {btn_fg}; font-size: 14px; font-weight: bold; padding: 10px; border-radius: 5px; margin-top: 10px;")
        btn_export.clicked.connect(self._on_submit)
        lay.addWidget(btn_export)

    def _on_submit(self):
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Внимание", "Введите название файла!")
            return
        self.result_config = {
            "name": name,
            "format": self.combo_fmt.currentText(),
            "resolution": self.combo_res.currentText() if self.combo_res else "Оригинал",
            "fps": self.combo_fps.currentText() if self.combo_fps else "Оригинал",
            "crf": self.combo_crf.currentText() if self.combo_crf else "Высокое качество (CRF 18)",
            "speed_mode": self.combo_speed.currentText() if hasattr(self, "combo_speed") and self.combo_speed else "",
            "no_audio": self.cb_no_audio.isChecked() if self.cb_no_audio else False,
        }
        self.accept()
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

        self.cb_last_dir = QCheckBox("Открывать последнюю папку (при экспорте и открытии)")
        self.cb_last_dir.setChecked(self.settings.get("open_last_dir", True))
        self.cb_last_dir.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_last_dir)

        self.lbl_beh_sec = QLabel("3. Поведение ползунков:")
        self.lay.addWidget(self.lbl_beh_sec)

        self.cb_sync_trim = QCheckBox("Привязывать ползунок длительности к границам начала и конца обрезки")
        self.cb_sync_trim.setChecked(self.settings.get("sync_seek_with_trim", False))
        self.cb_sync_trim.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_sync_trim)

        self.lbl_dev_sec = QLabel("4. Интеграция и режим разработчика:")
        self.lay.addWidget(self.lbl_dev_sec)

        self.cb_ctx_menu = QCheckBox("Добавить «Медиа Обрезчик» в меню «Открыть с помощью»")
        self.cb_ctx_menu.setChecked(self.settings.get("context_menu", False))
        self.cb_ctx_menu.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_ctx_menu)

        self.cb_show_console = QCheckBox("Отображение консоли программы")
        self.cb_show_console.setChecked(self.settings.get("show_console", False))
        self.cb_show_console.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_show_console)

        self._refresh_dialog_style()
    def _set_dark_mode(self, is_dark: bool):
        self.settings["dark_mode"] = is_dark
        set_windows_titlebar_theme(self, is_dark)
        self._save_and_apply()

    def _set_accent(self, hex_color: str):
        self.settings["accent"] = hex_color
        self._save_and_apply()

    def _pick_custom_color(self):
        chosen = QColorDialog.getColor(QColor(self.settings.get("accent", "#FF9900")), self, "Выберите свой цвет темы")
        if chosen.isValid():
            self.settings["accent"] = chosen.name().upper()
            self._save_and_apply()

    def _browse_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку по умолчанию", self.edit_dir.text())
        if folder:
            self.settings["default_dir"] = folder
            self.edit_dir.setText(folder)
            self._save_and_apply()

    def _on_flags_changed(self):
        self.settings["open_last_dir"] = self.cb_last_dir.isChecked()
        self.settings["sync_seek_with_trim"] = self.cb_sync_trim.isChecked()
        self.settings["context_menu"] = self.cb_ctx_menu.isChecked()
        self.settings["show_console"] = self.cb_show_console.isChecked()
        register_context_menu(self.settings["context_menu"])
        set_console_visible(self.settings["show_console"])
        self._save_and_apply()

    def _save_and_apply(self):
        save_app_settings(self.settings)
        self._refresh_dialog_style()
        self.on_settings_applied()
    def _refresh_dialog_style(self):
        is_dark = self.settings.get("dark_mode", True)
        accent = self.settings.get("accent", "#FF9900")
        btn_fg = get_contrast_text_color(accent)
        bg = "#1E1E1E" if is_dark else "#F4F4F5"
        fg = "#EEEEEE" if is_dark else "#18181B"
        inp = "#121212" if is_dark else "#FFFFFF"

        self.setStyleSheet(f"background-color: {bg}; color: {fg}; font-family: Arial;")
        for lbl in (self.lbl_theme_sec, self.lbl_dir_sec, self.lbl_beh_sec, self.lbl_dev_sec):
            lbl.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 12px; margin-top: 4px;")

        self.edit_dir.setStyleSheet(f"background-color: {inp}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 3px;")

        active_btn = f"background-color: {accent}; color: {btn_fg}; font-weight: bold; padding: 6px; border-radius: 4px;"
        inactive_btn = "background-color: #333333; color: #CCCCCC; padding: 6px; border-radius: 4px;"
        self.btn_dark.setStyleSheet(active_btn if is_dark else inactive_btn)
        self.btn_light.setStyleSheet(active_btn if not is_dark else inactive_btn)

        for btn, hex_c in self.color_buttons:
            border = "3px solid #FFFFFF" if (hex_c.upper() == accent.upper() and is_dark) else (
                "3px solid #111111" if hex_c.upper() == accent.upper() else "1px solid #555555"
            )
            btn.setStyleSheet(f"background-color: {hex_c}; border: {border}; border-radius: 5px;")


class ClickableVideoWidget(QGraphicsView):
    def __init__(self, on_click, on_double_click):
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
    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.viewport().rect()
        self.scene.setSceneRect(0, 0, rect.width(), rect.height())
        self.video_item.setSize(rect.size())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_click()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_double_click()
        super().mouseDoubleClickEvent(event)


class MediaTrimmerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Медиа Обрезчик")
        self.resize(940, 640)
        self.setMinimumSize(640, 360)
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
        self.master_volume = 0.8
        self.timeline_zoom = 100
        self.cache_dir = SCRIPT_DIR / ".trimmer_cache"
        self.cache_dir.mkdir(exist_ok=True)
        self._cleanup_cache_files()
        self.load_counter = 0
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
        self.lbl_title.setStyleSheet("font-size: 13px; font-weight: bold; padding-left: 8px;")
        top_layout.addWidget(self.lbl_title, 1)

        self.btn_tracks = QPushButton("Дорожки")
        self.btn_tracks.clicked.connect(self.open_tracks_dialog)
        self.btn_tracks.hide()
        top_layout.addWidget(self.btn_tracks)

        self.btn_settings = QPushButton("⚙ Настройки")
        self.btn_settings.clicked.connect(self.open_settings_dialog)
        top_layout.addWidget(self.btn_settings)

        main_layout.addWidget(self.top_bar)
        self.stack = QStackedWidget()
        self.video_widget = ClickableVideoWidget(self.toggle_play, self.toggle_fullscreen)
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

        self.lbl_time = QLabel("00:00.0  |  00:00.0")
        ctrl_layout.addWidget(self.lbl_time)

        self.lbl_trim_info = QLabel("Обрезка: 00:00.0 — 00:00.0")
        ctrl_layout.addWidget(self.lbl_trim_info)
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
        export_grid = QGridLayout()
        export_grid.setContentsMargins(0, 0, 0, 0)
        export_grid.setColumnStretch(0, 1)
        export_grid.setColumnStretch(1, 0)
        export_grid.setColumnStretch(2, 1)

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
    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._update_zoomed_widths)

    def resizeEvent(self, event):
        super().resizeEvent(event)
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

    def _step_zoom(self, delta: int):
        new_val = max(100, min(1000, self.zoom_slider.value() + delta))
        self.zoom_slider.setValue(new_val)

    def _on_zoom_changed(self, val: int):
        self.timeline_zoom = val
        self.lbl_zoom_pct.setText(f"{val}%")
        self._update_zoomed_widths()
    def _update_zoomed_widths(self):
        factor = self.timeline_zoom / 100.0
        vp_w = max(100, self.timeline_scroll.viewport().width())
        new_tl_w = int(vp_w * factor)

        tl_h = 78 if self.is_video else 54
        self.timeline_scroll.setFixedHeight(tl_h)
        self.timeline_container.setFixedSize(new_tl_w, tl_h - 16)

        ratio = (self.player.position() / 1000.0) / self.duration if self.duration > 0 else 0.0
        playhead_x = int(ratio * new_tl_w)
        self.timeline_scroll.horizontalScrollBar().setValue(max(0, playhead_x - vp_w // 2))

        base_wave_w = max(100, self.wave_scroll.viewport().width())
        base_wave_h = max(100, self.wave_scroll.viewport().height())
        new_wave_w = int(base_wave_w * factor)
        self.wave_widget.setFixedSize(new_wave_w, base_wave_h)
        self.wave_scroll.horizontalScrollBar().setValue(max(0, int(ratio * new_wave_w) - base_wave_w // 2))

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

        self.setStyleSheet(f"QMainWindow, QWidget {{ background-color: {win_bg}; color: {fg}; font-family: Arial; }}")
        self.top_bar.setStyleSheet(f"background-color: {panel_bg}; border-radius: 4px;")
        self.ctrl_bar.setStyleSheet(f"background-color: {panel_bg}; border-radius: 4px;")
        self.video_widget.setStyleSheet("background-color: #0D0D0D; border: none;" if is_dark else "background-color: #E4E4E7; border: none;")
        self.btn_open.setStyleSheet(f"background-color: {accent}; color: {btn_fg}; font-weight: bold; padding: 6px 14px; border-radius: 3px;")
        self.btn_play.setStyleSheet(f"background-color: {accent}; color: {btn_fg}; font-family: 'Segoe UI Symbol'; font-size: 15px; font-weight: bold; padding: 5px; border-radius: 3px;")
        self.btn_export.setStyleSheet(f"background-color: {accent}; color: {btn_fg}; font-size: 13px; font-weight: bold; padding: 8px 32px; border-radius: 4px;")
        self.btn_tracks.setStyleSheet(f"background-color: {btn_sec_bg}; color: {accent}; font-weight: bold; padding: 6px 12px; border-radius: 3px;")
        self.btn_settings.setStyleSheet(f"background-color: {btn_sec_bg}; color: {fg}; font-weight: bold; padding: 6px 12px; border-radius: 3px;")
        self.btn_full.setStyleSheet(f"background-color: {btn_sec_bg}; color: {fg}; font-size: 14px; font-weight: bold; padding: 4px; border-radius: 3px;")

        self.lbl_time.setStyleSheet(f"background-color: {time_bg}; color: {accent}; font-family: Consolas; font-size: 14px; font-weight: bold; padding: 5px 12px; border-radius: 3px;")
        self.lbl_trim_info.setStyleSheet(f"color: {sub_fg}; font-size: 11px; padding: 0 10px; background: transparent;")
        self.lbl_vol_icon.setStyleSheet(f"color: {accent}; font-size: 14px; font-weight: bold; background: transparent;")
        self.lbl_master_pct.setStyleSheet(f"color: {accent}; font-weight: bold; font-size: 11px; background: transparent;")
        self.lbl_zoom_icon.setStyleSheet(f"color: {accent}; font-size: 12px; background: transparent;")
        self.lbl_zoom_pct.setStyleSheet(f"color: {accent}; font-weight: bold; font-size: 11px; background: transparent;")

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
    def _format_time(self, sec):
        sec = max(0.0, sec)
        total_secs = int(sec)
        hrs = total_secs // 3600
        mins = (total_secs % 3600) // 60
        rem = sec - (hrs * 3600 + mins * 60)
        if hrs > 0 or self.duration >= 3600:
            return f"{hrs:02d}:{mins:02d}:{rem:04.1f}"
        return f"{mins:02d}:{rem:04.1f}"

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
        elif event.key() == Qt.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
        elif event.key() == Qt.Key_Space:
            self.toggle_play()

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
            QMessageBox.information(self, "Дорожки", "В этом файле не найдено звуковых дорожек.")
            return
        self._ensure_track_boost_layers()
        dlg = AudioTracksDialog(
            self, self.track_count, self.track_dbs, self.output_groups,
            self._on_single_track_db, self._update_tracks_btn_label,
            self.settings.get("accent", "#FF9900"), self.settings.get("dark_mode", True)
        )
        dlg.exec()
    def _ensure_track_boost_layers(self):
        if self.track_boost_layers or not self.is_video or self.track_count <= 0:
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(32000)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Int16)

        for idx in range(self.track_count):
            stream = GainAudioStream(str(self.file_path), idx, sample_rate=32000, channels=2)
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
    def _raw_db_to_real_gain(self, raw_val: int) -> float:
        if raw_val <= MUTE_DB_VAL:
            return 0.0
        db = raw_val / 10.0
        return min(16.0, 10.0 ** (db / 20.0))

    def _apply_all_volumes(self):
        if self.is_video and self.track_boost_layers:
            self.audio_out.setVolume(0.0)
            for idx, (sink, stream) in enumerate(self.track_boost_layers):
                raw_db = self.track_dbs.get(idx, 0)
                stream.gain = self._raw_db_to_real_gain(raw_db) * self.master_volume
                sink.setVolume(self.master_volume)
        else:
            gain = self._raw_db_to_real_gain(self.track_dbs.get(0, 0)) * self.master_volume
            self.audio_out.setVolume(min(1.0, gain))

    def _on_master_volume(self, val):
        self.master_volume = val / 100.0
        self.lbl_master_pct.setText(f"{val}%")
        self._apply_all_volumes()

    def _on_single_track_db(self, t_idx, raw_val):
        self.track_dbs[t_idx] = raw_val
        self._apply_all_volumes()

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
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        info = res.stderr.decode("utf-8", errors="ignore")
        dur = 0.0
        dur_m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
        if dur_m:
            dur = int(dur_m.group(1)) * 3600 + int(dur_m.group(2)) * 60 + float(dur_m.group(3))
        audio_cnt = sum(1 for line in info.splitlines() if "Audio:" in line)
        return dur, audio_cnt
    def _run_ffmpeg_with_progress(self, cmd, total_dur, title, header, cleanup_paths=None) -> bool:
        dlg = ProgressDialog(
            self, title, header,
            self.settings.get("accent", "#FF9900"),
            self.settings.get("dark_mode", True)
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
    def load_file(self):
        path_str, _ = QFileDialog.getOpenFileName(self, "Выберите аудио или видео", self._get_target_dir())
        if path_str:
            self._open_media_path(path_str)

    def _open_media_path(self, path_str: str):
        candidate = Path(path_str)
        if not candidate.exists():
            return

        self.player.stop()
        self._clear_track_players()
        self._cleanup_cache_files()
        self.load_counter += 1

        ext = candidate.suffix.lower().lstrip(".")
        is_vid = ext in VIDEO_EXTS
        probed_dur, probed_audio_cnt = self._probe_media_info(str(candidate))

        self.file_path = candidate
        self.duration = probed_dur
        self.lbl_title.setText(self.file_path.name)

        if is_vid:
            self.is_video = True
            self.stack.setCurrentIndex(0)
            self.seek_slider.show()
            self.btn_full.show()
            self.btn_tracks.show()

            self.track_count = probed_audio_cnt
            self.track_dbs = {i: 0 for i in range(self.track_count)}
            self.output_groups = [[i] for i in range(self.track_count)]
            self._update_tracks_btn_label()

            if probed_audio_cnt > 1:
                self._ensure_track_boost_layers()
        else:
            wav_path = self.cache_dir / f"wave_{self.load_counter}.wav"
            cmd = [
                FFMPEG_BIN, "-y", "-vn", "-sn", "-dn", "-threads", "0",
                "-i", str(candidate), "-ac", "1", "-ar", "8000", str(wav_path)
            ]
            ok = self._run_ffmpeg_with_progress(
                cmd, probed_dur, "Загрузка аудио",
                f"Построение волны: {candidate.name}",
                cleanup_paths=[wav_path]
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
            self.track_count = 0
            self.output_groups = []

            if wav_path.exists() and wav_path.stat().st_size > 44:
                raw = wav_path.read_bytes()
                pcm = np.frombuffer(raw.__getitem__(slice(44, None)), dtype=np.int16)
                self.wave_widget.set_waveform(pcm)

        self._apply_all_volumes()
        if self.is_video:
            self.player.setVideoOutput(self.video_widget.video_item)
        self.player.setSource(QUrl.fromLocalFile(str(self.file_path)))
        self.player.pause()
        self.player.setPosition(0)
        self._update_zoomed_widths()
    def _on_dur_changed(self, dur_ms):
        self.duration = dur_ms / 1000.0
        self.trim_slider.duration = self.duration
        self.trim_slider.start_trim = 0.0
        self.trim_slider.end_trim = self.duration
        self.trim_slider.playhead_sec = 0.0
        self.trim_slider.update()
        self.wave_widget.duration = self.duration
        self.wave_widget.start_trim = 0.0
        self.wave_widget.end_trim = self.duration
        self.wave_widget.update()
        self._update_labels(0.0)

    def _on_pos_changed(self, pos_ms):
        cur = pos_ms / 1000.0
        if self.player.playbackState() == QMediaPlayer.PlayingState and cur >= self.trim_slider.end_trim:
            self.player.pause()
            self.seek_to(self.trim_slider.start_trim, True)
            return

        if not self.seek_slider.is_dragging and not self.fs_seek_slider.is_dragging and self.duration > 0:
            pos_val = int((cur / self.duration) * 10000)
            self.seek_slider.setValue(pos_val)
            self.fs_seek_slider.setValue(pos_val)
        self.trim_slider.playhead_sec = cur
        self.trim_slider.update()
        self.wave_widget.current_pos = cur
        self.wave_widget.update()
        self._update_labels(cur)

    def _on_state_changed(self, state):
        is_play = state == QMediaPlayer.PlayingState
        self.btn_play.setText("⏸" if is_play else "▶")
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
            self.seek_to(ratio * self.duration, not is_drag)

    def _on_trim_changed(self, handle, immediate=True):
        self.wave_widget.start_trim = self.trim_slider.start_trim
        self.wave_widget.end_trim = self.trim_slider.end_trim
        self.wave_widget.update()
        if self.settings.get("sync_seek_with_trim", False):
            target = self.trim_slider.start_trim if handle == "start" else self.trim_slider.end_trim
            self.seek_to(target, immediate)
        else:
            self._update_labels(self.player.position() / 1000.0)

    def _flush_pending_seek(self):
        if self._pending_seek_sec is not None:
            sec = self._pending_seek_sec
            self._pending_seek_sec = None
            self.player.setPosition(int(sec * 1000))
            for sink, stream in self.track_boost_layers:
                stream.set_position_sec(sec)

    def seek_to(self, sec, immediate=True):
        sec = max(0.0, min(self.duration, sec))
        self.trim_slider.playhead_sec = sec
        self.trim_slider.update()
        self._update_labels(sec)
        if self.duration > 0:
            pos_val = int((sec / self.duration) * 10000)
            if not self.seek_slider.is_dragging:
                self.seek_slider.setValue(pos_val)
            if not self.fs_seek_slider.is_dragging:
                self.fs_seek_slider.setValue(pos_val)

        if immediate:
            self._pending_seek_sec = None
            self._seek_throttle_timer.stop()
            self.player.setPosition(int(sec * 1000))
            for sink, stream in self.track_boost_layers:
                stream.set_position_sec(sec)
        else:
            self._pending_seek_sec = sec
            if not self._seek_throttle_timer.isActive():
                self._seek_throttle_timer.start()
    def toggle_play(self):
        if self.duration <= 0:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            cur = self.player.position() / 1000.0
            if cur < self.trim_slider.start_trim or cur >= self.trim_slider.end_trim - 0.1:
                start_sec = self.trim_slider.start_trim
                self.player.setPosition(int(start_sec * 1000))
                for sink, stream in self.track_boost_layers:
                    stream.set_position_sec(start_sec)
            self.player.play()

    def _update_labels(self, cur):
        self.lbl_time.setText(f"{self._format_time(cur)}  |  {self._format_time(self.duration)}")
        self.lbl_trim_info.setText(f"Обрезка: {self._format_time(self.trim_slider.start_trim)} — {self._format_time(self.trim_slider.end_trim)}")

    def _build_ffmpeg_vol_filter(self, t_idx: int) -> str:
        raw_val = self.track_dbs.get(t_idx, 0)
        if raw_val <= MUTE_DB_VAL:
            return "volume=0"
        db = raw_val / 10.0
        if db <= 0.0:
            return f"volume={db:.1f}dB"
        return f"volume={db:.1f}dB,alimiter=limit=0.95:level=disabled"
        
    def _find_next_keyframe_sec(self, target_sec: float) -> float:
        """За 0.05 сек находит точное время ближайшего чистого ключевого кадра (I-frame) для разреза без артефактов"""
        if target_sec <= 0.05:
            return 0.0
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        cmd = [
            FFMPEG_BIN, "-read_intervals", f"{max(0.0, target_sec - 0.5):.2f}%+5.0",
            "-skip_frame", "nokey", "-select_streams", "v:0",
            "-i", str(self.file_path),
            "-vf", "showinfo", "-f", "null", "-"
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags, timeout=5)
            info = res.stderr.decode("utf-8", errors="ignore")
            pts_list = [float(m.group(1)) for m in re.finditer(r"pts_time:(\d+(?:\.\d+)?)", info)]
            for pts in pts_list:
                if pts >= target_sec - 0.05:
                    return pts
        except Exception:
            pass
        return target_sec

    def _snap_to_keyframe(self, target_sec: float) -> float:
        """За 0.05 сек находит точный I-frame, чтобы -c:v copy начинался без серых артефактов"""
        if target_sec <= 0.1:
            return 0.0
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        scan_from = max(0.0, target_sec - 1.0)
        cmd = [
            FFMPEG_BIN, "-read_intervals", f"{scan_from:.2f}%+6.0",
            "-skip_frame", "nokey", "-select_streams", "v:0",
            "-i", str(self.file_path),
            "-vf", "showinfo", "-f", "null", "-"
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags, timeout=4)
            info = res.stderr.decode("utf-8", errors="ignore")
            pts_list = [float(m.group(1)) for m in re.finditer(r"pts_time:(\d+(?:\.\d+)?)", info)]
            for pts in pts_list:
                if pts >= target_sec - 0.1:
                    # Чуть-чуть (на 10 мс) раньше ключевого кадра, чтобы FFmpeg захватил сам I-frame как первый пакет
                    return max(0.0, pts - 0.01)
        except Exception:
            pass
        return target_sec


    def open_export_dialog(self):
        if not self.file_path or self.duration <= 0:
            QMessageBox.warning(self, "Внимание", "Сначала откройте файл!")
            return

        is_trimmed = (self.trim_slider.start_trim > 0.05) or (self.trim_slider.end_trim < self.duration - 0.05)
        dlg = ExportDialog(
            self, self.file_path, self.is_video, is_trimmed,
            self.settings.get("accent", "#FF9900"),
            self.settings.get("dark_mode", True)
        )
        if dlg.exec() != QDialog.Accepted or not dlg.result_config:
            return

        cfg = dlg.result_config
        ext = cfg.get("format")
        save_base_dir = Path(self._get_target_dir())
        default_full = str(save_base_dir / f"{cfg.get('name')}.{ext}")
        out_path, _ = QFileDialog.getSaveFileName(self, "Куда сохранить файл", default_full, f"*.{ext}")
        if not out_path:
            return

        # Проверяем свободное место на диске перед стартом
        try:
            import shutil
            free_bytes = shutil.disk_usage(Path(out_path).parent).free
            if free_bytes < 50 * 1024 * 1024:
                QMessageBox.warning(
                    self, "Недостаточно места на диске",
                    f"На диске {Path(out_path).drive} осталось менее 50 МБ свободного места ({free_bytes // (1024 * 1024)} МБ).\n"
                    "Освободите место или выберите другой диск для сохранения."
                )
                return
        except Exception:
            pass


        self.settings["last_export_dir"] = str(Path(out_path).parent)
        save_app_settings(self.settings)

        clip_len = self.trim_slider.end_trim - self.trim_slider.start_trim
        if self.is_video:
            crf_str = cfg.get("crf", "")
            crf_val = "28" if "28" in crf_str else ("23" if "23" in crf_str else "18")

            vf_chain = []
            res_str = cfg.get("resolution", "Оригинал")
            res_map = {
                "4320p (8K)": 4320, "2160p (4K)": 2160, "1440p (2K)": 1440,
                "1080p": 1080, "720p": 720, "480p": 480, "240p": 240, "144p": 144
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
            can_stream_copy = want_copy and not vf_chain and ext == orig_ext

            if can_stream_copy:
                kf_start = self._snap_to_keyframe(self.trim_slider.start_trim)
                adj_len = max(0.2, self.trim_slider.end_trim - kf_start)
                cmd = [
                    FFMPEG_BIN, "-y",
                    "-ss", f"{kf_start:.3f}",
                    "-i", str(self.file_path),
                    "-t", f"{adj_len:.3f}",
                    "-map", "0:v:0",
                    "-c:v", "copy",
                    "-use_editlist", "0",
                    "-avoid_negative_ts", "make_zero"
                ]





            else:
                if BEST_GPU_ENCODER == "h264_nvenc":
                    v_codec_args = ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", crf_val, "-b:v", "0"]
                elif BEST_GPU_ENCODER == "h264_amf":
                    v_codec_args = ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", crf_val, "-qp_p", crf_val]
                elif BEST_GPU_ENCODER == "h264_qsv":
                    v_codec_args = ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", crf_val]
                else:
                    v_codec_args = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", crf_val, "-threads", "0"]

                cmd = [
                    FFMPEG_BIN, "-y",
                    "-ss", f"{max(0.0, self.trim_slider.start_trim - 2.0):.3f}",
                    "-i", str(self.file_path),
                    "-ss", f"{min(2.0, self.trim_slider.start_trim):.3f}",
                    "-t", f"{clip_len:.3f}",
                    "-map", "0:v:0",
                    *v_codec_args,
                    "-pix_fmt", "yuv420p"
                ]
                if vf_chain:
                    cmd.extend(["-vf", ",".join(vf_chain)])

            if cfg.get("no_audio") or ext == "gif" or not self.output_groups:
                cmd.append("-an")
            else:
                no_audio_edits = (
                    len(self.output_groups) == self.track_count
                    and all(len(g) == 1 and g == [i] and self.track_dbs.get(i, 0) == 0 for i, g in enumerate(self.output_groups))
                )
                # Если дорожки не объединяли и громкость не меняли — копируем звук напрямую за 0.5 сек без сдвига PTS!
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
                            filters.append(f"{joined}amix=inputs={len(grp)}:duration=first:dropout_transition=0[aout{out_i}]")

                    cmd.extend(["-filter_complex", ";".join(filters)])
                    for out_i in range(len(self.output_groups)):
                        cmd.extend(["-map", f"[aout{out_i}]"])
                    cmd.extend(["-c:a", "aac", "-b:a", "192k"])

            if ext in {"mp4", "mov"} and not can_stream_copy:
                cmd.extend(["-movflags", "+faststart"])
            cmd.append(str(out_path))

        else:
            cmd = [
                FFMPEG_BIN, "-y",
                "-ss", f"{self.trim_slider.start_trim:.3f}",
                "-i", str(self.file_path),
                "-t", f"{clip_len:.3f}",
                str(out_path)
            ]

        self.btn_export.setEnabled(False)
        ok = self._run_ffmpeg_with_progress(
            cmd, clip_len, "Экспорт файла",
            f"Сохранение: {Path(out_path).name}",
            cleanup_paths=[out_path]
        )
        self.btn_export.setEnabled(True)
        if ok:
            QMessageBox.information(self, "Готово", "Файл успешно экспортирован!")



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
