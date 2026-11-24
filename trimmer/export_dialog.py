"""Окно настроек экспорта: формат, разрешение, качество, звук."""

import re
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from trimmer.constants import AUDIO_FORMATS, VIDEO_FORMATS
from trimmer.platform_support import set_windows_titlebar_theme
from trimmer.settings import get_contrast_text_color
from trimmer.system import BEST_GPU_ENCODER


# === [БЛОК 18: ОКНО НАСТРОЕК ЭКСПОРТА (ЧАСТЬ 1)] ===
class ExportDialog(QDialog):
    def __init__(
        self,
        parent,
        file_path: Path,
        is_video: bool,
        is_trimmed: bool,
        segments_count: int,
        accent: str,
        dark_mode: bool,
    ):
        super().__init__(parent)
        self.setWindowTitle("Экспорт медиафайла")
        self.setFixedWidth(460)
        set_windows_titlebar_theme(self, dark_mode)

        bg = "#1E1E1E" if dark_mode else "#F4F4F5"
        fg = "#EEEEEE" if dark_mode else "#18181B"
        inp_bg = "#121212" if dark_mode else "#FFFFFF"
        btn_fg = get_contrast_text_color(accent)
        self.setStyleSheet(f"background-color: {bg}; color: {fg}; font-family: Arial;")

        self.result_config = None
        lay = QVBoxLayout(self)
        lay.setSpacing(7)

        lbl_name = QLabel("Название файла:")
        lbl_name.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 12px;")
        lay.addWidget(lbl_name)

        self.edit_name = QLineEdit(f"{file_path.stem}_обрезано")
        self.edit_name.setStyleSheet(
            f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 6px 8px; border-radius: 4px; font-size: 13px;"
        )
        lay.addWidget(self.edit_name)

        self.combo_multi = None
        if segments_count > 1:
            lbl_multi = QLabel(f"Режим нарезки ({segments_count} отмеченных отрезков):")
            lbl_multi.setStyleSheet(
                "font-weight: bold; color: #22C55E; font-size: 12px; margin-top: 4px;"
            )
            lay.addWidget(lbl_multi)

            self.combo_multi = QComboBox()
            self.combo_multi.addItems(
                [
                    f"Склеить все {segments_count} отрезков в один файл",
                    f"Сохранить как {segments_count} отдельных файлов",
                ]
            )
            self.combo_multi.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #22C55E; padding: 6px; border-radius: 4px;"
            )
            lay.addWidget(self.combo_multi)

        row_fmt = QHBoxLayout()
        col_f1 = QVBoxLayout()
        lbl_fmt = QLabel("Формат:")
        lbl_fmt.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 12px;")
        col_f1.addWidget(lbl_fmt)

        self.combo_fmt = QComboBox()
        formats = VIDEO_FORMATS if is_video else AUDIO_FORMATS
        self.combo_fmt.addItems(formats)
        orig_ext = file_path.suffix.lower().lstrip(".")
        if orig_ext in formats:
            self.combo_fmt.setCurrentText(orig_ext)
        self.combo_fmt.setStyleSheet(
            f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
        )
        col_f1.addWidget(self.combo_fmt)
        row_fmt.addLayout(col_f1)
        # === [БЛОК 19: ОКНО НАСТРОЕК ЭКСПОРТА (ЧАСТЬ 2)] ===
        self.combo_res = None
        if is_video:
            col_f2 = QVBoxLayout()
            lbl_res = QLabel("Разрешение:")
            lbl_res.setStyleSheet(
                f"font-weight: bold; color: {accent}; font-size: 12px;"
            )
            col_f2.addWidget(lbl_res)

            self.combo_res = QComboBox()
            self.combo_res.addItems(
                [
                    "Оригинал",
                    "4320p (8K)",
                    "2160p (4K)",
                    "1440p (2K)",
                    "1080p",
                    "720p",
                    "480p",
                    "240p",
                    "144p",
                ]
            )
            self.combo_res.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
            )
            col_f2.addWidget(self.combo_res)
            row_fmt.addLayout(col_f2)

        lay.addLayout(row_fmt)

        self.combo_fps = None
        self.combo_crf = None
        self.combo_vbitrate = None
        self.combo_speed = None
        self.cb_no_audio = None

        if is_video:
            row_v1 = QHBoxLayout()
            c_fps = QVBoxLayout()
            c_fps.addWidget(QLabel("FPS:"))
            self.combo_fps = QComboBox()
            self.combo_fps.addItems(["Оригинал", "60 FPS", "30 FPS", "24 FPS"])
            self.combo_fps.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
            )
            c_fps.addWidget(self.combo_fps)
            row_v1.addLayout(c_fps)

            c_vbr = QVBoxLayout()
            c_vbr.addWidget(QLabel("Битрейт видео:"))
            self.combo_vbitrate = QComboBox()
            self.combo_vbitrate.addItems(
                [
                    "Авто (по CRF)",
                    "20 Мбит/с (20M)",
                    "12 Мбит/с (12M)",
                    "8 Мбит/с (8M)",
                    "5 Мбит/с (5M)",
                    "2.5 Мбит/с (2500k)",
                ]
            )
            self.combo_vbitrate.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
            )
            c_vbr.addWidget(self.combo_vbitrate)
            row_v1.addLayout(c_vbr)
            lay.addLayout(row_v1)

            lay.addWidget(QLabel("Качество сжатия:"))
            self.combo_crf = QComboBox()
            self.combo_crf.addItems(
                [
                    "Высокое качество (CRF 18)",
                    "Сбалансированное (CRF 23)",
                    "Малый размер файла (CRF 28)",
                ]
            )
            self.combo_crf.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
            )
            lay.addWidget(self.combo_crf)

            lay.addWidget(QLabel("Режим скорости экспорта:"))
            self.combo_speed = QComboBox()
            self.combo_speed.addItems(
                [
                    "Мгновенно без перекодирования (по ключевым кадрам, 1-2 сек)",
                    f"Полное перекодирование до доли секунды ({BEST_GPU_ENCODER})",
                ]
            )
            self.combo_speed.setStyleSheet(
                f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
            )
            lay.addWidget(self.combo_speed)

        row_aud = QHBoxLayout()
        c_abr = QVBoxLayout()
        lbl_abr = QLabel("Битрейт аудио:")
        lbl_abr.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 11px;")
        c_abr.addWidget(lbl_abr)
        self.combo_abitrate = QComboBox()
        self.combo_abitrate.addItems(
            ["192 kbps", "320 kbps", "256 kbps", "128 kbps", "96 kbps", "64 kbps"]
        )
        self.combo_abitrate.setStyleSheet(
            f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
        )
        c_abr.addWidget(self.combo_abitrate)
        row_aud.addLayout(c_abr)

        c_ach = QVBoxLayout()
        lbl_ach = QLabel("Каналы звука:")
        lbl_ach.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 11px;")
        c_ach.addWidget(lbl_ach)
        self.combo_achannels = QComboBox()
        self.combo_achannels.addItems(["Оригинал", "Стерео (2.0)", "Моно (1.0)"])
        self.combo_achannels.setStyleSheet(
            f"background-color: {inp_bg}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 4px;"
        )
        c_ach.addWidget(self.combo_achannels)
        row_aud.addLayout(c_ach)
        lay.addLayout(row_aud)

        if is_video:
            self.cb_no_audio = QCheckBox("Удалить звук (экспорт без аудиодорожек)")
            self.cb_no_audio.setStyleSheet("font-size: 12px; margin-top: 2px;")
            lay.addWidget(self.cb_no_audio)

        btn_export = QPushButton("Экспорт")
        btn_export.setStyleSheet(
            f"background-color: {accent}; color: {btn_fg}; font-size: 14px; font-weight: bold; padding: 10px; border-radius: 5px; margin-top: 8px;"
        )
        btn_export.clicked.connect(self._on_submit)
        lay.addWidget(btn_export)

    def _on_submit(self):
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Внимание", "Введите название файла!")
            return
        abr_raw = self.combo_abitrate.currentText()
        abr_num = re.search(r"\d+", abr_raw)
        self.result_config = {
            "name": name,
            "format": self.combo_fmt.currentText(),
            "resolution": self.combo_res.currentText()
            if self.combo_res
            else "Оригинал",
            "fps": self.combo_fps.currentText() if self.combo_fps else "Оригинал",
            "crf": self.combo_crf.currentText()
            if self.combo_crf
            else "Высокое качество (CRF 18)",
            "vbitrate": self.combo_vbitrate.currentText()
            if self.combo_vbitrate
            else "Авто (по CRF)",
            "abitrate": abr_num.group(0) if abr_num else "192",
            "achannels": self.combo_achannels.currentText(),
            "speed_mode": self.combo_speed.currentText() if self.combo_speed else "",
            "multi_mode": self.combo_multi.currentText() if self.combo_multi else "",
            "no_audio": self.cb_no_audio.isChecked() if self.cb_no_audio else False,
        }
        self.accept()
