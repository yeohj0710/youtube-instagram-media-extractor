from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from youtube_instagram_media_extractor.settings import AppSettings
from youtube_instagram_media_extractor.utils import find_ffmpeg, get_media_duration, run_process, sanitize_filename


ProgressCallback = Callable[[str, float, str], None]
OUTPUT_FORMATS = {"MP3", "MP4"}
MEDIA_AUDIO_ONLY = "AUDIO_ONLY"
MEDIA_VIDEO_AUDIO = "VIDEO_AUDIO"
MEDIA_VIDEO_ONLY = "VIDEO_ONLY"
CHROMIUM_BASED_BROWSERS = {"brave", "chrome", "chromium", "edge", "opera", "vivaldi", "whale"}
AUDIO_EXTENSIONS = {
    ".aac",
    ".aif",
    ".aiff",
    ".amr",
    ".caf",
    ".flac",
    ".m4a",
    ".m4b",
    ".mp3",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".wma",
}
VIDEO_EXTENSIONS = {
    ".3g2",
    ".3gp",
    ".avi",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ogv",
    ".ts",
    ".webm",
    ".wmv",
}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


class UserFacingError(RuntimeError):
    """Error message that can be shown directly in the UI."""


@dataclass
class DownloadResult:
    output_dir: Path
    media_path: Path
    title: str
    output_format: str
    screenshot_dir: Path | None = None


