from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from video_content.cli import COMMAND_SURFACE, build_parser
from video_content.store import Store

ROOT = Path(__file__).resolve().parents[1]


def test_cli_exposes_only_grouped_v1_surface() -> None:
    assert COMMAND_SURFACE == {
        "system": {"setup", "configure", "doctor"},
        "source": {"inspect"},
        "evidence": {"start"},
        "job": {"get", "list", "update", "artifacts", "read-artifact"},
        "media": {"extract-frame"},
        "content": {"save-transcript", "save", "validate"},
        "watch-later": {"scan"},
        "wechat": {"prepare", "bind"},
    }
    help_text = build_parser().format_help()
    for group in COMMAND_SURFACE:
        assert group in help_text
    for removed in (
        "batch-init",
        "review-prepare",
        "content-phase-start",
        "automation-handoff-bind",
    ):
        assert removed not in help_text


def test_cli_emits_one_json_document_for_success_and_failure(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    success = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_content.cli",
            "--home",
            str(tmp_path),
            "job",
            "list",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert success.returncode == 0
    success_payload = json.loads(success.stdout)
    assert success_payload == {
        "ok": True,
        "result": {
            "schema_version": "video-content/job-list-v1",
            "jobs": [],
            "count": 0,
        },
    }
    failure = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_content.cli",
            "--home",
            str(tmp_path),
            "job",
            "get",
            "missing",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert failure.returncode == 1
    failure_payload = json.loads(failure.stdout)
    assert failure_payload["ok"] is False
    assert failure_payload["error"]["type"] == "FileNotFoundError"


def test_cli_config_home_is_used_without_explicit_home(tmp_path: Path) -> None:
    state = tmp_path / "state"
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "video-content/config-v1",
                "values": {"home": str(state)},
            }
        ),
        encoding="utf-8",
    )
    Store(state).create_job(
        source={"platform": "bilibili"},
        idempotency_key="from-config-home",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment.pop("VIDEO_CONTENT_HOME", None)
    environment.pop("VIDEO_CONTENT_CONFIG", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_content.cli",
            "--config",
            str(config),
            "job",
            "list",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["result"]["count"] == 1
    assert payload["result"]["jobs"][0]["idempotency_key"] == "from-config-home"


def test_cli_parses_transcript_and_wechat_inputs() -> None:
    parser = build_parser()
    evidence = parser.parse_args(
        [
            "evidence",
            "start",
            "https://www.bilibili.com/video/BV1test/",
            "--hard-subtitle-visual-decision",
            "continuous",
            "--visual-assessment-json",
            "scout.json",
        ]
    )
    assert evidence.hard_subtitle_visual_decision == "continuous"
    assert evidence.visual_assessment_json == Path("scout.json")
    frame = parser.parse_args(
        [
            "media",
            "extract-frame",
            "job_1",
            "42000",
            "--selection-reason",
            "对应论述转场",
        ]
    )
    assert frame.group == "media"
    assert frame.action == "extract-frame"
    assert frame.timestamp_ms == 42000
    assert frame.selection_reason == "对应论述转场"
    transcript = parser.parse_args(
        ["--home", "state", "content", "save-transcript", "job_1", "transcript.json"]
    )
    assert transcript.group == "content"
    assert transcript.action == "save-transcript"
    assert transcript.input == Path("transcript.json")
    handoff = parser.parse_args(
        [
            "wechat",
            "prepare",
            "job_1",
            "content_1",
            "--authorized",
            "--save-draft",
        ]
    )
    assert handoff.authorized is True
    assert handoff.save_draft is True


def test_cli_discovers_project_local_config_without_flags(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src" / "video_content").mkdir(parents=True)
    (project / ".video-content").mkdir()
    (project / "pyproject.toml").write_text(
        "[project]\nname='test'\n", encoding="utf-8"
    )
    state = tmp_path / "state"
    (project / ".video-content" / "config.json").write_text(
        json.dumps(
            {
                "schema_version": "video-content/config-v1",
                "values": {"home": str(state)},
            }
        ),
        encoding="utf-8",
    )
    Store(state).create_job(
        source={"platform": "bilibili", "bvid": "BV1auto"},
        idempotency_key="auto-discovered",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment.pop("VIDEO_CONTENT_HOME", None)
    environment.pop("VIDEO_CONTENT_CONFIG", None)

    result = subprocess.run(
        [sys.executable, "-m", "video_content.cli", "job", "list"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["result"]["count"] == 1
    assert payload["result"]["jobs"][0]["idempotency_key"] == "auto-discovered"
