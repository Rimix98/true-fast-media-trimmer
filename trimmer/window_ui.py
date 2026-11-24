"""Миксин: сборка интерфейса, события окна, умный зум и тема (блоки 25–31)."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from trimmer.constants import AUDIO_EXTS, VIDEO_EXTS
from trimmer.seek_slider import ClickableSeekSlider
from trimmer.settings import get_contrast_text_color
from trimmer.system import set_windows_titlebar_theme
from trimmer.trim_slider import DualTrimSlider
from trimmer.video_view import ClickableVideoWidget
from trimmer.waveform import AudioWaveformWidget


class WindowUiMixin:
    """Сборка интерфейса главного окна (не наследует QObject)."""

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
