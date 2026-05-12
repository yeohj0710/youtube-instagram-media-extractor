from __future__ import annotations

import os
import queue
import re
import threading
import traceback
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox
import tkinter as tk

import customtkinter as ctk

from youtube_instagram_media_extractor.downloader import DownloadResult, UserFacingError, YouTubeInstagramMediaPipeline
from youtube_instagram_media_extractor.settings import AppSettings, default_output_dir, is_current_default_output_dir, load_settings, save_settings
from youtube_instagram_media_extractor.utils import resource_path


PRODUCT_NAME = "YouTube·Instagram 미디어 추출기"
AUDIO_QUALITY_CHOICES = ["128", "192", "256", "320"]
VIDEO_QUALITY_CHOICES = ["최고", "2160p", "1440p", "1080p", "720p", "480p", "360p"]
BROWSER_CHOICES = ["chrome", "edge", "firefox", "brave", "whale"]
URL_RE = re.compile(r"https?://[^\s<>'\"`]+", re.IGNORECASE)
TRAILING_URL_CHARS = ".,;:!?)]}…"


@dataclass
class QueuedJob:
    id: int
    url: str
    settings: AppSettings
    media_label: str
    status: str = "queued"
    message: str = "대기 중"
    progress: float = 0.0
    result: DownloadResult | None = None
    error: str = ""


def extract_urls(text: str) -> list[str]:
    urls = [match.rstrip(TRAILING_URL_CHARS) for match in URL_RE.findall(text)]
    if not urls:
        candidate = text.strip().rstrip(TRAILING_URL_CHARS)
        if candidate.lower().startswith(("http://", "https://")):
            urls = [candidate]

    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


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


