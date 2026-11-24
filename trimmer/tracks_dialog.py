"""Окно микшера звуковых дорожек: дБ, мут и объединение дорожек."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from trimmer.constants import MAX_DB_VAL, MUTE_DB_VAL
from trimmer.platform_support import set_windows_titlebar_theme
from trimmer.settings import get_contrast_text_color
from trimmer.system import format_db_label


# === [БЛОК 14: ОКНО МИКШЕРА ЗВУКОВЫХ ДОРОЖЕК] ===
class AudioTracksDialog(QDialog):
    def __init__(
        self,
        parent,
        track_count,
        track_dbs,
        output_groups,
        on_db_changed,
        on_groups_changed,
        accent,
        dark_mode,
    ):
        super().__init__(parent)
        self.setWindowTitle("Звуковые дорожки и микшер (дБ)")
        self.resize(680, 320)
        self.setMinimumSize(520, 310)
        set_windows_titlebar_theme(self, dark_mode)

        self.track_count = track_count
        self.track_dbs = track_dbs
        self.output_groups = output_groups
        self.on_db_changed = on_db_changed
        self.on_groups_changed = on_groups_changed
        self.accent = accent
        self.dark_mode = dark_mode
        self.checkboxes = {}

        bg = "#1A1A1A" if dark_mode else "#F4F4F5"
        fg = "#EEEEEE" if dark_mode else "#18181B"
        scr_bg = "#121212" if dark_mode else "#E4E4E7"
        btn_sec = "#333333" if dark_mode else "#D4D4D8"
        btn_fg = get_contrast_text_color(accent)

        self.setStyleSheet(f"background-color: {bg}; color: {fg}; font-family: Arial;")
        layout = QVBoxLayout(self)

        lbl_top = QLabel(
            "Шкала в децибелах: от -∞ dB (тишина) и -100 dB до +24.0 dB (по умолчанию 0.0 dB):"
        )
        lbl_top.setStyleSheet(f"font-weight: bold; color: {accent}; font-size: 12px;")
        lbl_top.setWordWrap(True)
        layout.addWidget(lbl_top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(
            f"border: 1px solid #444444; background-color: {scr_bg};"
        )
        layout.addWidget(self.scroll, 1)

        btn_row = QHBoxLayout()
        btn_merge = QPushButton("🔗 Объединить выбранные в одну дорожку")
        btn_merge.setStyleSheet(
            f"background-color: {accent}; color: {btn_fg}; font-weight: bold; padding: 7px 14px; border-radius: 4px;"
        )
        btn_merge.clicked.connect(self.merge_selected)
        btn_row.addWidget(btn_merge)

        btn_reset = QPushButton("Сбросить все объединения")
        btn_reset.setStyleSheet(
            f"background-color: {btn_sec}; color: {fg}; padding: 7px 14px; border-radius: 4px;"
        )
        btn_reset.clicked.connect(self.reset_groups)
        btn_row.addWidget(btn_reset)
        layout.addLayout(btn_row)

        self._rebuild_cards()

    # === [БЛОК 15: ОТРИСОВКА КАРТОЧЕК ДОРОЖЕК В МИКШЕРЕ] ===
    def _rebuild_cards(self):
        self.checkboxes.clear()
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(8)

        card_bg = "#1E1E1E" if self.dark_mode else "#FFFFFF"
        card_merged_bg = "#241D14" if self.dark_mode else "#FFFBEB"
        fg = "#FFFFFF" if self.dark_mode else "#18181B"

        for out_idx, grp in enumerate(self.output_groups):
            is_merged = len(grp) > 1
            card = QFrame()
            if is_merged:
                card.setStyleSheet(
                    f"QFrame {{ background-color: {card_merged_bg}; border: 2px solid {self.accent}; border-radius: 6px; }}"
                )
            else:
                card.setStyleSheet(
                    f"QFrame {{ background-color: {card_bg}; border: 1px solid #555555; border-radius: 6px; }}"
                )

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(6)

            header = QHBoxLayout()
            if is_merged:
                title = QLabel(f"📦 Выходная дорожка {out_idx + 1}")
                title.setStyleSheet(
                    f"color: {self.accent}; font-weight: bold; font-size: 12px; border: none;"
                )
                header.addWidget(title, 1)

                btn_split = QPushButton("Разъединить")
                btn_split.setStyleSheet(
                    "background-color: #7F1D1D; color: #FECACA; padding: 3px 8px; border-radius: 3px; font-size: 11px;"
                )
                btn_split.clicked.connect(
                    lambda checked=False, g_i=out_idx: self.split_group(g_i)
                )
                header.addWidget(btn_split)
            else:
                title = QLabel(f"🎵 Выходная дорожка {out_idx + 1}")
                title.setStyleSheet(
                    "color: #888888; font-weight: bold; font-size: 11px; border: none;"
                )
                header.addWidget(title, 1)

            card_layout.addLayout(header)
            # === [БЛОК 16: ПОЛЗУНКИ ДБ ВНУТРИ КАРТОЧЕК ДОРОЖЕК] ===
            for t_idx in grp:
                row = QHBoxLayout()
                cb = QCheckBox(f"Дорожка {t_idx + 1}")
                cb.setStyleSheet(
                    f"font-size: 12px; border: none; color: {fg}; font-weight: bold;"
                )
                self.checkboxes[t_idx] = cb
                row.addWidget(cb, 0)

                cur_raw = self.track_dbs.get(t_idx, 0)
                lbl_val = QLabel(format_db_label(cur_raw))
                lbl_val.setFixedWidth(68)
                lbl_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                lbl_val.setStyleSheet(
                    "color: #22C55E; font-weight: bold; border: none;"
                    if cur_raw > 0
                    else f"color: {self.accent}; font-weight: bold; border: none;"
                )

                slider = QSlider(Qt.Horizontal)
                slider.setRange(MUTE_DB_VAL, MAX_DB_VAL)
                slider.setSingleStep(5)
                slider.setPageStep(20)
                slider.setValue(cur_raw)

                btn_zero = QPushButton("0 dB")
                btn_zero.setFixedWidth(42)
                btn_zero.setStyleSheet(
                    "background-color: #333333; color: #EEEEEE; font-size: 10px; padding: 2px; border-radius: 3px;"
                )

                def _make_handler(idx_t, lbl, sld):
                    def _changed(val):
                        if -15 <= val <= 15 and val != 0:
                            sld.blockSignals(True)
                            sld.setValue(0)
                            sld.blockSignals(False)
                            val = 0
                        self.track_dbs[idx_t] = val
                        lbl.setText(format_db_label(val))
                        lbl.setStyleSheet(
                            "color: #22C55E; font-weight: bold; border: none;"
                            if val > 0
                            else f"color: {self.accent}; font-weight: bold; border: none;"
                        )
                        self.on_db_changed(idx_t, val)

                    return _changed

                slider.valueChanged.connect(_make_handler(t_idx, lbl_val, slider))
                btn_zero.clicked.connect(
                    lambda checked=False, sld=slider: sld.setValue(0)
                )

                row.addWidget(slider, 1)
                row.addWidget(lbl_val)
                row.addWidget(btn_zero)
                card_layout.addLayout(row)

            vbox.addWidget(card)

        vbox.addStretch(1)
        self.scroll.setWidget(container)

    # === [БЛОК 17: ОБЪЕДИНЕНИЕ И РАЗЪЕДИНЕНИЕ ДОРОЖЕК] ===
    def split_group(self, group_index):
        grp = self.output_groups[group_index]
        new_groups = []
        for idx, g in enumerate(self.output_groups):
            if idx == group_index:
                for t in grp:
                    new_groups.append([t])
            else:
                new_groups.append(g)
        self.output_groups.clear()
        self.output_groups.extend(new_groups)
        self._rebuild_cards()
        self.on_groups_changed()

    def merge_selected(self):
        selected = [idx for idx, cb in self.checkboxes.items() if cb.isChecked()]
        if len(selected) < 2:
            QMessageBox.information(
                self,
                "Подсказка",
                "Отметьте галочками минимум 2 дорожки, чтобы объединить их.",
            )
            return
        sel_set = set(selected)
        new_groups = []
        merged_inserted = False
        for grp in self.output_groups:
            remaining = [t for t in grp if t not in sel_set]
            if not merged_inserted and any(t in sel_set for t in grp):
                new_groups.append(sorted(selected))
                merged_inserted = True
            if remaining:
                new_groups.append(remaining)
        self.output_groups.clear()
        self.output_groups.extend(new_groups)
        self._rebuild_cards()
        self.on_groups_changed()

    def reset_groups(self):
        self.output_groups.clear()
        for idx in range(self.track_count):
            self.output_groups.append([idx])
        self._rebuild_cards()
        self.on_groups_changed()
