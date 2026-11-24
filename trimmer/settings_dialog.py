"""Окно настроек программы: тема, папки, поведение, обновления."""

import subprocess
import sys

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from trimmer.constants import APP_VERSION, ENTRY_SCRIPT, SCRIPT_DIR
from trimmer.context_menu import register_context_menu
from trimmer.settings import (
    PALETTE_DARK,
    PALETTE_LIGHT,
    get_contrast_text_color,
    save_app_settings,
)
from trimmer.system import set_console_visible, set_windows_titlebar_theme
from trimmer.updater import (
    _parse_ver_tuple,
    check_github_update,
    download_and_restart_update,
)


# === [БЛОК 20: ОКНО НАСТРОЕК ПРОГРАММЫ (ЧАСТЬ 1)] ===
class SettingsDialog(QDialog):
    def __init__(self, parent, settings: dict, on_settings_applied):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setFixedWidth(480)
        self.settings = settings
        self.on_settings_applied = on_settings_applied
        set_windows_titlebar_theme(self, self.settings.get("dark_mode", True))

        self.lay = QVBoxLayout(self)
        self.lay.setSpacing(10)

        self.lbl_theme_sec = QLabel("1. Тема и цветовой акцент:")
        self.lay.addWidget(self.lbl_theme_sec)

        theme_mode_row = QHBoxLayout()
        self.btn_dark = QPushButton("🌙 Тёмная тема")
        self.btn_light = QPushButton("☀ Светлая тема")
        self.btn_dark.clicked.connect(lambda: self._set_dark_mode(True))
        self.btn_light.clicked.connect(lambda: self._set_dark_mode(False))
        theme_mode_row.addWidget(self.btn_dark)
        theme_mode_row.addWidget(self.btn_light)
        self.lay.addLayout(theme_mode_row)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.color_buttons = []

        for col, hex_c in enumerate(PALETTE_LIGHT):
            btn = QPushButton()
            btn.setFixedSize(46, 34)
            btn.clicked.connect(lambda checked=False, c=hex_c: self._set_accent(c))
            grid.addWidget(btn, 0, col)
            self.color_buttons.append((btn, hex_c))

        for col, hex_c in enumerate(PALETTE_DARK):
            btn = QPushButton()
            btn.setFixedSize(46, 34)
            btn.clicked.connect(lambda checked=False, c=hex_c: self._set_accent(c))
            grid.addWidget(btn, 1, col)
            self.color_buttons.append((btn, hex_c))

        # === [БЛОК 21: ОКНО НАСТРОЕК ПРОГРАММЫ (ЧАСТЬ 2)] ===
        self.btn_custom_color = QPushButton("+")
        self.btn_custom_color.setFixedSize(46, 34)
        self.btn_custom_color.setStyleSheet(
            "background-color: #D4D4D8; color: #111111; font-size: 18px; font-weight: bold; border: 1px solid #888; border-radius: 5px;"
        )
        self.btn_custom_color.clicked.connect(self._pick_custom_color)
        grid.addWidget(self.btn_custom_color, 1, 4)
        self.lay.addLayout(grid)

        self.lbl_dir_sec = QLabel("2. Папка по умолчанию (для открытия и экспорта):")
        self.lay.addWidget(self.lbl_dir_sec)

        dir_row = QHBoxLayout()
        self.edit_dir = QLineEdit(self.settings.get("default_dir", str(SCRIPT_DIR)))
        self.edit_dir.setReadOnly(True)
        dir_row.addWidget(self.edit_dir, 1)

        btn_browse = QPushButton("Обзор...")
        btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(btn_browse)
        self.lay.addLayout(dir_row)

        self.cb_last_dir = QCheckBox(
            "Открывать последнюю папку (при экспорте и открытии)"
        )
        self.cb_last_dir.setChecked(self.settings.get("open_last_dir", True))
        self.cb_last_dir.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_last_dir)

        self.lbl_beh_sec = QLabel("3. Поведение ползунков и предпросмотр кадров:")
        self.lay.addWidget(self.lbl_beh_sec)

        self.cb_sync_trim = QCheckBox(
            "Привязывать ползунок длительности к границам начала и конца обрезки"
        )
        self.cb_sync_trim.setChecked(self.settings.get("sync_seek_with_trim", False))
        self.cb_sync_trim.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_sync_trim)

        self.cb_scrub_audio = QCheckBox("Включить звук при перемотке медиафайла")
        self.cb_scrub_audio.setChecked(self.settings.get("scrub_audio", False))
        self.cb_scrub_audio.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_scrub_audio)

        self.cb_preload_frames = QCheckBox(
            "Предзагружать опорные кадры от начала до конца при открытии (с окном прогресса)"
        )
        self.cb_preload_frames.setChecked(
            self.settings.get("preload_frames_dialog", False)
        )
        self.cb_preload_frames.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_preload_frames)

        scrub_res_row = QHBoxLayout()
        scrub_res_row.addWidget(QLabel("Разрешение опорных кадров:"))
        self.combo_scrub_res = QComboBox()
        self.combo_scrub_res.addItems(
            [
                "Оригинал",
                "4320p (8K)",
                "2160p (4K)",
                "1440p (2K)",
                "1080p",
                "720p",
                "480p",
                "360p",
                "240p",
                "144p",
            ]
        )
        cur_sr = self.settings.get("scrub_resolution", "360p")
        if self.combo_scrub_res.findText(cur_sr) >= 0:
            self.combo_scrub_res.setCurrentText(cur_sr)
        self.combo_scrub_res.currentTextChanged.connect(self._on_flags_changed)
        scrub_res_row.addWidget(self.combo_scrub_res)
        self.lay.addLayout(scrub_res_row)

        self.lbl_dev_sec = QLabel("4. Интеграция и обновления:")
        self.lay.addWidget(self.lbl_dev_sec)

        self.cb_ctx_menu = QCheckBox(
            "Добавить «Медиа Обрезчик» в меню «Открыть с помощью»"
        )
        self.cb_ctx_menu.setChecked(self.settings.get("context_menu", False))
        self.cb_ctx_menu.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_ctx_menu)

        self.cb_show_console = QCheckBox("Отображение консоли программы")
        self.cb_show_console.setChecked(self.settings.get("show_console", False))
        self.cb_show_console.stateChanged.connect(self._on_flags_changed)
        self.lay.addWidget(self.cb_show_console)

        upd_row = QHBoxLayout()
        self.lbl_ver_info = QLabel(f"Текущая версия: {APP_VERSION}")
        self.lbl_ver_info.setStyleSheet("font-size: 11px; color: #888888;")
        upd_row.addWidget(self.lbl_ver_info, 1)

        self.btn_check_upd = QPushButton("🔄 Проверить обновления")
        self.btn_check_upd.clicked.connect(self._on_check_updates_clicked)
        upd_row.addWidget(self.btn_check_upd)
        self.lay.addLayout(upd_row)

        self._refresh_dialog_style()

    # === [БЛОК 22: ОБРАБОТЧИКИ ОКНА НАСТРОЕК И ПРОВЕРКА ОБНОВЛЕНИЙ] ===
    def _set_dark_mode(self, is_dark: bool):
        self.settings["dark_mode"] = is_dark
        set_windows_titlebar_theme(self, is_dark)
        self._save_and_apply()

    def _set_accent(self, hex_color: str):
        self.settings["accent"] = hex_color
        self._save_and_apply()

    def _pick_custom_color(self):
        chosen = QColorDialog.getColor(
            QColor(self.settings.get("accent", "#FF9900")),
            self,
            "Выберите свой цвет темы",
        )
        if chosen.isValid():
            self.settings["accent"] = chosen.name().upper()
            self._save_and_apply()

    def _browse_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку по умолчанию", self.edit_dir.text()
        )
        if folder:
            self.settings["default_dir"] = folder
            self.settings["last_export_dir"] = folder
            self.edit_dir.setText(folder)
            self._save_and_apply()

    def _on_flags_changed(self):
        old_res = self.settings.get("scrub_resolution", "360p")
        new_res = self.combo_scrub_res.currentText()
        self.settings["open_last_dir"] = self.cb_last_dir.isChecked()
        self.settings["sync_seek_with_trim"] = self.cb_sync_trim.isChecked()
        self.settings["scrub_audio"] = self.cb_scrub_audio.isChecked()
        self.settings["preload_frames_dialog"] = self.cb_preload_frames.isChecked()
        self.settings["scrub_resolution"] = new_res
        self.settings["context_menu"] = self.cb_ctx_menu.isChecked()
        self.settings["show_console"] = self.cb_show_console.isChecked()
        register_context_menu(self.settings["context_menu"])
        set_console_visible(self.settings["show_console"])
        self._save_and_apply()

        if old_res != new_res and hasattr(
            self.parent(), "_on_settings_scrub_res_changed"
        ):
            self.parent()._on_settings_scrub_res_changed(new_res)

    def _save_and_apply(self):
        save_app_settings(self.settings)
        self._refresh_dialog_style()
        self.on_settings_applied()

    def _on_check_updates_clicked(self):
        self.btn_check_upd.setEnabled(False)
        self.btn_check_upd.setText("Проверка...")
        QApplication.processEvents()

        ok, remote_ver, err_msg = check_github_update()
        self.btn_check_upd.setEnabled(True)
        self.btn_check_upd.setText("🔄 Проверить обновления")

        if not ok:
            QMessageBox.warning(self, "Проверка обновлений", err_msg)
            return

        if _parse_ver_tuple(remote_ver) <= _parse_ver_tuple(APP_VERSION):
            box = QMessageBox(self)
            box.setWindowTitle("Обновления")
            box.setText(f"Это последняя версия обрезчика! (v{APP_VERSION})")
            box.addButton("Отмена", QMessageBox.RejectRole)
            box.exec()
            return

        box = QMessageBox(self)
        box.setWindowTitle("Доступно обновление")
        box.setText(f"Обновить обрезчик?  {APP_VERSION}  →  {remote_ver}")
        btn_install = box.addButton("Установить", QMessageBox.AcceptRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()

        if box.clickedButton() == btn_install:
            dl_ok, dl_err = download_and_restart_update()
            if not dl_ok:
                QMessageBox.critical(self, "Ошибка обновления", dl_err)
                return
            QMessageBox.information(
                self,
                "Обновление установлено",
                f"Обрезчик обновлён до версии {remote_ver}!\nСейчас программа перезапустится.",
            )
            subprocess.Popen([sys.executable, str(ENTRY_SCRIPT)])
            QApplication.quit()

    # === [БЛОК 23: ОФОРМЛЕНИЕ ОКНА НАСТРОЕК И ВИДЕОВИДЖЕТ С ПРЕДПРОСМОТРОМ] ===
    def _refresh_dialog_style(self):
        is_dark = self.settings.get("dark_mode", True)
        accent = self.settings.get("accent", "#FF9900")
        btn_fg = get_contrast_text_color(accent)
        bg = "#1E1E1E" if is_dark else "#F4F4F5"
        fg = "#EEEEEE" if is_dark else "#18181B"
        inp = "#121212" if is_dark else "#FFFFFF"

        self.setStyleSheet(f"background-color: {bg}; color: {fg}; font-family: Arial;")
        for lbl in (
            self.lbl_theme_sec,
            self.lbl_dir_sec,
            self.lbl_beh_sec,
            self.lbl_dev_sec,
        ):
            lbl.setStyleSheet(
                f"font-weight: bold; color: {accent}; font-size: 12px; margin-top: 4px;"
            )

        self.edit_dir.setStyleSheet(
            f"background-color: {inp}; color: {fg}; border: 1px solid #555; padding: 5px; border-radius: 3px;"
        )

        active_btn = f"background-color: {accent}; color: {btn_fg}; font-weight: bold; padding: 6px; border-radius: 4px;"
        inactive_btn = "background-color: #333333; color: #CCCCCC; padding: 6px; border-radius: 4px;"
        self.btn_dark.setStyleSheet(active_btn if is_dark else inactive_btn)
        self.btn_light.setStyleSheet(active_btn if not is_dark else inactive_btn)

        for btn, hex_c in self.color_buttons:
            border = (
                "3px solid #FFFFFF"
                if (hex_c.upper() == accent.upper() and is_dark)
                else (
                    "3px solid #111111"
                    if hex_c.upper() == accent.upper()
                    else "1px solid #555555"
                )
            )
            btn.setStyleSheet(
                f"background-color: {hex_c}; border: {border}; border-radius: 5px;"
            )
