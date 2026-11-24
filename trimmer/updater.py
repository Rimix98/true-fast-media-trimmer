"""Проверка обновлений на GitHub и самобновление скрипта-лаунчера."""

import re
import urllib.request

from trimmer.constants import ENTRY_SCRIPT, GITHUB_SCRIPT_URL, GITHUB_VERSION_URL


def _parse_ver_tuple(ver_str: str) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", ver_str)]
    return tuple(nums) if nums else (0,)


def check_github_update() -> tuple:
    try:
        req = urllib.request.Request(
            GITHUB_VERSION_URL, headers={"User-Agent": "MediaTrimmerUpdater"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            remote_ver = resp.read().decode("utf-8", errors="ignore").strip()
        if not remote_ver or len(remote_ver) > 25:
            return False, "", "Некорректный формат файла version.txt на GitHub."
        return True, remote_ver, ""
    except Exception as e:
        return False, "", f"Не удалось подключиться к GitHub:\n{e}"


def download_and_restart_update() -> tuple:
    try:
        req = urllib.request.Request(
            GITHUB_SCRIPT_URL, headers={"User-Agent": "MediaTrimmerUpdater"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            new_code = resp.read().decode("utf-8")
        if "MediaTrimmerWindow" not in new_code:
            return False, "Скачанный файл повреждён или не является кодом программы."
        ENTRY_SCRIPT.write_text(new_code, encoding="utf-8")
        return True, ""
    except Exception as e:
        return False, f"Ошибка при скачивании обновления:\n{e}"
