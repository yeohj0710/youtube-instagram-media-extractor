from __future__ import annotations

from pathlib import Path

from youtube_instagram_media_extractor.downloader import MEDIA_AUDIO_ONLY, MEDIA_VIDEO_AUDIO, MEDIA_VIDEO_ONLY, YouTubeInstagramMediaPipeline, unique_dir, unique_path
from youtube_instagram_media_extractor.settings import AppSettings
from youtube_instagram_media_extractor.utils import sanitize_filename


def test_is_supported_url_accepts_youtube_and_instagram_hosts():
    assert YouTubeInstagramMediaPipeline.is_supported_url("https://www.youtube.com/watch?v=abc")
    assert YouTubeInstagramMediaPipeline.is_supported_url("https://youtu.be/abc")
    assert YouTubeInstagramMediaPipeline.is_supported_url("https://music.youtube.com/watch?v=abc")
    assert YouTubeInstagramMediaPipeline.is_supported_url("https://www.youtube.com/shorts/abc")
    assert YouTubeInstagramMediaPipeline.is_supported_url("https://www.instagram.com/reel/abc/")
    assert YouTubeInstagramMediaPipeline.is_supported_url("https://www.instagram.com/p/abc/")


def test_is_supported_url_rejects_other_hosts():
    assert not YouTubeInstagramMediaPipeline.is_supported_url("https://example.com/watch?v=abc")


def test_sanitize_filename_removes_windows_reserved_chars():
    assert sanitize_filename('bad <title> "demo" / test?') == "bad _title_ _demo_ _ test_"


def test_unique_path_uses_parentheses_for_duplicates(tmp_path: Path):
    existing = tmp_path / "song.mp3"
    existing.write_bytes(b"first")

    assert unique_path(existing) == tmp_path / "song (2).mp3"


def test_unique_dir_uses_parentheses_for_duplicates(tmp_path: Path):
    existing = tmp_path / "title"
    existing.mkdir()

    assert unique_dir(existing) == tmp_path / "title (2)"


def test_cleanup_extra_outputs_keeps_only_selected_file(tmp_path: Path):
    mp3 = tmp_path / "__download_260512120000_title.mp3"
    mp4 = tmp_path / "__download_260512120000_title.mp4"
    temp = tmp_path / "__download_260512120000_title.webm"
    other = tmp_path / "other.webm"
    mp3.write_bytes(b"mp3")
    mp4.write_bytes(b"mp4")
    temp.write_bytes(b"temp")
    other.write_bytes(b"other")

    YouTubeInstagramMediaPipeline._cleanup_extra_outputs(tmp_path, "260512120000", mp4)

    assert not mp3.exists()
    assert mp4.exists()
    assert not temp.exists()
    assert other.exists()


def test_rename_screenshots_with_timecodes(tmp_path: Path):
    first = tmp_path / "__screenshot_00001.jpg"
    second = tmp_path / "__screenshot_00002.jpg"
    first.write_bytes(b"1")
    second.write_bytes(b"2")

    YouTubeInstagramMediaPipeline._rename_screenshots_with_timecodes([first, second])

    assert (tmp_path / "0001_00-00-00.jpg").exists()
    assert (tmp_path / "0002_00-00-01.jpg").exists()


def test_media_mode_follows_video_and_audio_flags():
    assert YouTubeInstagramMediaPipeline(AppSettings(include_video=True, include_audio=True))._media_mode() == MEDIA_VIDEO_AUDIO
    assert YouTubeInstagramMediaPipeline(AppSettings(include_video=True, include_audio=False))._media_mode() == MEDIA_VIDEO_ONLY
    assert YouTubeInstagramMediaPipeline(AppSettings(include_video=False, include_audio=True))._media_mode() == MEDIA_AUDIO_ONLY


def test_video_format_selector_respects_quality_and_audio_choice():
    pipeline = YouTubeInstagramMediaPipeline(AppSettings(include_video=True, include_audio=False, video_quality="720"))

    selector = pipeline._video_format_selector(include_audio=False)

    assert "[height<=720]" in selector
    assert "+ba" not in selector
