"""Модальный диалог прогресс-бара с кнопкой отмены."""

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from trimmer.system import set_windows_titlebar_theme


# === [БЛОК 8: ДИАЛОГ ПРОГРЕСС-БАРА] ===
class ProgressDialog(QDialog):
    def __init__(
        self, parent, title_text: str, header_text: str, accent: str, dark_mode: bool
    ):
        super().__init__(parent)
        self.setWindowTitle(title_text)
        self.setFixedSize(380, 145)
        self.setModal(True)
        set_windows_titlebar_theme(self, dark_mode)

        bg = "#1E1E1E" if dark_mode else "#F4F4F5"
        fg = "#EEEEEE" if dark_mode else "#18181B"
        bar_bg = "#111111" if dark_mode else "#E4E4E7"
        self.setStyleSheet(f"background-color: {bg}; color: {fg}; font-family: Arial;")

        lay = QVBoxLayout(self)
        self.lbl_head = QLabel(header_text)
        self.lbl_head.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {accent};"
        )
        lay.addWidget(self.lbl_head)

        self.p_bar = QProgressBar()
        self.p_bar.setRange(0, 100)
        self.p_bar.setValue(0)
        self.p_bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid #555; border-radius: 4px; text-align: center; background: {bar_bg}; height: 20px; }}"
            f"QProgressBar::chunk {{ background-color: {accent}; }}"
        )
        lay.addWidget(self.p_bar)

        bottom_row = QHBoxLayout()
        self.lbl_eta = QLabel("Подготовка...")
        self.lbl_eta.setStyleSheet("font-size: 11px;")
        bottom_row.addWidget(self.lbl_eta, 1)

        self.btn_cancel = QPushButton("Отмена")
        self.btn_cancel.setStyleSheet(
            "background-color: #B91C1C; color: #FFFFFF; padding: 5px 14px; border-radius: 3px; font-weight: bold;"
        )
        bottom_row.addWidget(self.btn_cancel)
        lay.addLayout(bottom_row)

    def update_state(self, pct: int, eta_text: str):
        self.p_bar.setValue(pct)
        self.lbl_eta.setText(eta_text)
