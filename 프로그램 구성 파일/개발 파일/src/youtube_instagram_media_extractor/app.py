from __future__ import annotations

import os
import queue
import threading
import traceback
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox
import tkinter as tk

import customtkinter as ctk

from youtube_instagram_media_extractor.downloader import DownloadResult, UserFacingError, YouTubeInstagramMediaPipeline
from youtube_instagram_media_extractor.settings import AppSettings, default_output_dir, is_current_default_output_dir, load_settings, save_settings
from youtube_instagram_media_extractor.utils import resource_path


PRODUCT_NAME = "YouTube·Instagram 미디어 추출기"
OUTPUT_FORMAT_CHOICES = ["MP3", "MP4"]
QUALITY_CHOICES = ["128", "192", "256", "320"]
BROWSER_CHOICES = ["chrome", "edge", "firefox", "brave", "whale"]


class ActivitySpinner(tk.Canvas):
    def __init__(self, master: tk.Misc, size: int = 18, color: str = "#2563eb", bg: str = "#ffffff") -> None:
        super().__init__(master, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        self.size = size
        self.color = color
        self.angle = 90
        self.after_id: str | None = None
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._tick()

    def stop(self) -> None:
        self.running = False
        if self.after_id is not None:
            try:
                self.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        self.delete("all")

    def _tick(self) -> None:
        self.delete("all")
        pad = 3
        self.create_arc(
            pad,
            pad,
            self.size - pad,
            self.size - pad,
            start=self.angle,
            extent=285,
            style="arc",
            outline=self.color,
            width=3,
        )
        self.angle = (self.angle - 18) % 360
        if self.running:
            self.after_id = self.after(33, self._tick)


class YouTubeInstagramMediaApp(ctk.CTk):
    primary_color = "#2563eb"
    primary_hover = "#1d4ed8"
    secondary_color = "#eef4ff"
    secondary_hover = "#dbeafe"
    secondary_text = "#1d4ed8"
    success_color = "#059669"
    success_hover = "#047857"
    disabled_color = "#d8dee8"
    disabled_text = "#64748b"

    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.title(PRODUCT_NAME)
        self._set_window_icon()
        self.geometry("1020x720")
        self.minsize(900, 660)

        self.settings = load_settings()
        self.worker_thread: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.latest_result: DownloadResult | None = None
        self.is_processing = False

        self.url_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=self.settings.output_dir or str(default_output_dir()))
        self.output_format_var = tk.StringVar(value=str(self.settings.output_format or "MP3").upper())
        self.quality_var = tk.StringVar(value=str(self.settings.audio_quality or "192"))
        self.use_cookies_var = tk.BooleanVar(value=self.settings.use_browser_cookies)
        self.cookie_browser_var = tk.StringVar(value=self.settings.cookie_browser or "chrome")

        self._configure_typography()
        self._build_ui()
        self._ensure_user_folders()
        self.after(120, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_typography(self) -> None:
        available = set(tkfont.families(self))
        for candidate in ("Pretendard", "맑은 고딕", "Malgun Gothic", "Segoe UI"):
            if candidate in available:
                self.font_family = candidate
                break
        else:
            self.font_family = "Segoe UI"

        self.option_add("*Font", f"{{{self.font_family}}} 11")
        self.font_title = ctk.CTkFont(family=self.font_family, size=31, weight="bold")
        self.font_subtitle = ctk.CTkFont(family=self.font_family, size=15)
        self.font_credit = ctk.CTkFont(family=self.font_family, size=12, weight="bold")
        self.font_card_title = ctk.CTkFont(family=self.font_family, size=19, weight="bold")
        self.font_body = ctk.CTkFont(family=self.font_family, size=14)
        self.font_label = ctk.CTkFont(family=self.font_family, size=13)
        self.font_button = ctk.CTkFont(family=self.font_family, size=14, weight="bold")
        self.font_input = ctk.CTkFont(family=self.font_family, size=14)
        self.font_log = ctk.CTkFont(family=self.font_family, size=13)

    def _set_window_icon(self) -> None:
        icon_path = resource_path("assets", "youtube-instagram-media.ico")
        if not icon_path.exists():
            return
        try:
            self.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="#f8fafc", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(header, text=PRODUCT_NAME, font=self.font_title, text_color="#111827")
        title.grid(row=0, column=0, padx=32, pady=(24, 4), sticky="w")
        credit = ctk.CTkLabel(
            header,
            text="developed by yeohj0710",
            font=self.font_credit,
            text_color="#2563eb",
            fg_color="#eaf2ff",
            corner_radius=6,
            padx=10,
            pady=3,
        )
        credit.grid(row=1, column=0, padx=32, pady=(0, 8), sticky="w")
        subtitle = ctk.CTkLabel(
            header,
            text="YouTube 영상·Shorts와 Instagram 릴스를 MP3 또는 MP4로 빠르게 저장합니다.",
            font=self.font_subtitle,
            text_color="#475569",
        )
        subtitle.grid(row=2, column=0, padx=32, pady=(0, 22), sticky="w")

        body = ctk.CTkFrame(self, fg_color="#edf1f6", corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(body, fg_color="#edf1f6", corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(24, 12), pady=24)
        left.grid_columnconfigure(0, weight=1)

        right = ctk.CTkFrame(body, fg_color="#ffffff", corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 24), pady=24)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(3, weight=1)

        self._link_card(left).grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self._output_card(left).grid(row=1, column=0, sticky="ew", pady=(0, 14))
        self._action_card(left).grid(row=2, column=0, sticky="ew")
        self._status_panel(right)
        self._refresh_format_mode()
        self._refresh_cookie_mode()

    def _card(self, parent: ctk.CTkBaseClass, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color="#ffffff", corner_radius=10)
        card.grid_columnconfigure(0, weight=1)
        label = ctk.CTkLabel(card, text=title, font=self.font_card_title, text_color="#111827")
        label.grid(row=0, column=0, padx=22, pady=(20, 12), sticky="w")
        return card

    def _helper_label(self, parent: ctk.CTkBaseClass, text: str, row: int) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            parent,
            text=text,
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=520,
        )
        label.grid(row=row, column=0, padx=22, pady=(0, 12), sticky="ew")
        return label

    def _link_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "1. 링크")
        self._helper_label(card, "YouTube 영상/Shorts 또는 Instagram 릴스/게시물 링크를 그대로 넣으면 됩니다.", 1)

        input_box = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        input_box.grid(row=2, column=0, padx=22, pady=(0, 18), sticky="ew")
        input_box.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(
            input_box,
            textvariable=self.url_var,
            placeholder_text="https://www.youtube.com/shorts/... 또는 https://www.instagram.com/reel/...",
            height=42,
            font=self.font_input,
            corner_radius=7,
        )
        self.url_entry.grid(row=0, column=0, columnspan=2, padx=16, pady=(16, 10), sticky="ew")
        self.paste_button = ctk.CTkButton(
            input_box,
            text="붙여넣기",
            height=36,
            width=120,
            corner_radius=7,
            font=self.font_button,
            fg_color=self.secondary_color,
            hover_color=self.secondary_hover,
            text_color=self.secondary_text,
            command=self._paste_url,
        )
        self.paste_button.grid(row=1, column=0, padx=(16, 6), pady=(0, 16), sticky="w")
        self.clear_button = ctk.CTkButton(
            input_box,
            text="비우기",
            height=36,
            width=100,
            corner_radius=7,
            font=self.font_button,
            fg_color="#f1f5f9",
            hover_color="#e2e8f0",
            text_color="#334155",
            command=lambda: self.url_var.set(""),
        )
        self.clear_button.grid(row=1, column=1, padx=(6, 16), pady=(0, 16), sticky="e")

        cookie_box = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        cookie_box.grid(row=3, column=0, padx=22, pady=(0, 18), sticky="ew")
        cookie_box.grid_columnconfigure(1, weight=1)
        self.cookies_check = ctk.CTkCheckBox(
            cookie_box,
            text="브라우저 로그인 정보 사용",
            variable=self.use_cookies_var,
            font=self.font_label,
            text_color="#334155",
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            checkbox_width=20,
            checkbox_height=20,
            command=self._refresh_cookie_mode,
        )
        self.cookies_check.grid(row=0, column=0, padx=16, pady=(14, 7), sticky="w")
        self.cookie_browser_combo = ctk.CTkComboBox(
            cookie_box,
            values=BROWSER_CHOICES,
            variable=self.cookie_browser_var,
            height=34,
            width=120,
            state="readonly",
            font=self.font_input,
            dropdown_font=self.font_input,
            border_color="#94a3b8",
            button_color="#9ca3af",
        )
        self.cookie_browser_combo.grid(row=0, column=1, padx=16, pady=(14, 7), sticky="e")
        cookie_helper = self._helper_label(
            cookie_box,
            "Instagram 로그인이 필요한 릴스는 Chrome/Edge에 로그인된 상태면 더 잘 받아집니다. 꺼져 있어도 실패 시 자동 재시도합니다.",
            1,
        )
        cookie_helper.grid_configure(columnspan=2)
        return card

    def _output_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "2. 추출 옵션과 저장 폴더")
        self._helper_label(card, "MP3는 오디오만 저장합니다. MP4는 영상 제목 폴더 안에 영상과 1초 간격 스크린샷을 함께 저장합니다.", 1)

        format_row = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        format_row.grid(row=2, column=0, padx=22, pady=(0, 12), sticky="ew")
        format_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(format_row, text="저장 형식", font=self.font_label, text_color="#334155").grid(
            row=0, column=0, padx=(16, 12), pady=14, sticky="w"
        )
        self.format_segment = ctk.CTkSegmentedButton(
            format_row,
            values=OUTPUT_FORMAT_CHOICES,
            variable=self.output_format_var,
            command=lambda _value: self._refresh_format_mode(),
            height=36,
            corner_radius=8,
            font=self.font_button,
            fg_color="#e2e8f0",
            selected_color="#93c5fd",
            selected_hover_color="#60a5fa",
            unselected_color="#ffffff",
            unselected_hover_color="#edf2f7",
            text_color="#1f2937",
        )
        self.format_segment.grid(row=0, column=1, padx=(0, 16), pady=14, sticky="e")

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=3, column=0, padx=22, pady=(0, 12), sticky="ew")
        row.grid_columnconfigure(0, weight=1)
        self.output_dir_entry = ctk.CTkEntry(
            row,
            textvariable=self.output_dir_var,
            height=40,
            font=self.font_input,
            corner_radius=7,
        )
        self.output_dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.output_dir_button = ctk.CTkButton(
            row,
            text="변경",
            width=96,
            height=40,
            corner_radius=7,
            font=self.font_button,
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            command=self._choose_output_dir,
        )
        self.output_dir_button.grid(row=0, column=1)

        quality_row = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        quality_row.grid(row=4, column=0, padx=22, pady=(0, 20), sticky="ew")
        quality_row.grid_columnconfigure(1, weight=1)
        self.quality_label = ctk.CTkLabel(quality_row, text="MP3 품질", font=self.font_label, text_color="#334155")
        self.quality_label.grid(
            row=0, column=0, padx=(16, 12), pady=14, sticky="w"
        )
        self.quality_combo = ctk.CTkComboBox(
            quality_row,
            values=QUALITY_CHOICES,
            variable=self.quality_var,
            height=36,
            width=118,
            state="readonly",
            font=self.font_input,
            dropdown_font=self.font_input,
            border_color="#94a3b8",
            button_color="#9ca3af",
        )
        self.quality_combo.grid(row=0, column=1, padx=(0, 16), pady=14, sticky="e")
        return card

    def _action_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color="#ffffff", corner_radius=10)
        card.grid_columnconfigure(0, weight=1)
        self.start_button = ctk.CTkButton(
            card,
            text="빠르게 MP3 추출",
            height=52,
            corner_radius=8,
            font=self.font_button,
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            command=self._start_job,
        )
        self.start_button.grid(row=0, column=0, padx=22, pady=(22, 12), sticky="ew")
        self.start_button_spinner = ActivitySpinner(card, size=18, color="#ffffff", bg=self.primary_hover)
        self.action_helper_label = self._helper_label(card, "MP4는 제목 폴더를 만들고, 폴더 안에 영상과 스크린샷을 함께 넣습니다.", 1)
        return card

    def _status_panel(self, parent: ctk.CTkFrame) -> None:
        title_row = ctk.CTkFrame(parent, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 8))
        title_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(title_row, text="진행 상태", font=self.font_card_title, text_color="#111827").grid(
            row=0, column=0, sticky="w"
        )
        self.activity_spinner = ActivitySpinner(title_row, size=18, color=self.primary_color, bg="#ffffff")
        self.activity_spinner.grid(row=0, column=1, sticky="e")
        self.activity_spinner.grid_remove()

        self.status_label = ctk.CTkLabel(parent, text="대기 중", font=self.font_body, text_color="#334155", anchor="w")
        self.status_label.grid(row=1, column=0, padx=22, pady=(0, 8), sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(parent, height=12, corner_radius=6, progress_color=self.primary_color)
        self.progress_bar.grid(row=2, column=0, padx=22, pady=(0, 16), sticky="ew")
        self.progress_bar.set(0)

        self.log_box = ctk.CTkTextbox(
            parent,
            font=self.font_log,
            fg_color="#f8fafc",
            border_color="#e2e8f0",
            border_width=1,
            corner_radius=8,
            text_color="#334155",
            wrap="word",
        )
        self.log_box.grid(row=3, column=0, padx=22, pady=(0, 16), sticky="nsew")
        self.log_box.insert("end", "YouTube 또는 Instagram 링크를 넣고 추출을 시작해 주세요.\n")
        self.log_box.configure(state="disabled")

        self.open_output_button = ctk.CTkButton(
            parent,
            text="저장 폴더 열기",
            height=42,
            corner_radius=8,
            font=self.font_button,
            fg_color=self.disabled_color,
            hover_color=self.disabled_color,
            text_color_disabled=self.disabled_text,
            state="disabled",
            command=self._open_latest_output,
        )
        self.open_output_button.grid(row=4, column=0, padx=22, pady=(0, 22), sticky="ew")

    def _ensure_user_folders(self) -> None:
        try:
            Path(self.output_dir_var.get()).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def _paste_url(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if text:
            self.url_var.set(text)
            self.url_entry.focus_set()

    def _choose_output_dir(self) -> None:
        initial = self.output_dir_var.get().strip() or str(default_output_dir())
        path = filedialog.askdirectory(title="저장 폴더 선택", initialdir=initial if Path(initial).exists() else None)
        if path:
            self.output_dir_var.set(path)

    def _collect_settings(self) -> AppSettings:
        output_dir = self.output_dir_var.get().strip() or str(default_output_dir())
        output_format = self.output_format_var.get().strip().upper()
        if output_format not in OUTPUT_FORMAT_CHOICES:
            output_format = "MP3"
            self.output_format_var.set(output_format)
        quality = self.quality_var.get().strip()
        if quality not in QUALITY_CHOICES:
            quality = "192"
            self.quality_var.set(quality)
        settings = AppSettings(
            output_dir=output_dir,
            output_dir_custom=not is_current_default_output_dir(output_dir),
            output_format=output_format,
            audio_quality=quality,
            use_browser_cookies=bool(self.use_cookies_var.get()),
            cookie_browser=self.cookie_browser_var.get().strip() or "chrome",
        )
        save_settings(settings)
        self.settings = settings
        return settings

    def _start_job(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        source = self.url_var.get().strip()
        if not source:
            messagebox.showwarning("링크 필요", "YouTube 또는 Instagram 링크를 입력해 주세요.")
            return
        settings = self._collect_settings()

        self.latest_result = None
        self._set_output_button_enabled(False)
        self._set_start_button_busy(True)
        self._set_controls_locked(True)
        self.progress_bar.set(0)
        self._set_status("시작합니다", 0.01)
        self._append_log("작업을 시작합니다.")

        self.worker_thread = threading.Thread(target=self._run_worker, args=(settings, source), daemon=True)
        self.worker_thread.start()

    def _run_worker(self, settings: AppSettings, source: str) -> None:
        try:
            pipeline = YouTubeInstagramMediaPipeline(settings, progress=self._worker_progress)
            result = pipeline.run(source)
            self.events.put(("done", result))
        except BaseException as exc:
            if isinstance(exc, UserFacingError):
                self.events.put(("error", str(exc)))
                return
            self.events.put(("error", f"{exc}\n\n{traceback.format_exc()}"))

    def _worker_progress(self, message: str, percent: float, detail: str) -> None:
        self.events.put(("progress", (message, percent, detail)))

    def _drain_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                message, percent, detail = payload  # type: ignore[misc]
                self._set_status(str(message), float(percent))
                self._append_log(str(detail))
            elif kind == "done":
                self.latest_result = payload  # type: ignore[assignment]
                self._set_status("완료", 1.0)
                self._append_log(f"완료: {self.latest_result.media_path}")
                self._set_start_button_busy(False)
                self._set_controls_locked(False)
                self._set_output_button_enabled(True)
                if self.latest_result.output_format == "MP4":
                    messagebox.showinfo("완료", f"MP4와 스크린샷이 저장되었습니다.\n\n{self.latest_result.output_dir}")
                else:
                    messagebox.showinfo("완료", f"MP3 파일이 저장되었습니다.\n\n{self.latest_result.media_path}")
            elif kind == "error":
                self._set_status("오류", 0)
                self._append_log(str(payload))
                self._set_start_button_busy(False)
                self._set_controls_locked(False)
                messagebox.showerror("추출 실패", str(payload).splitlines()[0])
        self.after(120, self._drain_events)

    def _set_status(self, text: str, percent: float) -> None:
        self.status_label.configure(text=text)
        self.progress_bar.set(max(0.0, min(1.0, percent)))

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_controls_locked(self, locked: bool) -> None:
        state = "disabled" if locked else "normal"
        cursor = "no" if locked else ""
        for widget in (self.url_entry, self.output_dir_entry):
            widget.configure(
                state=state,
                fg_color="#edf2f7" if locked else "#ffffff",
                border_color="#cbd5e1" if locked else "#94a3b8",
                text_color="#94a3b8" if locked else "#111827",
            )
            self._set_widget_cursor(widget, cursor)
        self.format_segment.configure(state=state)
        if locked:
            self.quality_combo.configure(state="disabled", fg_color="#edf2f7")
        else:
            self._refresh_format_mode()
        self.cookies_check.configure(state=state)
        if locked:
            self.cookie_browser_combo.configure(state="disabled", fg_color="#edf2f7")
        else:
            self._refresh_cookie_mode()
        for button in (self.paste_button, self.clear_button, self.output_dir_button):
            button.configure(state=state)
            self._set_widget_cursor(button, cursor)

    def _set_start_button_busy(self, busy: bool) -> None:
        self.is_processing = busy
        if busy:
            self.start_button.configure(
                state="disabled",
                text="    추출 중",
                fg_color=self.primary_hover,
                hover_color=self.primary_hover,
                text_color_disabled="#ffffff",
            )
            self.start_button_spinner.place(in_=self.start_button, relx=0.39, rely=0.5, anchor="center")
            self.start_button_spinner.start()
            self.activity_spinner.grid()
            self.activity_spinner.start()
        else:
            self.activity_spinner.stop()
            self.activity_spinner.grid_remove()
            self.start_button_spinner.stop()
            self.start_button_spinner.place_forget()
            self.start_button.configure(
                state="normal",
                text=self._start_button_text(),
                fg_color=self.primary_color,
                hover_color=self.primary_hover,
                text_color="#ffffff",
                text_color_disabled=self.disabled_text,
            )

    def _set_output_button_enabled(self, enabled: bool) -> None:
        if enabled:
            self.open_output_button.configure(
                state="normal",
                fg_color=self.success_color,
                hover_color=self.success_hover,
                text_color="#ffffff",
            )
        else:
            self.open_output_button.configure(
                state="disabled",
                fg_color=self.disabled_color,
                hover_color=self.disabled_color,
                text_color_disabled=self.disabled_text,
            )

    def _refresh_format_mode(self) -> None:
        if not hasattr(self, "quality_combo"):
            return
        output_format = self.output_format_var.get().strip().upper()
        if output_format not in OUTPUT_FORMAT_CHOICES:
            output_format = "MP3"
            self.output_format_var.set(output_format)

        if output_format == "MP4":
            self.quality_combo.configure(state="disabled", fg_color="#edf2f7", border_color="#cbd5e1", button_color="#cbd5e1")
            self.quality_label.configure(text_color="#94a3b8")
        else:
            self.quality_combo.configure(state="readonly", fg_color="#ffffff", border_color="#94a3b8", button_color="#9ca3af")
            self.quality_label.configure(text_color="#334155")

        if hasattr(self, "start_button") and not self.is_processing:
            self.start_button.configure(text=self._start_button_text())

    def _refresh_cookie_mode(self) -> None:
        if not hasattr(self, "cookie_browser_combo"):
            return
        if self.use_cookies_var.get():
            self.cookie_browser_combo.configure(state="readonly", fg_color="#ffffff", border_color="#94a3b8", button_color="#9ca3af")
        else:
            self.cookie_browser_combo.configure(state="disabled", fg_color="#edf2f7", border_color="#cbd5e1", button_color="#cbd5e1")

    def _start_button_text(self) -> str:
        output_format = self.output_format_var.get().strip().upper()
        if output_format not in OUTPUT_FORMAT_CHOICES:
            output_format = "MP3"
        return f"빠르게 {output_format} 추출"

    def _set_widget_cursor(self, widget: object, cursor: str) -> None:
        targets = [widget, getattr(widget, "_canvas", None), getattr(widget, "_entry", None), getattr(widget, "_button", None)]
        for target in targets:
            if target is None:
                continue
            try:
                target.configure(cursor=cursor)
            except (tk.TclError, AttributeError, ValueError):
                pass

    def _open_latest_output(self) -> None:
        path = self.latest_result.output_dir if self.latest_result else Path(self.output_dir_var.get()).expanduser()
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            messagebox.showinfo("저장 폴더", str(path))

    def _on_close(self) -> None:
        self.activity_spinner.stop()
        self.start_button_spinner.stop()
        self._collect_settings()
        self.destroy()


def main() -> None:
    app = YouTubeInstagramMediaApp()
    app.mainloop()
