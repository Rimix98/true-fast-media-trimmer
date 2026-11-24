"""Фоновый извлечатель кадров для сетки и скраббинга (FFmpeg -> QImage)."""

import subprocess
import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from trimmer.constants import FFMPEG_BIN


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