class ChevronIcon(tk.Canvas):
    def __init__(self, master: tk.Misc, size: int = 18, color: str = "#64748b", bg: str = "#f8fafc") -> None:
        super().__init__(master, width=size, height=size, bg=bg, highlightthickness=0, bd=0)
        self.size = size
        self.color = color
        self.is_open = False
        self.draw()

    def set_open(self, is_open: bool) -> None:
        self.is_open = is_open
        self.draw()

    def draw(self) -> None:
        self.delete("all")
        if self.is_open:
            points = (self.size * 0.28, self.size * 0.42, self.size * 0.50, self.size * 0.64, self.size * 0.72, self.size * 0.42)
        else:
            points = (self.size * 0.38, self.size * 0.28, self.size * 0.62, self.size * 0.50, self.size * 0.38, self.size * 0.72)
        self.create_line(*points, fill=self.color, width=2.2, capstyle="round", joinstyle="round")


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
        self.geometry("1100x740")
        self.minsize(940, 660)

        self.settings = load_settings()
        if not self.settings.include_video and not self.settings.include_audio:
            self.settings.include_video = True
            self.settings.include_audio = True

        self.worker_thread: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.latest_result: DownloadResult | None = None
        self.queue_items: list[QueuedJob] = []
        self.current_job: QueuedJob | None = None
        self.next_job_id = 1
        self.is_processing = False
        self.advanced_options_open = False

        self.output_dir_var = tk.StringVar(value=self.settings.output_dir or str(default_output_dir()))
        self.include_video_var = tk.BooleanVar(value=bool(self.settings.include_video))
        self.include_audio_var = tk.BooleanVar(value=bool(self.settings.include_audio))
        self.capture_screenshots_var = tk.BooleanVar(
            value=bool(self.settings.capture_screenshots) and bool(self.settings.include_video)
        )
        self.video_quality_var = tk.StringVar(value=self._video_quality_label(self.settings.video_quality))
        initial_audio_quality = "320" if str(self.settings.audio_quality or "320") == "192" else str(self.settings.audio_quality or "320")
        self.audio_quality_var = tk.StringVar(value=initial_audio_quality)
        self.use_cookies_var = tk.BooleanVar(value=bool(self.settings.use_browser_cookies))
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
        self.font_small = ctk.CTkFont(family=self.font_family, size=12)

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
        credit.configure(cursor="hand2")
        credit.bind("<Button-1>", lambda _event: self._open_developer_profile())
        subtitle = ctk.CTkLabel(
            header,
            text="YouTube 영상·Shorts와 Instagram 릴스를 영상 또는 소리로 빠르게 저장합니다.",
            font=self.font_subtitle,
            text_color="#475569",
        )
        subtitle.grid(row=2, column=0, padx=32, pady=(0, 22), sticky="w")

        body = ctk.CTkFrame(self, fg_color="#edf1f6", corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        left = ctk.CTkScrollableFrame(
            body,
            fg_color="#edf1f6",
            corner_radius=0,
            scrollbar_button_color="#cbd5e1",
            scrollbar_button_hover_color="#94a3b8",
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(24, 12), pady=24)
        left.grid_columnconfigure(0, weight=1)
        self._configure_scroll_speed(left)

        right = ctk.CTkFrame(body, fg_color="#ffffff", corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 24), pady=24)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(4, weight=2)
        right.grid_rowconfigure(6, weight=1)

        self._settings_card(left).grid(row=0, column=0, sticky="ew")
        self._status_panel(right)
        self._refresh_media_options()
        self._refresh_cookie_mode()
        self._refresh_advanced_options()
        self._refresh_queue()

    @staticmethod
    def _configure_scroll_speed(frame: ctk.CTkScrollableFrame) -> None:
        try:
            frame._parent_canvas.configure(yscrollincrement=28)  # type: ignore[attr-defined]
        except (tk.TclError, AttributeError):
            pass

    def _card(self, parent: ctk.CTkBaseClass, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color="#ffffff", corner_radius=10)
        card.grid_columnconfigure(0, weight=1)
        label = ctk.CTkLabel(card, text=title, font=self.font_card_title, text_color="#111827")
        label.grid(row=0, column=0, padx=22, pady=(20, 12), sticky="w")
        return card

    def _helper_label(self, parent: ctk.CTkBaseClass, text: str, row: int, wraplength: int = 430) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            parent,
            text=text,
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=wraplength,
        )
        label.grid(row=row, column=0, padx=22, pady=(0, 12), sticky="ew")
        return label

    def _settings_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "링크와 옵션")
        self._helper_label(card, "링크 하나를 넣고 옵션을 고른 뒤 큐에 추가합니다. 처리 중에 새 링크를 추가하면 뒤에서 순서대로 실행됩니다.", 1)

        input_box = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        input_box.grid(row=2, column=0, padx=22, pady=(0, 12), sticky="ew")
        input_box.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(input_box, text="링크", font=self.font_label, text_color="#334155").grid(
            row=0, column=0, padx=(16, 12), pady=14, sticky="w"
        )
        self.url_text = ctk.CTkTextbox(
            input_box,
            height=42,
            font=self.font_input,
            fg_color="#ffffff",
            border_color="#94a3b8",
            border_width=1,
            corner_radius=7,
            text_color="#111827",
            wrap="none",
            undo=True,
            activate_scrollbars=False,
        )
        self.url_text.grid(row=0, column=1, padx=(0, 16), pady=12, sticky="ew")
        self.url_text.bind("<Return>", lambda _event: "break")

        option_box = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        option_box.grid(row=3, column=0, padx=22, pady=(0, 12), sticky="ew")
        option_box.grid_columnconfigure(1, weight=1)
        option_box.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(option_box, text="저장할 내용", font=self.font_label, text_color="#334155").grid(
            row=0, column=0, padx=(16, 12), pady=(14, 8), sticky="w"
        )
        checks = ctk.CTkFrame(option_box, fg_color="transparent")
        checks.grid(row=0, column=1, columnspan=3, padx=(0, 16), pady=(14, 8), sticky="e")
        self.video_check = ctk.CTkCheckBox(
            checks,
            text="영상",
            variable=self.include_video_var,
            font=self.font_label,
            text_color="#334155",
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            checkbox_width=20,
            checkbox_height=20,
            command=self._refresh_media_options,
        )
        self.video_check.grid(row=0, column=0, padx=(0, 18), sticky="w")
        self.audio_check = ctk.CTkCheckBox(
            checks,
            text="소리",
            variable=self.include_audio_var,
            font=self.font_label,
            text_color="#334155",
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            checkbox_width=20,
            checkbox_height=20,
            command=self._refresh_media_options,
        )
        self.audio_check.grid(row=0, column=1, sticky="w")

        self.video_quality_label = ctk.CTkLabel(option_box, text="영상 화질", font=self.font_label, text_color="#334155")
        self.video_quality_label.grid(row=1, column=0, padx=(16, 12), pady=(8, 14), sticky="w")
        self.video_quality_combo = ctk.CTkComboBox(
            option_box,
            values=VIDEO_QUALITY_CHOICES,
            variable=self.video_quality_var,
            height=34,
            width=108,
            state="readonly",
            font=self.font_input,
            dropdown_font=self.font_input,
            border_color="#94a3b8",
            button_color="#9ca3af",
        )
        self.video_quality_combo.grid(row=1, column=1, padx=(0, 18), pady=(8, 14), sticky="w")
        self.audio_quality_label = ctk.CTkLabel(option_box, text="소리 품질", font=self.font_label, text_color="#334155")
        self.audio_quality_label.grid(row=1, column=2, padx=(0, 12), pady=(8, 14), sticky="e")
        self.audio_quality_combo = ctk.CTkComboBox(
            option_box,
            values=AUDIO_QUALITY_CHOICES,
            variable=self.audio_quality_var,
            height=34,
            width=108,
            state="readonly",
            font=self.font_input,
            dropdown_font=self.font_input,
            border_color="#94a3b8",
            button_color="#9ca3af",
        )
        self.audio_quality_combo.grid(row=1, column=3, padx=(0, 16), pady=(8, 14), sticky="e")

        self.screenshot_row = ctk.CTkFrame(option_box, fg_color="transparent")
        self.screenshot_row.grid(row=2, column=0, columnspan=4, padx=16, pady=(0, 14), sticky="ew")
        self.screenshot_row.grid_columnconfigure(1, weight=1)
        self.screenshot_label = ctk.CTkLabel(
            self.screenshot_row,
            text="스크린샷",
            font=self.font_label,
            text_color="#334155",
        )
        self.screenshot_label.grid(row=0, column=0, padx=(0, 20), sticky="w")
        self.screenshot_check = ctk.CTkCheckBox(
            self.screenshot_row,
            text="1초 간격으로 이미지 추출",
            variable=self.capture_screenshots_var,
            font=self.font_label,
            text_color="#334155",
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            checkbox_width=20,
            checkbox_height=20,
            command=self._refresh_media_options,
        )
        self.screenshot_check.grid(row=0, column=1, sticky="w")

        folder_row = ctk.CTkFrame(card, fg_color="transparent")
        folder_row.grid(row=4, column=0, padx=22, pady=(0, 12), sticky="ew")
        folder_row.grid_columnconfigure(0, weight=1)
        self.output_dir_entry = ctk.CTkEntry(
            folder_row,
            textvariable=self.output_dir_var,
            height=40,
            font=self.font_input,
            corner_radius=7,
        )
        self.output_dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.output_dir_button = ctk.CTkButton(
            folder_row,
            text="변경",
            width=78,
            height=40,
            corner_radius=7,
            font=self.font_button,
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            command=self._choose_output_dir,
        )
        self.output_dir_button.grid(row=0, column=1, padx=(0, 8))
        self.open_selected_output_button = ctk.CTkButton(
            folder_row,
            text="열기",
            width=78,
            height=40,
            corner_radius=7,
            font=self.font_button,
            fg_color="#f1f5f9",
            hover_color="#e2e8f0",
            text_color="#334155",
            command=self._open_selected_output_dir,
        )
        self.open_selected_output_button.grid(row=0, column=2)

        advanced_header = ctk.CTkFrame(card, fg_color="#f8fafc", corner_radius=8)
        advanced_header.grid(row=5, column=0, padx=22, pady=(0, 10), sticky="ew")
        advanced_header.grid_columnconfigure(0, weight=1)
        self.advanced_button = ctk.CTkButton(
            advanced_header,
            text="",
            height=38,
            corner_radius=7,
            font=self.font_label,
            fg_color="#f8fafc",
            hover_color="#eef2f7",
            text_color="#334155",
            anchor="w",
            command=self._toggle_advanced_options,
        )
        self.advanced_button.grid(row=0, column=0, padx=(8, 0), pady=8, sticky="ew")
        self.advanced_chevron = ChevronIcon(advanced_header, size=18, color="#64748b", bg="#f8fafc")
        self.advanced_chevron.grid(row=0, column=1, padx=(4, 14), pady=8, sticky="e")
        self.advanced_chevron.bind("<Button-1>", lambda _event: self._toggle_advanced_options())

        self.advanced_box = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        self.advanced_box.grid(row=6, column=0, padx=22, pady=(0, 12), sticky="ew")
        self.advanced_box.grid_columnconfigure(1, weight=1)
        self.cookies_switch = ctk.CTkSwitch(
            self.advanced_box,
            text="브라우저 로그인 정보 사용",
            variable=self.use_cookies_var,
            font=self.font_label,
            text_color="#334155",
            progress_color=self.primary_color,
            command=self._refresh_cookie_mode,
        )
        self.cookies_switch.grid(row=0, column=0, padx=16, pady=(14, 7), sticky="w")
        self.cookie_browser_combo = ctk.CTkComboBox(
            self.advanced_box,
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
            self.advanced_box,
            "Instagram 로그인이 필요한 릴스는 PC 브라우저에 로그인된 상태면 더 잘 받아집니다.",
            1,
            wraplength=360,
        )
        cookie_helper.grid_configure(columnspan=2)

        self.selection_summary_label = ctk.CTkLabel(
            card,
            text="영상 또는 소리 중 하나 이상을 선택해 주세요.",
            font=self.font_label,
            text_color="#be123c",
            anchor="w",
            fg_color="#fff1f2",
            corner_radius=8,
            padx=14,
            pady=9,
        )
        self.selection_summary_label.grid(row=7, column=0, padx=22, pady=(0, 10), sticky="ew")

        self.add_button = ctk.CTkButton(
            card,
            text="큐에 추가하고 추출 시작",
            height=50,
            corner_radius=8,
            font=self.font_button,
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            text_color="#ffffff",
            command=self._enqueue_from_input,
        )
        self.add_button.grid(row=8, column=0, padx=22, pady=(0, 22), sticky="ew")
        return card

    def _link_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "1. 링크")
        self._helper_label(card, "YouTube 영상/Shorts 또는 Instagram 릴스/게시물 링크를 넣어 주세요. 여러 개는 줄마다 하나씩 넣으면 됩니다.", 1)

        input_box = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        input_box.grid(row=2, column=0, padx=22, pady=(0, 20), sticky="ew")
        input_box.grid_columnconfigure(0, weight=1)

        self.url_text = ctk.CTkTextbox(
            input_box,
            height=92,
            font=self.font_input,
            fg_color="#ffffff",
            border_color="#94a3b8",
            border_width=1,
            corner_radius=7,
            text_color="#111827",
            wrap="word",
        )
        self.url_text.grid(row=0, column=0, columnspan=2, padx=16, pady=(16, 10), sticky="ew")

        self.paste_button = ctk.CTkButton(
            input_box,
            text="붙여넣기",
            height=36,
            width=112,
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
            width=92,
            corner_radius=7,
            font=self.font_button,
            fg_color="#f1f5f9",
            hover_color="#e2e8f0",
            text_color="#334155",
            command=self._clear_url_input,
        )
        self.clear_button.grid(row=1, column=1, padx=(6, 16), pady=(0, 16), sticky="e")
        return card

    def _output_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "2. 옵션과 저장 폴더")
        self._helper_label(card, "저장할 내용을 고른 뒤 마지막 버튼으로 큐에 추가합니다. 처리 중에 추가한 링크는 뒤에서 순서대로 실행됩니다.", 1)

        media_row = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        media_row.grid(row=2, column=0, padx=22, pady=(0, 12), sticky="ew")
        media_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(media_row, text="저장할 내용", font=self.font_label, text_color="#334155").grid(
            row=0, column=0, padx=(16, 12), pady=14, sticky="w"
        )
        checks = ctk.CTkFrame(media_row, fg_color="transparent")
        checks.grid(row=0, column=1, padx=(0, 16), pady=10, sticky="e")
        self.video_check = ctk.CTkCheckBox(
            checks,
            text="영상",
            variable=self.include_video_var,
            font=self.font_label,
            text_color="#334155",
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            checkbox_width=20,
            checkbox_height=20,
            command=self._refresh_media_options,
        )
        self.video_check.grid(row=0, column=0, padx=(0, 16), sticky="w")
        self.audio_check = ctk.CTkCheckBox(
            checks,
            text="소리",
            variable=self.include_audio_var,
            font=self.font_label,
            text_color="#334155",
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            checkbox_width=20,
            checkbox_height=20,
            command=self._refresh_media_options,
        )
        self.audio_check.grid(row=0, column=1, sticky="w")

        quality_box = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        quality_box.grid(row=3, column=0, padx=22, pady=(0, 12), sticky="ew")
        quality_box.grid_columnconfigure(1, weight=1)
        self.video_quality_label = ctk.CTkLabel(quality_box, text="영상 화질", font=self.font_label, text_color="#334155")
        self.video_quality_label.grid(row=0, column=0, padx=(16, 12), pady=(14, 7), sticky="w")
        self.video_quality_combo = ctk.CTkComboBox(
            quality_box,
            values=VIDEO_QUALITY_CHOICES,
            variable=self.video_quality_var,
            height=34,
            width=118,
            state="readonly",
            font=self.font_input,
            dropdown_font=self.font_input,
            border_color="#94a3b8",
            button_color="#9ca3af",
        )
        self.video_quality_combo.grid(row=0, column=1, padx=(0, 16), pady=(14, 7), sticky="e")
        self.audio_quality_label = ctk.CTkLabel(quality_box, text="소리 품질", font=self.font_label, text_color="#334155")
        self.audio_quality_label.grid(row=1, column=0, padx=(16, 12), pady=(7, 14), sticky="w")
        self.audio_quality_combo = ctk.CTkComboBox(
            quality_box,
            values=AUDIO_QUALITY_CHOICES,
            variable=self.audio_quality_var,
            height=34,
            width=118,
            state="readonly",
            font=self.font_input,
            dropdown_font=self.font_input,
            border_color="#94a3b8",
            button_color="#9ca3af",
        )
        self.audio_quality_combo.grid(row=1, column=1, padx=(0, 16), pady=(7, 14), sticky="e")

        folder_row = ctk.CTkFrame(card, fg_color="transparent")
        folder_row.grid(row=4, column=0, padx=22, pady=(0, 12), sticky="ew")
        folder_row.grid_columnconfigure(0, weight=1)
        self.output_dir_entry = ctk.CTkEntry(
            folder_row,
            textvariable=self.output_dir_var,
            height=40,
            font=self.font_input,
            corner_radius=7,
        )
        self.output_dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.output_dir_button = ctk.CTkButton(
            folder_row,
            text="변경",
            width=78,
            height=40,
            corner_radius=7,
            font=self.font_button,
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            command=self._choose_output_dir,
        )
        self.output_dir_button.grid(row=0, column=1, padx=(0, 8))
        self.open_selected_output_button = ctk.CTkButton(
            folder_row,
            text="열기",
            width=78,
            height=40,
            corner_radius=7,
            font=self.font_button,
            fg_color="#f1f5f9",
            hover_color="#e2e8f0",
            text_color="#334155",
            command=self._open_selected_output_dir,
        )
        self.open_selected_output_button.grid(row=0, column=2)

        advanced_header = ctk.CTkFrame(card, fg_color="#f8fafc", corner_radius=8)
        advanced_header.grid(row=5, column=0, padx=22, pady=(0, 10), sticky="ew")
        advanced_header.grid_columnconfigure(0, weight=1)
        self.advanced_button = ctk.CTkButton(
            advanced_header,
            text="",
            height=38,
            corner_radius=7,
            font=self.font_label,
            fg_color="#f8fafc",
            hover_color="#eef2f7",
            text_color="#334155",
            anchor="w",
            command=self._toggle_advanced_options,
        )
        self.advanced_button.grid(row=0, column=0, padx=8, pady=8, sticky="ew")

        self.advanced_box = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        self.advanced_box.grid(row=6, column=0, padx=22, pady=(0, 12), sticky="ew")
        self.advanced_box.grid_columnconfigure(1, weight=1)
        self.cookies_switch = ctk.CTkSwitch(
            self.advanced_box,
            text="브라우저 로그인 정보 사용",
            variable=self.use_cookies_var,
            font=self.font_label,
            text_color="#334155",
            progress_color=self.primary_color,
            command=self._refresh_cookie_mode,
        )
        self.cookies_switch.grid(row=0, column=0, padx=16, pady=(14, 7), sticky="w")
        self.cookie_browser_combo = ctk.CTkComboBox(
            self.advanced_box,
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
            self.advanced_box,
            "Instagram 로그인이 필요한 릴스는 PC 브라우저에 로그인된 상태면 더 잘 받아집니다.",
            1,
            wraplength=360,
        )
        cookie_helper.grid_configure(columnspan=2)

        self.selection_summary_label = ctk.CTkLabel(
            card,
            text="",
            font=self.font_label,
            text_color="#64748b",
            anchor="w",
            fg_color="#f8fafc",
            corner_radius=8,
            padx=14,
            pady=9,
        )
        self.selection_summary_label.grid(row=7, column=0, padx=22, pady=(0, 10), sticky="ew")

        self.add_button = ctk.CTkButton(
            card,
            text="큐에 추가하고 추출 시작",
            height=50,
            corner_radius=8,
            font=self.font_button,
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            text_color="#ffffff",
            command=self._enqueue_from_input,
        )
        self.add_button.grid(row=8, column=0, padx=22, pady=(0, 22), sticky="ew")
        return card

    def _status_panel(self, parent: ctk.CTkFrame) -> None:
        title_row = ctk.CTkFrame(parent, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew", padx=22, pady=(22, 8))
        title_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(title_row, text="처리 큐", font=self.font_card_title, text_color="#111827").grid(
            row=0, column=0, sticky="w"
        )
        self.activity_spinner = ActivitySpinner(title_row, size=18, color=self.primary_color, bg="#ffffff")
        self.activity_spinner.grid(row=0, column=1, sticky="e")
        self.activity_spinner.grid_remove()

        self.queue_summary_label = ctk.CTkLabel(parent, text="처리 중 0 · 대기 0 · 완료 0 · 실패 0", font=self.font_label, text_color="#64748b", anchor="w")
        self.queue_summary_label.grid(row=1, column=0, padx=22, pady=(0, 8), sticky="ew")

        self.status_label = ctk.CTkLabel(parent, text="링크와 옵션을 정한 뒤 큐에 추가해 주세요.", font=self.font_body, text_color="#334155", anchor="w", wraplength=360)
        self.status_label.grid(row=2, column=0, padx=22, pady=(0, 8), sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(parent, height=12, corner_radius=6, progress_color=self.primary_color)
        self.progress_bar.grid(row=3, column=0, padx=22, pady=(0, 12), sticky="new")
        self.progress_bar.set(0)

        self.queue_list = ctk.CTkScrollableFrame(
            parent,
            fg_color="#f8fafc",
            border_color="#e2e8f0",
            border_width=1,
            corner_radius=8,
            scrollbar_button_color="#cbd5e1",
            scrollbar_button_hover_color="#94a3b8",
        )
        self.queue_list.grid(row=4, column=0, padx=22, pady=(0, 12), sticky="nsew")
        self.queue_list.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(parent, text="로그", font=self.font_label, text_color="#64748b").grid(
            row=5, column=0, padx=22, pady=(0, 6), sticky="nw"
        )
        self.log_box = ctk.CTkTextbox(
            parent,
            height=120,
            font=self.font_log,
            fg_color="#f8fafc",
            border_color="#e2e8f0",
            border_width=1,
            corner_radius=8,
            text_color="#334155",
            wrap="word",
        )
        self.log_box.grid(row=6, column=0, padx=22, pady=(0, 16), sticky="nsew")
        self.log_box.insert("end", "YouTube 또는 Instagram 링크를 큐에 추가해 주세요.\n")
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
        self.open_output_button.grid(row=7, column=0, padx=22, pady=(0, 22), sticky="ew")

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
        if not text:
            return

        current = self._get_url_text().strip()
        insert_text = text if not current else f"\n{text}"
        self.url_text.insert("end", insert_text)
        self.url_text.focus_set()

    def _clear_url_input(self) -> None:
        self.url_text.delete("1.0", "end")

    def _get_url_text(self) -> str:
        return " ".join(self.url_text.get("1.0", "end").split())

    def _choose_output_dir(self) -> None:
        initial = self.output_dir_var.get().strip() or str(default_output_dir())
        path = filedialog.askdirectory(title="저장 폴더 선택", initialdir=initial if Path(initial).exists() else None)
        if path:
            self.output_dir_var.set(path)
            self._ensure_user_folders()

    def _open_selected_output_dir(self) -> None:
        path = Path(self.output_dir_var.get().strip() or str(default_output_dir())).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("폴더 열기 실패", str(exc))
            return
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            messagebox.showinfo("저장 폴더", str(path))

    def _collect_settings(self) -> AppSettings:
        output_dir = self.output_dir_var.get().strip() or str(default_output_dir())
        include_video = bool(self.include_video_var.get())
        include_audio = bool(self.include_audio_var.get())
        if not include_video and not include_audio:
            include_video = True
            include_audio = True
        capture_screenshots = bool(self.capture_screenshots_var.get()) and include_video

        audio_quality = self.audio_quality_var.get().strip()
        if audio_quality not in AUDIO_QUALITY_CHOICES:
            audio_quality = "320"
            self.audio_quality_var.set(audio_quality)

        video_quality = self._video_quality_setting()
        output_format = "MP4" if include_video else "MP3"
        settings = AppSettings(
            output_dir=output_dir,
            output_dir_custom=not is_current_default_output_dir(output_dir),
            output_format=output_format,
            include_video=include_video,
            include_audio=include_audio,
            capture_screenshots=capture_screenshots,
            audio_quality=audio_quality,
            video_quality=video_quality,
            use_browser_cookies=bool(self.use_cookies_var.get()),
            cookie_browser=self.cookie_browser_var.get().strip() or "chrome",
        )
        save_settings(settings)
        self.settings = settings
        return settings

    def _enqueue_from_input(self) -> None:
        if not self.include_video_var.get() and not self.include_audio_var.get():
            messagebox.showwarning("저장할 내용 필요", "영상 또는 소리 중 하나 이상을 선택해 주세요.")
            return

        source_text = self._get_url_text()
        urls = extract_urls(source_text)
        if not urls:
            messagebox.showwarning("링크 필요", "YouTube 또는 Instagram 링크를 입력해 주세요.")
            return

        source = urls[0]
        if not YouTubeInstagramMediaPipeline.is_supported_url(source):
            messagebox.showwarning("지원하지 않는 링크", "YouTube 영상/Shorts 또는 Instagram 릴스/게시물 링크만 사용할 수 있습니다.")
            return

        settings = self._collect_settings()
        media_label = self._media_selection_label(settings.include_video, settings.include_audio, settings.capture_screenshots)
        job = QueuedJob(
            id=self.next_job_id,
            url=source,
            settings=AppSettings(
                output_dir=settings.output_dir,
                output_dir_custom=settings.output_dir_custom,
                output_format=settings.output_format,
                include_video=settings.include_video,
                include_audio=settings.include_audio,
                capture_screenshots=settings.capture_screenshots,
                audio_quality=settings.audio_quality,
                video_quality=settings.video_quality,
                use_browser_cookies=settings.use_browser_cookies,
                cookie_browser=settings.cookie_browser,
            ),
            media_label=media_label,
        )
        self.next_job_id += 1
        self.queue_items.append(job)
        self._append_log(f"큐 추가 #{job.id}: {job.media_label} · {job.url}")

        self._clear_url_input()
        self._refresh_queue()
        self._start_next_job_if_idle()

    def _start_next_job_if_idle(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        next_job = next((job for job in self.queue_items if job.status == "queued"), None)
        if next_job is None:
            self.current_job = None
            self._set_processing_indicator(False)
            self._refresh_queue()
            return

        self.current_job = next_job
        next_job.status = "processing"
        next_job.message = "준비 중"
        next_job.progress = 0.01
        self._set_output_button_enabled(self.latest_result is not None)
        self._set_processing_indicator(True)
        self._set_status(f"#{next_job.id} 처리 시작: {next_job.media_label}", next_job.progress)
        self._append_log(f"작업 시작 #{next_job.id}: {next_job.url}")
        self._refresh_queue()

        self.worker_thread = threading.Thread(target=self._run_worker, args=(next_job,), daemon=True)
        self.worker_thread.start()

    def _run_worker(self, job: QueuedJob) -> None:
        try:
            pipeline = YouTubeInstagramMediaPipeline(job.settings, progress=lambda message, percent, detail: self._worker_progress(job.id, message, percent, detail))
            result = pipeline.run(job.url)
            self.events.put(("done", (job.id, result)))
        except BaseException as exc:
            if isinstance(exc, UserFacingError):
                self.events.put(("error", (job.id, str(exc))))
                return
            self.events.put(("error", (job.id, f"{exc}\n\n{traceback.format_exc()}")))

    def _worker_progress(self, job_id: int, message: str, percent: float, detail: str) -> None:
        self.events.put(("progress", (job_id, message, percent, detail)))

    def _drain_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                job_id, message, percent, detail = payload  # type: ignore[misc]
                job = self._find_job(int(job_id))
                if job:
                    job.message = str(message)
                    job.progress = float(percent)
                self._set_status(f"#{job_id} {message}", float(percent))
                self._append_log(str(detail))
                self._refresh_queue()
            elif kind == "done":
                job_id, result = payload  # type: ignore[misc]
                job = self._find_job(int(job_id))
                if job:
                    job.status = "done"
                    job.message = "완료"
                    job.progress = 1.0
                    job.result = result
                self.latest_result = result
                self.current_job = None
                self.worker_thread = None
                self._set_status(f"#{job_id} 완료", 1.0)
                self._append_log(f"완료 #{job_id}: {result.media_path}")
                self._set_output_button_enabled(True)
                self._refresh_queue()
                self._start_next_job_if_idle()
            elif kind == "error":
                job_id, error_text = payload  # type: ignore[misc]
                job = self._find_job(int(job_id))
                first_line = str(error_text).splitlines()[0] if str(error_text).splitlines() else "알 수 없는 오류"
                if job:
                    job.status = "error"
                    job.message = first_line
                    job.error = str(error_text)
                    job.progress = 0
                self.current_job = None
                self.worker_thread = None
                self._set_status(f"#{job_id} 실패: {first_line}", 0)
                self._append_log(str(error_text))
                self._refresh_queue()
                self._start_next_job_if_idle()
        self.after(120, self._drain_events)

    def _find_job(self, job_id: int) -> QueuedJob | None:
        return next((job for job in self.queue_items if job.id == job_id), None)

    def _set_status(self, text: str, percent: float) -> None:
        self.status_label.configure(text=text)
        self.progress_bar.set(max(0.0, min(1.0, percent)))

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _refresh_queue(self) -> None:
        if not hasattr(self, "queue_list"):
            return

        for child in self.queue_list.winfo_children():
            child.destroy()

        if not self.queue_items:
            empty = ctk.CTkLabel(
                self.queue_list,
                text="아직 큐에 들어간 링크가 없습니다.",
                font=self.font_label,
                text_color="#94a3b8",
                anchor="center",
            )
            empty.grid(row=0, column=0, padx=16, pady=18, sticky="ew")
        else:
            for row_index, job in enumerate(self.queue_items):
                self._queue_row(self.queue_list, job).grid(row=row_index, column=0, padx=10, pady=(10 if row_index == 0 else 0, 10), sticky="ew")

        queued = sum(1 for job in self.queue_items if job.status == "queued")
        done = sum(1 for job in self.queue_items if job.status == "done")
        failed = sum(1 for job in self.queue_items if job.status == "error")
        processing = 1 if self.current_job else 0
        self.queue_summary_label.configure(text=f"처리 중 {processing} · 대기 {queued} · 완료 {done} · 실패 {failed}")

    def _queue_row(self, parent: ctk.CTkBaseClass, job: QueuedJob) -> ctk.CTkFrame:
        styles = {
            "queued": ("대기", "#f8fafc", "#e2e8f0", "#475569"),
            "processing": ("처리 중", "#eff6ff", "#dbeafe", "#1d4ed8"),
            "done": ("완료", "#ecfdf5", "#d1fae5", "#047857"),
            "error": ("실패", "#fff1f2", "#ffe4e6", "#be123c"),
        }
        status_text, row_color, pill_color, text_color = styles.get(job.status, styles["queued"])
        row = ctk.CTkFrame(parent, fg_color=row_color, corner_radius=8)
        row.grid_columnconfigure(1, weight=1)

        number = ctk.CTkLabel(
            row,
            text=f"{job.id}",
            width=32,
            height=32,
            font=self.font_button,
            text_color="#334155",
            fg_color="#ffffff",
            corner_radius=16,
        )
        number.grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=10, sticky="n")

        title = ctk.CTkLabel(
            row,
            text=f"{job.media_label} · {self._short_source_label(job.url)}",
            font=self.font_label,
            text_color="#111827",
            anchor="w",
        )
        title.grid(row=0, column=1, padx=(0, 8), pady=(10, 2), sticky="ew")

        detail = ctk.CTkLabel(
            row,
            text=self._compact_url(job.url) if job.status in {"queued", "processing"} else job.message,
            font=self.font_small,
            text_color="#64748b",
            anchor="w",
            justify="left",
            wraplength=250,
        )
        detail.grid(row=1, column=1, padx=(0, 8), pady=(0, 10), sticky="ew")

        pill = ctk.CTkLabel(
            row,
            text=status_text,
            width=62,
            height=26,
            font=self.font_small,
            text_color=text_color,
            fg_color=pill_color,
            corner_radius=13,
        )
        pill.grid(row=0, column=2, rowspan=2, padx=(0, 10), pady=10, sticky="e")
        return row

    def _refresh_media_options(self) -> None:
        if not hasattr(self, "video_quality_combo"):
            return

        include_video = bool(self.include_video_var.get())
        include_audio = bool(self.include_audio_var.get())
        video_state = "readonly" if include_video else "disabled"
        audio_state = "readonly" if include_audio else "disabled"
        self.video_quality_combo.configure(
            state=video_state,
            fg_color="#ffffff" if include_video else "#edf2f7",
            border_color="#94a3b8" if include_video else "#cbd5e1",
            button_color="#9ca3af" if include_video else "#cbd5e1",
        )
        self.video_quality_label.configure(text_color="#334155" if include_video else "#94a3b8")
        if hasattr(self, "screenshot_row"):
            if include_video:
                self.screenshot_row.grid()
                self.screenshot_check.configure(state="normal", text_color="#334155")
                self.screenshot_label.configure(text_color="#334155")
            else:
                self.capture_screenshots_var.set(False)
                self.screenshot_row.grid_remove()
        self.audio_quality_combo.configure(
            state=audio_state,
            fg_color="#ffffff" if include_audio else "#edf2f7",
            border_color="#94a3b8" if include_audio else "#cbd5e1",
            button_color="#9ca3af" if include_audio else "#cbd5e1",
        )
        self.audio_quality_label.configure(text_color="#334155" if include_audio else "#94a3b8")

        label = self._media_selection_label(include_video, include_audio, bool(self.capture_screenshots_var.get()))
        if label == "선택 필요":
            self.selection_summary_label.configure(text="영상 또는 소리 중 하나 이상을 선택해 주세요.", text_color="#be123c", fg_color="#fff1f2")
            self.selection_summary_label.grid()
            self.add_button.configure(state="disabled", fg_color=self.disabled_color, hover_color=self.disabled_color, text_color_disabled=self.disabled_text)
        else:
            self.selection_summary_label.grid_remove()
            self.add_button.configure(state="normal", fg_color=self.primary_color, hover_color=self.primary_hover, text_color="#ffffff")

    def _toggle_advanced_options(self) -> None:
        self.advanced_options_open = not self.advanced_options_open
        self._refresh_advanced_options()

    def _refresh_advanced_options(self) -> None:
        if not hasattr(self, "advanced_box"):
            return
        enabled_text = "켜짐" if self.use_cookies_var.get() else "꺼짐"
        self.advanced_button.configure(text=f"브라우저 로그인 정보: {enabled_text}")
        if hasattr(self, "advanced_chevron"):
            self.advanced_chevron.set_open(self.advanced_options_open)
        if self.advanced_options_open:
            self.advanced_box.grid()
        else:
            self.advanced_box.grid_remove()

    def _refresh_cookie_mode(self) -> None:
        if not hasattr(self, "cookie_browser_combo"):
            return
        if self.use_cookies_var.get():
            self.cookie_browser_combo.configure(state="readonly", fg_color="#ffffff", border_color="#94a3b8", button_color="#9ca3af")
        else:
            self.cookie_browser_combo.configure(state="disabled", fg_color="#edf2f7", border_color="#cbd5e1", button_color="#cbd5e1")
        self._refresh_advanced_options()

    def _set_processing_indicator(self, busy: bool) -> None:
        self.is_processing = busy
        if busy:
            self.activity_spinner.grid()
            self.activity_spinner.start()
        else:
            self.activity_spinner.stop()
            self.activity_spinner.grid_remove()

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

    @staticmethod
    def _media_selection_label(include_video: bool, include_audio: bool, capture_screenshots: bool = False) -> str:
        if include_video and include_audio:
            label = "영상+소리"
            return f"{label}+스크린샷" if capture_screenshots else label
        if include_video:
            label = "영상만"
            return f"{label}+스크린샷" if capture_screenshots else label
        if include_audio:
            return "소리만"
        return "선택 필요"

    @staticmethod
    def _video_quality_label(value: object) -> str:
        quality = str(value or "1080").strip().lower()
        if quality in {"best", "최고", "최고화질"}:
            return "최고"
        if quality.endswith("p"):
            quality = quality[:-1]
        return f"{quality}p" if quality in {"2160", "1440", "1080", "720", "480", "360"} else "1080p"

    def _video_quality_setting(self) -> str:
        label = self.video_quality_var.get().strip().lower()
        if label in {"최고", "best"}:
            return "best"
        if label.endswith("p"):
            label = label[:-1]
        return label if label in {"2160", "1440", "1080", "720", "480", "360"} else "1080"

    def _short_source_label(self, url: str) -> str:
        if YouTubeInstagramMediaPipeline.is_instagram_url(url):
            return "Instagram"
        if "/shorts/" in url:
            return "YouTube Shorts"
        return "YouTube"

    @staticmethod
    def _compact_url(url: str, max_length: int = 58) -> str:
        if len(url) <= max_length:
            return url
        return f"{url[: max_length - 3]}..."

    def _open_latest_output(self) -> None:
        path = self.latest_result.output_dir if self.latest_result else Path(self.output_dir_var.get()).expanduser()
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            messagebox.showinfo("저장 폴더", str(path))

    @staticmethod
    def _open_developer_profile() -> None:
        webbrowser.open("https://github.com/yeohj0710")

    def _on_close(self) -> None:
        self.activity_spinner.stop()
        self._collect_settings()
        self.destroy()


def main() -> None:
    app = YouTubeInstagramMediaApp()
    app.mainloop()
