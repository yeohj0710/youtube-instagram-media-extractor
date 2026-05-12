from __future__ import annotations

import json

from youtube_instagram_media_extractor import settings as settings_module
from youtube_instagram_media_extractor.settings import AppSettings, load_settings, save_settings


def test_load_settings_defaults_to_video_audio_and_browser_cookies(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.chdir(tmp_path)

    loaded = load_settings()

    assert loaded.include_video is True
    assert loaded.include_audio is True
    assert loaded.use_browser_cookies is True
    assert loaded.video_quality == "1080"


def test_saved_default_output_dir_follows_current_app_root(tmp_path, monkeypatch):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    appdata = tmp_path / "appdata"
    monkeypatch.setenv("APPDATA", str(appdata))
    new_root.mkdir()
    monkeypatch.chdir(new_root)
    path = settings_module.settings_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"output_dir": str(old_root / "다운로드한 MP3")}, ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = load_settings()

    assert loaded.output_dir == str(new_root / "다운로드한 미디어")


def test_save_settings_does_not_persist_default_output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.chdir(tmp_path)

    save_settings(AppSettings(output_dir=str(tmp_path / "다운로드한 미디어")))

    payload = json.loads(settings_module.settings_path().read_text(encoding="utf-8"))
    assert payload["output_dir"] == ""
    assert payload["output_dir_custom"] is False


def test_save_settings_keeps_custom_output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "music"

    save_settings(
        AppSettings(
            output_dir=str(custom),
            output_dir_custom=True,
            output_format="MP4",
            include_video=True,
            include_audio=False,
            audio_quality="256",
            video_quality="720",
        )
    )

    payload = json.loads(settings_module.settings_path().read_text(encoding="utf-8"))
    assert payload["output_dir"] == str(custom)
    assert payload["output_dir_custom"] is True
    assert payload["output_format"] == "MP4"
    assert payload["include_video"] is True
    assert payload["include_audio"] is False
    assert payload["audio_quality"] == "256"
    assert payload["video_quality"] == "720"
