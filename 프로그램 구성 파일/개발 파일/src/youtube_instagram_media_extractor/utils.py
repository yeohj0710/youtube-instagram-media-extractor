from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


INVALID_FILENAME_CHARS = r'<>:"/\|?*'


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base.joinpath(*parts)


def sanitize_filename(value: str, fallback: str = "downloaded_media") -> str:
    cleaned = "".join("_" if ch in INVALID_FILENAME_CHARS else ch for ch in value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = _truncate_filename(cleaned, 90)
    return cleaned or fallback


def _truncate_filename(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value.strip(" .")

    truncated = value[:max_length].rstrip(" .-_")
    best_boundary = max(
        truncated.rfind(mark)
        for mark in (
            " - ",
            " | ",
            " / ",
            ") ",
            "] ",
            "} ",
            ". ",
            ", ",
        )
    )
    if best_boundary >= max_length * 0.55:
        truncated = truncated[: best_boundary + 1].rstrip(" .-_")

    truncated = _drop_unclosed_tail(truncated, "(", ")")
    truncated = _drop_unclosed_tail(truncated, "[", "]")
    truncated = _drop_unclosed_tail(truncated, "{", "}")
    return truncated.strip(" .-_") or value[:max_length].strip(" .-_")


def _drop_unclosed_tail(value: str, opener: str, closer: str) -> str:
    if value.count(opener) <= value.count(closer):
        return value
    cut = value.rfind(opener)
    if cut <= 0:
        return value
    return value[:cut].rstrip(" .-_")


def find_ffmpeg() -> Path:
    env_path = os.getenv("FFMPEG_BINARY")
    if env_path:
        configured = _find_existing_ffmpeg_path(Path(env_path).expanduser())
        if configured is not None:
            return configured

    for bundled in _bundled_ffmpeg_candidates():
        if bundled.exists() and bundled.is_file():
            return bundled.resolve()

    try:
        import imageio_ffmpeg

        bundled = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if bundled.exists():
            return bundled
    except Exception:
        pass

    found = shutil.which("ffmpeg")
    if found:
        return Path(found)
    raise RuntimeError("FFmpeg을 찾을 수 없습니다. ffmpeg 설치 또는 재빌드가 필요합니다.")


def _find_existing_ffmpeg_path(path: Path) -> Path | None:
    if path.exists() and path.is_file():
        return path.resolve()
    if path.exists() and path.is_dir():
        for candidate in _ffmpeg_candidates_in_dir(path):
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
    return None


def _bundled_ffmpeg_candidates() -> list[Path]:
    roots = [
        Path(getattr(sys, "_MEIPASS", "")),
        Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(),
        resource_path(),
        Path(__file__).resolve().parents[2],
    ]
    candidates: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root:
            continue
        for directory in (
            root,
            root / "imageio_ffmpeg" / "binaries",
            root / "binaries",
        ):
            for candidate in _ffmpeg_candidates_in_dir(directory):
                key = os.path.normcase(str(candidate))
                if key not in seen:
                    candidates.append(candidate)
                    seen.add(key)
    return candidates


def _ffmpeg_candidates_in_dir(directory: Path) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return [directory / "ffmpeg.exe"]
    direct = [directory / "ffmpeg.exe"]
    return direct + sorted(directory.glob("ffmpeg*.exe"))


def run_process(args: list[str | os.PathLike[str]], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def get_media_duration(media_path: Path, ffmpeg_path: Path | None = None) -> float:
    ffmpeg = ffmpeg_path or find_ffmpeg()
    completed = run_process([ffmpeg, "-i", media_path])
    output = f"{completed.stdout}\n{completed.stderr}"
    match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", output)
    if not match:
        raise RuntimeError("영상 길이를 읽지 못했습니다.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
