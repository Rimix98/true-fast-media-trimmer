"""ДБ-подписи и выбор аппаратного кодировщика (платформо-независимо)."""

import subprocess

from trimmer.constants import FFMPEG_BIN, MUTE_DB_VAL
from trimmer.platform_support import subprocess_flags


# === [БЛОК 4: ДБ-ПОДПИСИ И ЭНКОДЕР] ===
def format_db_label(raw_val: int) -> str:
    if raw_val <= MUTE_DB_VAL:
        return "-∞ dB"
    db = raw_val / 10.0
    if db > 0:
        return f"+{db:.1f} dB"
    return f"{db:.1f} dB"


def detect_best_video_encoder() -> str:
    flags = subprocess_flags()
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
