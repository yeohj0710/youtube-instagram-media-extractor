from __future__ import annotations

from youtube_instagram_media_extractor.app import AUDIO_QUALITY_CHOICES, YouTubeInstagramMediaApp, extract_urls


def test_extract_urls_accepts_multiple_lines_and_deduplicates():
    text = """
    https://www.youtube.com/watch?v=abc
    https://www.instagram.com/reel/xyz/
    https://www.youtube.com/watch?v=abc
    """

    assert extract_urls(text) == [
        "https://www.youtube.com/watch?v=abc",
        "https://www.instagram.com/reel/xyz/",
    ]


def test_extract_urls_strips_common_trailing_punctuation():
    assert extract_urls("링크: https://youtu.be/abc).") == ["https://youtu.be/abc"]


def test_audio_quality_choices_start_with_best_then_descend():
    assert AUDIO_QUALITY_CHOICES == ["최고", "320", "256", "192", "128"]
    assert YouTubeInstagramMediaApp._audio_quality_label("320") == "최고"
    assert YouTubeInstagramMediaApp._audio_quality_label("256") == "256"