class YouTubeInstagramMediaPipeline:
    def __init__(self, settings: AppSettings, progress: ProgressCallback | None = None) -> None:
        self.settings = settings
        self.progress = progress or (lambda _message, _percent, _detail: None)
        self.ffmpeg = find_ffmpeg()
        self.active_media_mode = self._media_mode()
        self.active_output_format = self._output_format_for_mode(self.active_media_mode)
        self.active_url = ""

    def run(self, source: str) -> DownloadResult:
        source = source.strip()
        if not source:
            raise UserFacingError("YouTube/Instagram 링크 또는 내 컴퓨터 미디어 파일을 입력해 주세요.")
        output_root = Path(self.settings.output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        started = datetime.now().strftime("%y%m%d%H%M%S")
        media_mode = self._media_mode()
        output_format = self._output_format_for_mode(media_mode)
        self.active_output_format = output_format
        self.active_media_mode = media_mode

        self.progress("준비 중", 0.03, f"저장 폴더를 확인했습니다: {output_root}")
        if self.is_url(source):
            if not self.is_supported_url(source):
                raise UserFacingError("YouTube 영상/Shorts 또는 Instagram 릴스/게시물 링크만 사용할 수 있습니다.")
            self.active_url = source
            media_path, title, result_output_dir, screenshot_dir, done_detail = self._run_online_source(
                source,
                started,
                output_root,
                media_mode,
            )
        else:
            media_path, title, result_output_dir, screenshot_dir, output_format, done_detail = self._run_local_source(
                source,
                started,
                output_root,
                media_mode,
            )

        self._cleanup_extra_outputs(output_root, started, media_path)
        self.progress("완료", 1.0, done_detail)
        return DownloadResult(
            output_dir=result_output_dir,
            media_path=media_path,
            title=title,
            output_format=output_format,
            screenshot_dir=screenshot_dir,
        )

    def _run_online_source(
        self,
        url: str,
        started: str,
        output_root: Path,
        media_mode: str,
    ) -> tuple[Path, str, Path, Path | None, str]:
        if media_mode in {MEDIA_VIDEO_AUDIO, MEDIA_VIDEO_ONLY}:
            include_audio = media_mode == MEDIA_VIDEO_AUDIO
            capture_screenshots = bool(getattr(self.settings, "capture_screenshots", False))
            media_path, title, result_output_dir, screenshot_dir = self._download_mp4(
                url,
                started,
                output_root,
                include_audio,
                capture_screenshots,
            )
            done_detail = f"{self._mode_label(media_mode)} 저장 완료: {media_path}"
            if screenshot_dir is not None:
                done_detail = f"{done_detail}\n스크린샷 저장 완료: {screenshot_dir}"
        else:
            media_path, title = self._download_mp3(url, started, output_root)
            screenshot_dir = None
            result_output_dir = output_root
            done_detail = f"MP3 저장 완료: {media_path}"
        return media_path, title, result_output_dir, screenshot_dir, done_detail

    def _run_local_source(
        self,
        source: str,
        started: str,
        output_root: Path,
        media_mode: str,
    ) -> tuple[Path, str, Path, Path | None, str, str]:
        source_path = Path(source).expanduser().resolve()
        if not source_path.exists() or not source_path.is_file():
            raise UserFacingError(f"선택한 미디어 파일을 찾을 수 없습니다.\n\n{source_path}")

        suffix = source_path.suffix.lower()
        if suffix not in MEDIA_EXTENSIONS:
            raise UserFacingError("지원하는 영상 또는 오디오 파일을 선택해 주세요.")

        title = source_path.stem
        if suffix in AUDIO_EXTENSIONS:
            if media_mode == MEDIA_VIDEO_ONLY:
                raise UserFacingError("오디오 파일에는 영상이 없어서 '소리' 저장도 선택해 주세요.")
            self.active_output_format = "MP3"
            self.active_media_mode = MEDIA_AUDIO_ONLY
            media_path = self._save_local_audio_as_mp3(source_path, started, output_root, title)
            return (
                media_path,
                title,
                output_root.resolve(),
                None,
                "MP3",
                f"로컬 오디오 MP3 저장 완료: {media_path}",
            )

        if media_mode == MEDIA_AUDIO_ONLY:
            media_path = self._extract_local_video_audio(source_path, started, output_root, title)
            return (
                media_path,
                title,
                output_root.resolve(),
                None,
                "MP3",
                f"로컬 영상에서 MP3 저장 완료: {media_path}",
            )

        include_audio = media_mode == MEDIA_VIDEO_AUDIO
        capture_screenshots = bool(getattr(self.settings, "capture_screenshots", False))
        media_path = self._save_local_video_as_mp4(source_path, started, output_root, title, include_audio)
        screenshot_dir: Path | None = None
        if capture_screenshots:
            screenshot_dir = self._screenshot_output_dir(output_root, title)
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            self.progress("스크린샷 캡처 중", 0.94, "로컬 영상에서 1초 간격으로 화면을 캡처합니다.")
            screenshot_dir = self._capture_screenshots(media_path, screenshot_dir)
        done_detail = f"{self._mode_label(media_mode)} 저장 완료: {media_path}"
        if screenshot_dir is not None:
            done_detail = f"{done_detail}\n스크린샷 저장 완료: {screenshot_dir}"
        return media_path, title, output_root.resolve(), screenshot_dir.resolve() if screenshot_dir else None, "MP4", done_detail

    @staticmethod
    def is_url(source: str) -> bool:
        parsed = urlparse(source.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def is_supported_local_media(source: str) -> bool:
        return Path(source).suffix.lower() in MEDIA_EXTENSIONS

    def _save_local_audio_as_mp3(self, source_path: Path, started: str, output_root: Path, title: str) -> Path:
        target = unique_path(output_root / f"{started} {sanitize_filename(title)}.mp3")
        self.progress("오디오 파일 저장 중", 0.12, f"내 컴퓨터 오디오 파일을 저장합니다: {source_path.name}")
        if source_path.suffix.lower() == ".mp3":
            shutil.copy2(source_path, target)
            return target.resolve()
        return self._convert_audio_to_mp3(source_path, target)

    def _extract_local_video_audio(self, source_path: Path, started: str, output_root: Path, title: str) -> Path:
        target = unique_path(output_root / f"{started} {sanitize_filename(title)}.mp3")
        self.progress("오디오 추출 중", 0.12, f"로컬 영상에서 소리만 추출합니다: {source_path.name}")
        return self._convert_audio_to_mp3(source_path, target)

    def _convert_audio_to_mp3(self, source_path: Path, target: Path) -> Path:
        completed = run_process(
            [
                self.ffmpeg,
                "-y",
                "-i",
                source_path,
                "-vn",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                f"{self._audio_quality()}k",
                target,
            ]
        )
        if completed.returncode != 0 or not target.exists():
            try:
                target.unlink()
            except OSError:
                pass
            raise UserFacingError("로컬 미디어에서 MP3를 만드는 중 오류가 발생했습니다.")
        return target.resolve()

    def _save_local_video_as_mp4(
        self,
        source_path: Path,
        started: str,
        output_root: Path,
        title: str,
        include_audio: bool,
    ) -> Path:
        target = unique_path(output_root / f"{started} {sanitize_filename(title)}.mp4")
        mode_text = "소리 포함 MP4" if include_audio else "무음 MP4"
        self.progress("로컬 영상 저장 중", 0.12, f"내 컴퓨터 영상을 {mode_text}로 저장합니다: {source_path.name}")
        if include_audio and source_path.suffix.lower() == ".mp4":
            shutil.copy2(source_path, target)
            return target.resolve()

        args: list[str | os.PathLike[str]] = [
            self.ffmpeg,
            "-y",
            "-i",
            source_path,
            "-map",
            "0:v:0",
        ]
        if include_audio:
            args.extend(["-map", "0:a?"])
        args.extend(["-c:v", "copy"])
        if include_audio:
            args.extend(["-c:a", "aac"])
        else:
            args.append("-an")
        args.extend(["-movflags", "+faststart", target])
        completed = run_process(args)
        if completed.returncode == 0 and target.exists():
            return target.resolve()

        try:
            target.unlink()
        except OSError:
            pass
        return self._transcode_local_video_to_mp4(source_path, target, include_audio)

    def _transcode_local_video_to_mp4(self, source_path: Path, target: Path, include_audio: bool) -> Path:
        args: list[str | os.PathLike[str]] = [
            self.ffmpeg,
            "-y",
            "-i",
            source_path,
            "-map",
            "0:v:0",
        ]
        if include_audio:
            args.extend(["-map", "0:a?"])
        args.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"])
        if include_audio:
            args.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            args.append("-an")
        args.extend(["-movflags", "+faststart", target])
        completed = run_process(args)
        if completed.returncode != 0 or not target.exists():
            try:
                target.unlink()
            except OSError:
                pass
            raise UserFacingError("로컬 영상을 MP4로 저장하는 중 오류가 발생했습니다.")
        return target.resolve()

    def _normalized_output_format(self) -> str:
        output_format = str(getattr(self.settings, "output_format", "MP3") or "MP3").strip().upper()
        return output_format if output_format in OUTPUT_FORMATS else "MP3"

    def _media_mode(self) -> str:
        include_video = bool(getattr(self.settings, "include_video", False))
        include_audio = bool(getattr(self.settings, "include_audio", True))
        if include_video and include_audio:
            return MEDIA_VIDEO_AUDIO
        if include_video:
            return MEDIA_VIDEO_ONLY
        if include_audio:
            return MEDIA_AUDIO_ONLY
        raise UserFacingError("영상 또는 소리 중 하나 이상을 선택해 주세요.")

    @staticmethod
    def _output_format_for_mode(media_mode: str) -> str:
        return "MP4" if media_mode in {MEDIA_VIDEO_AUDIO, MEDIA_VIDEO_ONLY} else "MP3"

    @staticmethod
    def _mode_label(media_mode: str) -> str:
        if media_mode == MEDIA_VIDEO_AUDIO:
            return "영상+소리 MP4"
        if media_mode == MEDIA_VIDEO_ONLY:
            return "무음 MP4"
        return "MP3"

    @staticmethod
    def is_supported_url(url: str) -> bool:
        return YouTubeInstagramMediaPipeline.is_youtube_url(url) or YouTubeInstagramMediaPipeline.is_instagram_url(url)

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        parsed = urlparse(url.strip())
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host in {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "youtube-nocookie.com"}

    @staticmethod
    def is_instagram_url(url: str) -> bool:
        host = urlparse(url.strip()).netloc.lower()
        return "instagram.com" in host

    def _download_mp3(self, url: str, started: str, output_root: Path) -> tuple[Path, str]:
        yt_dlp = self._import_ytdlp()
        ydl_opts = self._base_ytdlp_opts(started, output_root)
        ydl_opts.update(
            {
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "keepvideo": False,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": self._audio_quality(),
                    }
                ],
            }
        )

        self.progress("오디오 다운로드 중", 0.08, f"{self._source_label(url)}에서 오디오 스트림을 가져옵니다.")
        info = self._extract_with_ytdlp(yt_dlp, url, ydl_opts)
        title = self._best_source_title(info)
        media_path = self._find_downloaded_file(output_root, started, ".mp3")
        if not media_path:
            raise UserFacingError("다운로드된 MP3 파일을 찾지 못했습니다.")

        final_path = self._friendly_final_path(output_root, started, title, ".mp3", media_path)
        if final_path != media_path:
            media_path.replace(final_path)
            media_path = final_path
        return media_path.resolve(), title

    def _download_mp4(
        self,
        url: str,
        started: str,
        output_root: Path,
        include_audio: bool,
        capture_screenshots: bool,
    ) -> tuple[Path, str, Path, Path | None]:
        yt_dlp = self._import_ytdlp()
        ydl_opts = self._base_ytdlp_opts(started, output_root)
        ydl_opts.update(
            {
                "format": self._video_format_selector(include_audio),
                "format_sort": self._video_format_sort(),
                "merge_output_format": "mp4",
                "postprocessors": [
                    {
                        "key": "FFmpegVideoRemuxer",
                        "preferedformat": "mp4",
                    }
                ],
            }
        )

        mode_text = "소리 포함 MP4" if include_audio else "무음 MP4"
        self.progress("영상 다운로드 중", 0.08, f"{self._source_label(url)} 영상을 {mode_text}로 저장할 준비를 합니다.")
        info = self._extract_with_ytdlp(yt_dlp, url, ydl_opts)
        title = self._best_source_title(info)
        downloaded_path = self._find_downloaded_file(output_root, started, ".mp4")
        if not downloaded_path:
            raise UserFacingError("다운로드된 MP4 파일을 찾지 못했습니다.")

        final_path = self._friendly_final_path(output_root, started, title, ".mp4", downloaded_path)
        if final_path != downloaded_path:
            downloaded_path.replace(final_path)
        if not include_audio:
            final_path = self._strip_audio(final_path)

        screenshot_dir: Path | None = None
        if capture_screenshots:
            screenshot_dir = self._screenshot_output_dir(output_root, title)
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            self.progress("스크린샷 캡처 중", 0.94, "MP4에서 1초 간격으로 화면을 캡처합니다.")
            screenshot_dir = self._capture_screenshots(final_path, screenshot_dir)
        return final_path.resolve(), title, output_root.resolve(), screenshot_dir.resolve() if screenshot_dir else None

    def _video_format_selector(self, include_audio: bool) -> str:
        video_mp4 = "bv*[ext=mp4]"
        video_any = "bv*"
        best_mp4 = "b[ext=mp4]"
        best_any = "best"
        if include_audio:
            return f"{video_mp4}+ba[ext=m4a]/{video_any}+ba/{best_mp4}/{best_any}/best"
        return f"{video_mp4}/{video_any}/bestvideo[ext=mp4]/bestvideo/{best_mp4}/{best_any}/best"

    def _video_format_sort(self) -> list[str]:
        quality = self._video_quality()
        if quality == "best":
            return ["res", "fps", "vcodec:h264", "acodec:aac", "br"]
        return [f"res:{quality}", "fps", "vcodec:h264", "acodec:aac", "br"]

    def _strip_audio(self, video_path: Path) -> Path:
        temp_path = unique_path(video_path.with_name(f"__muted_{video_path.name}"))
        completed = run_process(
            [
                self.ffmpeg,
                "-y",
                "-i",
                video_path,
                "-map",
                "0:v:0",
                "-c:v",
                "copy",
                "-an",
                "-movflags",
                "+faststart",
                temp_path,
            ]
        )
        if completed.returncode != 0 or not temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
            raise UserFacingError("무음 MP4로 정리하는 중 오류가 발생했습니다.")
        video_path.unlink()
        temp_path.replace(video_path)
        return video_path

    @staticmethod
    def _import_ytdlp() -> object:
        try:
            import yt_dlp
        except ImportError as exc:
            raise UserFacingError("yt-dlp 패키지가 설치되어 있지 않습니다. requirements.txt 설치가 필요합니다.") from exc
        return yt_dlp

    def _base_ytdlp_opts(self, started: str, output_root: Path) -> dict[str, object]:
        opts: dict[str, object] = {
            "outtmpl": str(output_root / f"__download_{started}_%(title).90s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "windowsfilenames": True,
            "ffmpeg_location": str(self.ffmpeg),
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 4,
            "progress_hooks": [self._download_progress_hook],
            "postprocessor_hooks": [self._postprocessor_progress_hook],
        }
        cookie_file = self._cookie_file_path()
        if cookie_file is not None:
            opts["cookiefile"] = str(cookie_file)
        elif self.settings.use_browser_cookies:
            opts["cookiesfrombrowser"] = self._default_cookie_browser_spec()
        return opts

    def _extract_with_ytdlp(self, yt_dlp_module: object, url: str, ydl_opts: dict[str, object]) -> dict[str, object]:
        try:
            return self._extract_once(yt_dlp_module, url, ydl_opts)
        except UserFacingError:
            raise
        except Exception as exc:
            if not self._download_error_needs_cookies(exc):
                raise self._friendly_download_error(exc) from exc

            self.progress(
                "브라우저 쿠키 자동 재시도 중",
                0.10,
                "로그인이 필요할 수 있어 PC 브라우저에 저장된 쿠키를 자동으로 확인합니다.",
            )
            try:
                return self._extract_with_browser_cookie_fallback(yt_dlp_module, url, ydl_opts, exc)
            except Exception as retry_exc:
                raise self._friendly_download_error(retry_exc, retried_with_cookies=True) from retry_exc

    @staticmethod
    def _extract_once(yt_dlp_module: object, url: str, ydl_opts: dict[str, object]) -> dict[str, object]:
        with yt_dlp_module.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if not isinstance(info, dict):
            raise UserFacingError("영상 정보를 가져오지 못했습니다.")
        return info

    def _extract_with_browser_cookie_fallback(
        self,
        yt_dlp_module: object,
        url: str,
        base_opts: dict[str, object],
        original_error: BaseException | None = None,
    ) -> dict[str, object]:
        tried = set()
        selected = base_opts.get("cookiesfrombrowser")
        if isinstance(selected, tuple) and selected:
            tried.add(self._cookie_spec_key(selected))

        last_error: Exception | None = None
        for spec in self._cookie_browser_specs():
            key = self._cookie_spec_key(spec)
            if key in tried:
                continue
            label = self._cookie_spec_label(spec)
            self.progress("브라우저 쿠키 확인 중", 0.12, f"{label} 로그인 정보로 다시 시도합니다.")
            retry_opts = dict(base_opts)
            if self._cookie_file_path() is not None and original_error and "failed to load cookies" in str(original_error).lower():
                retry_opts.pop("cookiefile", None)
            retry_opts["cookiesfrombrowser"] = spec
            try:
                return self._extract_once(yt_dlp_module, url, retry_opts)
            except Exception as exc:
                last_error = exc
                self.progress("다른 브라우저 확인 중", 0.12, f"{label} 쿠키 실패: {self._brief_error(exc)}")
        if last_error is not None:
            raise last_error
        raise RuntimeError("사용 가능한 브라우저 쿠키 후보가 없습니다.")

    @staticmethod
    def _download_error_needs_cookies(error: BaseException) -> bool:
        lowered = str(error).lower()
        return any(
            phrase in lowered
            for phrase in (
                "login required",
                "sign in",
                "cookies",
                "cookie",
                "rate-limit",
                "requested content is not available",
                "not available",
                "for authentication",
                "private",
                "decrypt",
                "dpapi",
                "cookie database",
            )
        )

    def _cookie_file_path(self) -> Path | None:
        cookie_file = str(getattr(self.settings, "cookie_file", "") or "").strip()
        if not cookie_file:
            return None
        path = Path(cookie_file).expanduser()
        return path if path.exists() and path.is_file() else None

    def _default_cookie_browser_spec(self) -> tuple[str, ...]:
        return ((self.settings.cookie_browser or "chrome").strip().lower(),)

    def _cookie_browser_candidates(self) -> list[str]:
        selected = (self.settings.cookie_browser or "chrome").strip().lower()
        common = [selected, "chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi", "whale"]
        candidates: list[str] = []
        seen: set[str] = set()
        for browser in common:
            if browser and browser not in seen:
                candidates.append(browser)
                seen.add(browser)
        return candidates

    def _cookie_browser_specs(self) -> list[tuple[str, ...]]:
        specs: list[tuple[str, ...]] = []
        seen: set[str] = set()
        for browser in self._cookie_browser_candidates():
            for spec in self._cookie_specs_for_browser(browser):
                key = self._cookie_spec_key(spec)
                if key not in seen:
                    specs.append(spec)
                    seen.add(key)
        return specs

    @classmethod
    def _cookie_specs_for_browser(cls, browser: str) -> list[tuple[str, ...]]:
        browser = browser.strip().lower()
        specs: list[tuple[str, ...]] = [(browser,)]
        if browser in CHROMIUM_BASED_BROWSERS:
            root = cls._chromium_user_data_dir(browser)
            if root and root.exists():
                for profile in cls._chromium_profile_names(root):
                    specs.append((browser, profile))
        elif browser == "firefox":
            root = cls._firefox_profiles_dir()
            if root and root.exists():
                for profile in cls._firefox_profile_paths(root):
                    specs.append((browser, str(profile)))
        return specs

    @staticmethod
    def _chromium_user_data_dir(browser: str) -> Path | None:
        local = os.getenv("LOCALAPPDATA")
        roaming = os.getenv("APPDATA")
        paths = {
            "brave": Path(local) / "BraveSoftware" / "Brave-Browser" / "User Data" if local else None,
            "chrome": Path(local) / "Google" / "Chrome" / "User Data" if local else None,
            "chromium": Path(local) / "Chromium" / "User Data" if local else None,
            "edge": Path(local) / "Microsoft" / "Edge" / "User Data" if local else None,
            "opera": Path(roaming) / "Opera Software" / "Opera Stable" if roaming else None,
            "vivaldi": Path(local) / "Vivaldi" / "User Data" if local else None,
            "whale": Path(local) / "Naver" / "Naver Whale" / "User Data" if local else None,
        }
        return paths.get(browser)

    @staticmethod
    def _firefox_profiles_dir() -> Path | None:
        roaming = os.getenv("APPDATA")
        return Path(roaming) / "Mozilla" / "Firefox" / "Profiles" if roaming else None

    @staticmethod
    def _chromium_profile_names(root: Path) -> list[str]:
        profiles = [
            child.name
            for child in root.iterdir()
            if child.is_dir() and ((child / "Network" / "Cookies").exists() or (child / "Cookies").exists())
        ]

        def sort_key(name: str) -> tuple[int, int, str]:
            if name == "Default":
                return (0, 0, name)
            match = re.fullmatch(r"Profile (\d+)", name)
            if match:
                return (1, int(match.group(1)), name)
            return (2, 0, name.lower())

        return sorted(profiles, key=sort_key)

    @staticmethod
    def _firefox_profile_paths(root: Path) -> list[Path]:
        return sorted(
            (child for child in root.iterdir() if child.is_dir() and (child / "cookies.sqlite").exists()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    @staticmethod
    def _cookie_spec_key(spec: tuple[object, ...]) -> str:
        browser = str(spec[0]).lower() if spec else ""
        profile = str(spec[1]).lower() if len(spec) > 1 and spec[1] else ""
        return f"{browser}:{profile}"

    @staticmethod
    def _cookie_spec_label(spec: tuple[object, ...]) -> str:
        browser = str(spec[0]) if spec else "browser"
        if len(spec) <= 1 or not spec[1]:
            return browser
        profile = Path(str(spec[1])).name
        return f"{browser}/{profile}"

    @staticmethod
    def _brief_error(error: BaseException, max_length: int = 120) -> str:
        text = " ".join(str(error).split())
        if not text:
            text = error.__class__.__name__
        return text if len(text) <= max_length else f"{text[: max_length - 3]}..."


    def _download_progress_hook(self, payload: dict[str, object]) -> None:
        status = payload.get("status")
        label = "영상 다운로드 중" if self.active_output_format == "MP4" else "오디오 다운로드 중"
        if status == "downloading":
            downloaded = _number(payload.get("downloaded_bytes"))
            total = _number(payload.get("total_bytes") or payload.get("total_bytes_estimate"))
            if total > 0:
                ratio = max(0.0, min(1.0, downloaded / total))
                percent = 0.08 + (ratio * 0.66)
                detail = f"다운로드 중... {ratio * 100:.1f}%"
            else:
                percent = 0.22
                detail = "다운로드 중..."
            self.progress(label, percent, detail)
        elif status == "finished":
            if self.active_output_format == "MP4":
                detail = "다운로드가 끝났습니다. 영상 파일을 정리합니다."
                if self.active_media_mode == MEDIA_VIDEO_AUDIO:
                    detail = "다운로드가 끝났습니다. 영상과 음성을 병합합니다."
                self.progress("MP4 정리 중", 0.76, detail)
            else:
                self.progress("MP3 변환 준비 중", 0.76, "다운로드가 끝났습니다. MP3로 변환합니다.")

    def _postprocessor_progress_hook(self, payload: dict[str, object]) -> None:
        status = payload.get("status")
        postprocessor = str(payload.get("postprocessor") or "")
        if status == "started":
            if self.active_output_format == "MP4":
                self.progress("MP4 병합 중", 0.84, "영상 파일을 MP4로 정리합니다.")
            else:
                self.progress("MP3 변환 중", 0.84, "오디오를 MP3 파일로 변환합니다.")
        elif status == "finished":
            if self.active_output_format == "MP4":
                label = "MP4 병합 완료" if "Remuxer" in postprocessor or "Merger" in postprocessor else "마무리 중"
            else:
                label = "MP3 변환 완료" if "ExtractAudio" in postprocessor else "마무리 중"
            self.progress(label, 0.90, "파일 이름과 저장 위치를 정리합니다.")

    def _capture_screenshots(self, video_path: Path, output_dir: Path) -> Path:
        duration = 0.0
        try:
            duration = get_media_duration(video_path, self.ffmpeg)
        except Exception:
            pass

        output_pattern = output_dir / "__screenshot_%05d.jpg"
        completed = run_process(
            [
                self.ffmpeg,
                "-y",
                "-i",
                video_path,
                "-vf",
                "fps=1",
                "-q:v",
                "3",
                output_pattern,
            ]
        )
        captures = sorted(output_dir.glob("__screenshot_*.jpg"))
        if completed.returncode != 0 or not captures:
            raise UserFacingError(
                "MP4는 저장했지만 스크린샷 캡처에 실패했습니다.\n\n"
                "FFmpeg가 영상을 읽지 못했거나 영상 파일에 문제가 있을 수 있습니다."
            )

        self._rename_screenshots_with_timecodes(captures)
        capture_count = len(list(output_dir.glob("*.jpg")))
        if duration > 0:
            self.progress("스크린샷 캡처 완료", 0.98, f"총 {capture_count}장 캡처했습니다. 영상 길이: 약 {int(duration)}초")
        else:
            self.progress("스크린샷 캡처 완료", 0.98, f"총 {capture_count}장 캡처했습니다.")
        return output_dir

    @staticmethod
    def _rename_screenshots_with_timecodes(paths: list[Path]) -> None:
        for index, path in enumerate(paths, start=1):
            seconds = index - 1
            hours, rem = divmod(seconds, 3600)
            minutes, secs = divmod(rem, 60)
            target = path.parent / f"{index:04d}_{hours:02d}-{minutes:02d}-{secs:02d}.jpg"
            if target.exists():
                target.unlink()
            path.rename(target)

    def _audio_quality(self) -> str:
        quality = str(self.settings.audio_quality or "320").strip().lower()
        if quality in {"best", "최고", "최고품질"}:
            return "320"
        return quality if quality in {"128", "192", "256", "320"} else "320"

    def _video_quality(self) -> str:
        quality = str(getattr(self.settings, "video_quality", "1080") or "1080").strip().lower()
        if quality.endswith("p"):
            quality = quality[:-1]
        if quality in {"best", "2160", "1440", "1080", "720", "480", "360"}:
            return quality
        return "1080"

    def _source_label(self, url: str) -> str:
        if self.is_instagram_url(url):
            return "Instagram 릴스/게시물"
        if "/shorts/" in url:
            return "YouTube Shorts"
        return "YouTube 영상"

    def _best_source_title(self, info: dict[str, object]) -> str:
        raw_title = self._metadata_text(info, "title")
        candidates: list[str] = []
        if raw_title and not self._is_generic_online_title(raw_title):
            candidates.append(raw_title)

        for key in ("description", "caption", "alt_title", "fulltitle"):
            candidate = self._caption_title(self._metadata_text(info, key))
            if candidate and not self._is_generic_online_title(candidate):
                candidates.append(candidate)

        if raw_title:
            candidates.append(raw_title)

        for candidate in candidates:
            cleaned = self._caption_title(candidate)
            if cleaned:
                return cleaned
        return "downloaded_media"

    @staticmethod
    def _metadata_text(info: dict[str, object], key: str) -> str:
        value = info.get(key)
        if isinstance(value, str):
            return value.strip()
        return ""

    @staticmethod
    def _is_generic_online_title(title: str) -> bool:
        normalized = re.sub(r"\s+", " ", title.strip()).lower()
        return bool(
            re.fullmatch(r"(video|reel|post)( by [\w_.-]+)?", normalized)
            or re.fullmatch(r"instagram (video|reel|post)", normalized)
            or normalized in {"downloaded_video", "video", "reel", "post"}
        )

    @staticmethod
    def _caption_title(text: str, max_length: int = 80) -> str:
        if not text.strip():
            return ""

        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"#\S+", "", text)
        text = re.sub(r"^\s*[\w.]+\s+on\s+Instagram:\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(
            r"^\s*[\d,]+\s+likes?,\s*[\d,]+\s+comments?\s*-\s*[^:]{1,80}:\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )

        lines = [re.sub(r"\s+", " ", line).strip(" -|:") for line in text.splitlines()]
        title = next((line for line in lines if len(line) >= 2), "")
        if not title:
            return ""

        title = YouTubeInstagramMediaPipeline._drop_repeated_title_suffix(title)
        if len(title) <= max_length:
            return title

        boundary = max(title.rfind(mark, 0, max_length) for mark in (".", "?", "!", "。", "요", "다"))
        if boundary >= 20:
            return title[: boundary + 1].strip()
        return title[:max_length].rstrip() + "..."

    @staticmethod
    def _drop_repeated_title_suffix(title: str) -> str:
        cleaned = re.sub(r"\s+", " ", title).strip()
        while cleaned.endswith(")"):
            depth = 0
            opener_index = -1
            for index in range(len(cleaned) - 1, -1, -1):
                char = cleaned[index]
                if char == ")":
                    depth += 1
                elif char == "(":
                    depth -= 1
                    if depth == 0:
                        opener_index = index
                        break
            if opener_index <= 0:
                break

            prefix = cleaned[:opener_index].strip()
            inner = cleaned[opener_index + 1 : -1].strip()
            if not prefix or not inner:
                break
            if _compact_heading(prefix) != _compact_heading(inner):
                break
            cleaned = prefix
        return cleaned

    def _friendly_download_error(self, error: BaseException, retried_with_cookies: bool = False) -> UserFacingError:
        media_word = "영상을" if self.active_output_format == "MP4" else "오디오를"
        if self.is_instagram_url(self.active_url):
            if retried_with_cookies or self.settings.use_browser_cookies:
                extra_help = self._instagram_cookie_help(error)
                return UserFacingError(
                    f"Instagram에서 이 {media_word} 바로 다운로드하지 못했습니다.\n\n"
                    "PC 브라우저 쿠키로 다시 시도했지만 로그인 정보가 없거나 Instagram이 요청을 막았습니다.\n\n"
                    f"{extra_help}"
                )
            return UserFacingError(
                f"Instagram에서 이 {media_word} 다운로드하지 못했습니다.\n\n"
                "비공개/삭제된 릴스이거나 로그인이 필요한 링크일 수 있습니다. 브라우저에서 링크가 정상 재생되는지 확인해 주세요."
            )

        lowered = str(error).lower()
        if "private" in lowered or "sign in" in lowered or "login" in lowered:
            return UserFacingError(
                f"YouTube에서 이 {media_word} 바로 다운로드하지 못했습니다.\n\n"
                "영상이 비공개이거나 로그인이 필요한 상태일 수 있습니다. 브라우저에서 영상이 정상 재생되는지 확인해 주세요."
            )
        if "ffmpeg" in lowered:
            if self.active_output_format == "MP4":
                return UserFacingError("MP4 병합 또는 스크린샷 캡처에 필요한 FFmpeg를 실행하지 못했습니다.")
            return UserFacingError("MP3 변환에 필요한 FFmpeg를 실행하지 못했습니다.")
        return UserFacingError(
            f"YouTube {media_word} 다운로드하지 못했습니다.\n\n"
            "링크가 올바른지, 영상이 삭제/비공개 상태가 아닌지 확인한 뒤 다시 시도해 주세요."
        )

    @staticmethod
    def _instagram_cookie_help(error: BaseException) -> str:
        lowered = str(error).lower()
        if "dpapi" in lowered or "decrypt" in lowered or "mac check failed" in lowered:
            return (
                "Chrome/Edge의 쿠키 암호화 때문에 자동 쿠키 읽기가 막힌 것으로 보입니다.\n"
                "브라우저 확장 프로그램으로 Instagram cookies.txt를 내보낸 뒤, 고급 옵션의 '쿠키 파일'에 선택해 주세요."
            )
        return (
            "Chrome 또는 Edge에서 Instagram에 로그인되어 있는지 확인해 주세요.\n"
            "여러 Chrome 프로필을 쓰는 경우 앱이 프로필별로 자동 재시도합니다. 그래도 안 되면 cookies.txt 파일을 선택해 주세요."
        )

    @staticmethod
    def _find_downloaded_file(output_root: Path, started: str, suffix: str) -> Path | None:
        candidates = sorted(
            output_root.glob(f"__download_{started}_*{suffix}"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    @staticmethod
    def _friendly_final_path(output_root: Path, started: str, title: str, suffix: str, current_path: Path) -> Path:
        safe_title = sanitize_filename(title)
        target = output_root / f"{started} {safe_title}{suffix}"
        if os.path.normcase(str(target.resolve())) == os.path.normcase(str(current_path.resolve())):
            return current_path
        return unique_path(target)

    @staticmethod
    def _screenshot_output_dir(output_root: Path, title: str) -> Path:
        return unique_dir(output_root / f"{sanitize_filename(title)} 스크린샷 추출본")

    @staticmethod
    def _cleanup_extra_outputs(output_root: Path, started: str, kept_path: Path) -> None:
        kept_resolved = kept_path.resolve()
        for path in output_root.glob(f"__download_{started}_*"):
            if path.resolve() == kept_resolved:
                continue
            try:
                path.unlink()
            except OSError:
                pass


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def unique_dir(path: Path) -> Path:
    if not path.exists():
        return path
    parent = path.parent
    name = path.name
    index = 2
    while True:
        candidate = parent / f"{name} ({index})"
        if not candidate.exists():
            return candidate
        index += 1


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _compact_heading(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).lower()
