"""Миксин: единое окно экспорта, нарезка отрезков, склейка (блок 39)."""

import re
import shutil
import subprocess
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from trimmer.constants import FFMPEG_BIN
from trimmer.export_dialog import ExportDialog
from trimmer.progress_dialog import ProgressDialog
from trimmer.settings import save_app_settings
from trimmer.system import BEST_GPU_ENCODER


class WindowExportMixin:
    """Сборка команд FFMpeg и пошаговый экспорт с прогрессом."""

    # === [БЛОК 39: ЕДИНОЕ ОКНО ЭКСПОРТА МЕДИАФАЙЛА, НАРЕЗКА ОТРЕЗКОВ И ТОЧКА ВХОДА] ===
    def _run_batch_export_single_dialog(
        self, tasks: list, total_all_dur: float, title: str
    ) -> bool:
        """Выполняет все этапы экспорта и склейки в ОДНОМ окне прогресса без мигания"""
        dlg = ProgressDialog(
            self,
            title,
            "Подготовка экспорта...",
            self.settings.get("accent", "#FF9900"),
            self.settings.get("dark_mode", True),
        )
        state = {
            "cancelled": False,
            "ok": True,
            "cur_proc": None,
            "done_dur": 0.0,
            "start_t": time.time(),
        }

        def _on_cancel():
            state["cancelled"] = True
            proc = state["cur_proc"]
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
            dlg.reject()

        dlg.btn_cancel.clicked.connect(_on_cancel)
        dlg.show()
        QApplication.processEvents()

        flags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
        safe_total = max(0.1, total_all_dur)

        for header_txt, cmd, step_dur, fallback_cmd, cleanup_list in tasks:
            if state["cancelled"]:
                state["ok"] = False
                break

            dlg.lbl_head.setText(header_txt)
            QApplication.processEvents()

            step_ok = False
            for attempt_cmd in [cmd, fallback_cmd] if fallback_cmd else [cmd]:
                if state["cancelled"]:
                    break
                last_lines = []
                try:
                    proc = subprocess.Popen(
                        attempt_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="ignore",
                        creationflags=flags,
                    )
                    state["cur_proc"] = proc
                    for line in proc.stdout:
                        if state["cancelled"]:
                            break
                        clean_l = line.strip()
                        if clean_l:
                            last_lines.append(clean_l)
                            if len(last_lines) > 8:
                                last_lines.pop(0)
                        m = time_re.search(line)
                        if m:
                            cur_sec = (
                                int(m.group(1)) * 3600
                                + int(m.group(2)) * 60
                                + float(m.group(3))
                            )
                            overall_cur = state["done_dur"] + min(step_dur, cur_sec)
                            pct = min(99, max(1, int((overall_cur / safe_total) * 100)))
                            elapsed = time.time() - state["start_t"]
                            if pct > 2 and elapsed > 0.4:
                                eta_sec = int((elapsed / pct) * (100 - pct))
                                mins, secs = divmod(max(0, eta_sec), 60)
                                eta_str = f"Общий прогресс: {pct}%  •  Осталось: ~{mins:02d}:{secs:02d}"
                            else:
                                eta_str = (
                                    f"Общий прогресс: {pct}%  •  Расчёт времени..."
                                )
                            dlg.update_state(pct, eta_str)
                        QApplication.processEvents()

                    proc.wait()
                    state["cur_proc"] = None
                    if not state["cancelled"] and proc.returncode == 0:
                        step_ok = True
                        break
                except Exception as e:
                    last_lines.append(str(e))

            if state["cancelled"] or not step_ok:
                state["ok"] = False
                for p in cleanup_list:
                    try:
                        Path(p).unlink(missing_ok=True)
                    except Exception:
                        pass
                if not state["cancelled"]:
                    dlg.reject()
                    QMessageBox.critical(
                        self,
                        "Ошибка",
                        "Операция прервана:\n" + "\n".join(last_lines[-6:]),
                    )
                break

            state["done_dur"] += step_dur

        if state["ok"] and not state["cancelled"]:
            dlg.update_state(100, "Готово!")
            QApplication.processEvents()
            dlg.accept()
        return state["ok"] and not state["cancelled"]

    def open_export_dialog(self):
        if not self.file_path or self.duration <= 0:
            QMessageBox.warning(self, "Внимание", "Сначала откройте файл!")
            return

        segments = self.trim_slider.get_sorted_segments() or [(0.0, self.duration)]
        is_trimmed = (
            len(segments) > 1
            or (segments[0][0] > 0.05)
            or (segments[-1][1] < self.duration - 0.05)
        )

        dlg = ExportDialog(
            self,
            self.file_path,
            self.is_video,
            is_trimmed,
            len(segments),
            self.settings.get("accent", "#FF9900"),
            self.settings.get("dark_mode", True),
        )
        if dlg.exec() != QDialog.Accepted or not dlg.result_config:
            return

        cfg = dlg.result_config
        ext = cfg.get("format")
        save_base_dir = Path(self._get_target_dir())
        default_full = str(save_base_dir / f"{cfg.get('name')}.{ext}")
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Куда сохранить файл", default_full, f"*.{ext}"
        )
        if not out_path:
            return

        try:
            free_bytes = shutil.disk_usage(Path(out_path).parent).free
            if free_bytes < 50 * 1024 * 1024:
                QMessageBox.warning(
                    self,
                    "Недостаточно места на диске",
                    f"На диске {Path(out_path).drive} осталось менее 50 МБ свободного места ({free_bytes // (1024 * 1024)} МБ).",
                )
                return
        except Exception:
            pass

        self.settings["last_export_dir"] = str(Path(out_path).parent)
        save_app_settings(self.settings)

        out_p_obj = Path(out_path)
        merge_segments = len(segments) > 1 and "Склеить" in cfg.get("multi_mode", "")
        temp_parts = []
        tasks = []
        has_gpu = BEST_GPU_ENCODER != "libx264"
        total_clips_dur = sum(max(0.1, e - s) for s, e in segments)

        for seg_idx, (seg_s, seg_e) in enumerate(segments, 1):
            clip_len = max(0.1, seg_e - seg_s)
            if merge_segments:
                part_path = (
                    self.cache_dir / f"seg_part_{self.load_counter}_{seg_idx}.{ext}"
                )
                temp_parts.append(part_path)
            elif len(segments) > 1:
                part_path = out_p_obj.with_name(
                    f"{out_p_obj.stem}_часть{seg_idx}{out_p_obj.suffix}"
                )
            else:
                part_path = out_p_obj

            hdr = (
                f"Обработка отрезка {seg_idx} из {len(segments)}: {part_path.name}"
                if len(segments) > 1
                else f"Сохранение: {part_path.name}"
            )
            cmd = self._build_segment_ffmpeg_cmd(
                cfg, seg_s, clip_len, ext, str(part_path), force_cpu=False
            )
            fb_cmd = (
                self._build_segment_ffmpeg_cmd(
                    cfg, seg_s, clip_len, ext, str(part_path), force_cpu=True
                )
                if has_gpu
                else None
            )
            tasks.append((hdr, cmd, clip_len, fb_cmd, [part_path]))

        concat_txt = None
        if merge_segments and len(temp_parts) > 1:
            concat_txt = self.cache_dir / f"concat_{self.load_counter}.txt"
            lines = [f"file '{p.as_posix()}'" for p in temp_parts]
            concat_txt.write_text("\n".join(lines), encoding="utf-8")
            merge_cmd = [
                FFMPEG_BIN,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_txt),
                "-c",
                "copy",
                str(out_p_obj),
            ]
            tasks.append(
                (
                    f"Финальная склейка {len(temp_parts)} отрезков в {out_p_obj.name}...",
                    merge_cmd,
                    max(0.5, total_clips_dur * 0.08),
                    None,
                    [out_p_obj],
                )
            )

        grand_total_dur = sum(t[2] for t in tasks)
        self.btn_export.setEnabled(False)
        all_ok = self._run_batch_export_single_dialog(
            tasks,
            grand_total_dur,
            "Экспорт и склейка" if merge_segments else "Экспорт файла",
        )

        for tp in temp_parts:
            tp.unlink(missing_ok=True)
        if concat_txt is not None:
            concat_txt.unlink(missing_ok=True)

        self.btn_export.setEnabled(True)
        if all_ok:
            QMessageBox.information(self, "Готово", "Экспорт успешно завершён!")

    def _build_segment_ffmpeg_cmd(
        self,
        cfg: dict,
        start_sec: float,
        clip_len: float,
        ext: str,
        out_path_str: str,
        force_cpu: bool = False,
    ) -> list:
        abr_kbps = str(cfg.get("abitrate", "192"))
        ach_str = cfg.get("achannels", "Оригинал")
        ach_args = (
            ["-ac", "1"]
            if "Моно" in ach_str
            else (["-ac", "2"] if "Стерео" in ach_str else [])
        )

        if not self.is_video:
            cmd = [
                FFMPEG_BIN,
                "-y",
                "-ss",
                f"{start_sec:.3f}",
                "-i",
                str(self.file_path),
                "-t",
                f"{clip_len:.3f}",
                *ach_args,
            ]
            if ext in {"mp3", "aac", "m4a", "ogg", "opus"}:
                cmd.extend(["-b:a", f"{abr_kbps}k"])
            cmd.append(out_path_str)
            return cmd

        crf_str = cfg.get("crf", "")
        crf_val = "28" if "28" in crf_str else ("23" if "23" in crf_str else "18")

        vbr_str = cfg.get("vbitrate", "Авто (по CRF)")
        vbr_match = re.search(r"\((\d+(?:\.\d+)?[Mk])\)", vbr_str)
        v_bitrate_args = ["-b:v", vbr_match.group(1)] if vbr_match else []

        vf_chain = []
        res_str = cfg.get("resolution", "Оригинал")
        res_map = {
            "4320p (8K)": 4320,
            "2160p (4K)": 2160,
            "1440p (2K)": 1440,
            "1080p": 1080,
            "720p": 720,
            "480p": 480,
            "240p": 240,
            "144p": 144,
        }
        if res_str in res_map:
            vf_chain.append(f"scale=-2:{res_map.get(res_str)}")

        fps_str = cfg.get("fps", "Оригинал")
        if "60" in fps_str:
            vf_chain.append("fps=60")
        elif "30" in fps_str:
            vf_chain.append("fps=30")
        elif "24" in fps_str:
            vf_chain.append("fps=24")

        orig_ext = self.file_path.suffix.lower().lstrip(".")
        want_copy = "Мгновенно" in cfg.get("speed_mode", "")
        can_stream_copy = (
            want_copy and not vf_chain and not v_bitrate_args and ext == orig_ext
        )

        if can_stream_copy:
            kf_start = self._snap_to_keyframe(start_sec)
            adj_len = max(0.2, (start_sec + clip_len) - kf_start)
            cmd = [
                FFMPEG_BIN,
                "-y",
                "-ss",
                f"{kf_start:.3f}",
                "-i",
                str(self.file_path),
                "-t",
                f"{adj_len:.3f}",
                "-map",
                "0:v:0",
                "-c:v",
                "copy",
                "-use_editlist",
                "0",
                "-avoid_negative_ts",
                "make_zero",
            ]
        else:
            encoder = "libx264" if force_cpu else BEST_GPU_ENCODER
            if encoder == "h264_nvenc":
                v_codec_args = ["-c:v", "h264_nvenc", "-preset", "p1", "-cq", crf_val]
                vf_chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2,format=nv12")
            elif encoder == "h264_amf":
                auto_bv = (
                    []
                    if v_bitrate_args
                    else [
                        "-b:v",
                        "12M"
                        if crf_val == "18"
                        else ("7M" if crf_val == "23" else "4M"),
                    ]
                )
                v_codec_args = ["-c:v", "h264_amf", *auto_bv]
                vf_chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2,format=nv12")
            elif encoder == "h264_qsv":
                v_codec_args = [
                    "-c:v",
                    "h264_qsv",
                    "-preset",
                    "veryfast",
                    "-global_quality",
                    crf_val,
                ]
                vf_chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2,format=nv12")
            else:
                v_codec_args = [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    crf_val,
                    "-threads",
                    "0",
                ]
                vf_chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p")

            cmd = [
                FFMPEG_BIN,
                "-y",
                "-ss",
                f"{max(0.0, start_sec - 2.0):.3f}",
                "-i",
                str(self.file_path),
                "-ss",
                f"{min(2.0, start_sec):.3f}",
                "-t",
                f"{clip_len:.3f}",
                "-map",
                "0:v:0",
                *v_codec_args,
                *v_bitrate_args,
                "-vf",
                ",".join(vf_chain),
            ]

        if cfg.get("no_audio") or ext == "gif" or not self.output_groups:
            cmd.append("-an")
        else:
            no_audio_edits = (
                len(self.output_groups) == self.track_count
                and all(
                    len(g) == 1 and g == [i] and self.track_dbs.get(i, 0) == 0
                    for i, g in enumerate(self.output_groups)
                )
                and not ach_args
                and abr_kbps == "192"
            )
            if no_audio_edits and ext in {"mp4", "mkv", "mov"}:
                cmd.extend(["-map", "0:a", "-c:a", "copy"])
            else:
                filters = []
                for out_i, grp in enumerate(self.output_groups):
                    if len(grp) == 1:
                        t_idx = next(iter(grp))
                        vf = self._build_ffmpeg_vol_filter(t_idx)
                        filters.append(f"[0:a:{t_idx}]{vf}[aout{out_i}]")
                    else:
                        in_labels = []
                        for t_idx in grp:
                            vf = self._build_ffmpeg_vol_filter(t_idx)
                            lbl = f"[v_{out_i}_{t_idx}]"
                            filters.append(f"[0:a:{t_idx}]{vf}{lbl}")
                            in_labels.append(lbl)
                        joined = "".join(in_labels)
                        filters.append(
                            f"{joined}amix=inputs={len(grp)}:duration=first:dropout_transition=0[aout{out_i}]"
                        )

                cmd.extend(["-filter_complex", ";".join(filters)])
                for out_i in range(len(self.output_groups)):
                    cmd.extend(["-map", f"[aout{out_i}]"])
                cmd.extend(["-c:a", "aac", "-b:a", f"{abr_kbps}k", *ach_args])

        if ext in {"mp4", "mov"} and not can_stream_copy:
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(out_path_str)
        return cmd
