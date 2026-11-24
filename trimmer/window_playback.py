"""Миксин: воспроизведение, перемотка, метки времени, ключевые кадры
(блоки 37–38)."""

import re
import subprocess

from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QAudio, QMediaPlayer

from trimmer.constants import FFMPEG_BIN, FFPROBE_BIN, MUTE_DB_VAL


class WindowPlaybackMixin:
    """Позиция воспроизведения, скраббинг и обновление меток."""

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

    def _keyframe_scan_cache(self):
        """Кэш ключевых кадров текущего файла: pts и просканированные интервалы."""
        path_key = str(self.file_path) if self.file_path else ""
        cache = getattr(self, "_keyframe_scan", None)
        if cache is None or cache.get("path") != path_key:
            cache = {"path": path_key, "pts": set(), "spans": []}
            self._keyframe_scan = cache
        return cache

    @staticmethod
    def _merge_span(spans, start_sec, end_sec):
        """Добавляет интервал в отсортированный список непересекающихся интервалов."""
        merged = []
        for span_s, span_e in sorted(spans):
            if span_e < start_sec or span_s > end_sec:
                merged.append((span_s, span_e))
            else:
                start_sec = min(start_sec, span_s)
                end_sec = max(end_sec, span_e)
        merged.append((start_sec, end_sec))
        return sorted(merged)

    @staticmethod
    def _spans_cover(spans, start_sec, end_sec):
        """Покрыт ли интервал объединением уже просканированных интервалов."""
        cur = start_sec
        for span_s, span_e in sorted(spans):
            if span_s > cur:
                break
            if span_e >= end_sec:
                return True
            cur = max(cur, span_e)
        return cur >= end_sec

    @staticmethod
    def _keyframe_window(target_sec):
        """Квантованное окно сканирования вокруг цели.

        Чуть более широкое, чем [target-1, target+6], но привязанное к сетке
        5 сек: похожие цели (правка отрезка, повторный экспорт) попадают в одно
        окно и переиспользуют кэш вместо нового запуска ffmpeg/ffprobe.
        """
        bucket = 5.0
        q_start = int(max(0.0, target_sec - 1.0) / bucket) * bucket
        return q_start, q_start + bucket + 7.0

    def _scan_keyframes(self, start_sec, end_sec):
        """Один проход по интервалу: (pts ключевых кадров, успех).

        ffprobe читает только ключевые кадры без декодирования остальных;
        ffmpeg с showinfo (полное декодирование интервала) — запасной путь,
        когда ffprobe недоступен.
        """
        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        span = end_sec - start_sec
        if FFPROBE_BIN:
            cmd = [
                FFPROBE_BIN,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-skip_frame",
                "nokey",
                "-read_intervals",
                f"{start_sec:.2f}%+{span:.2f}",
                "-show_entries",
                "frame=pts_time",
                "-of",
                "csv=p=0",
                str(self.file_path),
            ]
        else:
            # Запасной путь без ffprobe: -ss прыгает к ближайшему ключевому
            # кадру, -copyts/-start_at_zero сохраняют абсолютные pts в showinfo
            cmd = [
                FFMPEG_BIN,
                "-ss",
                f"{start_sec:.3f}",
                "-copyts",
                "-start_at_zero",
                "-skip_frame",
                "nokey",
                "-i",
                str(self.file_path),
                "-t",
                f"{span + 2.0:.3f}",
                "-an",
                "-sn",
                "-dn",
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
        except Exception:
            return [], False
        raw = res.stdout if FFPROBE_BIN else res.stderr
        text = raw.decode("utf-8", errors="ignore")
        if FFPROBE_BIN:
            pts_list = [
                float(m.group(1))
                for m in re.finditer(r"^\s*(\d+(?:\.\d+)?)\s*$", text, re.MULTILINE)
            ]
        else:
            pts_list = [
                float(m.group(1))
                for m in re.finditer(r"pts_time:(\d+(?:\.\d+)?)", text)
            ]
        return pts_list, res.returncode == 0

    def _keyframe_pts_in(self, start_sec, end_sec):
        """Ключевые кадры интервала; уже просканированное не сканируем заново."""
        cache = self._keyframe_scan_cache()
        if not self._spans_cover(cache["spans"], start_sec, end_sec):
            pts_list, ok = self._scan_keyframes(start_sec, end_sec)
            cache["pts"].update(pts_list)
            if ok:
                cache["spans"] = self._merge_span(cache["spans"], start_sec, end_sec)
        return sorted(pts for pts in cache["pts"] if start_sec <= pts <= end_sec)

    def _snap_to_keyframe(self, target_sec: float) -> float:
        if target_sec <= 0.1:
            return 0.0
        win_start, win_end = self._keyframe_window(target_sec)
        for pts in self._keyframe_pts_in(win_start, win_end):
            if pts >= target_sec - 0.1:
                return max(0.0, pts - 0.01)
        return target_sec
