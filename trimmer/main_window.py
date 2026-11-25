"""Главное окно приложения «Медиа Обрезчик».

Логика разнесена по миксинам (см. модули window_*.py):
- WindowUiMixin       — сборка интерфейса, тема, зум, drag & drop;
- WindowControlsMixin — хоткеи, диалоги, микшер дорожек, прогресс FFMpeg;
- WindowFilesMixin    — открытие файлов, опорные кадры, кэш, скриншоты;
- WindowPlaybackMixin — воспроизведение, перемотка, метки времени;
- WindowExportMixin   — пайплайн экспорта и команды FFMpeg.
"""

from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QMainWindow

from trimmer.constants import SCRIPT_DIR
from trimmer.frame_worker import FrameScrubWorker
from trimmer.platform_support import set_console_visible, set_windows_titlebar_theme
from trimmer.settings import load_app_settings
from trimmer.window_controls import WindowControlsMixin
from trimmer.window_export import WindowExportMixin
from trimmer.window_files import WindowFilesMixin
from trimmer.window_playback import WindowPlaybackMixin
from trimmer.window_ui import WindowUiMixin


class MediaTrimmerWindow(
    WindowUiMixin,
    WindowControlsMixin,
    WindowFilesMixin,
    WindowPlaybackMixin,
    WindowExportMixin,
    QMainWindow,
):
    """См. docstring модуля."""

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
        self._frame_cache_bytes = 0
        self._keyframe_scan = None
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
