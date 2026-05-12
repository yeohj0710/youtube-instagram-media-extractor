from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


APP_NAME = "YouTubeInstagramMediaExtractor"
LEGACY_APP_NAMES = ("YouTubeMediaExtractor", "YouTubeMP3Extractor")
DEFAULT_OUTPUT_FOLDER_NAME = "다운로드한 미디어"
LEGACY_DEFAULT_OUTPUT_FOLDER_NAMES = {"다운로드한 MP3"}
DEFAULT_OUTPUT_FORMAT = "MP3"
DEFAULT_AUDIO_QUALITY = "192"
OUTPUT_FORMAT_CHOICES = {"MP3", "MP4"}


@dataclass
class AppSettings:
    output_dir: str = ""
    output_dir_custom: bool = False
    output_format: str = DEFAULT_OUTPUT_FORMAT
    audio_quality: str = DEFAULT_AUDIO_QUALITY
    use_browser_cookies: bool = False
    cookie_browser: str = "chrome"


def app_data_dir() -> Path:
    base = os.getenv("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def app_root_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    cwd = Path.cwd()
    if cwd.name == "개발 파일" and cwd.parent.name == "프로그램 구성 파일":
        return cwd.parent.parent
    return cwd


def default_output_dir() -> Path:
    return app_root_dir() / DEFAULT_OUTPUT_FOLDER_NAME


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def legacy_settings_paths() -> list[Path]:
    base = os.getenv("APPDATA")
    if base:
        return [Path(base) / name / "settings.json" for name in LEGACY_APP_NAMES]
    return [Path.home() / f".{name.lower()}" / "settings.json" for name in LEGACY_APP_NAMES]


def _is_default_output_like(path_text: str) -> bool:
    if not path_text.strip():
        return True
    try:
        path = Path(path_text).expanduser()
    except (OSError, ValueError):
        return False
    return path.name == DEFAULT_OUTPUT_FOLDER_NAME or path.name in LEGACY_DEFAULT_OUTPUT_FOLDER_NAMES


def _is_current_default_output_dir(path_text: str) -> bool:
    if not path_text.strip():
        return True
    try:
        path = Path(path_text).expanduser().resolve()
        default_path = default_output_dir().expanduser().resolve()
    except (OSError, ValueError):
        return False
    return os.path.normcase(str(path)) == os.path.normcase(str(default_path))


def is_current_default_output_dir(path_text: str) -> bool:
    return _is_current_default_output_dir(path_text)


def load_settings() -> AppSettings:
    path = settings_path()
    if not path.exists():
        path = next((legacy_path for legacy_path in legacy_settings_paths() if legacy_path.exists()), path)
    data: dict[str, object] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}

    settings = AppSettings()
    for key, value in data.items():
        if hasattr(settings, key):
            setattr(settings, key, value)

    if not settings.output_dir:
        settings.output_dir = str(default_output_dir())
        settings.output_dir_custom = False
    elif not settings.output_dir_custom and _is_default_output_like(str(settings.output_dir)):
        settings.output_dir = str(default_output_dir())

    settings.output_format = str(settings.output_format).strip().upper()
    if settings.output_format not in OUTPUT_FORMAT_CHOICES:
        settings.output_format = DEFAULT_OUTPUT_FORMAT
    if str(settings.audio_quality).strip() not in {"128", "192", "256", "320"}:
        settings.audio_quality = DEFAULT_AUDIO_QUALITY
    return settings


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    if _is_current_default_output_dir(str(settings.output_dir)):
        payload["output_dir"] = ""
        payload["output_dir_custom"] = False
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
