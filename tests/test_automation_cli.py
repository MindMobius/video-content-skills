from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from video_subtitle.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]


def _profile() -> dict:
    return {
        "enabled": True,
        "source": {
            "kind": "bilibili_watch_later",
            "account_profile_alias": "bilibili-main",
            "poll_interval_seconds": 900,
        },
        "content": {
            "medium": "wechat_article",
            "objective": "faithful_information_transfer",
            "audience": "公众号读者",
            "output_language": "zh-CN",
            "style": "restrained-editorial",
            "image_policy": "source_video_only",
        },
        "evidence_policy": {
            "require_hard_subtitle_assessment": True,
            "allow_platform_subtitle": True,
            "allow_hard_ocr": True,
            "allow_audio_asr": True,
        },
        "retry_policy": {
            "max_technical_attempts": 2,
            "max_content_repairs": 1,
            "backoff_seconds": 1,
        },
        "draft_authorization_id": "auth-watch-later",
        "prohibited_actions": [
            "publish",
            "mass_send",
            "schedule",
            "originality",
            "account_management",
        ],
    }


def test_parser_exposes_automation_commands() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    for command in (
        "automation-profile-save",
        "automation-authorize-drafts",
        "automation-scan",
        "automation-jobs",
        "automation-job",
        "automation-job-update",
        "canonical-save",
        "canonical-status",
        "automation-content-init",
        "automation-handoff-prepare",
        "automation-handoff-bind",
    ):
        assert command in help_text


def test_parser_separates_browser_and_automation_profile_aliases() -> None:
    args = build_parser().parse_args(
        [
            "--profile",
            "j6g376bb",
            "automation-scan",
            "--profile",
            "profile.json",
            "--store",
            "automation-store",
            "--baseline-if-empty",
        ]
    )

    assert args.profile == "j6g376bb"
    assert args.automation_profile == Path("profile.json")
    assert args.baseline_if_empty is True


def test_doctor_accepts_watch_later_monitor_capability() -> None:
    args = build_parser().parse_args(["doctor", "--capability", "watch_later_monitor"])

    assert args.capability == ["watch_later_monitor"]


def test_profile_save_cli_emits_json(tmp_path: Path) -> None:
    document = tmp_path / "profile-input.json"
    output = tmp_path / "profile.json"
    document.write_text(json.dumps(_profile(), ensure_ascii=False), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_subtitle.cli",
            "automation-profile-save",
            "--document",
            str(document),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["schema_version"] == "video-automation/profile-v1"
    assert output.is_file()


def test_authorization_cli_requires_explicit_draft_only_confirmation(
    tmp_path: Path,
) -> None:
    profile_input = tmp_path / "profile-input.json"
    profile_path = tmp_path / "profile.json"
    profile_input.write_text(
        json.dumps(_profile(), ensure_ascii=False), encoding="utf-8"
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "video_subtitle.cli",
            "automation-profile-save",
            "--document",
            str(profile_input),
            "--output",
            str(profile_path),
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    document = tmp_path / "authorization-input.json"
    document.write_text(
        json.dumps(
            {
                "authorization_id": "auth-watch-later",
                "status": "active",
                "profile_ids": [profile["profile_id"]],
                "browser_profile_alias": "wechat-main",
                "allowed_actions": ["save_wechat_draft"],
                "prohibited_actions": profile["prohibited_actions"],
                "expires_at": None,
                "revoked_at": None,
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_subtitle.cli",
            "automation-authorize-drafts",
            "--document",
            str(document),
            "--output",
            str(tmp_path / "authorization.json"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert completed.returncode != 0
    assert "confirm" in completed.stderr.lower()


def test_mcp_exposes_composed_automation_actions() -> None:
    from video_subtitle import mcp_server

    assert callable(mcp_server.begin_video_automation_evidence)
    assert callable(mcp_server.complete_video_automation_evidence)
    assert callable(mcp_server.save_video_automation_canonical_subtitle)
    assert callable(mcp_server.audit_video_automation_store)
