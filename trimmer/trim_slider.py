"""Мульти-отрезковый ползунок обрезки с контекстным меню по ПКМ."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget


# === [БЛОК 12: МУЛЬТИ-ОТРЕЗКОВЫЙ ПОЛЗУНОК ОБРЕЗКИ С КОНТЕКСТНЫМ МЕНЮ ПО ПКМ] ===
class DualTrimSlider(QWidget):
    zoom_wheel_requested = Signal(int, float)

    def __init__(self, on_trim_changed):
        super().__init__()
        self.on_trim_changed = on_trim_changed
        self.setFixedHeight(38)
        self.accent_color = "#FF9900"
        self.dark_mode = True
        self.sync_seek = False
        self.duration = 0.0
        self.playhead_sec = 0.0
        self.video_fps = 30.0

        # Список всех отрезков на таймлайне: [[start_sec, end_sec], ...]
        self.segments = []
        self.active_seg_idx = 0
        self.active_handle = None  # "start" | "end"
        self.setCursor(Qt.PointingHandCursor)

    @property
    def start_trim(self) -> float:
        if 0 <= self.active_seg_idx < len(self.segments):
            return self.segments[self.active_seg_idx][0]
        return 0.0

    @start_trim.setter
    def start_trim(self, val: float):
        if not self.segments:
            self.segments = [[val, max(val, self.duration)]]
            self.active_seg_idx = 0
        elif 0 <= self.active_seg_idx < len(self.segments):
            self.segments[self.active_seg_idx][0] = val

    @property
    def end_trim(self) -> float:
        if 0 <= self.active_seg_idx < len(self.segments):
            return self.segments[self.active_seg_idx][1]
        return self.duration

    @end_trim.setter
    def end_trim(self, val: float):
        if not self.segments:
            self.segments = [[0.0, val]]
            self.active_seg_idx = 0
        elif 0 <= self.active_seg_idx < len(self.segments):
            self.segments[self.active_seg_idx][1] = val

    def reset_segments(self, dur: float):
        self.duration = max(0.0, dur)
        self.segments = [[0.0, self.duration]] if self.duration > 0 else []
        self.active_seg_idx = 0
        self.active_handle = None
        self.update()

    def get_sorted_segments(self) -> list:
        valid = [
            (round(s, 3), round(e, 3)) for s, e in self.segments if (e - s) >= 0.02
        ]
        valid.sort(key=lambda item: item[0])
        return valid

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad = 14
        tw = max(1, w - pad * 2)
        y = h // 2

        track_bg = QColor(58, 58, 62) if self.dark_mode else QColor(200, 200, 205)
        p.setPen(QPen(track_bg, 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pad, y, w - pad, y)

        if self.duration > 0 and self.segments:
            accent_q = QColor(self.accent_color)
            dim_accent = QColor(accent_q)
            dim_accent.setAlpha(155)

            for idx, (seg_s, seg_e) in enumerate(self.segments):
                x1 = pad + (seg_s / self.duration) * tw
                x2 = pad + (seg_e / self.duration) * tw
                is_active = idx == self.active_seg_idx

                # Полупрозрачная подложка зоны отрезка
                fill_c = QColor(accent_q)
                fill_c.setAlpha(55 if is_active else 28)
                p.fillRect(QRectF(x1, y - 10, max(2.0, x2 - x1), 20), fill_c)

                # Линия отрезка
                p.setPen(
                    QPen(
                        accent_q if is_active else dim_accent,
                        6,
                        Qt.SolidLine,
                        Qt.RoundCap,
                    )
                )
                p.drawLine(int(x1), y, int(x2), y)

                # Ручки начала и конца каждого отрезка
                for hx in (x1, x2):
                    p.setBrush(
                        QColor(255, 255, 255) if is_active else QColor(225, 225, 230)
                    )
                    p.setPen(QPen(accent_q if is_active else dim_accent, 2))
                    p.drawRoundedRect(QRectF(hx - 6, y - 12, 12, 24), 3, 3)

            xp = pad + (self.playhead_sec / self.duration) * tw
            tick_c = (
                QColor(255, 255, 255, 190)
                if self.dark_mode
                else QColor(20, 20, 20, 190)
            )
            p.setPen(QPen(tick_c, 2))
            p.drawLine(int(xp), y - 11, int(xp), y + 11)

    # === [БЛОК 13: СОБЫТИЯ МЫШИ, ПЕРЕМЕЩЕНИЕ ОТРЕЗКА ЦЕЛИКОМ И КОНТЕКСТНОЕ МЕНЮ (ПКМ)] ===
    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = 1 if event.angleDelta().y() > 0 else -1
            ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            self.zoom_wheel_requested.emit(delta, ratio)
            event.accept()
        else:
            super().wheelEvent(event)

    def _x_to_sec(self, mx: float) -> float:
        pad = 14
        tw = max(1, self.width() - pad * 2)
        ratio = max(0.0, min(1.0, (mx - pad) / tw))
        return ratio * self.duration

    def _find_segment_at_sec(self, sec: float) -> int:
        for idx, (s, e) in enumerate(self.segments):
            if s <= sec <= e:
                return idx
        return -1

    def _add_cut_at_sec(self, click_sec: float):
        if self.duration <= 0.1:
            return
        fps = getattr(self, "video_fps", 60.0)
        min_gap = (1.0 / fps) if fps > 0 else 0.02
        default_len = max(0.5, min(self.duration * 0.08, 12.0))

        ordered = sorted(self.segments, key=lambda item: item[0])

        for idx, seg in enumerate(ordered):
            if seg[0] < click_sec < seg[1] and (seg[1] - seg[0]) > min_gap * 4:
                new_s = click_sec
                new_e = min(seg[1], click_sec + default_len)
                if (seg[1] - new_e) >= min_gap * 2:
                    tail_e = seg[1]
                    seg[1] = max(seg[0] + min_gap, new_s - min_gap)
                    new_e = min(tail_e - min_gap, new_s + default_len)
                    self.segments.append([new_s, max(new_s + min_gap, new_e)])
                    self.segments.append(
                        [min(tail_e - min_gap, new_e + min_gap), tail_e]
                    )
                else:
                    seg[1] = max(seg[0] + min_gap, new_s - min_gap)
                    self.segments.append([new_s, new_e])
                self.segments.sort(key=lambda item: item[0])
                self.active_seg_idx = next(
                    (
                        i
                        for i, x in enumerate(self.segments)
                        if abs(x[0] - new_s) < 0.01
                    ),
                    len(self.segments) - 1,
                )
                self.update()
                self.on_trim_changed("start", True)
                return

        left_bound = 0.0
        right_bound = self.duration
        for s, e in ordered:
            if e <= click_sec:
                left_bound = max(left_bound, e + min_gap)
            if s >= click_sec:
                right_bound = min(right_bound, s - min_gap)
                break

        if right_bound - left_bound < min_gap * 2:
            return

        new_s = max(left_bound, min(click_sec, right_bound - min_gap * 2))
        new_e = min(right_bound, new_s + default_len)
        self.segments.append([new_s, new_e])
        self.segments.sort(key=lambda item: item[0])
        self.active_seg_idx = next(
            (i for i, x in enumerate(self.segments) if abs(x[0] - new_s) < 0.01),
            len(self.segments) - 1,
        )
        self.update()
        self.on_trim_changed("start", True)

    def contextMenuEvent(self, event):
        if self.duration <= 0:
            return
        click_sec = self._x_to_sec(event.pos().x())
        hit_idx = self._find_segment_at_sec(click_sec)

        menu = QMenu(self)
        act_add = menu.addAction("➕ Добавить обрезку здесь")
        act_del = None
        act_reset = None

        if hit_idx >= 0 and len(self.segments) > 1:
            act_del = menu.addAction(f"🗑 Удалить обрезку #{hit_idx + 1}")
        if len(self.segments) > 1:
            menu.addSeparator()
            act_reset = menu.addAction("🧹 Сбросить до одной обрезки")

        chosen = menu.exec(event.globalPos())
        if chosen == act_add:
            self._add_cut_at_sec(click_sec)
        elif act_del is not None and chosen == act_del:
            self.segments.pop(hit_idx)
            self.active_seg_idx = max(
                0, min(self.active_seg_idx, len(self.segments) - 1)
            )
            self.update()
            self.on_trim_changed("start", True)
        elif act_reset is not None and chosen == act_reset:
            self.reset_segments(self.duration)
            self.on_trim_changed("start", True)

    def mousePressEvent(self, event):
        if self.duration <= 0 or not self.segments:
            return
        if event.button() != Qt.LeftButton:
            return

        pad = 14
        tw = max(1, self.width() - pad * 2)
        mx = event.position().x()
        handle_hit_px = 10.0

        # 1. Сначала проверяем точное попадание по ручкам начала/конца любого отрезка
        best_dist = handle_hit_px + 1.0
        best_seg = -1
        best_handle = None

        for idx, (seg_s, seg_e) in enumerate(self.segments):
            x1 = pad + (seg_s / self.duration) * tw
            x2 = pad + (seg_e / self.duration) * tw
            d1 = abs(mx - x1)
            d2 = abs(mx - x2)
            if d1 <= handle_hit_px and d1 < best_dist:
                best_dist = d1
                best_seg = idx
                best_handle = "start"
            if d2 <= handle_hit_px and d2 < best_dist:
                best_dist = d2
                best_seg = idx
                best_handle = "end"

        if best_seg >= 0:
            self.active_seg_idx = best_seg
            self.active_handle = best_handle
            self.update()
            self.mouseMoveEvent(event)
            return

        # 2. Если нажали в любое место внутри тела обрезки — выделяем её и готовим перемещение целиком!
        for idx, (seg_s, seg_e) in enumerate(self.segments):
            x1 = pad + (seg_s / self.duration) * tw
            x2 = pad + (seg_e / self.duration) * tw
            if x1 <= mx <= x2:
                self.active_seg_idx = idx
                self.active_handle = "move"
                self._drag_grab_offset_sec = self._x_to_sec(mx) - seg_s
                self._drag_seg_len_sec = seg_e - seg_s
                self.update()
                self.on_trim_changed("start", False)
                return

    def mouseMoveEvent(self, event):
        if not self.active_handle or self.duration <= 0 or not self.segments:
            return
        pad = 14
        tw = max(1, self.width() - pad * 2)
        mx = event.position().x()

        fps = getattr(self, "video_fps", 60.0)
        min_gap = (1.0 / fps) if fps > 0 else 0.016
        idx = self.active_seg_idx
        seg_s, seg_e = self.segments[idx]

        prev_end = max(
            [
                s[1] + min_gap
                for i, s in enumerate(self.segments)
                if i != idx and s[1] <= seg_s
            ],
            default=0.0,
        )
        next_start = min(
            [
                s[0] - min_gap
                for i, s in enumerate(self.segments)
                if i != idx and s[0] >= seg_e
            ],
            default=self.duration,
        )

        if self.active_handle == "move":
            seg_len = getattr(self, "_drag_seg_len_sec", seg_e - seg_s)
            grab_off = getattr(self, "_drag_grab_offset_sec", 0.0)
            raw_new_s = self._x_to_sec(mx) - grab_off

            # Мягкое прилипание начала или конца перетаскиваемого отрезка к ползунку длительности
            if not self.sync_seek:
                xp = pad + (self.playhead_sec / self.duration) * tw
                x_new_s = pad + (raw_new_s / self.duration) * tw
                x_new_e = pad + ((raw_new_s + seg_len) / self.duration) * tw
                if abs(x_new_s - xp) <= 5.0:
                    raw_new_s = self.playhead_sec
                elif abs(x_new_e - xp) <= 5.0:
                    raw_new_s = self.playhead_sec - seg_len

            if fps > 0:
                raw_new_s = round(raw_new_s * fps) / fps

            max_allowed_s = max(prev_end, next_start - seg_len)
            clamped_s = max(prev_end, min(raw_new_s, max_allowed_s))
            clamped_e = min(next_start, clamped_s + seg_len)

            self.segments[idx][0] = clamped_s
            self.segments[idx][1] = clamped_e
            self.update()
            self.on_trim_changed("start", False)
            return

        xp = pad + (self.playhead_sec / self.duration) * tw
        if not self.sync_seek and abs(mx - xp) <= 5.0:
            sec = self.playhead_sec
        else:
            ratio = max(0.0, min(1.0, (mx - pad) / tw))
            sec = ratio * self.duration

        if fps > 0:
            sec = round(sec * fps) / fps

        if self.active_handle == "start":
            self.segments[idx][0] = max(prev_end, min(sec, seg_e - min_gap))
        else:
            self.segments[idx][1] = min(next_start, max(sec, seg_s + min_gap))

        self.update()
        self.on_trim_changed(self.active_handle, False)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.active_handle:
            h = "start" if self.active_handle == "move" else self.active_handle
            self.active_handle = None
            self.on_trim_changed(h, True)
