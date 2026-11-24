"""Поток PCM-звука дорожки с программным усилением (GainAudioStream)."""

import subprocess

import numpy as np
from PySide6.QtCore import QIODevice

from trimmer.constants import FFMPEG_BIN
from trimmer.platform_support import subprocess_flags


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
        flags = subprocess_flags()
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
