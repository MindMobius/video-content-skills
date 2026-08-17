from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from video_content.cli import COMMAND_SURFACE, build_parser

ROOT = Path(__file__).resolve().parents[1]


def test_cli_exposes_only_grouped_v1_surface() -> None:
    assert COMMAND_SURFACE == {
        "system": {"setup", "configure", "doctor"},
        "source": {"inspect"},
        "evidence": {"start"},
        "job": {"get", "list", "update", "artifacts", "read-artifact"},
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


def test_cli_parses_transcript_and_wechat_inputs() -> None:
    parser = build_parser()
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
