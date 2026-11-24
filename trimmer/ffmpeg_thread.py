"""Фоновый поток запуска FFMpeg с прогрессом, ETA и логом ошибок."""

import re
import subprocess
import time

from PySide6.QtCore import QThread, Signal


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
