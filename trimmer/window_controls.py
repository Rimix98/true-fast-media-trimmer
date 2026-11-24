"""Миксин: хоткеи, диалоги, микшер дорожек, громкость, прогресс FFMpeg
(блоки 32–35)."""

import json
import re
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaPlayer
from PySide6.QtWidgets import QMessageBox

from trimmer.audio_stream import GainAudioStream
from trimmer.constants import FFMPEG_BIN, FFPROBE_BIN, MUTE_DB_VAL, SCRIPT_DIR
from trimmer.ffmpeg_thread import FFmpegTaskThread
from trimmer.progress_dialog import ProgressDialog
from trimmer.settings_dialog import SettingsDialog
from trimmer.tracks_dialog import AudioTracksDialog


class WindowControlsMixin:
    """Управление воспроизведением, дорожками и служебные диалоги."""

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
        """Метаданные файла: (дур., аудиодорожек, fps, ширина, высота).

        Основной путь — ffprobe: один лёгкий запуск и структурированный JSON
        вместо запуска ffmpeg -i и парсинга его stderr. ffmpeg -i с
        регулярками остаётся запасным вариантом (ffprobe недоступен/ошибка).
        """
        if FFPROBE_BIN:
            probed = self._probe_media_info_ffprobe(path_str)
            if probed is not None:
                return probed

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

    @staticmethod
    def _parse_fps_value(raw):
        """'30000/1001' | '25.0' -> 29.97 (или None, если не похоже на fps)."""
        if not raw or raw in ("0/0", "N/A"):
            return None
        try:
            if "/" in str(raw):
                num_s, den_s = str(raw).split("/", 1)
                num, den = float(num_s), float(den_s)
                val = num / den if den else 0.0
            else:
                val = float(raw)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        return val if 5.0 <= val <= 240.0 else None

    @staticmethod
    def _video_stream_rotation(video_stream) -> int:
        """Угол поворота из display matrix (для вертикальных видео с телефона)."""
        rot = 0.0
        for side_data in video_stream.get("side_data_list") or []:
            try:
                rot = float(side_data.get("rotation", 0.0) or 0.0)
            except (TypeError, ValueError):
                pass
        if not rot:
            try:
                rot = float((video_stream.get("tags") or {}).get("rotate", 0) or 0)
            except (TypeError, ValueError):
                pass
        return round(rot) % 360

    def _probe_media_info_ffprobe(self, path_str):
        """Чтение метаданных через ffprobe. None — если ffprobe не справился."""
        cmd = [
            FFPROBE_BIN,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_streams",
            "-of",
            "json",
            path_str,
        ]
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=flags,
                timeout=15,
            )
            if res.returncode != 0:
                return None
            data = json.loads(res.stdout.decode("utf-8", errors="ignore") or "{}")
        except Exception:
            return None
        if not isinstance(data, dict):
            return None

        fmt = data.get("format") or {}
        streams = data.get("streams") or []

        dur = 0.0
        try:
            dur = float(fmt.get("duration") or 0.0)
        except (TypeError, ValueError):
            dur = 0.0
        if dur <= 0.0:
            # у части контейнеров длительность есть только у потоков
            for st in streams:
                try:
                    dur = max(dur, float(st.get("duration") or 0.0))
                except (TypeError, ValueError):
                    continue

        audio_cnt = sum(1 for st in streams if st.get("codec_type") == "audio")

        fps = 30.0
        src_w, src_h = 1920, 1080
        for st in streams:
            if st.get("codec_type") != "video":
                continue
            try:
                w = int(st.get("width") or 0)
                h = int(st.get("height") or 0)
            except (TypeError, ValueError):
                w = h = 0
            if w > 0 and h > 0:
                # ffmpeg показывает кадр уже развёрнутым по повороту
                if self._video_stream_rotation(st) % 180 == 90:
                    w, h = h, w
                src_w, src_h = w, h
            fps = (
                self._parse_fps_value(st.get("avg_frame_rate"))
                or self._parse_fps_value(st.get("r_frame_rate"))
                or fps
            )
            break

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
