from __future__ import annotations

from pathlib import Path

from video_subtitle.config import (
    apply_configuration,
    read_configuration,
    update_configuration,
)
from video_subtitle.environment import build_setup_report, read_requirements


def test_persisted_config_fills_missing_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.delenv("VIDEO_SUBTITLE_OPENCLI", raising=False)
    monkeypatch.setenv("VIDEO_SUBTITLE_FFMPEG", "environment-ffmpeg")

    update_configuration(
        {
            "opencli": "C:/tools/OpenCLI/main.js",
            "ffmpeg": "C:/tools/ffmpeg.exe",
        },
        path=config_path,
    )
    result = apply_configuration(config_path)

    assert result["applied_fields"] == ["opencli"]
    assert result["shadowed_by_environment"] == ["ffmpeg"]
    assert result["values"]["opencli"] == "C:/tools/OpenCLI/main.js"


def test_config_update_preserves_and_clears_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    update_configuration(
        {"opencli_profile": "bridge", "videocr": "videocr.exe"},
        path=config_path,
    )
    update_configuration(
        {"ffmpeg": "ffmpeg.exe"},
        clear=["videocr"],
        path=config_path,
    )

    values = read_configuration(config_path)["values"]
    assert values == {
        "ffmpeg": "ffmpeg.exe",
        "opencli_profile": "bridge",
    }


def test_requirements_document_covers_agent_capabilities() -> None:
    document = read_requirements()

    assert document["schema_version"] == "video-subtitle/requirements-v1"
    assert "hard_ocr_url" in document["capabilities"]
    assert "audio_asr_url" in document["capabilities"]
    assert document["dependencies"]["browser_bridge"]["kind"] == "human_session"


def test_setup_report_separates_agent_and_human_actions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for name in (
        "VIDEO_SUBTITLE_ASR_PYTHON",
        "VIDEO_SUBTITLE_QWEN_ASR_MODEL",
        "VIDEO_SUBTITLE_QWEN_ALIGNER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    diagnostics = {
        "opencli": {
            "available": True,
            "platform_ready": False,
            "command": "node OpenCLI/main.js",
            "profile": None,
        },
        "download_tools": {
            "yt_dlp": {"available": False, "path": None},
            "ffmpeg": {"available": True, "path": "ffmpeg"},
        },
        "hard_ocr": {"available": False, "executable": None},
        "audio_asr": {"available": False, "error": "not configured"},
    }

    report = build_setup_report(
        diagnostics,
        capabilities=["hard_ocr_url"],
        config_path=tmp_path / "config.json",
    )

    assert report["ready"] is False
    assert report["status"] == "human_action_required"
    assert {item["dependency_id"] for item in report["agent_actions"]} == {
        "yt_dlp",
        "videocr",
    }
    assert [item["dependency_id"] for item in report["human_actions"]] == [
        "browser_bridge"
    ]
    assert not any(
        item["dependency_id"].startswith("qwen") for item in report["dependencies"]
    )
