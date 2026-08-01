from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from video_subtitle.config import (
    apply_configuration,
    read_configuration,
    update_configuration,
)
from video_subtitle.environment import build_setup_report, read_requirements

ROOT = Path(__file__).resolve().parents[1]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


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
    document = json.loads(config_path.read_text(encoding="utf-8"))
    jsonschema.validate(document, _schema("config.schema.json"))


def test_requirements_document_covers_agent_capabilities() -> None:
    document = read_requirements()

    jsonschema.validate(document, _schema("requirements.schema.json"))
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
    jsonschema.validate(report, _schema("setup.schema.json"))
    assert not any(
        item["dependency_id"].startswith("qwen") for item in report["dependencies"]
    )


def test_deep_ready_report_starts_task_instead_of_rechecking(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "video_subtitle.environment.shutil.which",
        lambda command: f"/tools/{command}",
    )
    diagnostics = {
        "deep": True,
        "opencli": {
            "available": True,
            "platform_ready": True,
            "command": "node OpenCLI/main.js",
            "profile": "bridge",
        },
        "download_tools": {},
        "hard_ocr": {},
        "audio_asr": {},
    }

    report = build_setup_report(
        diagnostics,
        capabilities=["platform_subtitle"],
        config_path=tmp_path / "config.json",
    )

    assert report["ready"] is True
    assert report["next_step"] == (
        "Start the subtitle task with the verified capabilities."
    )


def test_remote_model_ids_require_confirmed_local_download(
    tmp_path: Path,
) -> None:
    asr_python = tmp_path / "python"
    asr_python.write_text("", encoding="utf-8")
    diagnostics = {
        "deep": False,
        "opencli": {},
        "download_tools": {
            "ffmpeg": {"available": True, "path": "ffmpeg"},
        },
        "hard_ocr": {},
        "audio_asr": {
            "available": True,
            "python": str(asr_python),
            "model": "Qwen/Qwen3-ASR-1.7B",
            "aligner": "Qwen/Qwen3-ForcedAligner-0.6B",
            "runtime_checked": False,
        },
    }

    report = build_setup_report(
        diagnostics,
        capabilities=["audio_asr_local"],
        config_path=tmp_path / "config.json",
    )

    assert report["ready"] is False
    model_actions = {item["dependency_id"]: item for item in report["agent_actions"]}
    assert model_actions["qwen_asr_model"]["confirmation_required"] is True
    assert model_actions["qwen_aligner_model"]["confirmation_required"] is True


def test_bundled_opencli_executable_does_not_require_node(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "video_subtitle.environment.shutil.which",
        lambda _command: None,
    )
    diagnostics = {
        "deep": True,
        "opencli": {
            "available": True,
            "platform_ready": True,
            "command": str(tmp_path / "opencli.exe"),
            "profile": "bridge",
        },
        "download_tools": {},
        "hard_ocr": {},
        "audio_asr": {},
    }

    report = build_setup_report(
        diagnostics,
        capabilities=["platform_subtitle"],
        config_path=tmp_path / "config.json",
    )

    node = next(
        item for item in report["dependencies"] if item["dependency_id"] == "node"
    )
    assert node["status"] == "ready"
    assert node["detected"] == "not required by configured OpenCLI executable"
