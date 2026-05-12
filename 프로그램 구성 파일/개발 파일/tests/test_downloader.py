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


def test_mp4_final_path_stays_in_output_root(tmp_path: Path):
    current = tmp_path / "__download_260512120000_title.mp4"
    current.write_bytes(b"mp4")

    target = YouTubeInstagramMediaPipeline._friendly_final_path(tmp_path, "260512120000", "Title", ".mp4", current)

    assert target == tmp_path / "260512120000 Title.mp4"


def test_screenshot_output_dir_is_separate_from_media_files(tmp_path: Path):
    target = YouTubeInstagramMediaPipeline._screenshot_output_dir(tmp_path, "Title")

    assert target == tmp_path / "Title 스크린샷 추출본"


def test_mp4_download_skips_screenshots_when_option_is_off(tmp_path: Path, monkeypatch):
    started = "260512120000"
    downloaded = tmp_path / f"__download_{started}_demo.mp4"
    downloaded.write_bytes(b"mp4")
    pipeline = YouTubeInstagramMediaPipeline(AppSettings(output_dir=str(tmp_path), include_video=True, include_audio=True))
    monkeypatch.setattr(pipeline, "_import_ytdlp", lambda: object())
    monkeypatch.setattr(pipeline, "_extract_with_ytdlp", lambda _module, _url, _opts: {"title": "Demo Video"})

    def fail_capture(_video_path: Path, _output_dir: Path) -> Path:
        raise AssertionError("screenshots should be skipped")

    monkeypatch.setattr(pipeline, "_capture_screenshots", fail_capture)

    media_path, title, output_dir, screenshot_dir = pipeline._download_mp4(
        "https://youtu.be/demo",
        started,
        tmp_path,
        include_audio=True,
        capture_screenshots=False,
    )

    assert title == "Demo Video"
    assert media_path == (tmp_path / f"{started} Demo Video.mp4").resolve()
    assert output_dir == tmp_path.resolve()
    assert screenshot_dir is None
    assert not (tmp_path / "Demo Video").exists()


def test_mp4_download_puts_screenshots_in_separate_folder(tmp_path: Path, monkeypatch):
    started = "260512120000"
    downloaded = tmp_path / f"__download_{started}_demo.mp4"
    downloaded.write_bytes(b"mp4")
    pipeline = YouTubeInstagramMediaPipeline(AppSettings(output_dir=str(tmp_path), include_video=True, include_audio=True, capture_screenshots=True))
    monkeypatch.setattr(pipeline, "_import_ytdlp", lambda: object())
    monkeypatch.setattr(pipeline, "_extract_with_ytdlp", lambda _module, _url, _opts: {"title": "Demo Video"})

    def fake_capture(_video_path: Path, output_dir: Path) -> Path:
        (output_dir / "0001_00-00-00.jpg").write_bytes(b"jpg")
        return output_dir

    monkeypatch.setattr(pipeline, "_capture_screenshots", fake_capture)

    media_path, _title, output_dir, screenshot_dir = pipeline._download_mp4(
        "https://youtu.be/demo",
        started,
        tmp_path,
        include_audio=True,
        capture_screenshots=True,
    )

    assert media_path.parent == tmp_path.resolve()
    assert output_dir == tmp_path.resolve()
    assert screenshot_dir == (tmp_path / "Demo Video 스크린샷 추출본").resolve()
    assert (tmp_path / f"{started} Demo Video.mp4").exists()
    assert (tmp_path / "Demo Video 스크린샷 추출본" / "0001_00-00-00.jpg").exists()


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
