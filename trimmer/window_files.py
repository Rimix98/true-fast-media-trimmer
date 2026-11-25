"""Миксин: открытие файлов, опорные кадры, кэш и скриншоты (блок 36)."""

import subprocess
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox

from trimmer.constants import FFMPEG_BIN, VIDEO_EXTS
from trimmer.platform_support import subprocess_flags
from trimmer.progress_dialog import ProgressDialog


class WindowFilesMixin:
    """Работа с открытым файлом и кэшем опорных кадров."""

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
            self.player.setVideoOutput(self.video_widget.video_output)
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

    @staticmethod
    def _run_ffmpeg_bytes(cmd, flags, timeout=4) -> bytes:
        """Запуск ffmpeg с выводом кадра в stdout — без файлов на диске."""
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                timeout=timeout,
            )
        except Exception:
            return b""
        if res.returncode != 0:
            return b""
        return res.stdout or b""

    @staticmethod
    def _qimage_from_rgb24(data, width, height) -> QImage:
        """Сырой rgb24-кадр из памяти -> QImage с проверкой размеров."""
        if not data or width <= 0 or height <= 0:
            return QImage()
        row_bytes = width * 3
        if len(data) < row_bytes * height or len(data) % height != 0:
            return QImage()
        stride = len(data) // height
        # rawvideo может выравнивать строки — допускаем «хвост» до 3 байт
        if stride > row_bytes + 3:
            return QImage()
        if stride != row_bytes:
            data = b"".join(
                data[i * stride : i * stride + row_bytes] for i in range(height)
            )
            stride = row_bytes
        img = QImage(data, width, height, stride, QImage.Format_RGB888)
        return img.copy() if not img.isNull() else QImage()

    def _extract_current_fullres_qimage(self) -> QImage:
        if not self.is_video or not self.file_path:
            return QImage()
        cur_sec = self.trim_slider.playhead_sec
        flags = subprocess_flags()
        src_w = int(getattr(self, "video_src_w", 0) or 0)
        src_h = int(getattr(self, "video_src_h", 0) or 0)
        seek_args = [
            "-ss",
            f"{cur_sec:.3f}",
            "-i",
            str(self.file_path),
            "-frames:v",
            "1",
        ]

        # 1) сырой кадр сразу в память: без временного .png на диске
        img = self._qimage_from_rgb24(
            self._run_ffmpeg_bytes(
                [
                    FFMPEG_BIN,
                    "-v",
                    "error",
                    *seek_args,
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "pipe:1",
                ],
                flags,
            ),
            src_w,
            src_h,
        )
        if not img.isNull():
            return img

        # 2) запасной путь: PNG в буфер байтов, если размеры кадра не
        # совпали с метаданными (поворот, нестандартный контейнер)
        data = self._run_ffmpeg_bytes(
            [
                FFMPEG_BIN,
                "-v",
                "error",
                *seek_args,
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ],
            flags,
        )
        if data:
            img = QImage()
            img.loadFromData(data)
            return img
        return QImage()

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
        flags = subprocess_flags()
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
        flags = subprocess_flags()
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
            self.player.setVideoOutput(self.video_widget.video_output)
